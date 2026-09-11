"""Loans: lenders' products, and farmers applying with their project report."""

from __future__ import annotations

import importlib
import sys
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, LoanApplication, Notification
from app.services import sync_client
from app.services.events import EventType

from .conftest import UP, become
from .test_marketplace import insert_profile, make_owner
from .test_profiles import farmer_body, partner_national_body
from .test_sync import SYNC_DIR, OtherDevice, ServerTransport, fresh_sync_module


def loan_body(**overrides) -> dict:
    body = {
        "purpose": "horticulture",
        "title": "Orchard development loan",
        "summary": "For new orchards: saplings, drip and fencing.",
        "minAmount": 100000,
        "maxAmount": 2500000,
        "rateMin": 8.5,
        "rateMax": 11,
        "tenureMinMonths": 36,
        "tenureMaxMonths": 84,
        "collateral": "No collateral up to Rs 2 lakh",
        "documents": ["aadhaar", "land_record", "project_report"],
        "states": [UP],
        "segments": ["farmer"],
    }
    body.update(overrides)
    return body


def lender(**details) -> str:
    """A bank on the platform, shared online."""
    return insert_profile(
        "partner_national", display_name="Branch Manager", organisation_name="Purvanchal Gramin Bank",
        details={"organisation_type": "bank", **details},
    )


def report_for(client, parcel_id: str) -> dict:
    created = client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json={
        "opportunityCode": "guava_meadow", "language": "en", "promoterName": "Ramesh Yadav",
    })
    assert created.status_code == 201, created.text
    return created.json()


def shared_loan(client, lender_id: str, **overrides) -> dict:
    become(lender_id)
    product = client.post("/api/v1/loans", json=loan_body(**overrides))
    assert product.status_code == 201, product.text
    shared = client.post(f"/api/v1/loans/{product.json()['id']}/share")
    assert shared.status_code == 200, shared.text
    return shared.json()


def apply(client, product_id: str, report_id: str | None, amount: float = 300000, **extra):
    return client.post("/api/v1/loan-applications", json={
        "productId": product_id, "reportId": report_id, "amountRequested": amount,
        "tenureMonths": 60, "applicantNote": "Drip is already in.", "shareContact": True, **extra,
    })


def decide(client, application_id: str, action: str, **extra):
    return client.post(f"/api/v1/loan-applications/{application_id}/decide", json={"action": action, **extra})


def events(kind: str) -> list[AppEvent]:
    with session_scope() as session:
        rows = list(session.scalars(select(AppEvent).where(AppEvent.event_type == kind)))
        session.expunge_all()
        return rows


# --------------------------------------------------------------------------- #
# On one device, taking turns
# --------------------------------------------------------------------------- #


def test_a_farmer_applies_with_a_report_and_the_lender_takes_it_to_disbursement(client, parcel_id):
    farmer = make_owner(client, farmer_body())
    report = report_for(client, parcel_id)
    bank = lender()
    product = shared_loan(client, bank)
    # One far away, for the wrong kind of project, that the farmer still sees below it.
    shared_loan(client, bank, purpose="dairy_livestock", title="Dairy loan", states=["27"])

    become(farmer["id"])
    offers = client.get("/api/v1/loans", params={"reportId": report["id"]}).json()
    assert [o["title"] for o in offers] == ["Orchard development loan", "Dairy loan"]
    assert offers[0]["match"] == {"score": 100, "reasons": ["purpose", "amount", "state"], "misses": []}
    assert set(offers[1]["match"]["misses"]) == {"purpose", "state"}

    applied = apply(client, product["id"], report["id"], amount=round(report["termLoan"]))
    assert applied.status_code == 201, applied.text
    application = applied.json()
    assert application["status"] == "submitted" and application["consent"] == {
        "report": True, "land": True, "contact": True}
    snapshot = application["snapshot"]
    assert snapshot["plan"]["reportNumber"] == report["reportNumber"] and snapshot["plan"]["kind"]
    assert snapshot["contact"]["phone"] and snapshot["land"]["areaHectares"] > 0 and "Varanasi" in snapshot["place"]
    # Asking twice is not two applications.
    assert apply(client, product["id"], report["id"]).status_code == 409
    assert client.get("/api/v1/loans", params={"reportId": report["id"]}).json()[0]["myApplicationId"] == application["id"]

    become(bank)
    inbox = client.get("/api/v1/loan-applications/desk").json()
    assert [a["id"] for a in inbox] == [application["id"]]
    assert inbox[0]["applicant"]["contact"] is not None  # consent given
    steps = [
        ("review", {}, "under_review"),
        ("documents", {"documents": ["bank_statement"], "note": "Six months of passbook, please."}, "documents_requested"),
        ("sanction", {"amount": 250000, "rate": 9.5, "tenureMonths": 60}, "sanctioned"),
        ("disburse", {"amount": 250000, "disbursedOn": date.today().isoformat()}, "disbursed"),
    ]
    for action, extra, status in steps:
        answer = decide(client, application["id"], action, **extra)
        assert answer.status_code == 200, (action, answer.text)
        assert answer.json()["status"] == status
    done = answer.json()
    assert done["sanctionedAmount"] == 250000 and done["disbursedAmount"] == 250000
    assert done["documentsRequested"] == ["bank_statement"] and done["lenderNote"] == "Six months of passbook, please."
    assert [e.payload["amount"] for e in events(EventType.LOAN_SANCTIONED)] == [250000]
    assert [e.payload["amount"] for e in events(EventType.LOAN_DISBURSED)] == [250000]
    counts = {p["id"]: p["applicationCounts"] for p in client.get("/api/v1/loans/mine").json()}
    assert counts[product["id"]] == {"disbursed": 1}

    become(farmer["id"])
    mine = client.get("/api/v1/loan-applications/mine").json()
    assert mine[0]["status"] == "disbursed" and mine[0]["lender"]["contact"] is not None
    assert len(events(EventType.LOAN_APPLIED)) == 1


def test_who_may_lend_apply_and_answer(client, parcel_id):
    farmer = make_owner(client, farmer_body())
    assert client.post("/api/v1/loans", json=loan_body()).status_code == 403  # a farmer does not lend
    roles = client.get("/api/v1/loans/roles").json()
    assert roles == {"lender": False, "applicant": True}

    seller = insert_profile("partner_national", organisation_name="Agro Inputs", details={"organisation_type": "input_supplier"})
    become(seller)
    assert client.post("/api/v1/loans", json=loan_body()).status_code == 403  # not a lender either

    bank = lender()
    become(bank)
    assert client.post("/api/v1/loans", json=loan_body(minAmount=900000, maxAmount=100000)).status_code == 422
    assert client.post("/api/v1/loans", json=loan_body(purpose="custom:Anything")).status_code == 422
    product = shared_loan(client, bank)
    assert apply(client, product["id"], None).status_code == 403  # a lender does not apply to itself

    become(farmer["id"])
    assert apply(client, product["id"], None, amount=5_000_000).status_code == 422  # beyond its range
    assert apply(client, product["id"], None, shareContact=False).status_code == 422
    application = apply(client, product["id"], None).json()
    assert application["consent"]["report"] is False and "plan" not in application["snapshot"]
    assert decide(client, application["id"], "sanction", amount=100000).status_code == 403
    assert decide(client, application["id"], "reply").status_code == 422
    assert decide(client, application["id"], "reply", note="Papers are at the branch.").json()["applicantNote"] == \
        "Papers are at the branch."

    become(bank)
    assert decide(client, application["id"], "withdraw").status_code == 403
    assert decide(client, application["id"], "disburse", amount=100000).status_code == 409  # not sanctioned
    assert decide(client, application["id"], "sanction").status_code == 422  # no amount
    future = (date.today() + timedelta(days=3)).isoformat()
    decide(client, application["id"], "sanction", amount=100000)
    assert decide(client, application["id"], "disburse", disbursedOn=future).status_code == 422

    become(farmer["id"])
    assert decide(client, application["id"], "withdraw").status_code == 409  # sanctioned: too late


def test_the_applicant_withdraws_and_may_apply_again(client):
    farmer = make_owner(client, farmer_body())
    bank = lender()
    product = shared_loan(client, bank)
    become(farmer["id"])
    first = apply(client, product["id"], None).json()
    assert decide(client, first["id"], "withdraw").json()["status"] == "withdrawn"
    assert apply(client, product["id"], None).status_code == 201


def test_a_paused_or_offline_loan_takes_no_applications(client):
    farmer = make_owner(client, farmer_body())
    bank = lender()
    product = shared_loan(client, bank)
    client.put(f"/api/v1/loans/{product['id']}", json=loan_body(status="paused"))
    become(farmer["id"])
    assert client.get("/api/v1/loans").json() == []
    assert apply(client, product["id"], None).status_code == 404


def test_the_data_export_lists_loans(client):
    farmer = make_owner(client, farmer_body())
    bank = lender()
    product = shared_loan(client, bank)
    become(farmer["id"])
    apply(client, product["id"], None)
    exported = client.get("/api/v1/my-data").json()
    assert len(exported["loan_applications"]) == 1


# --------------------------------------------------------------------------- #
# Through the sync server, between two devices
# --------------------------------------------------------------------------- #


@pytest.fixture()
def cloud(monkeypatch):
    module = fresh_sync_module(monkeypatch)
    server = TestClient(module.app)
    monkeypatch.setattr(sync_client, "HttpTransport", lambda url: ServerTransport(server))
    yield server, module
    sys.path.remove(str(SYNC_DIR))


BANK_ID = "a0000000-0000-0000-0000-00000000b001"
PRODUCT_ID = "e0000000-0000-0000-0000-00000000b001"


def bank_device(server) -> OtherDevice:
    bank = OtherDevice(server, {"id": BANK_ID, "segment": "partner_national"})
    bank.push({"entity_type": "profile", "entity_id": BANK_ID, "payload": {
        "id": BANK_ID, "segment": "partner_national", "display_name": "Branch Manager",
        "organisation_name": "Purvanchal Gramin Bank", "phone": "+915420000000", "country_code": "IN",
        "preferred_language": "en", "details": {"organisation_type": "bank"}, "visibility": "online",
        "state_code": UP,
    }})
    bank.push({"entity_type": "loan_product", "entity_id": PRODUCT_ID, "payload": {
        "id": PRODUCT_ID, "profile_id": BANK_ID, "purpose": "horticulture", "title": "Orchard loan",
        "min_amount": 100000, "max_amount": 2500000, "documents": ["aadhaar"], "states": [], "segments": ["farmer"],
        "status": "active", "visibility": "online",
    }})
    return bank


def test_an_application_travels_and_the_lenders_answer_comes_back(client, cloud):
    server, module = cloud
    bank = bank_device(server)
    make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    assert client.post("/api/v1/sync/run").status_code == 200

    offers = client.get("/api/v1/loans").json()
    assert [o["id"] for o in offers] == [PRODUCT_ID]
    application = apply(client, PRODUCT_ID, None).json()
    client.post("/api/v1/sync/run")

    pulled = [r for r in bank.pull() if r["entityType"] == "loan_application"]
    assert pulled and pulled[-1]["payload"]["snapshot"]["contact"]["phone"]
    payload = dict(pulled[-1]["payload"])

    # The bank sanctions -- and tries to lower what was asked for, which it may not.
    payload.update(status="sanctioned", sanctioned_amount=200000, interest_rate=9.0, sanctioned_tenure_months=60,
                   amount_requested=1, lender_note="Sanctioned; visit the branch.")
    assert bank.push({"entity_type": "loan_application", "entity_id": application["id"], "payload": payload})[
        "accepted"] == 1
    client.post("/api/v1/sync/run")

    mine = client.get("/api/v1/loan-applications/mine").json()[0]
    assert mine["status"] == "sanctioned" and mine["sanctionedAmount"] == 200000 and mine["interestRate"] == 9.0
    assert mine["amountRequested"] == 300000 and mine["lenderNote"] == "Sanctioned; visit the branch."
    with session_scope() as session:
        assert "loan_sanctioned" in set(session.scalars(select(Notification.kind)))


def test_an_applicant_cannot_mark_their_own_loan_paid(client, cloud):
    server, module = cloud
    bank_device(server)
    make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    client.post("/api/v1/sync/run")
    application = apply(client, PRODUCT_ID, None).json()
    with session_scope() as session:
        row = session.get(LoanApplication, application["id"])
        row.status, row.disbursed_amount, row.sanctioned_amount = "disbursed", 9_999_999, 9_999_999
    client.post("/api/v1/sync/run")
    with module.db() as con:
        stored = module.json.loads(module._stored(con, "loan_application", application["id"])["payload"])
    assert stored["status"] == "submitted" and stored.get("disbursed_amount") is None


def test_a_lender_cannot_apply_for_someone_nor_pay_out_before_sanctioning(cloud):
    server, module = cloud
    bank = bank_device(server)
    farmer = OtherDevice(server, {"id": "a0000000-0000-0000-0000-00000000f00d", "segment": "farmer"})
    forged = {"id": "c0000000-0000-0000-0000-00000000f00d", "product_id": PRODUCT_ID, "lender_profile_id": BANK_ID,
              "profile_id": farmer.profile["id"], "amount_requested": 100000, "status": "submitted"}
    answer = bank.push({"entity_type": "loan_application", "entity_id": forged["id"], "payload": forged})
    assert answer["rejected"]  # only the applicant applies

    assert farmer.push({"entity_type": "loan_application", "entity_id": forged["id"], "payload": forged})["accepted"]
    bank.push({"entity_type": "loan_application", "entity_id": forged["id"],
               "payload": {**forged, "status": "disbursed", "disbursed_amount": 100000}})
    with module.db() as con:
        stored = module.json.loads(module._stored(con, "loan_application", forged["id"])["payload"])
    assert stored["status"] == "submitted"  # not sanctioned, so not disbursed

    # A loan the server has never seen cannot be applied for.
    stray = {**forged, "id": "c0000000-0000-0000-0000-00000000f00e", "product_id": "nope"}
    assert farmer.push({"entity_type": "loan_application", "entity_id": stray["id"], "payload": stray})["rejected"]


def test_admin_sees_loans_per_lender(cloud, capsys):
    server, module = cloud
    bank = bank_device(server)
    farmer = OtherDevice(server, {"id": "a0000000-0000-0000-0000-00000000f00f", "segment": "farmer"})
    app_id = "c0000000-0000-0000-0000-00000000f00f"
    base = {"id": app_id, "product_id": PRODUCT_ID, "lender_profile_id": BANK_ID,
            "profile_id": farmer.profile["id"], "amount_requested": 300000}
    farmer.push({"entity_type": "loan_application", "entity_id": app_id, "payload": base})
    bank.push({"entity_type": "loan_application", "entity_id": app_id,
               "payload": {**base, "status": "sanctioned", "sanctioned_amount": 250000}})
    bank.push({"entity_type": "loan_application", "entity_id": app_id,
               "payload": {**base, "status": "disbursed", "sanctioned_amount": 250000, "disbursed_amount": 250000}})

    sys.modules.pop("admin", None)
    admin = importlib.import_module("admin")
    admin.server = module
    admin.loans_report(30)
    out = capsys.readouterr().out
    assert "Purvanchal Gramin Bank" in out and "Rs 250000" in out

"""Farmer groups, backups and personal data rights, and the insights dashboard."""

from __future__ import annotations

import io
import zipfile

from sqlalchemy import select

from app.db import session_scope
from app.models import Farmer, LandParcel, Profile

from .conftest import PINDRA, RAMPUR_BUJURG, UP, VARANASI, become
from .test_marketplace import insert_interest, insert_profile, insert_request, make_owner
from .test_profiles import farmer_body, government_body, investor_india_body, partner_national_body


def group_body(**overrides) -> dict:
    body = {
        "name": "Pindra Tomato Growers",
        "kind": "informal",
        "description": "Twelve neighbours growing tomato together.",
        "stateCode": UP,
        "districtCode": VARANASI,
        "subdistrictCode": PINDRA,
        "crops": ["tomato"],
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------- #
# Groups
# --------------------------------------------------------------------------- #


def test_a_group_pools_land_and_asks_for_investment(client):
    make_owner(client, farmer_body())
    group = client.post("/api/v1/groups", json=group_body()).json()
    assert group["isMine"] and group["memberCount"] == 0

    for name, hectares in (("Ram", 0.8), ("Shyam", 1.2), ("Geeta", 0.5)):
        response = client.post(
            f"/api/v1/groups/{group['id']}/members",
            json={"name": name, "phone": "98390 00001", "villageCode": RAMPUR_BUJURG, "landHectares": hectares, "crops": ["tomato", "chilli"]},
        )
        assert response.status_code == 201, response.text
    group = response.json()
    assert group["memberCount"] == 3 and group["totalHectares"] == 2.5
    assert group["members"][0]["phone"] == "+919839000001" and group["members"][0]["village"]

    response = client.post(
        f"/api/v1/groups/{group['id']}/requests",
        json={
            "opportunityCode": "open_field_vegetables",
            "title": "Tomato collection centre and crates for 3 families",
            "amountSought": 350000,
            "seeking": ["investment", "partnership"],
            "modes": ["revenue_share"],
            "partnershipTypes": ["buy_back"],
            "openTo": ["investor_india", "partner_national"],
        },
    )
    assert response.status_code == 201, response.text
    request = response.json()
    assert request["listing"]["land"]["areaHectares"] == 2.5
    assert request["listing"]["land"]["members"] == 3
    assert set(request["listing"]["land"]["existingCrops"]) == {"tomato", "chilli"}
    assert client.get(f"/api/v1/groups/{group['id']}").json()["requestIds"] == [request["id"]]


def test_group_needs_members_before_asking(client):
    make_owner(client, farmer_body())
    group = client.post("/api/v1/groups", json=group_body()).json()
    response = client.post(
        f"/api/v1/groups/{group['id']}/requests",
        json={"title": "x", "amountSought": 1000, "seeking": ["investment"], "modes": ["loan"], "openTo": ["investor_india"]},
    )
    assert response.status_code == 422


def test_farmers_join_a_shared_group(client):
    organiser = make_owner(client, farmer_body())
    group = client.post("/api/v1/groups", json=group_body()).json()
    client.post(f"/api/v1/groups/{group['id']}/share")

    joiner = insert_profile("farmer", display_name="Mohan", state_code=UP, district_code=VARANASI)
    become(joiner)
    visible = client.get("/api/v1/groups").json()
    assert [g["id"] for g in visible] == [group["id"]]
    joined = client.post(f"/api/v1/groups/{group['id']}/join", json={"landHectares": 1.1, "crops": ["tomato"]}).json()
    assert joined["myMembership"]["status"] == "requested"
    again = client.post(f"/api/v1/groups/{group['id']}/join", json={"landHectares": 1.1})
    assert again.status_code == 409

    become(organiser["id"])
    group = client.get(f"/api/v1/groups/{group['id']}").json()
    member = next(m for m in group["members"] if m["status"] == "requested")
    group = client.patch(f"/api/v1/groups/{group['id']}/members/{member['id']}", params={"status": "active"}).json()
    assert group["memberCount"] == 1 and group["totalHectares"] == 1.1


def test_who_may_run_a_group(client):
    make_owner(client, investor_india_body())
    assert client.post("/api/v1/groups", json=group_body()).status_code == 403
    client.delete("/api/v1/profile")
    fpo = partner_national_body()
    make_owner(client, fpo)
    assert client.post("/api/v1/groups", json=group_body(kind="fpo")).status_code == 201


# --------------------------------------------------------------------------- #
# Backup, export, erasure
# --------------------------------------------------------------------------- #


def test_backup_contains_the_database_and_can_be_staged(client, parcel_id):
    make_owner(client, farmer_body())
    backup = client.post("/api/v1/backups").json()
    assert backup["name"].startswith("viksitgaanw-backup-")
    assert "database.sqlite" in backup["includes"] and "manifest.json" in backup["includes"]
    assert [b["name"] for b in client.get("/api/v1/backups").json()] == [backup["name"]]

    download = client.get(f"/api/v1{backup['downloadPath']}")
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert "database.sqlite" in archive.namelist()

    staged = client.post("/api/v1/backups/restore", content=download.content)
    assert staged.status_code == 200 and staged.json()["staged"] is True
    from app.config import get_settings
    import shutil

    pending = get_settings().db_path.parent / "restore-pending"
    assert (pending / "database.sqlite").is_file()
    shutil.rmtree(pending)  # do not actually swap the test database

    assert client.post("/api/v1/backups/restore", content=b"not a zip").status_code == 422
    assert client.get("/api/v1/backups/..%2Fsecret.zip").status_code == 404


def test_export_my_data(client, parcel_id):
    make_owner(client, farmer_body())
    response = client.get("/api/v1/my-data")
    assert response.status_code == 200
    data = response.json()
    assert data["profile"]["display_name"] == "Ramesh Yadav"
    assert [p["id"] for p in data["land_parcels"]] == [parcel_id]


def test_erase_my_data_needs_the_phrase_and_removes_everything_mine(client, parcel_id):
    owner = make_owner(client, farmer_body())
    other = insert_profile("investor_india")
    assert client.post("/api/v1/my-data/erase", json={"confirm": "yes"}).status_code == 422

    response = client.post("/api/v1/my-data/erase", json={"confirm": "DELETE MY DATA"})
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/profile").json() is None
    with session_scope() as session:
        assert session.get(Profile, owner["id"]) is None
        assert session.scalars(select(LandParcel)).first() is None
        assert session.scalars(select(Farmer)).first() is None
        assert session.get(Profile, other) is not None, "other people's records stay"


# --------------------------------------------------------------------------- #
# Insights
# --------------------------------------------------------------------------- #


def test_insights_for_a_block_officer(client):
    make_owner(client, government_body())
    farmer_id = insert_profile("farmer", state_code=UP, district_code=VARANASI, subdistrict_code=PINDRA)
    here = insert_request(farmer_id, amount_sought=500000)
    insert_request(farmer_id, amount_sought=900000, state_code="27", district_code="992701", subdistrict_code=None)
    investor = insert_profile("investor_india")
    insert_interest(here, investor, status="accepted")

    insights = client.get("/api/v1/insights").json()
    assert insights["scope"] == "subdistrict" and insights["place"].startswith("Pindra")
    assert insights["requestsOpen"] == 1 and insights["amountSought"] == 500000
    assert insights["matches"] == 1
    assert insights["requestsByKind"][0]["code"] == "horticulture"


def test_insights_for_an_investor_are_national(client):
    make_owner(client, investor_india_body())
    farmer_id = insert_profile("farmer")
    insert_request(farmer_id)
    insert_request(farmer_id, state_code="27", district_code="992701", subdistrict_code=None)
    insights = client.get("/api/v1/insights").json()
    assert insights["scope"] == "national" and insights["requestsOpen"] == 2
    assert len(insights["requestsByState"]) == 2

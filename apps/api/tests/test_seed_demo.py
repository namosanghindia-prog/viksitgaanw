"""The sample-data script that stands in for cloud sync."""

from __future__ import annotations

from sqlalchemy import func, select

from app.db import session_scope
from app.models import InvestmentInterest, InvestmentRequest, Profile

from .test_marketplace import request_body
from .test_profiles import farmer_body, investor_india_body


def _count(model, **where) -> int:
    with session_scope() as session:
        stmt = select(func.count()).select_from(model)
        for field, value in where.items():
            stmt = stmt.where(getattr(model, field) == value)
        return session.scalar(stmt)


def test_seed_gives_an_investor_something_to_browse(client):
    import seed_demo_marketplace

    client.post("/api/v1/profile", json=investor_india_body())
    assert seed_demo_marketplace.main([]) == 0

    rows = client.get("/api/v1/investment-requests").json()
    assert rows, "the sample should include requests an Indian investor may see"
    assert all(row["origin"] == "demo" for row in rows)
    assert all(row["requester"]["contact"] is None for row in rows)
    statuses = {policy["status"] for row in rows for policy in row["insurance"]}
    assert statuses == {"insured", "planned"}, "the sample should show both kinds of cover"

    # Re-running replaces the sample rather than doubling it.
    before = _count(InvestmentRequest)
    seed_demo_marketplace.main([])
    assert _count(InvestmentRequest) == before


def test_seed_answers_a_farmers_own_request_and_removes_cleanly(client, parcel_id):
    import seed_demo_marketplace

    client.post("/api/v1/profile", json=farmer_body())
    client.post("/api/v1/investment-requests", json=request_body(parcel_id))
    seed_demo_marketplace.main([])

    [mine] = client.get("/api/v1/investment-requests/mine").json()
    kinds = sorted(interest["kind"] for interest in mine["interests"])
    assert kinds == ["investment", "partnership"]

    seed_demo_marketplace.main(["--remove"])
    assert _count(Profile, origin="demo") == 0
    assert _count(InvestmentInterest) == 0
    # The farmer's own profile and request are untouched.
    assert _count(Profile, is_device_owner=True) == 1
    assert _count(InvestmentRequest, origin="local") == 1

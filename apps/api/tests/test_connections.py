"""Connections, land shared with them, and farm updates."""

from __future__ import annotations

import io

from PIL import Image
from sqlalchemy import select

from app.db import session_scope
from app.models import Connection, LandShare

from .conftest import become
from .test_marketplace import insert_interest, insert_profile, insert_request, make_owner
from .test_profiles import farmer_body


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (640, 480), (40, 140, 60)).save(out, format="JPEG")
    return out.getvalue()


def timeline(client, **params) -> list[dict]:
    response = client.get("/api/v1/timeline", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def connect(client, me: str, other: str) -> None:
    """``me`` asks ``other``, and ``other`` accepts -- taking turns on one device."""
    become(me)
    asked = client.post("/api/v1/connections", json={"profileId": other, "message": "Neighbours in Pindra"})
    assert asked.status_code == 201, asked.text
    become(other)
    answered = client.patch(f"/api/v1/connections/{asked.json()['id']}", json={"status": "accepted"})
    assert answered.status_code == 200, answered.text
    become(me)


# --------------------------------------------------------------------------- #
# Connections
# --------------------------------------------------------------------------- #


def test_a_connection_needs_both_sides(client):
    me = make_owner(client, farmer_body())
    other = insert_profile("farmer", display_name="Mohan Lal", phone="+919811111111")

    asked = client.post("/api/v1/connections", json={"profileId": other})
    assert asked.status_code == 201, asked.text
    assert asked.json()["status"] == "requested" and asked.json()["sentByMe"]
    assert asked.json()["other"]["contact"] is None, "no phone number before they agree"
    again = client.post("/api/v1/connections", json={"profileId": other})
    assert again.status_code == 409

    overview = client.get("/api/v1/connections").json()
    assert [c["other"]["id"] for c in overview["outgoing"]] == [other]
    assert other not in [s["id"] for s in overview["suggestions"]]

    # Their side: it is waiting for an answer; only they can give it.
    become(other)
    incoming = client.get("/api/v1/connections").json()["incoming"]
    assert [c["other"]["id"] for c in incoming] == [me["id"]]
    card = client.get("/api/v1/connections").json()["incoming"][0]["other"]
    assert card["connection"]["state"] == "requested_by_them"
    accepted = client.patch(f"/api/v1/connections/{incoming[0]['id']}", json={"status": "accepted"})
    assert accepted.status_code == 200

    become(me["id"])
    [connected] = client.get("/api/v1/connections").json()["connected"]
    assert connected["via"] == "request"
    assert connected["other"]["contact"]["phone"] == "+919811111111"
    assert connected["other"]["connection"]["state"] == "connected"
    # Connected people may message each other.
    message = client.post(f"/api/v1/conversations/{other}/messages", json={"body": "Namaste"})
    assert message.status_code == 201, message.text


def test_asking_back_is_saying_yes(client):
    me = make_owner(client, farmer_body())
    other = insert_profile("investor_india")
    with session_scope() as session:
        session.add(Connection(requester_profile_id=other, addressee_profile_id=me["id"], origin="synced"))
    answer = client.post("/api/v1/connections", json={"profileId": other})
    assert answer.status_code == 201
    assert answer.json()["status"] == "accepted"


def test_rules_for_asking(client):
    client.post("/api/v1/profile", json=farmer_body())  # not shared online
    other = insert_profile("farmer")
    assert client.post("/api/v1/connections", json={"profileId": other}).status_code == 409
    client.post("/api/v1/profile/share")
    hidden = insert_profile("farmer", visibility="offline")
    assert client.post("/api/v1/connections", json={"profileId": hidden}).status_code == 404
    me = client.get("/api/v1/profile").json()["id"]
    assert client.post("/api/v1/connections", json={"profileId": me}).status_code == 422


def test_working_together_is_a_connection(client):
    farmer = make_owner(client, farmer_body())
    investor = insert_profile("investor_india", display_name="Priya")
    request_id = insert_request(farmer["id"], origin="local")
    insert_interest(request_id, investor, status="accepted")
    [connected] = client.get("/api/v1/connections").json()["connected"]
    assert connected["via"] == "work" and connected["links"] == ["interest"]


def test_ending_and_withdrawing(client):
    me = make_owner(client, farmer_body())
    other = insert_profile("farmer")
    asked = client.post("/api/v1/connections", json={"profileId": other}).json()
    assert client.delete(f"/api/v1/connections/{asked['id']}").status_code == 204
    assert client.get("/api/v1/connections").json()["outgoing"] == []

    # Asking again after withdrawing reuses the owner's own request.
    asked = client.post("/api/v1/connections", json={"profileId": other}).json()
    become(other)
    client.patch(f"/api/v1/connections/{asked['id']}", json={"status": "accepted"})
    # Either side may end it.
    assert client.delete(f"/api/v1/connections/{asked['id']}").status_code == 204
    become(me["id"])
    assert client.get("/api/v1/connections").json()["connected"] == []
    with session_scope() as session:
        assert len(session.scalars(select(Connection)).all()) == 1


# --------------------------------------------------------------------------- #
# Shared land
# --------------------------------------------------------------------------- #


def test_land_is_shared_with_connections_only(client, parcel_id):
    farmer = make_owner(client, farmer_body())
    friend = insert_profile("investor_india", display_name="Friend")
    stranger = insert_profile("investor_india", display_name="Stranger")

    shared = client.post(f"/api/v1/land-parcels/{parcel_id}/share")
    assert shared.status_code == 200, shared.text
    assert shared.json()["shareVisibility"] == "online"
    [mine] = [item for item in timeline(client) if item["type"] == "land"]
    card = mine["land"]
    assert card["isMine"] and card["label"] == "Ganga side plot"
    assert card["place"].startswith("Rampur Bujurg") and card["existingCrops"] == ["wheat", "rice"]
    assert "surveyNumber" not in card and "latitude" not in card, "private details stay on the plot"

    connect(client, farmer["id"], friend)
    become(friend)
    assert [i["land"]["id"] for i in timeline(client, kind="land")] == [parcel_id]
    assert client.get(f"/api/v1/land-shares/{parcel_id}").status_code == 200
    become(stranger)
    assert timeline(client, kind="land") == []
    assert client.get(f"/api/v1/land-shares/{parcel_id}").status_code == 404

    # Taken offline, nobody sees it.
    become(farmer["id"])
    client.post(f"/api/v1/land-parcels/{parcel_id}/unshare")
    become(friend)
    assert timeline(client, kind="land") == []


def test_sharing_land_needs_the_profile_online(client, parcel_id):
    client.post("/api/v1/profile", json=farmer_body())
    response = client.post(f"/api/v1/land-parcels/{parcel_id}/share")
    assert response.status_code == 409
    assert "profile online" in response.json()["detail"]


def test_editing_shared_land_updates_the_card(client, parcel_id):
    make_owner(client, farmer_body())
    client.post(f"/api/v1/land-parcels/{parcel_id}/share")

    # A private detail changes: connections see nothing new.
    client.patch(f"/api/v1/land-parcels/{parcel_id}", json={"surveyNumber": "999/1"})
    assert timeline(client, kind="land")[0]["land"]["changedAt"] is None

    client.patch(f"/api/v1/land-parcels/{parcel_id}", json={"existingCrops": ["tomato"]})
    card = timeline(client, kind="land")[0]["land"]
    assert card["changedAt"] and card["existingCrops"] == ["tomato"]

    photo = client.post(f"/api/v1/land-parcels/{parcel_id}/photos", content=jpeg(), headers={"Content-Type": "image/jpeg"})
    assert photo.status_code == 200 and len(photo.json()["photos"]) == 1
    assert len(timeline(client, kind="land")[0]["land"]["photos"]) == 1

    # Deleting the plot takes its card down.
    client.delete(f"/api/v1/land-parcels/{parcel_id}")
    assert timeline(client, kind="land") == []


def test_only_a_farmer_shares_land(client, parcel_id):
    from .test_profiles import investor_india_body

    make_owner(client, investor_india_body())
    assert client.post(f"/api/v1/land-parcels/{parcel_id}/share").status_code in (403, 404)


# --------------------------------------------------------------------------- #
# Updates
# --------------------------------------------------------------------------- #


def test_updates_reach_connections(client, parcel_id):
    farmer = make_owner(client, farmer_body())
    friend = insert_profile("farmer", display_name="Friend")
    stranger = insert_profile("farmer", display_name="Stranger")

    not_shared = client.post("/api/v1/updates", json={"body": "Sowing done", "landShareId": parcel_id})
    assert not_shared.status_code == 404, "the plot has to be shared first"
    client.post(f"/api/v1/land-parcels/{parcel_id}/share")
    posted = client.post("/api/v1/updates", json={"body": "  Sowing done on the Ganga side plot.  ", "landShareId": parcel_id})
    assert posted.status_code == 201, posted.text
    update = posted.json()
    assert update["body"] == "Sowing done on the Ganga side plot." and update["landLabel"] == "Ganga side plot"
    photo = client.post(f"/api/v1/updates/{update['id']}/photos", content=jpeg(), headers={"Content-Type": "image/jpeg"})
    assert len(photo.json()["photos"]) == 1
    general = client.post("/api/v1/updates", json={"body": "Tractor serviced for the season."})
    assert general.status_code == 201

    connect(client, farmer["id"], friend)
    become(friend)
    feed = timeline(client, kind="updates")
    assert [i["type"] for i in feed].count("update") == 2
    assert any(i["type"] == "land" and i["land"]["updates"] == 1 for i in feed)
    assert len(client.get("/api/v1/updates", params={"landShareId": parcel_id}).json()) == 1
    # Only the author can take an update down.
    assert client.delete(f"/api/v1/updates/{update['id']}").status_code == 404

    become(stranger)
    assert client.get("/api/v1/updates").json() == []

    become(farmer["id"])
    assert client.delete(f"/api/v1/updates/{update['id']}").status_code == 204
    assert len(client.get("/api/v1/updates").json()) == 1


def test_taking_the_profile_offline_takes_land_and_updates_with_it(client, parcel_id):
    make_owner(client, farmer_body())
    client.post(f"/api/v1/land-parcels/{parcel_id}/share")
    client.post("/api/v1/updates", json={"body": "First picking tomorrow."})
    client.post("/api/v1/profile/unshare")
    with session_scope() as session:
        assert session.get(LandShare, parcel_id).visibility == "offline"
    assert timeline(client, kind="updates") == []


def test_erasing_removes_connections_land_and_updates(client, parcel_id):
    make_owner(client, farmer_body())
    other = insert_profile("farmer")
    client.post("/api/v1/connections", json={"profileId": other})
    client.post(f"/api/v1/land-parcels/{parcel_id}/share")
    client.post("/api/v1/updates", json={"body": "Hello"})
    assert client.post("/api/v1/my-data/erase", json={"confirm": "DELETE MY DATA"}).status_code == 200
    with session_scope() as session:
        assert session.scalars(select(Connection)).first() is None
        assert session.scalars(select(LandShare)).first() is None

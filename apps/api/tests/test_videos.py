"""Introduction and biodata videos: YouTube links, and direct uploads through Mux."""

from __future__ import annotations

import importlib
import re
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, Notification, Profile, VideoUpload
from app.services import videos
from app.services.videos import VideoError, youtube_id

from .conftest import become
from .test_marketplace import insert_profile, insert_request, make_owner, request_body
from .test_profiles import farmer_body, investor_india_body, partner_national_body
from .test_sync import SYNC_DIR, OtherDevice, ServerTransport

VIDEO_ID = "dQw4w9WgXcQ"


def put(client, target: str, entity_id: str, url: str = f"https://youtu.be/{VIDEO_ID}"):
    return client.put(f"/api/v1/videos/{target}/{entity_id}", json={"url": url})


# --------------------------------------------------------------------------- #
# YouTube links
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "link",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/watch?feature=share&v={VIDEO_ID}&t=42",
        f"https://m.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}?si=abcdef",
        f"youtu.be/{VIDEO_ID}",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}?feature=share",
        f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}",
        f"  {VIDEO_ID}  ",
    ],
)
def test_every_kind_of_youtube_link(link):
    assert youtube_id(link) == VIDEO_ID


@pytest.mark.parametrize(
    "link",
    [
        "https://vimeo.com/123456",
        "https://www.youtube.com/channel/UC1234567890",
        "https://www.youtube.com/watch?v=short",
        "https://evil.example/watch?v=dQw4w9WgXcQ",
        "not a link",
    ],
)
def test_links_that_are_not_one_youtube_video(link):
    with pytest.raises(VideoError):
        youtube_id(link)


# --------------------------------------------------------------------------- #
# Setting videos
# --------------------------------------------------------------------------- #


def test_a_farmer_adds_videos_to_profile_plot_request_and_group(client, parcel_id):
    from .test_groups_data import group_body

    me = make_owner(client, farmer_body())
    assert put(client, "biodata", me["id"]).json() == {"provider": "youtube", "id": VIDEO_ID}
    assert client.get("/api/v1/profile").json()["biodataVideo"]["id"] == VIDEO_ID

    assert put(client, "land", parcel_id).status_code == 200
    assert client.get(f"/api/v1/land-parcels/{parcel_id}").json()["introVideo"]["id"] == VIDEO_ID

    request = client.post("/api/v1/investment-requests", json=request_body(parcel_id)).json()
    assert put(client, "request", request["id"], f"https://www.youtube.com/shorts/{VIDEO_ID}").status_code == 200
    assert client.get(f"/api/v1/investment-requests/{request['id']}").json()["introVideo"]["id"] == VIDEO_ID

    group = client.post("/api/v1/groups", json=group_body()).json()
    assert put(client, "group", group["id"]).status_code == 200
    assert client.get(f"/api/v1/groups/{group['id']}").json()["introVideo"]["id"] == VIDEO_ID

    # A farmer has no investor listing to put a video on.
    assert put(client, "listing", me["id"]).status_code == 403

    assert client.delete(f"/api/v1/videos/biodata/{me['id']}").status_code == 204
    assert client.get("/api/v1/profile").json()["biodataVideo"] is None
    with session_scope() as session:
        kinds = list(session.scalars(select(AppEvent.event_type)))
    assert kinds.count("video.set") == 4 and "video.removed" in kinds


def test_an_investor_listing_and_a_machine_carry_videos(client):
    from .test_sharing_equipment import machine

    me = make_owner(client, partner_national_body())
    assert put(client, "listing", me["id"]).status_code == 403, "a partner that does not invest has no listing"
    body = partner_national_body()
    body["details"].update(alsoInvests=True, investmentModes=["revenue_share"])
    assert client.put("/api/v1/profile", json=body).status_code == 200
    assert put(client, "listing", me["id"]).status_code == 200
    assert client.get("/api/v1/profile").json()["introVideo"]["id"] == VIDEO_ID

    listing = client.post("/api/v1/equipment", json=machine()).json()
    assert put(client, "machine", listing["id"]).status_code == 200
    assert client.get(f"/api/v1/equipment/{listing['id']}").json()["introVideo"]["id"] == VIDEO_ID


def test_only_the_owner_changes_a_video(client, parcel_id):
    make_owner(client, farmer_body())
    someone = insert_profile("farmer", display_name="Someone else")
    their_request = insert_request(someone)
    assert put(client, "request", their_request).status_code == 403
    assert put(client, "biodata", someone).status_code == 403
    assert put(client, "nonsense", parcel_id).status_code == 404
    assert put(client, "land", "no-such-plot").status_code == 404
    bad = put(client, "land", parcel_id, "https://vimeo.com/1")
    assert bad.status_code == 422 and "YouTube" in bad.json()["detail"]


def test_the_shared_plot_card_shows_its_video(client, parcel_id):
    make_owner(client, farmer_body())
    client.post(f"/api/v1/land-parcels/{parcel_id}/share")
    put(client, "land", parcel_id)
    [item] = client.get("/api/v1/timeline", params={"kind": "land"}).json()
    assert item["land"]["introVideo"] == {"provider": "youtube", "id": VIDEO_ID}


def test_a_biodata_video_shows_on_the_card_of_someone_else(client):
    make_owner(client, investor_india_body())
    farmer = insert_profile("farmer", display_name="Ramesh", biodata_video={"provider": "youtube", "id": VIDEO_ID})
    insert_request(farmer)
    [request] = client.get("/api/v1/investment-requests").json()
    assert request["requester"]["biodataVideo"]["id"] == VIDEO_ID


# --------------------------------------------------------------------------- #
# Through sync
# --------------------------------------------------------------------------- #


class FakeMux:
    """Mux's API, as far as direct uploads go."""

    configured = True

    def __init__(self) -> None:
        self.uploads: dict[str, dict] = {}
        self.assets: dict[str, dict] = {}

    def create_upload(self, passthrough: str) -> dict:
        upload_id = f"upload{len(self.uploads) + 1}"
        self.uploads[upload_id] = {
            "id": upload_id, "url": f"https://storage.test/{upload_id}", "status": "waiting",
            "passthrough": passthrough,
        }
        return self.uploads[upload_id]

    def get_upload(self, upload_id: str) -> dict:
        return self.uploads[upload_id]

    def get_asset(self, asset_id: str) -> dict:
        return self.assets[asset_id]


class FakeStorage:
    """The address Mux hands out: takes a file in Content-Range pieces."""

    def __init__(self, mux: FakeMux) -> None:
        self.mux = mux
        self.received: dict[str, bytearray] = {}
        self.drop_after: int | None = None
        self.calls = 0

    def __call__(self, url: str, body: bytes, headers: dict) -> tuple[int, dict]:
        self.calls += 1
        held = self.received.setdefault(url, bytearray())
        if headers["Content-Range"].startswith("bytes */"):
            return 308, ({"range": f"bytes=0-{len(held) - 1}"} if held else {})
        if self.drop_after is not None and self.calls > self.drop_after:
            self.drop_after = None
            raise OSError("connection reset")
        start, end, total = map(int, re.match(r"bytes (\d+)-(\d+)/(\d+)", headers["Content-Range"]).groups())
        assert start == len(held), "pieces arrive in order, with nothing missing"
        held.extend(body)
        if end + 1 < total:
            return 308, {"range": f"bytes=0-{end}"}
        upload_id = url.rsplit("/", 1)[1]
        self.mux.uploads[upload_id].update(status="asset_created", asset_id=f"asset-{upload_id}")
        self.mux.assets[f"asset-{upload_id}"] = {"status": "preparing", "playback_ids": []}
        return 201, {}


@pytest.fixture()
def cloud(monkeypatch):
    """A sync server with a fake Mux, and this device pointed at it."""
    monkeypatch.setenv("VG_SYNC_DB", str(Path(tempfile.mkdtemp()) / "sync.db"))
    sys.path.insert(0, str(SYNC_DIR))
    module = importlib.reload(importlib.import_module("server"))
    module.mux = FakeMux()
    storage = FakeStorage(module.mux)
    monkeypatch.setattr(videos, "put_chunk", storage)
    monkeypatch.setattr(videos, "CHUNK_BYTES", 256 * 1024)
    monkeypatch.setattr(videos, "CHECK_EVERY_SECONDS", 0)
    server = TestClient(module.app)
    yield server, module, storage
    sys.path.remove(str(SYNC_DIR))


def sync(transport) -> None:
    from app.services import sync_client

    with session_scope() as session:
        sync_client.run(session, transport)


def check_plan(transport) -> dict:
    with session_scope() as session:
        return videos.plan(session, transport).model_dump(by_alias=True)


def work(transport) -> int:
    with session_scope() as session:
        return videos.work(session, transport)


def subscribe(module, profile_id: str, until: str | None = None) -> None:
    with module.db() as con:
        con.execute(
            "INSERT OR REPLACE INTO subscriptions (profile_id, plan, until, created_at) VALUES (?, 'video', ?, ?)",
            (profile_id, until, module._now()),
        )


def video_bytes(size: int = 700 * 1024) -> bytes:
    return bytes(i % 251 for i in range(size))


def test_a_youtube_video_travels_with_what_it_is_on(client, cloud, parcel_id):
    server, _, _ = cloud
    transport = ServerTransport(server)
    me = make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    put(client, "biodata", me["id"])
    request = client.post("/api/v1/investment-requests", json=request_body(parcel_id)).json()
    put(client, "request", request["id"])
    client.post(f"/api/v1/investment-requests/{request['id']}/share")
    sync(transport)

    other = OtherDevice(server, {"id": "a0000000-0000-0000-0000-00000000000b", "segment": "investor_india"})
    pulled = {r["entityType"]: r["payload"] for r in other.pull()}
    assert pulled["profile"]["biodata_video"] == {"provider": "youtube", "id": VIDEO_ID}
    assert pulled["investment_request"]["intro_video"] == {"provider": "youtube", "id": VIDEO_ID}


def test_direct_upload_is_for_subscribers(client, cloud):
    server, module, _ = cloud
    transport = ServerTransport(server)
    me = make_owner(client, farmer_body())
    assert check_plan(transport)["reason"] == "sync_off"

    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    plan = check_plan(transport)
    assert plan["subscribed"] is False and plan["reason"] == "not_subscribed"
    refused = client.post(f"/api/v1/videos/biodata/{me['id']}/upload", content=video_bytes(1024),
                          headers={"Content-Type": "video/mp4"})
    assert refused.status_code == 402

    subscribe(module, me["id"], until="2020-01-01")
    assert check_plan(transport)["subscribed"] is False, "an expired subscription does not count"
    subscribe(module, me["id"])
    plan = check_plan(transport)
    assert plan["subscribed"] is True and plan["uploadsAvailable"] is True and plan["reason"] is None

    wrong_type = client.post(f"/api/v1/videos/biodata/{me['id']}/upload", content=b"%PDF",
                             headers={"Content-Type": "application/pdf"})
    assert wrong_type.status_code == 415


def test_a_subscriber_uploads_a_video_and_it_plays_everywhere(client, cloud):
    server, module, storage = cloud
    transport = ServerTransport(server)
    me = make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    subscribe(module, me["id"])
    check_plan(transport)

    data = video_bytes()
    started = client.post(f"/api/v1/videos/biodata/{me['id']}/upload", content=data,
                          headers={"Content-Type": "video/mp4"})
    assert started.status_code == 201, started.text
    assert started.json()["status"] == "queued" and started.json()["size"] == len(data)

    assert work(transport) == 1, "sent, and waiting for Mux to process it"
    [upload] = client.get("/api/v1/videos/uploads").json()
    assert upload["status"] == "processing" and upload["progress"] == 100
    assert bytes(storage.received["https://storage.test/upload1"]) == data
    assert module.mux.uploads["upload1"]["passthrough"] == f"{me['id']}:biodata:{me['id']}"
    with session_scope() as session:
        assert not videos.upload_path(session.get(VideoUpload, upload["id"])).exists(), "the file is not kept"

    work(transport)
    assert client.get("/api/v1/profile").json()["biodataVideo"] is None, "not until Mux has it ready"

    module.mux.assets["asset-upload1"] = {"status": "ready", "playback_ids": [{"id": "play123", "policy": "public"}]}
    assert work(transport) == 0
    assert client.get("/api/v1/profile").json()["biodataVideo"] == {"provider": "mux", "id": "play123"}
    with session_scope() as session:
        assert "video_ready" in list(session.scalars(select(Notification.kind)))
        assert "video.uploaded" in list(session.scalars(select(AppEvent.event_type)))

    sync(transport)
    other = OtherDevice(server, {"id": "a0000000-0000-0000-0000-00000000000c", "segment": "investor_india"})
    [profile] = [r["payload"] for r in other.pull() if r["entityType"] == "profile"]
    assert profile["biodata_video"] == {"provider": "mux", "id": "play123"}


def test_an_interrupted_upload_carries_on_where_it_stopped(client, cloud):
    server, module, storage = cloud
    transport = ServerTransport(server)
    me = make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    subscribe(module, me["id"])
    check_plan(transport)

    data = video_bytes()
    client.post(f"/api/v1/videos/biodata/{me['id']}/upload", content=data, headers={"Content-Type": "video/mp4"})
    storage.drop_after = 1  # the connection drops after the first piece
    work(transport)
    [upload] = client.get("/api/v1/videos/uploads").json()
    assert upload["status"] == "uploading" and 0 < upload["progress"] < 100
    assert "interrupted" in upload["error"]

    work(transport)
    assert bytes(storage.received["https://storage.test/upload1"]) == data
    assert client.get("/api/v1/videos/uploads").json()[0]["status"] == "processing"


def test_uploads_wait_while_the_server_has_them_switched_off(client, cloud):
    server, module, _ = cloud
    transport = ServerTransport(server)
    me = make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    subscribe(module, me["id"])
    check_plan(transport)
    client.post(f"/api/v1/videos/biodata/{me['id']}/upload", content=video_bytes(1024),
                headers={"Content-Type": "video/mp4"})

    module.mux.configured = False
    assert check_plan(transport)["reason"] == "server_off"
    work(transport)
    [upload] = client.get("/api/v1/videos/uploads").json()
    assert upload["status"] == "queued" and "not switched on" in upload["error"]


def test_a_youtube_link_replaces_an_upload_still_on_its_way(client, cloud):
    server, module, _ = cloud
    transport = ServerTransport(server)
    me = make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    subscribe(module, me["id"])
    check_plan(transport)
    client.post(f"/api/v1/videos/biodata/{me['id']}/upload", content=video_bytes(1024),
                headers={"Content-Type": "video/mp4"})
    put(client, "biodata", me["id"])
    [upload] = client.get("/api/v1/videos/uploads").json()
    assert upload["status"] == "failed" and "Replaced" in upload["error"]
    assert work(transport) == 0
    assert client.get("/api/v1/profile").json()["biodataVideo"]["provider"] == "youtube"


def test_admin_command_manages_subscriptions(client, cloud, capsys):
    server, module, _ = cloud
    sys.modules.pop("admin", None)
    admin = importlib.import_module("admin")
    admin.server = module
    OtherDevice(server, {"id": "a0000000-0000-0000-0000-00000000000d", "segment": "farmer"})

    admin.subscribe("a0000000-0000-0000-0000-00000000000d", "video", "2030-12-31")
    with module.db() as con:
        assert module.subscription(con, "a0000000-0000-0000-0000-00000000000d")["active"] is True
    admin.list_profiles()
    assert "2030-12-31" in capsys.readouterr().out
    admin.unsubscribe("a0000000-0000-0000-0000-00000000000d")
    with module.db() as con:
        assert module.subscription(con, "a0000000-0000-0000-0000-00000000000d") is None
    with pytest.raises(SystemExit):
        admin.subscribe("not-registered", "video", None)


def test_erasing_removes_pending_uploads(client, cloud):
    server, module, _ = cloud
    transport = ServerTransport(server)
    me = make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    subscribe(module, me["id"])
    check_plan(transport)
    client.post(f"/api/v1/videos/biodata/{me['id']}/upload", content=video_bytes(1024),
                headers={"Content-Type": "video/mp4"})
    with session_scope() as session:
        path = videos.upload_path(session.scalars(select(VideoUpload)).one())
    assert path.exists()
    assert client.post("/api/v1/my-data/erase", json={"confirm": "DELETE MY DATA"}).status_code == 200
    assert not path.exists()
    with session_scope() as session:
        assert session.scalars(select(VideoUpload)).first() is None
        assert session.scalars(select(Profile)).first() is None

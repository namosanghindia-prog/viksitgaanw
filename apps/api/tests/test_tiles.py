"""Offline map tiles served straight out of an MBTiles file.

An MBTiles pack is SQLite, so the app can read one with no tile server and no
extra dependency. The one thing that is easy to get wrong is the row order:
MBTiles counts rows bottom-up (TMS) while web maps count top-down (XYZ), and
getting it backwards produces a map that looks plausible but is mirrored
vertically.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routers import tiles as tiles_router

# Distinct payloads so a test can prove *which* tile came back.
TILE_TOP = b"\x89PNG-top"
TILE_BOTTOM = b"\x89PNG-bottom"


def _make_mbtiles(path: Path) -> None:
    """A minimal zoom-1 pack with two tiles in the same column."""
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    connection.executemany(
        "INSERT INTO metadata VALUES (?, ?)",
        [
            ("name", "Test pack"),
            ("format", "png"),
            ("minzoom", "0"),
            ("maxzoom", "1"),
            ("bounds", "68.0,8.0,97.0,37.0"),
            ("attribution", "Test data"),
        ],
    )
    connection.execute(
        "CREATE TABLE tiles ("
        "zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
    )
    # At zoom 1 there are two rows. TMS row 1 is the *top* half of the world.
    connection.executemany(
        "INSERT INTO tiles VALUES (?, ?, ?, ?)",
        [
            (1, 0, 1, TILE_TOP),
            (1, 0, 0, TILE_BOTTOM),
        ],
    )
    connection.commit()
    connection.close()


@pytest.fixture()
def tile_client(tmp_path, monkeypatch):
    """A client whose settings point at a temporary tile pack."""
    pack = tmp_path / "test.mbtiles"
    _make_mbtiles(pack)

    settings = get_settings()
    monkeypatch.setattr(settings, "tiles_path", pack)
    tiles_router._metadata.cache_clear()
    yield TestClient(app)
    tiles_router._metadata.cache_clear()


@pytest.fixture()
def no_tiles_client(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tiles_path", None)
    tiles_router._metadata.cache_clear()
    yield TestClient(app)
    tiles_router._metadata.cache_clear()


def test_status_reports_an_installed_pack(tile_client):
    body = tile_client.get("/api/v1/tiles/status").json()
    assert body["available"] is True
    assert body["name"] == "Test pack"
    assert body["minZoom"] == 0
    assert body["maxZoom"] == 1
    assert body["bounds"] == [68.0, 8.0, 97.0, 37.0]
    assert body["attribution"] == "Test data"


def test_status_reports_no_pack(no_tiles_client):
    """The UI uses this to decide whether it may fall back to online imagery."""
    body = no_tiles_client.get("/api/v1/tiles/status").json()
    assert body["available"] is False


def test_xyz_y_is_flipped_to_tms_row(tile_client):
    """XYZ y=0 is the top of the world; in MBTiles that is the highest row.

    Getting this backwards yields a vertically mirrored map, which is subtle
    enough to ship unnoticed.
    """
    top = tile_client.get("/api/v1/tiles/1/0/0")
    bottom = tile_client.get("/api/v1/tiles/1/0/1")
    assert top.content == TILE_TOP
    assert bottom.content == TILE_BOTTOM


def test_tile_is_served_with_its_declared_content_type(tile_client):
    response = tile_client.get("/api/v1/tiles/1/0/0")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert "max-age" in response.headers["cache-control"]


def test_a_hole_in_the_pack_returns_a_blank_tile(tile_client):
    """Edges of a downloaded region are legitimately empty; a 404 there would
    litter the map with broken-image icons."""
    response = tile_client.get("/api/v1/tiles/1/1/1")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_requesting_a_tile_with_no_pack_installed_is_a_404(no_tiles_client):
    assert no_tiles_client.get("/api/v1/tiles/1/0/0").status_code == 404


@pytest.mark.parametrize(("z", "x", "y"), [(1, 2, 0), (1, 0, 2), (1, -1, 0)])
def test_coordinates_outside_the_zoom_grid_are_refused(tile_client, z, x, y):
    assert tile_client.get(f"/api/v1/tiles/{z}/{x}/{y}").status_code == 400


def test_absurd_zoom_is_refused(tile_client):
    """Guards the 1 << z shift from being handed something enormous."""
    assert tile_client.get("/api/v1/tiles/40/0/0").status_code == 400

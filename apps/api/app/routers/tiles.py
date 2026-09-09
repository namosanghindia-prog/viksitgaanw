"""Offline map tiles.

An MBTiles file is just SQLite, which this app already speaks, so a downloaded
tile pack can be served straight off the villager's disk with no tile server
process and no new dependency.

Nothing here reaches the internet. If no tile pack is installed the status
endpoint says so and the UI falls back to online imagery, which is fine for a
prototype but is not what should ship to a field device.
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from ..config import get_settings
from ..schemas import TileStatusOut

router = APIRouter(prefix="/tiles", tags=["tiles"])

#: A 1x1 transparent PNG, returned for tiles that the pack does not contain.
#: Leaflet would otherwise render broken-image icons across the empty area.
_BLANK_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c63000100000500010d0a2db4000000"
    "0049454e44ae426082"
)

_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "pbf": "application/x-protobuf",
}


def _tiles_path() -> Path | None:
    path = get_settings().tiles_path
    return path if path and path.is_file() else None


@lru_cache(maxsize=1)
def _metadata(path_str: str, mtime: float) -> dict[str, str]:
    """Read the MBTiles metadata table.

    Keyed on mtime so replacing the tile pack invalidates the cache.
    """
    del mtime  # only part of the cache key
    with sqlite3.connect(f"file:{path_str}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT name, value FROM metadata").fetchall()
    return {name: value for name, value in rows}


def _open_tiles(path: Path) -> sqlite3.Connection:
    # Read-only: a tile pack is reference data and must never be written to.
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)


@router.get("/status", response_model=TileStatusOut)
def tile_status() -> TileStatusOut:
    """Tell the UI whether offline imagery is installed."""
    path = _tiles_path()
    if path is None:
        return TileStatusOut(
            available=False,
            path=str(get_settings().tiles_path) if get_settings().tiles_path else None,
        )

    try:
        meta = _metadata(path.as_posix(), path.stat().st_mtime)
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=500, detail=f"Tile pack could not be read: {exc}"
        ) from exc

    def _as_int(key: str) -> int | None:
        try:
            return int(meta[key])
        except (KeyError, TypeError, ValueError):
            return None

    bounds: list[float] | None = None
    if "bounds" in meta:
        try:
            parsed = [float(part) for part in meta["bounds"].split(",")]
            bounds = parsed if len(parsed) == 4 else None
        except ValueError:
            bounds = None

    return TileStatusOut(
        available=True,
        path=str(path),
        name=meta.get("name"),
        format=meta.get("format", "png"),
        min_zoom=_as_int("minzoom"),
        max_zoom=_as_int("maxzoom"),
        bounds=bounds,
        attribution=meta.get("attribution"),
    )


@router.get("/{z}/{x}/{y}")
def get_tile(z: int, x: int, y: int) -> Response:
    """Serve one tile from the installed pack."""
    path = _tiles_path()
    if path is None:
        raise HTTPException(status_code=404, detail="No offline tile pack installed.")

    if not (0 <= z <= 24):
        raise HTTPException(status_code=400, detail="Zoom out of range.")
    span = 1 << z
    if not (0 <= x < span and 0 <= y < span):
        raise HTTPException(status_code=400, detail="Tile coordinates out of range.")

    meta = _metadata(path.as_posix(), path.stat().st_mtime)
    tile_format = (meta.get("format") or "png").lower()

    # MBTiles indexes rows bottom-up (TMS); web maps count top-down (XYZ).
    flipped_y = span - 1 - y

    connection = _open_tiles(path)
    try:
        row = connection.execute(
            "SELECT tile_data FROM tiles "
            "WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
            (z, x, flipped_y),
        ).fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"Tile read failed: {exc}") from exc
    finally:
        connection.close()

    if row is None:
        # A hole in the pack is normal at the edges of a downloaded region.
        return Response(
            content=_BLANK_PNG,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    return Response(
        content=row[0],
        media_type=_CONTENT_TYPES.get(tile_format, "application/octet-stream"),
        # Tiles are immutable for the life of a pack.
        headers={"Cache-Control": "public, max-age=604800"},
    )

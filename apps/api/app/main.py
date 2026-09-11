"""ViksitGaanw local API.

This process runs on the villager's own device. It is bound to loopback only:
the "server" is the user's own laptop or phone, and nothing here is meant to be
reachable from the network.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import init_db
from .routers import (
    data,
    directory,
    equipment,
    farm,
    geo,
    groups,
    health,
    inbox,
    insurance,
    kyc,
    land,
    locations,
    marketplace,
    markets,
    media,
    opportunities,
    profiles,
    promotion,
    reports,
    social,
    subscription,
    sync,
    tiles,
    trust,
    videos,
)

logger = logging.getLogger("viksitgaanw")

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    init_db()
    logger.info("ViksitGaanw API ready. Database: %s", settings.db_path)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Offline-first local API for the ViksitGaanw agricultural OS.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(locations.router, prefix=API_PREFIX)
    app.include_router(land.router, prefix=API_PREFIX)
    app.include_router(tiles.router, prefix=API_PREFIX)
    app.include_router(geo.router, prefix=API_PREFIX)
    app.include_router(opportunities.router, prefix=API_PREFIX)
    app.include_router(reports.router, prefix=API_PREFIX)
    app.include_router(profiles.router, prefix=API_PREFIX)
    app.include_router(marketplace.router, prefix=API_PREFIX)
    app.include_router(insurance.router, prefix=API_PREFIX)
    app.include_router(profiles.known_router, prefix=API_PREFIX)
    app.include_router(media.router, prefix=API_PREFIX)
    app.include_router(equipment.router, prefix=API_PREFIX)
    app.include_router(inbox.router, prefix=API_PREFIX)
    app.include_router(trust.router, prefix=API_PREFIX)
    app.include_router(farm.router, prefix=API_PREFIX)
    app.include_router(markets.router, prefix=API_PREFIX)
    app.include_router(groups.router, prefix=API_PREFIX)
    app.include_router(data.router, prefix=API_PREFIX)
    app.include_router(sync.router, prefix=API_PREFIX)
    app.include_router(social.router, prefix=API_PREFIX)
    app.include_router(videos.router, prefix=API_PREFIX)
    app.include_router(directory.router, prefix=API_PREFIX)
    app.include_router(subscription.router, prefix=API_PREFIX)
    app.include_router(kyc.router, prefix=API_PREFIX)
    app.include_router(promotion.router, prefix=API_PREFIX)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": settings.app_name, "version": settings.version, "docs": "/docs"}

    return app


app = create_app()


def main() -> None:
    """Entry point used by the Electron shell and ``python -m app.main``."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()

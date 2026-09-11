"""Runtime configuration for the local ViksitGaanw API.

Every setting can be overridden with a ``VG_``-prefixed environment variable so
the Electron shell can point the backend at the user's own data directory when
the app is packaged, without changing any code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .../apps/api/app/config.py -> app -> api -> apps -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VG_", env_file=".env", extra="ignore")

    app_name: str = "ViksitGaanw API"
    version: str = "0.1.0"

    #: Where the offline SQLite database lives. The Electron main process
    #: overrides this with the OS user-data directory in a packaged build.
    db_path: Path = REPO_ROOT / "apps" / "api" / "data" / "viksitgaanw.db"

    #: Bilingual reference lists shared with the frontend.
    reference_dir: Path = REPO_ROOT / "packages" / "shared" / "reference"

    #: Curated farming/business knowledge base and the DPR translation
    #: catalogues. Shared with the frontend the same way the reference lists
    #: are, so a card in the UI and a line in the PDF cannot disagree.
    knowledge_dir: Path = REPO_ROOT / "packages" / "shared" / "knowledge"

    #: Fonts used to render project reports in Indian scripts. Populated by
    #: scripts/fetch_fonts.py; on Windows the bundled Nirmala UI is used as a
    #: fallback so a fresh install can still print Hindi without a download.
    fonts_dir: Path = REPO_ROOT / "data" / "fonts"

    #: Where generated project reports are written. Overridden by the Electron
    #: shell to the OS user-data directory in a packaged build, for the same
    #: reason the database is.
    reports_dir: Path = REPO_ROOT / "apps" / "api" / "data" / "reports"

    #: Profile photos and equipment pictures. Left unset, they sit in a
    #: ``media`` folder beside the database, so they follow it into the OS
    #: user-data directory in a packaged build -- and into a test's temp dir.
    media_dir_override: Path | None = Field(default=None, alias="VG_MEDIA_DIR")

    #: Optional offline map tile pack (MBTiles). When absent the map falls
    #: back to online imagery, which is fine for a prototype but not for a
    #: field device.
    tiles_path: Path | None = REPO_ROOT / "data" / "tiles" / "india.mbtiles"

    host: str = "127.0.0.1"
    port: int = 8756

    #: Vite dev server + the packaged Electron origin.
    cors_origins: list[str] = [
        "http://localhost:5273",
        "http://127.0.0.1:5273",
        "app://viksitgaanw",
    ]

    #: Cap on rows returned by list endpoints; villages alone number ~660k.
    max_page_size: int = 500

    #: Whether the device may reach the internet for the few features that
    #: genuinely cannot work offline: coarse position from the network, and
    #: reverse geocoding a dropped pin into a place name. Everything else in
    #: this app works with the radio switched off. Set VG_ALLOW_NETWORK=false
    #: to forbid it outright.
    allow_network: bool = True

    #: Seconds to wait on any outbound call. Kept short: a villager pressing
    #: "find me" on a dead connection must get an answer, not a spinner.
    network_timeout_seconds: float = 6.0

    #: Free key from data.gov.in, for pulling Agmarknet mandi prices. Without
    #: one, prices can still be imported from a downloaded CSV.
    data_gov_api_key: str | None = None

    #: Where backups are written. Beside the database by default, which in a
    #: packaged build is the OS user-data directory.
    backups_dir_override: Path | None = Field(default=None, alias="VG_BACKUPS_DIR")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def media_dir(self) -> Path:
        return self.media_dir_override or self.db_path.parent / "media"

    @property
    def backups_dir(self) -> Path:
        return self.backups_dir_override or self.db_path.parent / "backups"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    return settings

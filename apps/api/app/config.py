"""Runtime configuration for the local ViksitGaanw API.

Every setting can be overridden with a ``VG_``-prefixed environment variable so
the Electron shell can point the backend at the user's own data directory when
the app is packaged, without changing any code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return settings

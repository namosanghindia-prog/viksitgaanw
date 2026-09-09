#!/usr/bin/env python
"""Create the local SQLite database and its schema.

Safe to run repeatedly: existing tables are left alone. The LGD hierarchy is
loaded separately by ``scripts/import_lgd.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.config import get_settings  # noqa: E402
from app.db import init_db  # noqa: E402


def main() -> int:
    settings = get_settings()
    init_db()
    print(f"Database ready: {settings.db_path}")
    print("Next: python scripts/import_lgd.py --sample")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

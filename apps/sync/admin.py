"""Manage subscriptions on the sync server by hand, until payments exist.

    python apps/sync/admin.py list
    python apps/sync/admin.py subscribe <profile-id> [--plan video] [--until 2027-03-31]
    python apps/sync/admin.py unsubscribe <profile-id>

A subscription lets its profile upload videos directly (through Mux) instead
of linking them on YouTube. It works on the same database as the server
(``VG_SYNC_DB``), so run it where the server runs. Profile ids are listed by
``list``, next to the names people gave.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import server  # noqa: E402


def _names(con) -> dict[str, str]:
    names = {}
    for row in con.execute("SELECT entity_id, payload FROM records WHERE entity_type = 'profile' AND deleted = 0"):
        payload = json.loads(row["payload"])
        names[row["entity_id"]] = payload.get("organisation_name") or payload.get("display_name") or ""
    return names


def list_profiles() -> None:
    with server.db() as con:
        names = _names(con)
        subscribed = {row["profile_id"]: row for row in con.execute("SELECT * FROM subscriptions")}
        devices = con.execute("SELECT profile_id, segment, last_seen FROM devices ORDER BY created_at").fetchall()
    print(f"{'profile id':38} {'segment':22} {'plan':8} {'until':12} name")
    for device in devices:
        plan = subscribed.get(device["profile_id"])
        print(
            f"{device['profile_id']:38} {device['segment']:22} "
            f"{(plan['plan'] if plan else '-'):8} {((plan['until'] or 'no end') if plan else '-'):12} "
            f"{names.get(device['profile_id'], '')}"
        )
    print(f"\nMux uploads: {'on' if server.mux.configured else 'off (set MUX_TOKEN_ID and MUX_TOKEN_SECRET)'}")


def subscribe(profile_id: str, plan: str, until: str | None) -> None:
    if until:
        date.fromisoformat(until)  # refuse a malformed date before storing it
    with server.db() as con:
        if not con.execute("SELECT 1 FROM devices WHERE profile_id = ?", (profile_id,)).fetchone():
            sys.exit(f"No device has registered profile {profile_id} here yet. Sync from it once first.")
        con.execute(
            "INSERT INTO subscriptions (profile_id, plan, until, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (profile_id) DO UPDATE SET plan = excluded.plan, until = excluded.until",
            (profile_id, plan, until, server._now()),
        )
    print(f"{profile_id}: {plan} until {until or 'no end date'}")


def unsubscribe(profile_id: str) -> None:
    with server.db() as con:
        con.execute("DELETE FROM subscriptions WHERE profile_id = ?", (profile_id,))
    print(f"{profile_id}: no subscription")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="devices, their profiles and subscriptions")
    add = commands.add_parser("subscribe", help="give a profile a subscription")
    add.add_argument("profile_id")
    add.add_argument("--plan", default="video")
    add.add_argument("--until", help="last day, YYYY-MM-DD; omit for no end date")
    remove = commands.add_parser("unsubscribe", help="take a subscription away")
    remove.add_argument("profile_id")
    args = parser.parse_args()

    if args.command == "list":
        list_profiles()
    elif args.command == "subscribe":
        subscribe(args.profile_id, args.plan, args.until)
    else:
        unsubscribe(args.profile_id)


if __name__ == "__main__":
    main()

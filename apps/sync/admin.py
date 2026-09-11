"""Manage plans, payments and subscriptions on the sync server.

    python apps/sync/admin.py list
    python apps/sync/admin.py set-plan video-month --name "Video uploads, 1 month" --price 99 --months 1
    python apps/sync/admin.py retire-plan video-month
    python apps/sync/admin.py plans
    python apps/sync/admin.py payments [--profile <profile-id>]
    python apps/sync/admin.py subscribe <profile-id> [--plan video] [--until 2027-03-31]
    python apps/sync/admin.py unsubscribe <profile-id>

A subscription lets its profile upload videos directly (through Mux) instead
of linking them on YouTube. People buy one from the app once a plan is on
sale and Razorpay keys are set; ``subscribe`` grants one by hand -- a trial, a
partner, a refund made good. Prices are the operator's to set: nothing is on
sale until ``set-plan`` says so. It works on the same database as the server
(``VG_SYNC_DB``), so run it where the server runs. Profile ids are listed by
``list``, next to the names people gave.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
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
    print(f"Razorpay payments: {'on' if server.razorpay.configured else 'off (set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)'}")


def _rupees(paise: int) -> str:
    # "Rs", not the rupee sign: a Windows console piped to a file may not encode it.
    return f"Rs {paise // 100}" + (f".{paise % 100:02d}" if paise % 100 else "")


def to_paise(price: str) -> int:
    """'99' or '99.50' rupees as paise; Razorpay takes Rs 1 at the least."""
    try:
        amount = Decimal(price)
    except InvalidOperation:
        sys.exit(f"Not a price: {price}")
    if amount != amount.quantize(Decimal("0.01")) or amount < 1:
        sys.exit("A price is in rupees, at least 1, with up to two decimals.")
    return int(amount * 100)


def set_plan(code: str, name: str, price: str, months: int) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", code):
        sys.exit("A plan code is up to 32 lower-case letters, digits and dashes, like video-month.")
    if not 1 <= months <= 36:
        sys.exit("A plan lasts 1 to 36 months.")
    paise = to_paise(price)
    with server.db() as con:
        con.execute(
            "INSERT INTO plans (code, name, amount_paise, months, active, created_at) VALUES (?, ?, ?, ?, 1, ?) "
            "ON CONFLICT (code) DO UPDATE SET name = excluded.name, amount_paise = excluded.amount_paise, "
            "months = excluded.months, active = 1",
            (code, name, paise, months, server._now()),
        )
    print(f"{code}: {name}, {_rupees(paise)} for {months} month{'s' if months > 1 else ''} -- on sale")


def retire_plan(code: str) -> None:
    with server.db() as con:
        if con.execute("UPDATE plans SET active = 0 WHERE code = ?", (code,)).rowcount == 0:
            sys.exit(f"No plan {code}.")
    print(f"{code}: no longer on sale (links already sent can still be paid)")


def list_plans() -> None:
    with server.db() as con:
        rows = con.execute("SELECT * FROM plans ORDER BY active DESC, months").fetchall()
    if not rows:
        print("No plans yet. Add one with set-plan.")
    for row in rows:
        print(f"{row['code']:24} {_rupees(row['amount_paise']):>10} {row['months']:>3} mo  "
              f"{'on sale' if row['active'] else 'retired':8} {row['name']}")


def list_payments(profile_id: str | None) -> None:
    with server.db() as con:
        names = _names(con)
        query, params = "SELECT * FROM payments", ()
        if profile_id:
            query, params = query + " WHERE profile_id = ?", (profile_id,)
        rows = con.execute(query + " ORDER BY created_at DESC LIMIT 100", params).fetchall()
    if not rows:
        print("No payments.")
    for row in rows:
        print(f"{row['created_at'][:10]} {row['id']:24} {row['status']:9} {_rupees(row['amount_paise']):>10} "
              f"{row['plan']:16} until {row['until_after'] or '-':10} {names.get(row['profile_id'], row['profile_id'])}")


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
    plan = commands.add_parser("set-plan", help="put a plan on sale, or change its name, price or length")
    plan.add_argument("code")
    plan.add_argument("--name", required=True)
    plan.add_argument("--price", required=True, help="in rupees, e.g. 99")
    plan.add_argument("--months", type=int, required=True)
    retire = commands.add_parser("retire-plan", help="take a plan off sale")
    retire.add_argument("code")
    commands.add_parser("plans", help="plans and their prices")
    payments = commands.add_parser("payments", help="recent payments")
    payments.add_argument("--profile")
    args = parser.parse_args()

    if args.command == "list":
        list_profiles()
    elif args.command == "subscribe":
        subscribe(args.profile_id, args.plan, args.until)
    elif args.command == "unsubscribe":
        unsubscribe(args.profile_id)
    elif args.command == "set-plan":
        set_plan(args.code, args.name, args.price, args.months)
    elif args.command == "retire-plan":
        retire_plan(args.code)
    elif args.command == "plans":
        list_plans()
    else:
        list_payments(args.profile)


if __name__ == "__main__":
    main()

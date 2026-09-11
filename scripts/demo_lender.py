"""Play a bank on a development sync server, to try the loan flow on one laptop.

One device is one person, so a farmer testing loans alone has no lender to
apply to. This script is that lender: a test bank that publishes a few loans
through the sync server, lists the applications it receives, and answers them
-- exactly as a bank's own device would.

    python scripts/demo_lender.py setup                       # publish the test bank and its loans
    python scripts/demo_lender.py list                        # applications received
    python scripts/demo_lender.py answer <id> review
    python scripts/demo_lender.py answer <id> documents --docs bank_statement land_record --note "At the branch"
    python scripts/demo_lender.py answer <id> sanction --amount 250000 --rate 9.5 --months 60
    python scripts/demo_lender.py answer <id> disburse [--amount 250000]
    python scripts/demo_lender.py answer <id> decline --note "Outside our area"

Then press Sync in the app (or wait for it) to see the answer. The bank is
marked as a test, and its device token is kept in apps/sync/data/ (git-ignored).
For development only: never point it at a server real people use.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "apps" / "sync" / "data" / "demo_lender.json"
BANK_ID = "de000000-0000-4000-8000-00000000ba01"
LOANS = [
    {"id": "de000000-0000-4000-8000-00000000ba11", "purpose": "horticulture",
     "title": "Orchard and polyhouse loan", "min_amount": 100000, "max_amount": 2500000,
     "rate_min": 8.5, "rate_max": 10.5, "tenure_min_months": 36, "tenure_max_months": 84,
     "collateral": "No security up to Rs 2 lakh; land mortgage above",
     "documents": ["aadhaar", "land_record", "project_report", "bank_statement"]},
    {"id": "de000000-0000-4000-8000-00000000ba12", "purpose": "dairy_livestock",
     "title": "Dairy and animal loan", "min_amount": 50000, "max_amount": 1000000,
     "rate_min": 9, "rate_max": 12, "tenure_min_months": 24, "tenure_max_months": 60,
     "collateral": "Hypothecation of the animals", "documents": ["aadhaar", "project_report", "quotation"]},
    {"id": "de000000-0000-4000-8000-00000000ba13", "purpose": "crop_loan_kcc",
     "title": "Kisan Credit Card crop loan", "min_amount": 25000, "max_amount": 300000,
     "rate_min": 7, "rate_max": 7, "tenure_min_months": 12, "tenure_max_months": 12,
     "collateral": "No security up to Rs 1.6 lakh", "documents": ["aadhaar", "land_record"]},
]
STATUS = {"review": "under_review", "documents": "documents_requested", "sanction": "sanctioned",
          "disburse": "disbursed", "decline": "declined"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def call(server: str, method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    request = urllib.request.Request(
        server.rstrip("/") + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        sys.exit(f"{method} {path}: {exc.code} {exc.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as exc:
        sys.exit(f"Sync server not reachable at {server}: {exc.reason}")


def load() -> dict:
    return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.is_file() else {}


def save(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def token(server: str) -> str:
    state = load()
    if state.get("server") == server and state.get("token"):
        return state["token"]
    answer = call(server, "POST", "/v1/devices", {"profile_id": BANK_ID, "segment": "partner_national"})
    save({"server": server, "token": answer["token"], "rev": 0})
    return answer["token"]


def push(server: str, records: list[dict]) -> None:
    answer = call(server, "POST", "/v1/push", {"records": records}, token(server))
    if answer.get("rejected"):
        sys.exit(f"The server refused: {answer['rejected']}")


def setup(server: str) -> None:
    stamp = now()
    records = [{"entity_type": "profile", "entity_id": BANK_ID, "payload": {
        "id": BANK_ID, "segment": "partner_national", "display_name": "Branch Manager (test)",
        "organisation_name": "Demo Gramin Bank (test)", "phone": "+910000000000", "email": "loans@demo-bank.test",
        "country_code": "IN", "preferred_language": "en", "visibility": "online", "shared_at": stamp,
        "details": {"organisation_type": "bank", "registration_number": "TEST-ONLY"},
        "about": "A pretend bank for trying the loan flow. It lends nothing.",
        "created_at": stamp, "updated_at": stamp,
    }}]
    for loan in LOANS:
        records.append({"entity_type": "loan_product", "entity_id": loan["id"], "payload": {
            **loan, "profile_id": BANK_ID, "summary": "Test loan: apply to see the whole flow.",
            "processing_fee": "Nil (test)", "states": [], "segments": ["farmer", "partner_national"],
            "status": "active", "visibility": "online", "shared_at": stamp, "created_at": stamp, "updated_at": stamp,
        }})
    push(server, records)
    print(f"Published Demo Gramin Bank (test) and {len(LOANS)} loans on {server}. Sync the app to see them.")


def applications(server: str) -> dict[str, dict]:
    """Every application received, latest version of each."""
    state = load()
    found: dict[str, dict] = state.get("applications", {})
    since = int(state.get("rev", 0))
    while True:
        answer = call(server, "GET", f"/v1/pull?since={since}&limit=500", token=token(server))
        for record in answer.get("records", []):
            if record["entityType"] == "loan_application" and not record.get("deleted"):
                found[record["entityId"]] = record["payload"]
        since = answer.get("nextRev", since)
        if not answer.get("more"):
            break
    state = load()
    state.update(rev=since, applications=found)
    save(state)
    return found


def list_applications(server: str) -> None:
    found = applications(server)
    if not found:
        print("No applications yet. Apply from the app, sync it, then run this again.")
    for application_id, p in found.items():
        who = (p.get("snapshot") or {}).get("contact", {}).get("name", "?")
        print(f"{application_id}  {p.get('status', ''):20} Rs {p.get('amount_requested', 0):>10,.0f}  {who}")


def answer(server: str, application_id: str, action: str, args: argparse.Namespace) -> None:
    found = applications(server)
    if application_id not in found:
        sys.exit(f"No application {application_id}. Run: python scripts/demo_lender.py list")
    payload = dict(found[application_id])
    payload.update(status=STATUS[action], responded_at=now(), updated_at=now())
    if args.note:
        payload["lender_note"] = args.note
    if action == "documents":
        payload["documents_requested"] = args.docs or ["bank_statement"]
    elif action == "sanction":
        payload.update(sanctioned_amount=args.amount or payload["amount_requested"], interest_rate=args.rate,
                       sanctioned_tenure_months=args.months or payload.get("tenure_months"))
    elif action == "disburse":
        payload.update(disbursed_amount=args.amount or payload.get("sanctioned_amount"),
                       disbursed_on=date.today().isoformat())
    push(server, [{"entity_type": "loan_application", "entity_id": application_id, "payload": payload}])
    # The server does not send a device its own writes back: remember this version here.
    state = load()
    state.setdefault("applications", {})[application_id] = payload
    save(state)
    print(f"{application_id}: {STATUS[action]}. Sync the app to see it.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", default="http://127.0.0.1:8900")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup")
    commands.add_parser("list")
    ans = commands.add_parser("answer")
    ans.add_argument("application_id")
    ans.add_argument("action", choices=sorted(STATUS))
    ans.add_argument("--amount", type=float)
    ans.add_argument("--rate", type=float, default=9.5)
    ans.add_argument("--months", type=int)
    ans.add_argument("--docs", nargs="*")
    ans.add_argument("--note")
    args = parser.parse_args()
    if args.command == "setup":
        setup(args.server)
    elif args.command == "list":
        list_applications(args.server)
    else:
        answer(args.server, args.application_id, args.action, args)


if __name__ == "__main__":
    main()

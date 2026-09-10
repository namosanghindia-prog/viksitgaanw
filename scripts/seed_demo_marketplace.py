#!/usr/bin/env python
"""Fill the marketplace with clearly-labelled sample data, for trying it out.

    python scripts/seed_demo_marketplace.py            # add sample data
    python scripts/seed_demo_marketplace.py --remove   # take it all out again

Why this exists: one device holds one profile, and until cloud sync is built
an investor's laptop has no way to receive a farmer's request -- so the
investor screens would be empty, and a farmer would never see an interest
arrive. This script stands in for sync. It adds:

* a handful of sample farmers' requests in real LGD districts, visible to
  investors, partners and government officers (one is placed in the device
  owner's own district, so a block officer or a local investor sees one too);
* if this device belongs to a farmer, sample interests from an investor and
  a partner on each of the farmer's open requests.

Every row it writes has ``origin = "demo"``, the app labels it "Sample", and
``--remove`` deletes exactly those rows and nothing else.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import init_db, session_scope  # noqa: E402
from app.models import (  # noqa: E402
    District,
    InsurancePolicy,
    InvestmentInterest,
    InvestmentRequest,
    Profile,
    State,
    SubDistrict,
)
from app.services.marketplace import make_listing, opportunity_summary  # noqa: E402
from app.services.profiles import get_owner  # noqa: E402

DEMO = "demo"

#: (state name, district name) is looked up in the imported LGD data, so the
#: sample works against the full dataset and the bundled development sample.
SAMPLE_REQUESTS: list[dict] = [
    {
        "farmer": "Sunil Pawar",
        "place": ("Maharashtra", "Nashik"),
        "opportunity": "pomegranate_orchard",
        "title": "Pomegranate orchard on 3 acres, drip already installed",
        "summary": "Well water is sweet at 60 ft. Need money for saplings, trellis and the first two years of care. Open to selling the crop to one buyer.",
        "amount": 650000,
        "own": 150000,
        "seeking": ["investment", "partnership"],
        "modes": ["revenue_share", "offtake"],
        "partnerships": ["buy_back", "export"],
        "open_to": ["investor_india", "investor_international", "partner_national", "partner_international", "government"],
        "land": {"areaValue": 3, "areaUnit": "acre", "areaHectares": 1.214, "soilType": "black", "waterSources": ["borewell"], "waterType": "sweet", "irrigationType": "drip", "existingCrops": ["grapes", "onion"], "ownershipType": "owned"},
        "plan": {"totalProjectCost": 800000, "termLoan": 600000, "netPerYear": 420000, "suitabilityScore": 84},
    },
    {
        "farmer": "Geeta Devi",
        "place": ("Uttar Pradesh", "Varanasi"),
        "opportunity": "dairy_crossbred",
        "title": "Five-cow dairy unit with a milk route to the town cooperative",
        "summary": "Two cows already. Want three more crossbred cows, a shed and a chaff cutter.",
        "amount": 420000,
        "own": 60000,
        "seeking": ["investment"],
        "modes": ["loan", "revenue_share"],
        "partnerships": [],
        "open_to": ["investor_india", "government"],
        "land": {"areaValue": 4, "areaUnit": "bigha", "areaHectares": 0.67, "soilType": "alluvial", "waterSources": ["borewell", "canal"], "waterType": "sweet", "irrigationType": "flood", "existingCrops": ["wheat", "rice"], "ownershipType": "owned"},
        "plan": None,
    },
    {
        "farmer": "Harpreet Singh",
        "place": ("Punjab", "Ludhiana"),
        "opportunity": "basmati_export_paddy",
        "title": "Basmati for export: looking for a buyer who needs residue-tested grain",
        "summary": "10 acres, will follow the buyer's spray schedule and get the crop tested.",
        "amount": 300000,
        "own": 100000,
        "seeking": ["partnership"],
        "modes": [],
        "partnerships": ["contract_farming", "buy_back", "export"],
        "open_to": ["partner_national", "partner_international", "government"],
        "land": {"areaValue": 10, "areaUnit": "acre", "areaHectares": 4.047, "soilType": "alluvial", "waterSources": ["canal", "borewell"], "waterType": "sweet", "irrigationType": "flood", "existingCrops": ["rice", "wheat"], "ownershipType": "owned"},
        "plan": None,
    },
    {
        "farmer": "Lakshmi Narayana",
        "place": ("Karnataka", "Kolar"),
        "opportunity": "polyhouse_vegetables",
        "title": "Half-acre polyhouse for capsicum, 40 km from Bengaluru",
        "summary": "Horticulture department subsidy is sanctioned; need the farmer share and working capital.",
        "amount": 1800000,
        "own": 300000,
        "seeking": ["investment"],
        "modes": ["loan", "revenue_share", "equity"],
        "partnerships": [],
        "open_to": ["investor_india", "investor_international", "government"],
        "land": {"areaValue": 20, "areaUnit": "guntha", "areaHectares": 0.2, "soilType": "red", "waterSources": ["borewell"], "waterType": "sweet", "irrigationType": "drip", "existingCrops": ["tomato", "ragi"], "ownershipType": "owned"},
        "plan": {"totalProjectCost": 2400000, "termLoan": 1800000, "netPerYear": 950000, "suitabilityScore": 78},
    },
    {
        "farmer": "Ravi Chaudhari",
        "place": ("Maharashtra", "Jalgaon"),
        "opportunity": "banana_tissue_culture",
        "title": "Tissue-culture banana on 2 acres",
        "summary": "Looking for a buyer who will take the whole harvest, and a loan for plants and drip.",
        "amount": 380000,
        "own": 80000,
        "seeking": ["investment", "partnership"],
        "modes": ["loan", "input_finance"],
        "partnerships": ["buy_back", "input_supply"],
        "open_to": ["investor_india", "partner_national", "government"],
        "land": {"areaValue": 2, "areaUnit": "acre", "areaHectares": 0.809, "soilType": "black", "waterSources": ["open_well"], "waterType": "sweet", "irrigationType": "drip", "existingCrops": ["cotton"], "ownershipType": "leased"},
        "plan": None,
    },
]

#: Placed in the device owner's own district, so a local investor, partner or
#: block officer has something nearby to look at.
LOCAL_REQUEST: dict = {
    "farmer": "Mohan Lal",
    "opportunity": "custom_hiring_centre",
    "title": "Tractor and rotavator hire centre for the village",
    "summary": "Nearest hire centre is 18 km away. Six neighbours have agreed to book it every season.",
    "amount": 900000,
    "own": 150000,
    "seeking": ["investment", "partnership"],
    "modes": ["loan", "revenue_share"],
    "partnerships": ["equipment", "training"],
    "open_to": ["investor_india", "investor_international", "partner_national", "partner_international", "government"],
    "land": {"areaValue": 1, "areaUnit": "acre", "areaHectares": 0.405, "soilType": "loamy", "waterSources": ["borewell"], "waterType": "sweet", "irrigationType": "sprinkler", "existingCrops": ["wheat", "mustard"], "ownershipType": "owned"},
    "plan": None,
}

#: Sample cover per option: some insured, some only promised, so both states
#: can be seen on the investor screens.
SAMPLE_INSURANCE: dict[str, list[dict]] = {
    "pomegranate_orchard": [
        {"category": "crop", "status": "insured", "scheme": "rwbcis", "insurer": "Agriculture Insurance Company of India", "policy_number": "RWB-MH-26-004417", "sum_insured": 330000, "season": "annual", "season_year": 2026, "valid_months": 11},
    ],
    "dairy_crossbred": [
        {"category": "livestock", "status": "planned"},
    ],
    "polyhouse_vegetables": [
        {"category": "structure", "status": "insured", "insurer": "New India Assurance", "policy_number": "NIA-GH-2026-55120", "sum_insured": 1800000, "valid_months": 12},
    ],
    "custom_hiring_centre": [
        {"category": "machinery", "status": "planned"},
    ],
}

SAMPLE_INVESTOR = {
    "segment": "investor_india",
    "display_name": "Anita Rao",
    "organisation_name": "Green Furrow Capital (sample)",
    "phone": "+919000000001",
    "email": "anita@greenfurrow.example",
    "details": {"investor_type": "fund", "modes": ["revenue_share", "loan"], "sectors": ["horticulture"]},
}

SAMPLE_PARTNER = {
    "segment": "partner_national",
    "display_name": "Vikas Jadhav",
    "organisation_name": "Sahyadri Growers FPO (sample)",
    "phone": "+919000000002",
    "email": "vikas@sahyadri.example",
    "details": {"organisation_type": "fpo", "partnership_types": ["buy_back", "technical"]},
}


def _find_place(session: Session, state_name: str, district_name: str):
    state = session.scalars(
        select(State).where(func.lower(State.name) == state_name.lower())
    ).first()
    if state is None:
        return None
    district = session.scalars(
        select(District)
        .where(District.state_code == state.code)
        .where(func.lower(District.name) == district_name.lower())
    ).first()
    if district is None:
        return None
    subdistrict = session.scalars(
        select(SubDistrict).where(SubDistrict.district_code == district.code).limit(1)
    ).first()
    return state.code, district.code, subdistrict.code if subdistrict else None


def _add_request(session: Session, spec: dict, place: tuple[str, str, str | None]) -> None:
    state_code, district_code, subdistrict_code = place
    farmer = Profile(
        segment="farmer",
        display_name=spec["farmer"],
        phone="+919000000100",
        country_code="IN",
        state_code=state_code,
        district_code=district_code,
        origin=DEMO,
        is_device_owner=False,
        details={"needs": ["investment"]},
    )
    session.add(farmer)
    session.flush()

    opportunity = opportunity_summary(spec["opportunity"])
    request = InvestmentRequest(
        profile_id=farmer.id,
        opportunity_code=spec["opportunity"],
        opportunity_kind=opportunity["kind"] if opportunity else None,
        state_code=state_code,
        district_code=district_code,
        subdistrict_code=subdistrict_code,
        title=spec["title"],
        summary=spec["summary"],
        amount_sought=spec["amount"],
        own_contribution=spec["own"],
        seeking=spec["seeking"],
        modes=spec["modes"],
        partnership_types=spec["partnerships"],
        open_to=spec["open_to"],
        listing=make_listing(
            session,
            state_code=state_code,
            district_code=district_code,
            subdistrict_code=subdistrict_code,
            village_code=None,
            land=spec["land"],
            opportunity_code=spec["opportunity"],
            plan=spec["plan"],
        ),
        status="open",
        origin=DEMO,
    )
    session.add(request)
    session.flush()

    today = date.today()
    for cover in SAMPLE_INSURANCE.get(spec["opportunity"], []):
        cover = dict(cover)
        months = cover.pop("valid_months", None)
        session.add(
            InsurancePolicy(
                request_id=request.id,
                origin=DEMO,
                valid_from=today if months else None,
                valid_until=today + timedelta(days=30 * months) if months else None,
                **cover,
            )
        )


def _add_interests(session: Session, owner: Profile) -> int:
    requests = session.scalars(
        select(InvestmentRequest)
        .where(InvestmentRequest.profile_id == owner.id)
        .where(InvestmentRequest.status == "open")
    ).all()
    if not requests:
        return 0

    investor = Profile(is_device_owner=False, origin=DEMO, country_code="IN", **SAMPLE_INVESTOR)
    partner = Profile(is_device_owner=False, origin=DEMO, country_code="IN", **SAMPLE_PARTNER)
    session.add_all([investor, partner])
    session.flush()

    added = 0
    for request in requests:
        existing = {interest.profile_id for interest in request.interests}
        if "investment" in request.seeking and investor.id not in existing:
            session.add(
                InvestmentInterest(
                    request_id=request.id,
                    profile_id=investor.id,
                    kind="investment",
                    amount_offered=round(request.amount_sought * 0.6, -3),
                    mode=(request.modes or ["loan"])[0],
                    message="We fund orchards and protected cultivation. Could we visit the field next month?",
                    status="sent",
                    origin=DEMO,
                )
            )
            added += 1
        if "partnership" in request.seeking and partner.id not in existing:
            session.add(
                InvestmentInterest(
                    request_id=request.id,
                    profile_id=partner.id,
                    kind="partnership",
                    partnership_type=(request.partnership_types or ["buy_back"])[0],
                    message="Our FPO can buy the full harvest at the agreed grade and help with spray schedules.",
                    status="sent",
                    origin=DEMO,
                )
            )
            added += 1
    return added


def remove(session: Session) -> int:
    counts = 0
    for model in (InsurancePolicy, InvestmentInterest, InvestmentRequest, Profile):
        result = session.execute(delete(model).where(model.origin == DEMO))
        counts += result.rowcount or 0
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--remove", action="store_true", help="delete all sample rows")
    args = parser.parse_args(argv)

    init_db()
    with session_scope() as session:
        if args.remove:
            print(f"Removed {remove(session)} sample rows.")
            return 0

        # Re-running replaces the sample rather than doubling it.
        remove(session)

        added = 0
        for spec in SAMPLE_REQUESTS:
            place = _find_place(session, *spec["place"])
            if place is None:
                print(f"  skipped {spec['place'][1]}: not in the imported LGD data")
                continue
            _add_request(session, spec, place)
            added += 1

        owner = get_owner(session)
        if owner is not None and owner.state_code and owner.district_code:
            subdistrict = owner.subdistrict_code or (
                session.scalars(
                    select(SubDistrict.code)
                    .where(SubDistrict.district_code == owner.district_code)
                    .limit(1)
                ).first()
            )
            _add_request(session, LOCAL_REQUEST, (owner.state_code, owner.district_code, subdistrict))
            added += 1
        print(f"Added {added} sample requests.")

        if owner is not None and owner.segment == "farmer":
            print(f"Added {_add_interests(session, owner)} sample interests on your own requests.")
        elif owner is None:
            print("No profile on this device yet: set one up in the app, then run this again.")

    print("Run with --remove to take the sample data out again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

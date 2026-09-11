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
  a partner on each of the farmer's open requests;
* sample equipment sellers with machines for sale and rent, and -- if this
  device belongs to a seller -- sample rent and buy enquiries on its shared
  machines and a sample farmer asking to become its partner;
* an inbox notification for each sample interest, enquiry and partner
  request, the way one appears when sync delivers it;
* a sample neighbour already connected to the owner, with a plot shared on
  the timeline and two farm updates, and a sample connection request waiting
  for an answer.

Sample items are shared online, as anything arriving by sync would be.

Every row it writes has ``origin = "demo"``, the app labels it "Sample", and
``--remove`` deletes exactly those rows and nothing else.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import init_db, session_scope  # noqa: E402
from app.models import (  # noqa: E402
    Connection,
    District,
    EquipmentEnquiry,
    EquipmentListing,
    EquipmentPartnership,
    FarmUpdate,
    InsurancePolicy,
    InvestmentInterest,
    InvestmentRequest,
    LandShare,
    Notification,
    Profile,
    State,
    SubDistrict,
)
from app.services.marketplace import make_listing, opportunity_summary  # noqa: E402
from app.services.notify import notify  # noqa: E402
from app.services.notify import notify  # noqa: E402
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


#: Two sample machinery organisations and what they offer. Places are looked
#: up like the requests; a seller whose district is missing is skipped.
SAMPLE_SELLERS: list[dict] = [
    {
        "profile": {
            "segment": "partner_national",
            "display_name": "Sanjay Deshmukh",
            "organisation_name": "Kisan Yantra Seva (sample)",
            "phone": "+919000000003",
            "email": "sanjay@kisanyantra.example",
            "details": {"organisation_type": "agri_company", "partnership_types": ["equipment", "training"]},
        },
        "place": ("Maharashtra", "Nashik"),
        "machines": [
            {"equipment_type": "tractor", "title": "45 HP tractor with driver", "condition": "good", "year_made": 2021, "for_rent": True, "rent_rate": 900, "rent_unit": "hour", "quantity": 3, "with_operator": True, "description": "Available for ploughing, rotavator and haulage. Diesel included in the rate."},
            {"equipment_type": "rotavator", "title": "Rotavator, 7 feet", "condition": "like_new", "year_made": 2024, "for_rent": True, "rent_rate": 1800, "rent_unit": "acre", "for_sale": True, "sale_price": 115000, "quantity": 2},
            {"equipment_type": "drone", "title": "Spraying drone with trained pilot", "condition": "new", "year_made": 2026, "for_rent": True, "rent_rate": 450, "rent_unit": "acre", "with_operator": True, "quantity": 1, "description": "10-litre tank. Covers an acre in about seven minutes. Pilot is licensed."},
        ],
    },
    {
        "profile": {
            "segment": "partner_national",
            "display_name": "Gurpreet Kaur",
            "organisation_name": "Doaba Agro Machines (sample)",
            "phone": "+919000000004",
            "email": "gurpreet@doaba.example",
            "details": {"organisation_type": "input_supplier", "partnership_types": ["equipment"]},
        },
        "place": ("Punjab", "Ludhiana"),
        "machines": [
            {"equipment_type": "harvester", "title": "Combine harvester for wheat and paddy", "condition": "good", "year_made": 2020, "for_rent": True, "rent_rate": 2200, "rent_unit": "acre", "with_operator": True, "delivery": True, "quantity": 2, "description": "Travels to Haryana and western Uttar Pradesh in season. Book two weeks ahead."},
            {"equipment_type": "seed_drill", "title": "Happy seeder (sow without burning straw)", "condition": "new", "year_made": 2026, "for_sale": True, "sale_price": 165000, "for_rent": True, "rent_rate": 2500, "rent_unit": "day", "quantity": 4},
            {"equipment_type": "chaff_cutter", "title": "Electric chaff cutter, 2 HP", "condition": "new", "year_made": 2026, "for_sale": True, "sale_price": 18500, "delivery": True, "quantity": 20},
        ],
    },
]


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
        visibility="online",
        shared_at=_shared_at(),
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
        # Other farmers see it on the common timeline, as the app's default.
        open_to=[*spec["open_to"], "farmer"],
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
        visibility="online",
        shared_at=_shared_at(),
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

    investor = Profile(
        is_device_owner=False, origin=DEMO, country_code="IN", visibility="online", **SAMPLE_INVESTOR
    )
    partner = Profile(
        is_device_owner=False, origin=DEMO, country_code="IN", visibility="online", **SAMPLE_PARTNER
    )
    session.add_all([investor, partner])
    session.flush()

    added = 0
    for request in requests:
        existing = {interest.profile_id for interest in request.interests}
        if "investment" in request.seeking and investor.id not in existing:
            _received(
                session, owner, request, investor,
                InvestmentInterest(
                    request_id=request.id,
                    profile_id=investor.id,
                    kind="investment",
                    amount_offered=round(request.amount_sought * 0.6, -3),
                    mode=(request.modes or ["loan"])[0],
                    message="We fund orchards and protected cultivation. Could we visit the field next month?",
                    status="sent",
                    origin=DEMO,
                ),
            )
            added += 1
        if "partnership" in request.seeking and partner.id not in existing:
            _received(
                session, owner, request, partner,
                InvestmentInterest(
                    request_id=request.id,
                    profile_id=partner.id,
                    kind="partnership",
                    partnership_type=(request.partnership_types or ["buy_back"])[0],
                    message="Our FPO can buy the full harvest at the agreed grade and help with spray schedules.",
                    status="sent",
                    origin=DEMO,
                ),
            )
            added += 1
    return added


def _received(
    session: Session, owner: Profile, request: InvestmentRequest, sender: Profile, interest: InvestmentInterest
) -> None:
    session.add(interest)
    session.flush()
    notify(
        session, owner.id, "interest_received",
        params={"name": sender.organisation_name or sender.display_name, "title": request.title},
        link="/requests", entity_type="investment_interest", entity_id=interest.id,
    )


_CLOCK = {"step": 0}


def _shared_at() -> datetime:
    """Stagger sample share times, so the timeline has an order to show."""
    _CLOCK["step"] += 1
    return datetime.now(timezone.utc) - timedelta(hours=3 * _CLOCK["step"])


def _add_sellers(session: Session) -> int:
    added = 0
    for spec in SAMPLE_SELLERS:
        place = _find_place(session, *spec["place"])
        if place is None:
            print(f"  skipped seller in {spec['place'][1]}: not in the imported LGD data")
            continue
        state_code, district_code, subdistrict_code = place
        seller = Profile(
            is_device_owner=False,
            origin=DEMO,
            country_code="IN",
            state_code=state_code,
            district_code=district_code,
            visibility="online",
            shared_at=_shared_at(),
            **spec["profile"],
        )
        session.add(seller)
        session.flush()
        for machine in spec["machines"]:
            session.add(
                EquipmentListing(
                    profile_id=seller.id,
                    state_code=state_code,
                    district_code=district_code,
                    subdistrict_code=subdistrict_code,
                    visibility="online",
                    shared_at=_shared_at(),
                    status="active",
                    origin=DEMO,
                    **machine,
                )
            )
            added += 1
    return added


def _add_seller_activity(session: Session, owner: Profile) -> tuple[int, int]:
    """Sample enquiries on the owner's shared machines, and a partner request."""
    farmer = Profile(
        segment="farmer",
        display_name="Baldev Singh (sample)",
        phone="+919000000200",
        country_code="IN",
        state_code=owner.state_code,
        district_code=owner.district_code,
        is_device_owner=False,
        origin=DEMO,
        visibility="online",
        details={"needs": ["equipment"]},
    )
    session.add(farmer)
    session.flush()

    enquiries = 0
    listings = session.scalars(
        select(EquipmentListing)
        .where(EquipmentListing.profile_id == owner.id)
        .where(EquipmentListing.visibility == "online")
        .where(EquipmentListing.status == "active")
    ).all()
    for listing in listings:
        kind = "rent" if listing.for_rent else "buy"
        start = date.today() + timedelta(days=10)
        enquiry = EquipmentEnquiry(
            listing_id=listing.id,
            profile_id=farmer.id,
            kind=kind,
            quantity=1,
            start_date=start if kind == "rent" else None,
            end_date=start + timedelta(days=2) if kind == "rent" else None,
            area_acres=4 if kind == "rent" and listing.rent_unit == "acre" else None,
            message="Need it before the rains. Can your operator come to our village?",
            status="sent",
            origin=DEMO,
        )
        session.add(enquiry)
        session.flush()
        notify(
            session, owner.id, "enquiry_received",
            params={"name": farmer.display_name, "title": listing.title, "kind": kind},
            link="/my-machines", entity_type="equipment_enquiry", entity_id=enquiry.id,
        )
        enquiries += 1

    partnership = EquipmentPartnership(
        seller_profile_id=owner.id,
        partner_kind="farmer",
        partner_profile_id=farmer.id,
        state_code=owner.state_code,
        district_code=owner.district_code,
        role="rental_point",
        message="I have a shed by the main road and can keep two machines for hire in our village.",
        initiated_by="partner",
        status="proposed",
        origin=DEMO,
    )
    session.add(partnership)
    session.flush()
    notify(
        session, owner.id, "partnership_requested", params={"name": farmer.display_name},
        link="/partners", entity_type="equipment_partnership", entity_id=partnership.id,
    )
    return enquiries, 1


def _add_connections(session: Session, owner: Profile) -> tuple[int, int]:
    """A connected neighbour with shared land and updates, and a request to answer."""
    neighbour = Profile(
        segment="farmer",
        display_name="Sita Ram (sample)",
        phone="+919000000300",
        country_code="IN",
        state_code=owner.state_code,
        district_code=owner.district_code,
        is_device_owner=False,
        origin=DEMO,
        visibility="online",
        shared_at=_shared_at(),
        details={"needs": ["market_linkage"]},
    )
    asker = Profile(
        segment="partner_national",
        display_name="Kavita Joshi",
        organisation_name="Kisan Beej Bhandar (sample)",
        phone="+919000000301",
        country_code="IN",
        state_code=owner.state_code,
        district_code=owner.district_code,
        is_device_owner=False,
        origin=DEMO,
        visibility="online",
        details={"organisation_type": "input_supplier", "partnership_types": ["input_supply"]},
    )
    session.add_all([neighbour, asker])
    session.flush()

    session.add(
        Connection(
            requester_profile_id=neighbour.id,
            addressee_profile_id=owner.id,
            status="accepted",
            message="Namaste, we farm next to each other.",
            responded_at=datetime.now(timezone.utc),
            origin=DEMO,
        )
    )
    place = None
    if owner.district_code:
        district = session.get(District, owner.district_code)
        state = session.get(State, owner.state_code) if owner.state_code else None
        place = ", ".join(unit.name for unit in (district, state) if unit is not None) or None
    share = LandShare(
        id=str(uuid.uuid4()),
        profile_id=neighbour.id,
        snapshot={
            "label": "Sita Ram's river field",
            "place": place,
            "state_code": owner.state_code,
            "area_value": 3,
            "area_unit": "bigha",
            "area_hectares": 0.5,
            "soil_type": "alluvial",
            "water_sources": ["borewell"],
            "water_type": "sweet",
            "irrigation_type": "drip",
            "existing_crops": ["tomato", "chilli"],
        },
        visibility="online",
        shared_at=_shared_at(),
        origin=DEMO,
    )
    session.add(share)
    session.flush()
    updates = [
        FarmUpdate(profile_id=neighbour.id, land_share_id=share.id, origin=DEMO,
                   body="Drip lines laid on the whole field. Tomato seedlings go in on Sunday.",
                   created_at=datetime.now(timezone.utc) - timedelta(hours=5)),
        FarmUpdate(profile_id=neighbour.id, origin=DEMO,
                   body="Buying neem cake together brings the price down. Anyone in for 20 bags?",
                   created_at=datetime.now(timezone.utc) - timedelta(hours=2)),
    ]
    session.add_all(updates)
    request = Connection(
        requester_profile_id=asker.id,
        addressee_profile_id=owner.id,
        status="requested",
        message="We supply seed and fertiliser in your block. Happy to connect.",
        origin=DEMO,
    )
    session.add(request)
    session.flush()

    name = neighbour.display_name
    notify(session, owner.id, "land_shared", params={"name": name, "plot": share.snapshot["label"]},
           link="/timeline", entity_type="land_share", entity_id=share.id)
    notify(session, owner.id, "update_posted", params={"name": name, "text": updates[1].body[:80]},
           link="/timeline", entity_type="farm_update", entity_id=updates[1].id)
    notify(session, owner.id, "connection_requested", params={"name": asker.organisation_name},
           link="/connections", entity_type="connection", entity_id=request.id)
    return 1, 1


def remove(session: Session) -> int:
    counts = 0
    # Notifications have no origin of their own: they go with what they are about.
    for model in (InvestmentInterest, EquipmentEnquiry, EquipmentPartnership, Connection, LandShare, FarmUpdate):
        demo_ids = select(model.id).where(model.origin == DEMO)
        result = session.execute(delete(Notification).where(Notification.entity_id.in_(demo_ids)))
        counts += result.rowcount or 0
    for model in (
        FarmUpdate,
        LandShare,
        Connection,
        InsurancePolicy,
        InvestmentInterest,
        InvestmentRequest,
        EquipmentEnquiry,
        EquipmentPartnership,
        EquipmentListing,
        Profile,
    ):
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

        print(f"Added {_add_sellers(session)} sample machines for sale or rent.")

        if owner is not None and owner.segment == "farmer":
            print(f"Added {_add_interests(session, owner)} sample interests on your own requests.")
        elif owner is not None and owner.segment.startswith("partner_") and owner.state_code:
            enquiries, partners = _add_seller_activity(session, owner)
            print(
                f"Added {enquiries} sample enquiries on your shared machines "
                f"and {partners} sample partner request."
            )
        elif owner is None:
            print("No profile on this device yet: set one up in the app, then run this again.")

        if owner is not None:
            connected, waiting = _add_connections(session, owner)
            print(
                f"Added {connected} sample connection with a shared plot and updates, "
                f"and {waiting} connection request to answer."
            )

    print("Run with --remove to take the sample data out again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

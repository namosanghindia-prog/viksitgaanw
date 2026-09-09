# ViksitGaanw — Project Brief for Claude Code

## What this is

ViksitGaanw is a village-focused Agricultural Operating System for India. It runs on a
villager's own laptop or phone (that device acts as the "server" for that user), works
offline-first, and syncs to the cloud when internet is available. Its job is to take a
villager's land and location, tell them the best local and international-grade smart
farming options for that land, generate investment-ready project reports automatically,
and connect them to real investors, partners, and markets — safely, through KYC.

Primary users: village-level MSME farmers and rural entrepreneurs across India.
Secondary users: agri-investors, FPOs, Gram Panchayats, and government scheme
administrators.

## Project location

Create and work entirely inside `D:\ViksitGaanw`. All source, docs, and build output
live there. Do not scatter files outside this folder.

## Core tech stack (matches the founder's existing product line)

- Desktop shell: Electron 28 + React 18 + Vite
- Backend: Python FastAPI, running locally on the user's own machine for offline mode
- Local database: SQLite (offline-first, holds the full LGD village/district/state
  dataset plus the user's own farm and business data)
- Cloud sync (optional, when online): PostgreSQL via Supabase or AWS RDS — used only
  for cross-device sync, investor-marketplace matching, and market data that must stay
  current
- Maps: Leaflet.js + OpenStreetMap tiles for plot visualization and pin-drop; plan to
  self-host a tile server and a Nominatim instance once usage grows past prototype scale
  (the public OSM/Nominatim services have usage limits not meant for production traffic)
- Location/admin hierarchy data: Local Government Directory (LGD) dataset from
  data.gov.in — the official state → district → sub-district → block → village
  directory, free for commercial use. Import this as a seed dataset into SQLite at
  build time so it works fully offline.
- PDF generation for auto project reports: a Python PDF library (e.g. reportlab or
  WeasyPrint) driven from FastAPI
- KYC: Aadhaar eKYC via a UIDAI-authorized KUA, plus DigiLocker for document
  verification, for phase 1. Full police verification is a phase-2+ item that requires
  a government/Gram Panchayat partnership — do not build it as a standalone feature
  yet, just leave a clean integration point for it.

## Suggested folder structure

```
D:\ViksitGaanw
├── apps
│   ├── desktop        (Electron + React frontend)
│   └── api             (Python FastAPI backend)
├── data
│   └── lgd             (seed data: states, districts, sub-districts, villages)
├── packages
│   └── shared          (shared types/constants between frontend and backend)
├── docs
│   └── project-brief.md (this file, or an expanded version)
└── scripts             (setup, data-import, build scripts)
```

## Phase 1 — foundation (what to build first)

Location cascading selector (state → district → sub-district → village) backed by the
imported LGD dataset, working fully offline. A land-intake form (size, soil type if
known, water source, existing crops) tied to that location. A rules-based business/crop
suggestion engine seeded with local and export-oriented farming options per
region/crop — this can start as a curated knowledge base rather than ML, and get
smarter later. Auto-generated project report (PDF) from the farmer's land and business
choice, in a format a bank or investor would actually accept. Basic offline-first
architecture with a sync queue, so nothing depends on being online.

## Phase 2 — marketplace and trust layer

Investor-facing side of the platform, with a matching layer between farmer project
reports and investor interests. A trust and dispute-resolution layer (ratings,
milestone-based fund release) — this needs to exist before real money moves through
the platform. FPO/cooperative grouping tools so smallholders can pool land to qualify
for larger deals. Local mandi price tracking and a machinery/equipment rental
marketplace, both of which are high-value, frequently-requested features in Indian
agri-tech.

## Phase 3 — scale and government integration

Self-hosted map/geocoding infrastructure to replace public OSM services. Government
scheme aggregator with application-assistance workflows. Partnership-based police
verification tier. International market intelligence module. Success-story/testimonial
module tied to real completed deals.

## Language and accessibility

Hindi plus major regional languages, voice-first where possible — a meaningful share of
users will have low literacy, so this is core, not a later add-on.

## Monetization direction (for context, not to hardcode into the app)

Keep the core farmer-facing app free to drive adoption. Monetize via a success fee on
completed investor deals, an institutional license for FPOs/Gram Panchayats, and
optional paid add-ons (premium report formats, premium market data). Build the app so
these can be metered later without a rearchitecture — e.g. keep deal-completion and
report-generation as clean, loggable events from day one.

## First task for Claude Code

Scaffold the `apps/desktop` (Electron + React + Vite) and `apps/api` (FastAPI) apps
inside `D:\ViksitGaanw`, wire up a local SQLite database, and write a data-import
script in `scripts/` that loads the LGD village/district/state CSV dump into that
database. Once that's working, build the Phase 1 location selector and land-intake
form end to end before touching anything else.

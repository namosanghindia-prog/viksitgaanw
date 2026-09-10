# ViksitGaanw

A village-focused Agricultural Operating System for India. It runs on the
villager's own laptop or phone — that device *is* the server — works fully
offline, and syncs to the cloud only when there is internet.

**Current state: phase 1 complete.** A farmer can enter a plot, see ranked
farming and agri-business options costed for that specific piece of land, and
generate a bank-format project report as a PDF in their own language. See
[Roadmap](#roadmap) for what is next.

---

## Quick start

Requires Node 18+ and Python 3.11+.

```bash
# 1. Python environment
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r apps/api/requirements-dev.txt   # Windows
# source .venv/bin/activate && pip install -r apps/api/requirements-dev.txt  # macOS/Linux

# 2. Node dependencies
npm install

# 3. Create the database and load the real government location data
#    (36 states, 784 districts, 7,092 sub-districts, 677,523 villages)
python scripts/init_db.py
python scripts/fetch_lgd.py
python scripts/import_lgd.py --source data/lgd/dump --replace

# 4. Fonts for project reports in Indian scripts.
#    Optional on Windows: the bundled Nirmala UI already covers nine Indic
#    scripts. Needed for Urdu/Kashmiri/Sindhi, Santali, and on macOS/Linux.
python scripts/fetch_fonts.py --all

# 5. Run the app (starts the local API, Vite, and Electron together)
npm run dev
```

The download is ~10 MB and the import takes about a minute, producing a
~100 MB SQLite file. No internet on this machine? Run
`python scripts/import_lgd.py --sample` instead for a small development sample
(real place names, synthetic codes), and see
[`data/lgd/README.md`](data/lgd/README.md) for the offline import path.

### Running the pieces separately

```bash
npm run api          # local FastAPI backend on 127.0.0.1:8756 (docs at /docs)
npm run dev:web      # Vite dev server on 127.0.0.1:5273, in a normal browser
cd apps/api && python -m pytest    # API test suite (214 tests)
npm run typecheck    # TypeScript
npm run build        # production frontend build
python scripts/check_translations.py   # report translation coverage
```

---

## What works today

- **Cascading location selector** — state → district → block/tehsil → village,
  answered entirely from local SQLite across the full national dataset (784
  districts, 677,523 villages). Every level is searchable, including mid-word
  matching, so typing `bujurg` finds `Rampur Bujurg`. Cascade steps resolve in
  under 10 ms and a nationwide village search in about 120 ms.
- **Land intake** — a three-step form capturing location, plot size in the unit
  the farmer actually uses (acre, bigha, guntha, kanal, …), soil, water
  sources, irrigation method and current crops.
- **Area normalisation** — every plot stores both the number the farmer said
  and the hectare figure a bank needs. Units whose size varies by state (bigha,
  katha) are flagged in the UI rather than silently assumed.
- **Hindi and English** throughout, Hindi by default, switchable at any time.
- **Map pin-drop with working location detection** — mark the exact plot on a
  Leaflet map, or press "use my location" and get an answer on a laptop with no
  GPS radio and no Google API key. See
  [Finding the device](#finding-the-device-without-google) for how, and for the
  reverse lookup that offers to fill in the district from a dropped pin.
- **Business and farming options** — 44 curated options (orchards, protected
  cultivation, spices, livestock, processing units, farm-service businesses)
  ranked against the plot's own soil, water, salinity, size, region and the
  crops the farmer already grows. Every option carries what it would cost and
  earn *on that plot*, and every point of its score is attached to a sentence
  the farmer can read and argue with.
- **Project reports (DPR)** — a bank-format PDF: promoter and land particulars,
  project cost, means of finance, a year-by-year profitability projection,
  repayment schedule with DSCR, break-even, applicable government schemes,
  export-market analysis, risks and assumptions. Generated on the device, in
  any of the 22 scheduled languages plus English.
- **Foreign market intelligence** — for every exportable option: world import
  market size, India's current exports, the main buying countries, the
  registrations and certificates needed, and the barrier that actually stops
  people. Every figure declares whether it comes from official Indian trade
  reporting or a private estimate.
- **Offline-first plumbing** — a durable sync outbox and an append-only event
  log are written on every change, so the cloud sync worker and usage metering
  can be added later without touching the write paths or backfilling history.

---

## Architecture

```
D:\ViksitGaanw
├── apps
│   ├── desktop     Electron 28 + React 18 + Vite (TypeScript)
│   │   ├── electron/   main process: boots the local API, then the window
│   │   └── src/        UI, i18n, API client
│   └── api         Python FastAPI, bound to loopback only
│       ├── app/        routers, models, services
│       └── tests/      pytest suite
├── data
│   ├── lgd         Government location dataset (seed + import target)
│   └── fonts       Noto faces for Indian scripts (fetched, git-ignored)
├── packages/shared
│   ├── reference   Bilingual lists: soil, water, crops, area units
│   └── knowledge   Farming options, export markets, report translations
└── scripts         Database setup, LGD import, fonts, translation report
```

**Why this shape.** The backend is a normal HTTP API rather than in-process
code so the same server can later back a phone app on the same device, or a
Gram Panchayat machine serving several households, with no rewrite.

**Data flow.** Electron's main process starts `uvicorn` as a child process,
points it at the OS user-data directory (so an app upgrade never wipes a
farmer's records), polls `/health`, and only then opens the window. Nothing in
the renderer talks to the internet; the content-security policy allows the
loopback API and nothing else.

**Shared reference data.** Soil types, water sources, crops and area units live
in `packages/shared/reference/*.json` as bilingual lists. The React app imports
them at build time and the API reads the same files at runtime, so a dropdown
option and the value the server accepts cannot drift apart. Adding a crop is a
one-line change in one file.

**Knowledge base.** The farming options, the export-market figures and the
report translations live in `packages/shared/knowledge/` as plain JSON, one
file per category and one per language. They are content, not code: an agronomist
edits `opportunities/horticulture.json` and a native speaker edits `dpr/ta.json`,
without touching Python. `apps/api/tests/test_knowledge.py` guards the joins
between them — a scheme code that does not exist, a soil type spelled wrong so a
rule never fires, an income band below its cost band, a translation key nobody
translated.

### Database

SQLite in WAL mode with a busy timeout — the app has to survive being closed
mid-write on a machine that may lose power.

| Table                                          | Purpose                                            |
| ---------------------------------------------- | -------------------------------------------------- |
| `states`, `districts`, `subdistricts`, `villages` | Imported LGD hierarchy (read-only reference)     |
| `farmers`, `land_parcels`                      | The user's own records                             |
| `project_reports`                              | Index of generated DPRs; the PDFs live on disk     |
| `sync_queue`                                   | Durable outbox for the eventual cloud push         |
| `app_events`                                   | Append-only log; the basis for usage metering      |
| `dataset_meta`                                 | Which LGD release produced the location names      |

`villages` carries denormalised `state_code` and `district_code` so the
selector can filter at any level without a three-way join across ~660k rows.

---

## Business options and project reports

### How an option is ranked

The engine (`apps/api/app/services/opportunities.py`) is a transparent rules
engine, not a model, and it answers three questions in order.

1. **Is this possible here at all?** Salty water under a salt-sensitive crop,
   land below the minimum viable size, soil the crop will not grow in, a vine
   with nothing to climb — any of these is a *blocker*. The option is marked
   unsuitable and sinks to the bottom of the list, but it is never hidden: a
   farmer who wonders why pomegranate was not suggested deserves to be told the
   water is too salty for it.
2. **How well does it fit?** Weighted signals over region, soil, area, water,
   irrigation, salinity, risk, gestation and the crops the farmer already grows
   produce a score out of 100.
3. **What would it earn on *this* plot?** The knowledge base holds per-hectare
   or per-unit bands; those are scaled to the recorded area and returned as
   rupee figures for that specific piece of land.

Every point awarded or removed carries a reason string, rendered by the API in
the farmer's language, so the recommendation can always be interrogated — and
so the project report can answer the credit officer's "why this crop".

Two things the engine is careful about, because both produce plausible-looking
nonsense if you get them wrong:

- **Unit-priced options do not multiply with land.** A polyhouse is limited by
  hectares; a dal mill is limited by capital and by the local market. Owning
  fifty hectares is no reason to plan eight dal mills, so each unit-priced
  option declares `unitsFromLand`.
- **Payback honours the gestation.** Cost divided by full-yield income would
  claim a guava orchard pays for itself in ten months, before it has fruited.
  Both the suggestion and the report ramp income from the first bearing year,
  using the same function.

### The report

`POST /api/v1/land-parcels/{id}/reports` writes a PDF to disk, indexes it, and
records a `project_report.generated` event. The layout is deliberately tabular:
a credit officer reads cost, finance, profitability and DSCR as tables, and a
table survives translation far better than prose when the same template has to
come out in Tamil, Odia or Marathi.

Financial conventions are the ordinary ones for an agricultural term loan and
are all stated on the face of the report: 25% promoter margin, 11% interest,
equal principal instalments after a moratorium matching the gestation, straight-
line depreciation over the asset's life, no subsidy assumed — so any subsidy
actually sanctioned can only improve the picture. DSCR is quoted only for years
principal falls due, which is how it is read.

### Languages

The report can be written in any of the 22 scheduled languages plus English.
Two things have to be true for that to mean anything, and both are checked:

- **The script has to render.** A PDF carries its own glyphs and Indic scripts
  need real shaping. On Windows the app extracts a face from the bundled Nirmala
  UI, which covers nine Indic scripts plus Latin, so a fresh install prints
  Hindi or Kannada with nothing downloaded. For the Perso-Arabic scripts, Ol
  Chiki, and non-Windows machines, run `python scripts/fetch_fonts.py --all`
  once. A language whose script has no font is **refused with the exact command
  that fixes it**, rather than producing a page of empty boxes.
- **The words have to exist.** Coverage counts everything a report can print —
  headings, labels, option names *and* their descriptive paragraphs — not just
  the headings, because a language with the headings alone still produces a
  document half in English. Anything untranslated falls back to English, never
  to Hindi: a Tamil speaker who asked for Tamil is not helped by Hindi. When
  coverage is below 100% the report says so on its own cover.

```bash
python scripts/check_translations.py              # coverage per language
python scripts/check_translations.py --language ta --missing
```

Complete today: **English, Hindi, Marathi, Tamil**. Every other language renders
correctly and falls back to English; filling one in means adding
`packages/shared/knowledge/dpr/<code>.json` with the same keys as `en.json` —
no code change.

### Trade figures

Market sizes in `export-markets.json` carry a `confidence` of either `reported`
(from APEDA, the Spices Board or DGCI&S — reliable to about a year's revision)
or `estimate` (private market research — treat as a rough scale only), plus the
source to re-check. The distinction is shown in the UI and printed in the
report, because a number with no provenance must never end up on a document a
bank is asked to lend against.

---

## Design notes

**Built for the actual user.** A meaningful share of users read slowly or not
at all, on a shared low-end laptop. So: large type and touch targets, choices
shown as visible chips rather than hidden in dropdowns, selection marked with a
check mark as well as colour, one idea per screen, and Hindi first.

**Refuse rather than guess.** An unknown area unit, a district that does not
belong to the selected state, or a village under the wrong sub-district is
rejected with a clear message. A silently-wrong plot size or an unverifiable
address would end up on a project report a bank is asked to lend against.

**Metering hooks from day one.** `app_events` records parcel creation, report
generation and deal completion as first-class events. The monetisation plan
bills on the latter two, and retrofitting an event log means losing history.

---

## Roadmap

Phase 1 is complete: offline location selector, land intake, suggestion engine,
and project report PDFs.

Phase 2: investor marketplace and matching, trust/dispute layer with
milestone-based fund release, FPO grouping, mandi prices, equipment rental.

Phase 3: self-hosted map and geocoding infrastructure, government scheme
aggregator, partnership-based verification tier, international market
intelligence.

Integration points already stubbed: `Farmer.kyc_status` for Aadhaar eKYC and
DigiLocker; `sync_queue` for cloud sync; `LandParcel.latitude/longitude` for
Leaflet plot mapping.

---

## Maps and location

The map serves tiles from **an MBTiles pack on disk**, read by the local API
(`/api/v1/tiles/{z}/{x}/{y}`). MBTiles is SQLite, which the app already speaks,
so a downloaded region needs no tile server and no extra dependency. Drop a
pack at `data/tiles/india.mbtiles` (or set `VG_TILES_PATH`) and the map goes
fully offline; `/api/v1/tiles/status` is what the UI checks.

With no pack installed it falls back to OpenStreetMap tiles over the internet.
That is fine for development and **not** what should ship to a field device:
it breaks the offline promise, and the OSM tile policy does not cover app
traffic at scale. Ship regional packs instead.

The content-security policy stays loopback-only except for `img-src` on the OSM
tile hosts — images only, never script or fetch, so imagery cannot become a
code-execution path.

### Finding the device, without Google

`navigator.geolocation` cannot work inside the Electron desktop shell: Chromium
resolves position through a Google network service that needs a `GOOGLE_API_KEY`
compiled into the build, and Electron ships without a usable one. The call fails
with `POSITION_UNAVAILABLE` however the permission is answered. That is why
"use my location" appeared to do nothing on the desktop app.

The fix is not a key. **"Use my location" now runs a chain of four providers**,
each of which reports what it is so the screen can be honest about the accuracy:

| Provider         | Where it comes from                                       | Typical accuracy | Needs internet |
| ---------------- | --------------------------------------------------------- | ---------------- | -------------- |
| `device_gps`     | `navigator.geolocation` — a real GPS radio on a phone      | 5–50 m           | no             |
| `os_location`    | Windows Location Service via `System.Device.Location`      | 50–500 m         | no¹            |
| `network_ip`     | Keyless IP geolocation                                     | ~25 km           | yes            |
| `admin_centroid` | Centre of the state already chosen in the selector, bundled | ~150 km          | no             |

¹ Uses whatever the machine has — a GPS radio, or Microsoft's Wi-Fi positioning,
which does need a connection. No API key either way.

The map draws the uncertainty as a circle and zooms out for a coarse fix, so a
25 km guess can never be mistaken for a survey pin. **Tapping the map remains
the authoritative way to mark a plot**; detection just saves the farmer from
starting at zoom 4 over the Arabian Sea.

Once there is a position, `/api/v1/geo/reverse` matches it back onto the LGD
hierarchy — through OpenStreetMap Nominatim when online, and through bundled
state bounding boxes when not — and offers to fill in the state, district and
block. It is always a *suggestion* carrying a confidence, never a decision: a
silently wrong district would put a wrong address on a bank document. The
suggestion never reaches village level, because OSM's idea of a village and the
LGD's rarely agree.

---

## Configuration

Every setting takes a `VG_`-prefixed environment variable.

| Variable            | Default                            | Purpose                        |
| ------------------- | ---------------------------------- | ------------------------------ |
| `VG_DB_PATH`        | OS user-data dir (Electron)        | SQLite database location       |
| `VG_REFERENCE_DIR`  | `packages/shared/reference`        | Bilingual reference lists      |
| `VG_PORT`           | `8756`                             | Local API port                 |
| `VG_PYTHON`         | repo `.venv`, then `PATH`          | Interpreter the shell spawns   |
| `VG_TILES_PATH`     | `data/tiles/india.mbtiles`         | Offline map tile pack          |
| `VG_KNOWLEDGE_DIR`  | `packages/shared/knowledge`        | Options, markets, translations |
| `VG_FONTS_DIR`      | `data/fonts`                       | Fonts for report scripts       |
| `VG_REPORTS_DIR`    | OS user-data dir (Electron)        | Where generated PDFs are kept  |
| `VG_ALLOW_NETWORK`  | `true`                             | Permit the two online lookups  |

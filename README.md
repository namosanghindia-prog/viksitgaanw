# ViksitGaanw

A village-focused Agricultural Operating System for India. It runs on the
villager's own laptop or phone — that device *is* the server — works fully
offline, and syncs to the cloud only when there is internet.

**Current state: phase 1 foundation.** The offline location selector and land
intake are complete end to end. See [Roadmap](#roadmap) for what is next.

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

# 4. Run the app (starts the local API, Vite, and Electron together)
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
cd apps/api && python -m pytest    # API test suite
npm run typecheck    # TypeScript
npm run build        # production frontend build
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
- **Map pin-drop with GPS** — mark the exact plot on a Leaflet map, or use the
  device location. Imagery comes from an offline MBTiles pack served by our own
  backend when one is installed; only when it is not does it fall back to
  OpenStreetMap over the internet.
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
├── data/lgd        Government location dataset (seed + import target)
├── packages/shared TypeScript contract types + bilingual reference lists
└── scripts         Database setup and LGD import
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

### Database

SQLite in WAL mode with a busy timeout — the app has to survive being closed
mid-write on a machine that may lose power.

| Table                                          | Purpose                                            |
| ---------------------------------------------- | -------------------------------------------------- |
| `states`, `districts`, `subdistricts`, `villages` | Imported LGD hierarchy (read-only reference)     |
| `farmers`, `land_parcels`                      | The user's own records                             |
| `sync_queue`                                   | Durable outbox for the eventual cloud push         |
| `app_events`                                   | Append-only log; the basis for usage metering      |
| `dataset_meta`                                 | Which LGD release produced the location names      |

`villages` carries denormalised `state_code` and `district_code` so the
selector can filter at any level without a three-way join across ~660k rows.

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

Phase 1 (remaining): rules-based crop and business suggestion engine, and
auto-generated investment-grade project report PDFs.

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

### GPS on desktop is unreliable, by design of the platform

Chromium resolves `navigator.geolocation` through a Google network service that
requires an API key, so on a laptop with no GPS radio the call fails with
*"Failed to query location from network service"* even though Electron grants
the permission. This is expected, not a bug in the app.

Because of that, **tapping the map is the primary way to place a pin**, and GPS
is the shortcut. A future phone shell will have a real GPS radio and the button
will simply start working. If desktop GPS is needed sooner, supply a
`GOOGLE_API_KEY` with the Geolocation API enabled — at the cost of a network
dependency the rest of the app does not have.

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

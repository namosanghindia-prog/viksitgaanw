# ViksitGaanw

A village-focused Agricultural Operating System for India. It runs on the
villager's own laptop or phone — that device *is* the server — works fully
offline, and syncs to the cloud only when there is internet.

**Current state: phase 2 largely built, in development.** A farmer can enter a
plot, see ranked farming and agri-business options costed for that specific
piece of land, and generate a bank-format project report as a PDF in their own
language. Profiles exist for all six kinds of user; a farmer (or a group of
farmers pooling land) turns a plot into an investment request that investors
and partners answer; an accepted investment becomes a deal paid in stages
against evidence, with disputes and ratings. Around that: messages and
notifications, a farm diary with traceability certificates, weather advice,
mandi prices, government-scheme checks, backups and an opt-in sync. See
[Roadmap](#roadmap) for what is next.

> [!WARNING]
> **Development build — not for public release.** Nothing here should be
> published online or put in front of real users yet: there is no identity
> verification (every profile shows as unverified); sync works only against the
> development sync server in `apps/sync`, which has no hardening, rate limits or
> hosting and must only be run on your own machine or network; the deal and
> milestone layer records payments made bank to bank but has had no legal or
> financial-regulation review; scheme eligibility, insurance and
> foreign-investment guidance have not been checked by a lawyer or against
> current government notifications. Server-side error messages are English only.

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
#    scripts and Santali's Ol Chiki. Needed for Urdu/Kashmiri/Sindhi, and on
#    macOS/Linux.
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
cd apps/api && python -m pytest    # API test suite (470 tests)
npm run typecheck    # TypeScript
npm run build        # production frontend build
python scripts/check_translations.py   # report translation coverage
python scripts/seed_demo_marketplace.py            # sample marketplace data (+ inbox)
python scripts/seed_demo_marketplace.py --remove   # ...and take it out again
npm run sync-server  # development sync server on 127.0.0.1:8900 (local only)
python scripts/import_mandi_prices.py --csv prices.csv          # Agmarknet CSV
python scripts/import_mandi_prices.py --fetch --api-key <key>   # data.gov.in
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
- **Business and farming options** — 50 curated options (orchards, protected
  cultivation, spices, livestock, processing units, farm-service businesses and
  village enterprises) ranked against the plot's own soil, water, salinity,
  size, region and the crops the farmer already grows. Every option carries what it would cost and
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
- **Profiles for six kinds of user** — farmer, Indian investor, international
  investor, national farmer partner (FPOs, cooperatives, agri-companies,
  processors, exporters), international farmer partner (foreign buyers,
  importers, agri-companies, research bodies) and government (Gram Panchayat to
  central ministry). See [Profiles and the marketplace](#profiles-and-the-marketplace).
- **Investment requests** — a farmer turns a plot, ideally with its project
  report, into a request for investment, a partner, or both, and chooses who may
  see it. Investors and partners browse requests ranked by how well they match
  their own profile, and answer; the farmer accepts or declines. No money moves
  through the app yet.
- **Offline until shared** — profiles, projects and machines are saved on the
  device only. *Share online* puts them on a common **timeline** of farm
  projects and machines; *Take offline* removes them. Profile photos and
  organisation logos, with location data stripped from the picture.
- **Equipment marketplace** — agriculture organisations list machines for sale
  or rent with pictures; farmers ask to rent or buy; sellers build a partner
  network of farmers, villages, districts and distributors, and farmers can ask
  to become a seller's direct partner.
- **Insurance** — crop cover per plot and season, personal and trade cover on
  profiles, and project cover on every request, with the categories a project
  *must* carry decided by the kind of farming it is. See
  [Profiles and the marketplace](#profiles-and-the-marketplace).
- **Notifications and messages** — a bell and a message icon in the top bar.
  Notifications store only a kind and the names in it, so they read in whatever
  language the app is in. People can message each other once one has answered
  the other's request, machine, partnership or group — without handing out a
  phone number.
- **Deals paid in stages** — an accepted investment becomes a deal plan: the
  money split into stages, each saying what work it pays for. Both sides agree
  the plan; the farmer shows each stage done with a note and photos; the
  investor approves (recording the bank reference of the payment) or sends it
  back. The app never holds money. Either side can report a problem, which
  pauses the deal until both agree a fix. Completion and each release are
  billing events.
- **Ratings** — after finished work each side can rate the other: a completed
  deal, a machine hire or sale once either side marks it done, and an
  equipment partnership once it has run. One rating per piece of work, which
  its giver can change. The average shows on every profile card; tapping it
  shows what people said, and each profile lists what people say about its
  owner. A withdrawn proposal or an agreement that never happened cannot be
  rated, and the sync server refuses any rating that is not about work the two
  people finished together.
- **Farm diary and traceability** — per plot: sowing, sprays (with product,
  dose and pre-harvest interval), fertiliser, harvests and sales, with photos.
  Every harvest gets a lot code and a printable traceability record; a harvest
  taken before a spray's waiting period ended is flagged.
- **Weather advice** — a 7-day forecast per plot (Open-Meteo, kept for offline
  use) turned into plain advice: do not spray before rain or in wind, heavy
  rain, heat, frost, dry spells. Alerts reach the notification bell.
- **Mandi prices and exchange rates** — Agmarknet prices per crop, the owner's
  state first, with a 30-day trend; imported from a CSV or fetched with a
  data.gov.in key. International profiles see amounts as "≈ £/$/€" beside
  rupees, from stored rates that can be set by hand.
- **Government schemes** — 15 central schemes checked against the profile and
  land ("you may be eligible", "ask at the office", "probably not"), each with
  what the app cannot check, the papers needed and an application tracker.
- **Farmer groups** — farmers and FPOs/cooperatives/SHGs form groups, add
  members (including people with no phone), approve join requests, and ask for
  investment on the pooled land of all members at once.
- **My data** — one-file backups (database, pictures and reports) and restore,
  a copy of everything held about the owner, and erasure behind a typed
  confirmation.
- **Insights** — counts of farmers, requests, offers, deals, money released,
  machines and groups, for the owner's block, district, state or all of India.
- **Read aloud** — a "Listen" button on requests, notifications, messages,
  schemes, weather and deals, using the device's own voices.
- **Connections, shared land and farm updates** — people connect when both
  agree (a request, accepted), and people who already work together — a deal,
  an accepted offer or rental, a machinery partnership, the same group — are
  connected without asking. A farmer can share a plot with their connections:
  it appears on their timeline with place, size, soil, water, crops and
  pictures, never the survey number or exact pin, and moves back up marked
  *Updated* whenever the plot changes. Short farm updates with a picture go to
  the same people. Connected people can message each other and see each
  other's phone number.
- **Videos** — every plot, project request, machine and farmer group can carry
  an introduction video, and every profile a video biodata: the person telling
  their own story, which a reader who reads slowly takes in far better than a
  form. An investor, or a partner that invests, also has a video for their
  listing. A video is a YouTube link (only its id is stored and synced), or —
  for subscribers — a file uploaded directly to Mux. See [Videos](#videos).
- **Find investors, find farmers** — a farmer's "Find investors" lists every
  investor and investing partner who shared their profile, with what they
  fund, how much, where and how, best match for the farmer's own projects
  first; the farmer can send any shared project to one of them, and it is
  pinned at the top of that investor's Opportunities until they answer or say
  they are not interested. Investors and partners get "Find farmers": farmers
  who shared their profile, with their video biodata and the projects open to
  the viewer. Contact details stay hidden until the farmer accepts or the two
  connect.
- **Opt-in sync** — see [Sync](#sync).

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
| `profiles`                                     | All six user segments; one row is the device owner |
| `investment_requests`, `investment_interests`  | The marketplace: farmers' asks and the answers     |
| `insurance_policies`                           | Cover on a plot, a profile or a request            |
| `equipment_listings`, `equipment_enquiries`    | Machines for sale or rent, and asks to rent or buy |
| `equipment_partnerships`                       | Each seller's network of partners                  |
| `media_files`                                  | Index of photos; the files sit beside the database |
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

**Farming and non-farming projects.** The plan page shows two columns, each
ranked on its own: *farming projects* — crops, orchards, vegetables, spices,
livestock and fish — and *non-farming projects* — processing, storage and
services, most of which need little or no land. The split follows NABARD and
NRLM: crops and allied activities are the farm sector. Each kind in
`opportunities/_meta.json` carries `"sector": "farm"` or `"nonfarm"`, and an
option can override its kind (the sapling nursery is filed as a service but is
plants on land, so it is `farm`). Every option the API returns says which it
is.

**How a non-farming project is scored.** Soil and water say whether something
will grow; they say nothing about whether a dal mill will pay. So a non-farming
project skips those signals and is judged on what the device actually knows
about its business, from each option's `business` block (`crops` it works
with — codes or whole categories such as `pulse` — and the `catchmentVillages`
at which there is comfortably enough trade):

- **Raw material or customers in the family's own fields**, across all its
  plots: for a processing unit its raw material, for a service what its
  customers grow.
- **Farms nearby that grow it**: other farmers' open projects and farmer
  groups in the same district that the device can see (never sample data).
- **The catchment**: how many villages the tehsil has, from the LGD directory.
- **Honest cautions**: a mill with none of its raw material nearby is told it
  will buy everything in; a small tehsil is flagged.

Without evidence a non-farming project sits in the 40s; with its raw material
in hand and a large tehsil, one with sound economics reaches *Best suited*. The
list covers processing (spice grinding, dal mill, oil ghani, solar dryer, cold
room, atta chakki, mini rice mill, jaggery, village bakery) and services
(custom hiring, vermicompost, drone spraying, milk collection centre with bulk
cooler, agri-input shop and crop advice centre).

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
  UI, which covers nine Indic scripts, Ol Chiki and Latin, so a fresh install
  prints Hindi, Kannada or Santali with nothing downloaded. For the
  Perso-Arabic scripts and non-Windows machines, run `python scripts/fetch_fonts.py --all`
  once. A language whose script has no font is **refused with the exact command
  that fixes it**, rather than producing a page of empty boxes. Single-script
  faces such as Noto Naskh Arabic and Noto Sans Ol Chiki carry no Latin (Ol
  Chiki not even 0-9), so place names, web addresses and figures borrow from
  the Latin face, and any character nothing can draw is logged by name.
  Urdu, Kashmiri and Sindhi reports are laid out right to left once they have
  any translated text.
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

Complete today: **English, Hindi, Bengali, Marathi, Telugu, Tamil, Kannada**.
Every other language renders
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

## Profiles and the marketplace

**One profile per device.** Whoever owns this laptop or phone sets up one
profile on first run, and the app reshapes itself around it: a farmer sees
their land and their requests, an investor or partner sees farm projects to
answer, a government officer sees requests in their jurisdiction. The API has
no login because it only listens on loopback; every marketplace call acts as
the device owner. Other people's profiles sit in the same `profiles` table,
marked `origin = synced`, and only ever reach the UI as cards.

**What each segment records.** Common fields (name, organisation, phone, email,
place) are columns; what differs is in a `details` JSON column checked against
a per-segment schema in `apps/api/app/schemas.py`:

| Segment                 | Must give                                               | Checked                                      |
| ----------------------- | ------------------------------------------------------- | -------------------------------------------- |
| Farmer                  | Name, mobile, state and district                        | 10-digit Indian mobile; LGD codes            |
| Indian investor         | Investor type, ways of investing, mobile                | PAN format; organisation name for firms      |
| International investor  | Investor type, ways of investing, country, email        | Country outside India; FDI acknowledgement   |
| National farmer partner | Organisation name and type, what it offers, state       | GSTIN format; organisation type for segment  |
| International partner   | Organisation name and type, what it offers, country     | Country outside India                        |
| Government              | Office, level, department, designation, official email  | The area the level covers, as LGD codes      |

**Privacy by default.** A request's public face is a `listing` snapshot taken
when it is published: place names, land facts and the report's headline
figures. It leaves out the phone number, survey number and pin. Contact details
are exchanged only when a farmer accepts an interest. International and
government visibility are both opt-in, and a request a viewer may not see
returns 404 rather than 403.

**Identity.** Aadhaar numbers are never collected or stored.
`apps/api/app/services/kyc.py` fixes which verification route applies to which
segment (Aadhaar eKYC and DigiLocker for farmers, passport checks abroad,
registration documents for organisations, official email for government) and
refuses plainly until a UIDAI-authorised KUA is contracted. Every profile is
shown as "not verified" until then.

**Foreign investment.** Foreign nationals, NRIs and OCIs cannot buy or lease
Indian farmland, and FDI in farming is permitted only for some activities.
International investors must acknowledge this to create a profile, farmers are
warned before showing a request abroad, and investment modes describe a stake
in the farm *business*, never the land. This is guidance, not legal advice, and
should be reviewed by counsel before real money moves.

**Match score.** Each request is scored 0–100 against the viewer's profile:
for investors, preferred states, sectors, ticket size and investment mode; for
partners, operating states, partnership types and crops. A criterion the
viewer left blank scores half, so an empty preference is neutral rather than a
penalty. The reasons are shown beside the score.

**Insurance.** Policies live in one `insurance_policies` table, attached to
exactly one of a land parcel (crop cover per season, polyhouse structures), the
owner's profile (a farmer's accident, life, health, animals and machinery; a
partner's cargo, trade-credit and premises cover), or an investment request
(the project's own cover). Which categories each place accepts is the `scopes`
field in `packages/shared/reference/insurance-types.json`, and the schemes —
PMFBY, RWBCIS, NLM livestock, PMSBY, PMJJBY, PM-JAY, ECGC, or a private
policy — are in `insurance-schemes.json` with their published premium terms.

What a project must carry is content, not code:
`packages/shared/knowledge/insurance-rules.json` maps each kind of option (and a
few specific options) to **required** and **recommended** categories —
livestock projects require animal cover, polyhouses their structure,
processing units fire-and-allied cover, and hire centres and drone services
machinery cover because the law already requires third-party insurance for
them. A request cannot be published until every required category has either
a policy or the farmer's promise to insure before funds are released; the
promise is shown to investors as exactly that, and turns into a policy later
from *Find investors*. An expired policy does not count, and a required
policy cannot be deleted while the request is open. Investors see who insures
the project, for how much and until when, but the policy number stays masked
and the premium hidden until the farmer accepts them.

**Offline until shared.** Every profile, project and machine starts with
`visibility = offline`: it exists on the device and nowhere else. *Share
online* sets it `online`, stamps `shared_at`, and queues a `share` entry in the
sync outbox; *Take offline* reverses it. A project or machine can only be
shared once its owner's profile is shared, and taking the profile offline takes
everything under it offline too. Answering a request, asking about a machine or
asking to partner all need the asker's own profile shared, so the other side
can see who they are dealing with. The sync worker, when it is built, must
publish only `online` rows to the shared marketplace (`services/sharing.py`).

**The common timeline.** `GET /timeline` merges shared projects and machines,
newest first. Everyone reads the same feed, but projects still honour their
audiences (other farmers are now one of them, on by default and read-only),
and government officers still see only their own area.

**Photos.** `PUT /profile/photo` and `POST /equipment/{id}/photos` take the
image itself as the request body. Every picture is re-encoded with Pillow:
that proves it is an image, applies the phone's rotation, drops EXIF (which can
carry the GPS position of a farmer's house) and resizes it — 512 px for a
profile, 1280 px for a machine, four pictures per machine. Files live in a
`media` folder beside the database, so they follow it into the user-data
directory in a packaged build.

**Organisations that invest.** A partner organisation can tick *we also
invest* and give its investment modes and ticket size; it then answers a
farmer's request with either a partnership or an investment offer. Companies,
funds, banks and CSR foundations that only invest use the investor profiles.

**Equipment.** Partner organisations list machines (type, condition, year,
rent per hour, day, acre or season, sale price, quantity, operator, delivery,
place). Anyone else can ask to rent — with dates and acreage — or to buy; the
seller agrees or declines, and agreeing shares both sides' contact and records
`equipment_enquiry.accepted`. A seller's **partner network** holds farmers,
villages, districts and distributors in roles such as rental point, operator,
sales agent, service centre or distributor, with the machines covered and a
commission. A partner not on the platform is recorded by name and phone and is
active at once; one on the platform must accept. A farmer can ask a seller to
make them a direct partner, covering their own village.

**Events.** `profile.*`, `investment_request.*` and `investment_interest.*`
are recorded, with `investment_interest.accepted` as its own event: it is the
match the success fee will eventually be measured against. `deal.completed`
stays reserved for when the trust layer exists.

**Trying it on one machine.** Until cloud sync exists an investor's device has
no way to receive a farmer's request. `scripts/seed_demo_marketplace.py` stands
in for it: it adds sample requests in real LGD districts (plus one in the
owner's own district), and on a farmer's device sample answers to the farmer's
open requests. Everything it writes is `origin = demo`, labelled "Sample data"
in the app, and removed by `--remove`.

---

## Sync

Sync is off until the owner enters a sync server address under **More → My
data & sync**. Then, every five minutes and on "Sync now":

- **Only what is shared online leaves the device.** The outbox holds every
  change, but land, the diary, drafts and anything offline are *held*, never
  sent. Taking an item offline sends a deletion.
- **The server enforces ownership.** A device registers for one profile (the
  first device to claim a profile id owns it). It may write only its own
  records; the other party in an interest, enquiry, deal or dispute may change
  only its status (and a deal's milestones), never its content.
- **Contact details are redacted** — phone numbers, emails and policy numbers
  are removed from what other devices pull until the two people are connected
  (an accepted interest, enquiry or partnership, or a deal).
- **Requests reach only their chosen audiences; shared land and farm updates
  only the owner's connections.** When two people connect, the server sends
  each what the other had already shared (and the phone number the connection
  now reveals); when they disconnect, the other device drops it.
- What arrives is written locally and turned into notifications on the
  receiving device.

The server in `apps/sync/server.py` (FastAPI + its own SQLite, `VG_SYNC_DB`)
exists to develop and test this against. It is **not** a production service.
`apps/api/tests/test_sync.py` runs two devices against it end to end.

### Videos

A YouTube link needs nothing set up: paste it under the item's 🎬 video, and
only the 11-character video id is stored and synced. It plays from YouTube when
the device is online (the player shows a picture of it first, and fetches
nothing until someone presses play).

**Direct uploads** are for subscribers and go through [Mux](https://www.mux.com):

1. The Mux keys live on the sync server only — never on a villager's device.
   Create an API access token in the Mux dashboard (Video: read and write),
   then either set `MUX_TOKEN_ID` and `MUX_TOKEN_SECRET` in the environment
   before starting the server, or put them in `apps/sync/.env` (git-ignored):

   ```
   MUX_TOKEN_ID=...
   MUX_TOKEN_SECRET=...
   ```

2. There are no payments yet, so subscriptions are set by hand where the
   server runs. A device appears once it has synced:

   ```bash
   python apps/sync/admin.py list
   python apps/sync/admin.py subscribe <profile-id> --until 2027-03-31
   python apps/sync/admin.py unsubscribe <profile-id>
   ```

3. A subscriber then sees **Upload a video file** next to the YouTube box. The
   file is saved on the device first, then sent to Mux in 8 MB pieces on a
   background thread; a dropped connection resumes where it stopped on the next
   sync, and Mux keeps the upload address open for a week. Once Mux has encoded
   it, the playback id goes on the item and travels like any other change. Mux
   streams it adaptively (HLS, played with hls.js), so it suits a slow
   connection.

Uploads and video changes are recorded in `app_events`
(`video.upload_started`, `video.uploaded`), ready for metering paid hosting.

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

Phase 2, done: profiles for all six segments with photos, investment requests,
interests, match scoring, insurance on plots, profiles and projects, offline-
until-shared visibility with a common timeline, the equipment marketplace with
seller partner networks, notifications and messages, deals with milestone
release, disputes, ratings for deals, machine hires and sales and
partnerships, farmer groups with pooled requests, mandi
prices, the farm diary, weather advice, backups and the sync protocol with a
development server, introduction and biodata videos with Mux uploads for
subscribers, and farmers and investors finding each other. Phase 2, next:
payments for subscriptions, KYC through an authorised provider, a
production sync service (PostgreSQL, authentication beyond device tokens,
abuse controls), and legal review of the deal and dispute terms.

Phase 3: self-hosted map and geocoding infrastructure, scheme application
assistance beyond tracking, partnership-based verification tier, voice input,
more languages in the app itself (reports already cover 22).

Integration points already stubbed: `services/kyc.py` and the `Profile.kyc_*`
columns for Aadhaar eKYC, DigiLocker and the later police-verification tier;
`sync_queue` for cloud sync; `LandParcel.latitude/longitude` for Leaflet plot
mapping.

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
| `VG_MEDIA_DIR`      | next to the database, `media/`     | Photos and logos               |
| `VG_BACKUPS_DIR`    | next to the database, `backups/`   | One-file backups               |
| `VG_ALLOW_NETWORK`  | `true`                             | `false` keeps the API offline  |
| `VG_DATA_GOV_API_KEY` | none                             | Fetch Agmarknet mandi prices   |
| `VG_SYNC_DB`        | `apps/sync/data/sync.db`           | Development sync server's DB   |
| `MUX_TOKEN_ID`      | none (sync server only)            | Mux token for video uploads    |
| `MUX_TOKEN_SECRET`  | none (sync server only)            | Its secret; or `apps/sync/.env`|
| `VG_ALLOW_NETWORK`  | `true`                             | Permit the two online lookups  |

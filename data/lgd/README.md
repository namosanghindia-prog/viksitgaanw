# LGD location data

The app's location selector is backed by the **Local Government Directory
(LGD)** — the Government of India's official directory of states, districts,
sub-districts and villages. It is published on
[data.gov.in](https://data.gov.in) and [lgdirectory.gov.in](https://lgdirectory.gov.in),
and is free for commercial use.

The whole dataset is imported into SQLite at setup time, so the selector works
with the device fully offline.

## What ships in this repo

`sample/` — a small development sample so the app runs before anyone downloads
the real dump.

> [!IMPORTANT]
> **The sample is not authoritative.** State codes in `01-states.csv` are the
> real LGD/Census codes, but every district, sub-district and village code in
> `02-villages.csv` is **synthetic**, allocated from a reserved `99xxxx` range
> so it can never be mistaken for an official code. The place names are real;
> the codes attached to them are not.
>
> Import the real dump before this app produces any report someone relies on.

Regenerate the sample with:

```bash
python scripts/generate_sample_lgd.py
```

## Importing the real dump

```bash
python scripts/fetch_lgd.py                                  # download
python scripts/import_lgd.py --source data/lgd/dump --replace  # import
```

`fetch_lgd.py` pulls dated CSV archives from a public daily mirror of
lgdirectory.gov.in, because the official download page is session-based and
cannot be scripted. Pin a snapshot with `--date 09Sep2026`, or fetch a single
level with `--levels districts`.

**No internet on the target machine?** Download the archives on any machine,
copy the CSVs into `data/lgd/dump/` (git-ignored), and run the import. The
importer does not care how the files got there.

A single village-level CSV is also enough on its own: it repeats the full
state → district → sub-district chain on every row, and the importer
back-fills the three parent tables from it.

### What a full import produces

Snapshot of 9 Sep 2026:

| Level          |    Rows |
| -------------- | ------: |
| States / UTs   |      36 |
| Districts      |     784 |
| Sub-districts  |   7,092 |
| Villages       | 677,523 |

Takes about a minute and leaves an approximately 100 MB SQLite file. The import
is idempotent — re-running against a newer LGD release updates rows in place
rather than duplicating them — and finishes with a `VACUUM` and `ANALYZE`
(skip with `--no-optimise`).

> [!NOTE]
> ~100 MB is fine for a laptop. When the phone shell arrives, ship a per-state
> subset rather than the national table; the schema already carries
> `state_code` on every level to make that a `WHERE` clause.

## Column handling

LGD exports do not use consistent headers between downloads. The importer
matches columns by normalised name (lowercased, non-alphanumerics stripped),
so all of these resolve to the same field:

| Header in the file                | Resolved field   |
| --------------------------------- | ---------------- |
| `Sub-District Code`               | `subdistrict_code` |
| `Sub District Code`               | `subdistrict_code` |
| `SubDistrict Code`                | `subdistrict_code` |
| `Village Name (In English)`       | `village_name`   |
| `Village Name(In English)`        | `village_name`   |

If a file has no recognisable columns the importer says so and skips it rather
than importing garbage. Add new spellings to `COLUMN_ALIASES` in
`scripts/import_lgd.py`.

Codes are canonicalised to unpadded integer strings (`"09"`, `"9.0"` and `" 9 "`
all become `"9"`), so codes from different exports always join correctly.

## Blocks vs sub-districts

LGD models the *sub-district* (tehsil / taluk / mandal) and the *Panchayat
Samiti block* as two parallel hierarchies. Phase 1 stores the sub-district,
which is the one villages hang off in the village directory. If block-level
grouping is needed later (likely for FPO and Gram Panchayat features in phase
2), it should be added as a separate table rather than by overloading
`subdistricts`.

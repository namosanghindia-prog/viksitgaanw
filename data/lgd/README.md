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

1. Download the village directory export from
   [lgdirectory.gov.in](https://lgdirectory.gov.in) (Reports → Village
   directory) or the LGD dataset on data.gov.in. A single village-level CSV is
   enough: it repeats the full state → district → sub-district chain on every
   row, and the importer back-fills the three parent tables from it.
2. Put the CSV(s) in `data/lgd/dump/` (git-ignored).
3. Run:

```bash
python scripts/import_lgd.py --source data/lgd/dump --replace
```

Expect roughly 660,000 village rows. The import is idempotent — re-running it
against a newer LGD release updates rows in place rather than duplicating them.

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

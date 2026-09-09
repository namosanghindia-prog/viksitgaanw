#!/usr/bin/env python
"""Regenerate the bundled development sample in ``data/lgd/sample``.

IMPORTANT
---------
This sample exists so the app is runnable before anyone downloads the ~250 MB
official dump. The **state codes are the real LGD/Census codes**, but every
district, sub-district and village code below is **synthetic**, allocated from a
reserved ``99xxxx`` range precisely so it can never be confused with an official
LGD code. Place names are real; the codes attached to them are not.

Before this app produces a project report anyone relies on, import the real
dump (see ``data/lgd/README.md``):

    python scripts/import_lgd.py --source data/lgd/dump --replace
"""

from __future__ import annotations

import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "data" / "lgd" / "sample" / "02-villages.csv"

#: state -> districts -> sub-districts -> villages, with (english, local) names.
SAMPLE: dict[tuple[str, str], list] = {
    ("09", "Uttar Pradesh"): [
        ("990901", "Varanasi", "वाराणसी", [
            ("99090101", "Pindra", "पिण्डरा", [
                ("Bhagwanpur", "भगवानपुर"), ("Kachnar", "कचनार"),
                ("Rampur Bujurg", "रामपुर बुजुर्ग"), ("Sindhora", "सिंधोरा"),
                ("Barai", "बरई"), ("Dhanapur", "धनापुर"),
            ]),
            ("99090102", "Rajatalab", "राजातालाब", [
                ("Kachhwa", "कछवां"), ("Mirzamurad", "मिर्जामुराद"),
                ("Kapsethi", "कपसेठी"), ("Bhikharipur", "भिखारीपुर"),
                ("Jansa", "जनसा"), ("Karkhiyaon", "करखियांव"),
            ]),
        ]),
        ("990902", "Gorakhpur", "गोरखपुर", [
            ("99090201", "Sahjanwa", "सहजनवां", [
                ("Piprauli", "पिपरौली"), ("Jangal Kaudia", "जंगल कौड़िया"),
                ("Bhathat", "भथहट"), ("Khajni", "खजनी"),
                ("Belghat", "बेलघाट"), ("Uruwa", "उरुवा"),
            ]),
            ("99090202", "Bansgaon", "बांसगांव", [
                ("Kauriram", "कौड़ीराम"), ("Gagaha", "गगहा"),
                ("Barhalganj", "बड़हलगंज"), ("Sikriganj", "सिकरीगंज"),
                ("Hariharpur", "हरिहरपुर"), ("Madhopur", "मधोपुर"),
            ]),
        ]),
    ],
    ("27", "Maharashtra"): [
        ("992701", "Nashik", "नाशिक", [
            ("99270101", "Niphad", "निफाड", [
                ("Pimpalgaon Baswant", "पिंपळगाव बसवंत"), ("Ozar", "ओझर"),
                ("Lasalgaon", "लासलगाव"), ("Chandori", "चांदोरी"),
                ("Saikheda", "सायखेडा"), ("Ugaon", "उगाव"),
            ]),
            ("99270102", "Dindori", "दिंडोरी", [
                ("Vani", "वणी"), ("Mohadi", "मोहाडी"), ("Janori", "जानोरी"),
                ("Umrale", "उमराळे"), ("Palkhed", "पालखेड"), ("Karanjwan", "करंजवण"),
            ]),
        ]),
        ("992702", "Ahmednagar", "अहमदनगर", [
            ("99270201", "Rahuri", "राहुरी", [
                ("Deolali Pravara", "देवळाली प्रवरा"), ("Tahakari", "ताहाकारी"),
                ("Vambori", "वांबोरी"), ("Kendal", "केंदळ"),
                ("Sadatpur", "सदातपूर"), ("Manjori", "मांजोरी"),
            ]),
            ("99270202", "Sangamner", "संगमनेर", [
                ("Ashvi", "आश्वी"), ("Ghargaon", "घारगाव"), ("Samnapur", "सामनापूर"),
                ("Nimgaon Jali", "निमगाव जाळी"), ("Talegaon", "तळेगाव"), ("Akolner", "अकोलनेर"),
            ]),
        ]),
    ],
    ("29", "Karnataka"): [
        ("992901", "Belagavi", "ಬೆಳಗಾವಿ", [
            ("99290101", "Bailhongal", "ಬೈಲಹೊಂಗಲ", [
                ("Sampgaon", "ಸಂಪಗಾವ"), ("Neginhal", "ನೇಗಿನಹಾಳ"),
                ("Budarkatti", "ಬುಡರಕಟ್ಟಿ"), ("Amatur", "ಅಮಟೂರು"),
                ("Hosur", "ಹೊಸೂರು"), ("Devalapur", "ದೇವಲಾಪುರ"),
            ]),
            ("99290102", "Gokak", "ಗೋಕಾಕ", [
                ("Konnur", "ಕೊಣ್ಣೂರು"), ("Ghataprabha", "ಘಟಪ್ರಭಾ"),
                ("Mudalgi", "ಮುದಲಗಿ"), ("Yadwad", "ಯಡವಾಡ"),
                ("Kaladgi", "ಕಲಾದಗಿ"), ("Arabhavi", "ಅರಭಾವಿ"),
            ]),
        ]),
        ("992902", "Mysuru", "ಮೈಸೂರು", [
            ("99290201", "Nanjangud", "ನಂಜನಗೂಡು", [
                ("Hullahalli", "ಹುಲ್ಲಹಳ್ಳಿ"), ("Biligere", "ಬಿಳಿಗೆರೆ"),
                ("Thandavapura", "ತಾಂಡವಪುರ"), ("Kalale", "ಕಳಲೆ"),
                ("Devanur", "ದೇವನೂರು"), ("Hedathale", "ಹೆದತಲೆ"),
            ]),
            ("99290202", "T. Narasipura", "ತಿ. ನರಸೀಪುರ", [
                ("Talakadu", "ತಲಕಾಡು"), ("Bannur", "ಬನ್ನೂರು"), ("Sosale", "ಸೋಸಲೆ"),
                ("Mugur", "ಮೂಗೂರು"), ("Hemmige", "ಹೆಮ್ಮಿಗೆ"), ("Halegowdanahalli", "ಹಳೇಗೌಡನಹಳ್ಳಿ"),
            ]),
        ]),
    ],
}

# Deliberately mirrors the real LGD export header style, including the
# inconsistent spacing, so the importer is exercised against realistic input.
FIELDNAMES = [
    "State Code",
    "State Name (In English)",
    "District Code",
    "District Name (In English)",
    "District Name (In Local)",
    "Sub-District Code",
    "Sub-District Name (In English)",
    "Sub-District Name (In Local)",
    "Village Code",
    "Village Name (In English)",
    "Village Name (In Local)",
]


def build_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for (state_code, state_name), districts in SAMPLE.items():
        for district_code, district_name, district_local, subdistricts in districts:
            for sub_code, sub_name, sub_local, villages in subdistricts:
                for index, (village_name, village_local) in enumerate(villages, start=1):
                    rows.append(
                        {
                            "State Code": state_code,
                            "State Name (In English)": state_name,
                            "District Code": district_code,
                            "District Name (In English)": district_name,
                            "District Name (In Local)": district_local,
                            "Sub-District Code": sub_code,
                            "Sub-District Name (In English)": sub_name,
                            "Sub-District Name (In Local)": sub_local,
                            "Village Code": f"{sub_code}{index:02d}",
                            "Village Name (In English)": village_name,
                            "Village Name (In Local)": village_local,
                        }
                    )
    return rows


def main() -> int:
    rows = build_rows()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} village rows to {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

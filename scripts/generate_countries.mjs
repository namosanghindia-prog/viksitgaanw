#!/usr/bin/env node
/**
 * Generate packages/shared/reference/countries.json from ICU.
 *
 *     node scripts/generate_countries.mjs
 *
 * International investors and partners need a country, and the reference lists
 * carry English and Hindi labels. Typing 249 Hindi country names by hand is how
 * typos get into a KYC record, so they come from the ICU data Node already
 * ships instead. Re-run after a Node upgrade if a name needs refreshing.
 */

import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT = join(
  dirname(fileURLToPath(import.meta.url)),
  '..',
  'packages',
  'shared',
  'reference',
  'countries.json',
);

// Two-letter codes ICU knows as regions but which are not ISO 3166-1 countries:
// reserved, exceptional or grouping codes, and retired aliases ICU still
// resolves (UK for GB, SU for Russia, YU for Serbia...). Leaving the aliases
// in would list a country twice under two codes.
const NOT_COUNTRIES = new Set([
  'AC', 'CP', 'CQ', 'DG', 'EA', 'EU', 'EZ', 'IC', 'QO', 'TA', 'UN', 'XA', 'XB', 'ZZ',
  'AN', 'BU', 'CS', 'DD', 'DY', 'FX', 'HV', 'NH', 'RH', 'SU', 'TP', 'UK', 'VD', 'YD',
  'YU', 'ZR',
]);

const english = new Intl.DisplayNames(['en'], { type: 'region', fallback: 'none' });
const hindi = new Intl.DisplayNames(['hi'], { type: 'region', fallback: 'none' });

const items = [];
for (let first = 65; first <= 90; first += 1) {
  for (let second = 65; second <= 90; second += 1) {
    const code = String.fromCharCode(first, second);
    if (NOT_COUNTRIES.has(code)) continue;
    const en = english.of(code);
    if (!en || en === code) continue;
    items.push({ code, label: { en, hi: hindi.of(code) ?? en } });
  }
}
items.sort((a, b) => a.label.en.localeCompare(b.label.en, 'en'));

const body = {
  key: 'countries',
  version: 1,
  source: `ICU ${process.versions.icu} via Node ${process.versions.node}`,
  items,
};
writeFileSync(OUT, `${JSON.stringify(body, null, 2)}\n`, 'utf8');
console.log(`Wrote ${items.length} countries to ${OUT}`);

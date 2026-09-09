import type { LanguageCode, LocationPath } from '@viksitgaanw/shared';

/** Locale tags used for number formatting. Devanagari digits are *not* used:
 *  farmers read Latin digits on every land record and phone they own. */
const LOCALES: Record<LanguageCode, string> = {
  en: 'en-IN',
  hi: 'hi-IN',
};

export function formatNumber(value: number, lang: LanguageCode, maxFractionDigits = 2): string {
  return new Intl.NumberFormat(LOCALES[lang], {
    maximumFractionDigits: maxFractionDigits,
    numberingSystem: 'latn',
  }).format(value);
}

export function formatDate(iso: string, lang: LanguageCode): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(LOCALES[lang], {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    numberingSystem: 'latn',
  }).format(date);
}

/** "Rampur Bujurg, Pindra, Varanasi, Uttar Pradesh" -- most specific first. */
export function formatLocationPath(path: LocationPath | undefined): string {
  if (!path) return '';
  return [path.village, path.subdistrict, path.district, path.state]
    .filter((unit) => unit !== null && unit !== undefined)
    .map((unit) => unit!.name)
    .join(', ');
}

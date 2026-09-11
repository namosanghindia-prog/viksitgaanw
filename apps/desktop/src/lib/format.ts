import type { LanguageCode, LocationPath } from '@viksitgaanw/shared';

/** Locale tags used for number formatting. Devanagari digits are *not* used:
 *  farmers read Latin digits on every land record and phone they own. */
const LOCALES: Record<LanguageCode, string> = {
  en: 'en-IN',
  hi: 'hi-IN',
  bn: 'bn-IN',
  mr: 'mr-IN',
  ta: 'ta-IN',
  te: 'te-IN',
  kn: 'kn-IN',
};

/** The locale tag for a language, for the few places that format directly. */
export function localeFor(lang: LanguageCode): string {
  return LOCALES[lang] ?? 'en-IN';
}

export function formatNumber(
  value: number,
  lang: LanguageCode,
  maxFractionDigits = 2,
  minFractionDigits = 0,
): string {
  return new Intl.NumberFormat(LOCALES[lang], {
    maximumFractionDigits: maxFractionDigits,
    minimumFractionDigits: minFractionDigits,
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

/**
 * Money the way it is spoken in India: 4.25 lakh, 1.30 crore.
 *
 * A farmer reads "12,34,567" more slowly than "12.35 lakh", and every figure in
 * the options list is an estimate anyway, so the precision would be false.
 * Exact rupee amounts are still printed in the project report's tables.
 */
export function formatMoneyShort(
  rupees: number,
  lang: LanguageCode,
  t: (key: 'plan.lakh' | 'plan.crore') => string,
): string {
  const amount = Math.abs(rupees);
  if (amount >= 10_000_000) {
    return `${formatNumber(rupees / 10_000_000, lang, 2)} ${t('plan.crore')}`;
  }
  if (amount >= 100_000) {
    return `${formatNumber(rupees / 100_000, lang, 2)} ${t('plan.lakh')}`;
  }
  return formatNumber(rupees, lang, 0);
}

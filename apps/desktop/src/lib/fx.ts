import { useEffect, useState } from 'react';
import type { FxRate, LanguageCode, Profile } from '@viksitgaanw/shared';

import { localeFor } from './format';

import { api } from './api';
import { isInternational } from './segments';

/** Countries that price in euro, for an international profile's own currency. */
const EURO_COUNTRIES = new Set([
  'AT', 'BE', 'CY', 'DE', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PT', 'SI', 'SK',
]);

/** The currency a foreign investor or partner thinks in; null for Indian profiles. */
export function viewerCurrency(profile: Profile | null): string | null {
  if (!profile || !isInternational(profile.segment)) return null;
  if (profile.countryCode === 'GB') return 'GBP';
  if (EURO_COUNTRIES.has(profile.countryCode)) return 'EUR';
  return 'USD';
}

let cache: Promise<FxRate[]> | null = null;

/** Stored exchange rates, fetched once per session; empty when none are stored. */
export function useFxRates(enabled: boolean): FxRate[] {
  const [rates, setRates] = useState<FxRate[]>([]);
  useEffect(() => {
    if (!enabled) return;
    cache ??= api
      .fx()
      .then((answer) => answer.rates)
      .catch(() => {
        cache = null;
        return [];
      });
    let active = true;
    void cache.then((value) => {
      if (active) setRates(value);
    });
    return () => {
      active = false;
    };
  }, [enabled]);
  return rates;
}

/** Forget the cached rates after they were refreshed or overridden. */
export function invalidateFx() {
  cache = null;
}

/** "≈ US$4,560" for a rupee amount, or null without a rate. */
export function approxForeign(rupees: number, currency: string | null, rates: FxRate[], lang: LanguageCode) {
  if (!currency) return null;
  const rate = rates.find((entry) => entry.currency === currency);
  if (!rate || rate.inrPerUnit <= 0) return null;
  return new Intl.NumberFormat(localeFor(lang), {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
    numberingSystem: 'latn',
  }).format(rupees / rate.inrPerUnit);
}

import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { LanguageCode, Label, ReferenceItem } from '@viksitgaanw/shared';
import { pickLabel } from '@viksitgaanw/shared';

import { DICTIONARIES, type StringKey } from './strings';

const STORAGE_KEY = 'viksitgaanw.language';
const DEFAULT_LANGUAGE: LanguageCode = 'hi';

/**
 * The languages the screens are in, each named in its own script so a reader
 * finds theirs without reading English. Hindi and English are complete; the
 * others are drafts awaiting a native speaker's review, and anything not yet
 * translated shows in English.
 */
export const LANGUAGES: ReadonlyArray<{ code: LanguageCode; name: string; draft: boolean }> = [
  { code: 'hi', name: 'हिन्दी', draft: false },
  { code: 'en', name: 'English', draft: false },
  { code: 'bn', name: 'বাংলা', draft: true },
  { code: 'mr', name: 'मराठी', draft: true },
  { code: 'te', name: 'తెలుగు', draft: true },
  { code: 'ta', name: 'தமிழ்', draft: true },
  { code: 'kn', name: 'ಕನ್ನಡ', draft: true },
];

const KNOWN = new Set<string>(LANGUAGES.map((entry) => entry.code));

interface I18nValue {
  lang: LanguageCode;
  setLang: (lang: LanguageCode) => void;
  /** Translate a UI string, substituting {placeholders}. */
  t: (key: StringKey, vars?: Record<string, string | number>) => string;
  /** Label a reference item (soil type, crop, ...) in the current language. */
  rt: (item: ReferenceItem | undefined) => string;
  /** Label a bilingual value coming from the API (a village name, say). */
  lt: (label: Label | undefined) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

function readStoredLanguage(): LanguageCode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && KNOWN.has(stored)) return stored as LanguageCode;
  } catch {
    // Private mode or a locked-down profile: fall through to the default.
  }
  return DEFAULT_LANGUAGE;
}

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<LanguageCode>(readStoredLanguage);

  const setLang = useCallback((next: LanguageCode) => {
    setLangState(next);
    document.documentElement.lang = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Remembering the choice is a convenience, not a requirement.
    }
  }, []);

  const value = useMemo<I18nValue>(() => {
    const dictionary = DICTIONARIES[lang];
    return {
      lang,
      setLang,
      t: (key, vars) => interpolate(dictionary[key] ?? DICTIONARIES.en[key] ?? key, vars),
      rt: (item) => (item ? pickLabel(item.label, lang) || item.code : ''),
      lt: (label) => pickLabel(label, lang),
    };
  }, [lang, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const context = useContext(I18nContext);
  if (!context) throw new Error('useI18n must be used inside <I18nProvider>.');
  return context;
}

export type { StringKey };

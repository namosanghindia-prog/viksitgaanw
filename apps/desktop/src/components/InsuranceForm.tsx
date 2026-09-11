import { useEffect, useMemo, useState } from 'react';
import type { CropSeason, InsuranceInput, ReferenceItem } from '@viksitgaanw/shared';
import { findItem, pickLabel, schemesFor } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { ChoiceGroup } from './ChoiceGroup';
import { TextField } from './TextField';

const SEASONS: CropSeason[] = ['kharif', 'rabi', 'zaid', 'annual'];
const CURRENCIES = ['INR', 'USD', 'EUR', 'GBP', 'AED'];

interface InsuranceFormProps {
  /** Categories that may be chosen. With one, the choice is not shown. */
  categories: ReferenceItem[];
  initial?: Partial<InsuranceInput> | null;
  /** Partners trading abroad hold policies in other currencies. */
  currencyChoice?: boolean;
  onSubmit: (input: InsuranceInput) => Promise<void> | void;
  onClose: () => void;
}

/**
 * Enter one insurance policy.
 *
 * Only the scheme or the insurer is required -- a farmer holding a PMFBY
 * receipt may not know which company underwrote it, and a private policy has
 * no scheme at all. Everything else helps an investor judge the cover but is
 * never a reason to refuse it.
 */
export function InsuranceForm({ categories, initial, currencyChoice = false, onSubmit, onClose }: InsuranceFormProps) {
  const { t, lang, rt } = useI18n();

  const [category, setCategory] = useState<string | null>(initial?.category ?? categories[0]?.code ?? null);
  const [scheme, setScheme] = useState<string | null>(initial?.scheme ?? null);
  const [insurer, setInsurer] = useState(initial?.insurer ?? '');
  const [policyNumber, setPolicyNumber] = useState(initial?.policyNumber ?? '');
  const [sumInsured, setSumInsured] = useState(initial?.sumInsured ? String(initial.sumInsured) : '');
  const [premium, setPremium] = useState(initial?.premium != null ? String(initial.premium) : '');
  const [currency, setCurrency] = useState(initial?.currency ?? 'INR');
  const [validFrom, setValidFrom] = useState(initial?.validFrom ?? '');
  const [validUntil, setValidUntil] = useState(initial?.validUntil ?? '');
  const [season, setSeason] = useState<string | null>(initial?.season ?? null);
  const [seasonYear, setSeasonYear] = useState(
    initial?.seasonYear ? String(initial.seasonYear) : String(new Date().getFullYear()),
  );
  const [covered, setCovered] = useState(initial?.covered ?? '');
  const [notes, setNotes] = useState(initial?.notes ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  const schemes = useMemo(() => (category ? schemesFor(category) : []), [category]);
  const chosenScheme = findItem('insurance_schemes', scheme);
  const seasonItems = useMemo<ReferenceItem[]>(
    () => SEASONS.map((code) => ({ code, label: { en: t(`season.${code}`), hi: t(`season.${code}`) } })),
    [t],
  );

  // A scheme belongs to a category; switching category clears a stale one.
  const pickCategory = (next: string | null) => {
    setCategory(next);
    if (next && scheme && !schemesFor(next).some((item) => item.code === scheme)) setScheme(null);
  };

  const submit = async () => {
    if (!category) {
      setError(`${t('insurance.category')}: ${t('error.chooseOne')}`);
      return;
    }
    if (!scheme && !insurer.trim()) {
      setError(t('insurance.needSchemeOrInsurer'));
      return;
    }
    if (validFrom && validUntil && validFrom > validUntil) {
      setError(t('insurance.datesOrder'));
      return;
    }
    const number = (text: string) => {
      const value = Number.parseFloat(text);
      return Number.isFinite(value) && value >= 0 ? value : null;
    };
    setBusy(true);
    setError(null);
    try {
      await onSubmit({
        category,
        status: 'insured',
        scheme,
        insurer: insurer.trim() || null,
        policyNumber: policyNumber.trim() || null,
        sumInsured: number(sumInsured) || null,
        premium: number(premium),
        currency,
        validFrom: validFrom || null,
        validUntil: validUntil || null,
        season: category === 'crop' ? ((season as CropSeason | null) ?? null) : null,
        seasonYear: category === 'crop' && season ? Number.parseInt(seasonYear, 10) || null : null,
        covered: covered.trim() || null,
        notes: notes.trim() || null,
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={t('insurance.formTitle')}>
      <div className="modal__backdrop" onClick={() => (busy ? undefined : onClose())} />
      <div className="modal__panel">
        <header className="modal__head">
          <div>
            <h3 className="modal__title">{t('insurance.formTitle')}</h3>
            {category ? <p className="modal__subtitle">{rt(findItem('insurance_types', category))}</p> : null}
          </div>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={onClose}
            disabled={busy}
            aria-label={t('common.cancel')}
          >
            ✕
          </button>
        </header>

        <div className="modal__body stack">
          {categories.length > 1 ? (
            <ChoiceGroup label={t('insurance.category')} items={categories} allowCustom value={category} onChange={pickCategory} />
          ) : null}

          {schemes.length ? (
            <ChoiceGroup label={t('insurance.scheme')} items={schemes} value={scheme} onChange={setScheme} />
          ) : null}
          {chosenScheme?.note ? (
            <p className="callout callout--info">
              {pickLabel(chosenScheme.note, lang)}{' '}
              {chosenScheme.url ? (
                <a href={chosenScheme.url} target="_blank" rel="noreferrer">
                  {t('insurance.learnMore')}
                </a>
              ) : null}
            </p>
          ) : null}

          <TextField id="insurer" label={t('insurance.insurer')} value={insurer} onChange={setInsurer} maxLength={160} />
          <TextField
            id="policyNumber"
            label={t('insurance.policyNumber')}
            value={policyNumber}
            onChange={setPolicyNumber}
            optional
            maxLength={80}
          />

          <div className="field-row">
            <TextField
              id="sumInsured"
              label={t('insurance.sumInsured')}
              type="number"
              inputMode="numeric"
              min={0}
              value={sumInsured}
              onChange={setSumInsured}
              optional
            />
            <TextField
              id="premium"
              label={t('insurance.premium')}
              type="number"
              inputMode="numeric"
              min={0}
              value={premium}
              onChange={setPremium}
              optional
            />
          </div>

          {currencyChoice ? (
            <div className="field narrow">
              <label className="field__label" htmlFor="currency">
                {t('insurance.currency')}
              </label>
              <select id="currency" className="input" value={currency} onChange={(event) => setCurrency(event.target.value)}>
                {CURRENCIES.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          {category === 'crop' ? (
            <>
              <ChoiceGroup label={t('insurance.season')} items={seasonItems} value={season} onChange={setSeason} />
              {season ? (
                <div className="narrow">
                  <TextField
                    id="seasonYear"
                    label={t('insurance.seasonYear')}
                    type="number"
                    inputMode="numeric"
                    min={2000}
                    value={seasonYear}
                    onChange={setSeasonYear}
                  />
                </div>
              ) : null}
            </>
          ) : null}

          <div className="field-row">
            <TextField id="validFrom" label={t('insurance.validFrom')} type="date" value={validFrom} onChange={setValidFrom} optional />
            <TextField id="validUntil" label={t('insurance.validUntil')} type="date" value={validUntil} onChange={setValidUntil} optional />
          </div>

          <TextField
            id="covered"
            label={t('insurance.covered')}
            hint={t('insurance.coveredHint')}
            value={covered}
            onChange={setCovered}
            optional
            maxLength={300}
          />
          <TextField id="insuranceNotes" label={t('insurance.notes')} value={notes} onChange={setNotes} optional multiline maxLength={2000} />

          {error ? <p className="callout callout--error">{error}</p> : null}
        </div>

        <footer className="modal__foot">
          <button type="button" className="button button--ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </button>
          <button type="button" className="button button--primary" onClick={submit} disabled={busy}>
            {busy ? t('common.saving') : t('common.save')}
          </button>
        </footer>
      </div>
    </div>
  );
}

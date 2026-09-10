import { useEffect, useMemo, useState } from 'react';
import type { LandParcel, Opportunity, ProjectReport } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatMoneyShort } from '../lib/format';
import { useAsync } from '../lib/hooks';

interface DprDialogProps {
  parcel: LandParcel;
  opportunity: Opportunity;
  onClose: () => void;
  onCreated: (report: ProjectReport) => void;
}

/**
 * Turn a chosen option into a project report, in the language the farmer picks.
 *
 * The language list is not cosmetic. It is served by the backend and carries
 * two facts per language: how much of the report has actually been translated,
 * and whether this device has a font that can draw the script at all. Both are
 * shown, because handing someone a PDF of empty boxes -- or one that silently
 * came out in English -- would be worse than telling them plainly.
 */
export function DprDialog({ parcel, opportunity, onClose, onCreated }: DprDialogProps) {
  const { t, lang } = useI18n();

  const languages = useAsync((signal) => api.reportLanguages(lang, signal), [lang]);

  // Deliberately a plain string, not the app's LanguageCode: the report can be
  // written in any of the twenty-two scheduled languages, while the interface
  // itself is only translated into two so far.
  const [language, setLanguage] = useState<string>(lang);
  const [promoterName, setPromoterName] = useState('');
  const [promoterPhone, setPromoterPhone] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [margin, setMargin] = useState('25');
  const [interest, setInterest] = useState('11');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  const selected = useMemo(
    () => languages.data?.find((entry) => entry.code === language),
    [languages.data, language],
  );

  const usable = useMemo(
    () => (languages.data ?? []).filter((entry) => entry.fontAvailable),
    [languages.data],
  );
  const blocked = useMemo(
    () => (languages.data ?? []).filter((entry) => !entry.fontAvailable),
    [languages.data],
  );

  const submit = async () => {
    if (!promoterName.trim()) {
      setError(t('dpr.nameRequired'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const report = await api.createReport(parcel.id, {
        opportunityCode: opportunity.code,
        language,
        promoterName: promoterName.trim(),
        promoterPhone: promoterPhone.trim() || null,
        margin: advanced ? Number.parseFloat(margin) / 100 : null,
        interestRate: advanced ? Number.parseFloat(interest) / 100 : null,
      });
      onCreated(report);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={t('dpr.title')}>
      <div className="modal__backdrop" onClick={() => (busy ? undefined : onClose())} />
      <div className="modal__panel">
        <header className="modal__head">
          <div>
            <h3 className="modal__title">{t('dpr.title')}</h3>
            <p className="modal__subtitle">{opportunity.name}</p>
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

        <div className="modal__body">
          <p className="callout callout--info">
            {t('dpr.lede', {
              cost: formatMoneyShort(opportunity.economics.totalProjectCost, lang, t),
              net: formatMoneyShort(opportunity.economics.netPerYear.mid, lang, t),
            })}
          </p>

          <div className="field">
            <label className="field__label" htmlFor="promoter">
              {t('dpr.promoterName')}
              <span className="field__required"> *</span>
            </label>
            <p className="field__hint">{t('dpr.promoterHint')}</p>
            <input
              id="promoter"
              className="input"
              value={promoterName}
              onChange={(event) => setPromoterName(event.target.value)}
              maxLength={160}
              autoFocus
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="phone">
              {t('dpr.promoterPhone')}{' '}
              <span className="field__optional">({t('common.optional')})</span>
            </label>
            <input
              id="phone"
              className="input"
              value={promoterPhone}
              onChange={(event) => setPromoterPhone(event.target.value)}
              maxLength={20}
              inputMode="tel"
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="dprLang">
              {t('dpr.language')}
              <span className="field__required"> *</span>
            </label>
            <p className="field__hint">{t('dpr.languageHint')}</p>
            <select
              id="dprLang"
              className="input"
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              disabled={languages.loading}
            >
              {usable.map((entry) => (
                <option key={entry.code} value={entry.code}>
                  {/* The endonym is what a farmer scans for. The English name
                      is only added when it says something different. */}
                  {entry.endonym}
                  {entry.label && entry.label !== entry.endonym ? ` — ${entry.label}` : ''}
                  {entry.coverage < 0.999 ? ` (${t('dpr.partial')})` : ''}
                </option>
              ))}
            </select>

            {selected && selected.coverage < 0.999 ? (
              <p className="callout callout--warn">
                {t('dpr.partialWarning', {
                  language: selected.endonym,
                  percent: Math.round(selected.coverage * 100),
                })}
              </p>
            ) : null}

            {blocked.length > 0 ? (
              <p className="field__hint">
                {t('dpr.fontMissing', {
                  languages: blocked.map((entry) => entry.endonym).join(', '),
                })}{' '}
                <code>python scripts/fetch_fonts.py --all</code>
              </p>
            ) : null}
          </div>

          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => setAdvanced((value) => !value)}
            aria-expanded={advanced}
          >
            {advanced ? '▾' : '▸'} {t('dpr.loanTerms')}
          </button>

          {advanced ? (
            <div className="field-row">
              <div className="field field--area">
                <label className="field__label" htmlFor="margin">
                  {t('dpr.margin')}
                </label>
                <input
                  id="margin"
                  className="input"
                  type="number"
                  min="5"
                  max="90"
                  step="5"
                  value={margin}
                  onChange={(event) => setMargin(event.target.value)}
                />
              </div>
              <div className="field field--area">
                <label className="field__label" htmlFor="interest">
                  {t('dpr.interest')}
                </label>
                <input
                  id="interest"
                  className="input"
                  type="number"
                  min="1"
                  max="36"
                  step="0.5"
                  value={interest}
                  onChange={(event) => setInterest(event.target.value)}
                />
              </div>
            </div>
          ) : null}

          {error ? <p className="callout callout--error">{error}</p> : null}
        </div>

        <footer className="modal__foot">
          <button
            type="button"
            className="button button--ghost"
            onClick={onClose}
            disabled={busy}
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={submit}
            disabled={busy || languages.loading}
          >
            {busy ? t('dpr.making') : t('dpr.make')}
          </button>
        </footer>
      </div>
    </div>
  );
}

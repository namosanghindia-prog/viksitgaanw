import { useEffect, useState } from 'react';
import type { InsuranceInput, InsurancePolicy, InsuranceRequirement } from '@viksitgaanw/shared';
import { insuranceCategoriesFor, pickLabel } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { InsuranceForm } from './InsuranceForm';
import { InsuranceRow } from './InsuranceRow';

interface RequestInsuranceProps {
  requirement: InsuranceRequirement | null;
  /** Policies already saved on the plot, offered for reuse. */
  saved: InsurancePolicy[];
  value: Record<string, InsuranceInput>;
  onChange: (value: Record<string, InsuranceInput>) => void;
  error?: string | null;
}

/** Copy a plot's saved policy onto the request, without its database identity. */
function fromSaved(policy: InsurancePolicy): InsuranceInput {
  return {
    category: policy.category,
    status: 'insured',
    scheme: policy.scheme ?? null,
    insurer: policy.insurer ?? null,
    policyNumber: policy.policyNumber ?? null,
    sumInsured: policy.sumInsured ?? null,
    premium: policy.premium ?? null,
    currency: policy.currency,
    validFrom: policy.validFrom ?? null,
    validUntil: policy.validUntil ?? null,
    season: policy.season ?? null,
    seasonYear: policy.seasonYear ?? null,
    covered: policy.covered ?? null,
  };
}

/**
 * The cover a project is published with, before it is saved.
 *
 * Each required category needs an answer: a policy, or the promise to insure
 * before money is released. Recommended cover can be added or left. A policy
 * already saved on the plot -- this season's PMFBY, say -- can be reused with
 * one tap rather than typed twice.
 */
export function RequestInsurance({ requirement, saved, value, onChange, error }: RequestInsuranceProps) {
  const { t, lang } = useI18n();
  const [editing, setEditing] = useState<string | null>(null);

  const required = requirement?.required ?? [];
  const recommended = requirement?.recommended ?? [];

  // When the chosen report changes, so may the rule; drop answers that no
  // longer apply rather than publishing cover nobody asked for.
  useEffect(() => {
    if (!requirement) return;
    const relevant = new Set([...required, ...recommended]);
    const kept = Object.fromEntries(Object.entries(value).filter(([category]) => relevant.has(category)));
    if (Object.keys(kept).length !== Object.keys(value).length) onChange(kept);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requirement]);

  const set = (category: string, input: InsuranceInput | null) => {
    const next = { ...value };
    if (input) next[category] = input;
    else delete next[category];
    onChange(next);
  };

  const reusable = (category: string) =>
    saved.find((policy) => policy.category === category && policy.isCurrent) ?? null;

  const row = (category: string, isRequired: boolean) => {
    const entry = value[category] ?? null;
    const savedPolicy = reusable(category);
    return (
      <InsuranceRow
        key={category}
        category={category}
        policy={entry}
        tag={isRequired ? t('insurance.required') : t('insurance.recommended')}
        showWhy
      >
        <button
          type="button"
          className={`button button--small ${entry?.status === 'insured' ? 'button--primary' : ''}`}
          onClick={() => setEditing(category)}
        >
          {entry?.status === 'insured' ? t('common.edit') : t('insurance.haveIt')}
        </button>
        {savedPolicy && entry?.status !== 'insured' ? (
          <button type="button" className="button button--small" onClick={() => set(category, fromSaved(savedPolicy))}>
            {t('insurance.useSaved')}
          </button>
        ) : null}
        {isRequired ? (
          <button
            type="button"
            className={`button button--small ${entry?.status === 'planned' ? 'button--primary' : 'button--ghost'}`}
            aria-pressed={entry?.status === 'planned'}
            onClick={() => set(category, { category, status: 'planned' })}
          >
            {entry?.status === 'planned' ? '✓ ' : ''}
            {t('insurance.willInsure')}
          </button>
        ) : entry ? (
          <button type="button" className="button button--ghost button--small" onClick={() => set(category, null)}>
            {t('common.delete')}
          </button>
        ) : null}
      </InsuranceRow>
    );
  };

  return (
    <section className="card">
      <h3 className="card__title">{t('insurance.requestTitle')}</h3>
      <p className="card__help">{t('insurance.requestLede')}</p>
      {requirement?.reason ? <p className="callout callout--info">{pickLabel(requirement.reason, lang)}</p> : null}

      <ul className="covers__list">
        {required.map((category) => row(category, true))}
        {recommended.map((category) => row(category, false))}
      </ul>
      {error ? <p className="field__error">{error}</p> : null}

      {editing ? (
        <InsuranceForm
          categories={insuranceCategoriesFor('request').filter((item) => item.code === editing)}
          initial={value[editing]?.status === 'insured' ? value[editing] : { category: editing }}
          onSubmit={(input) => {
            set(editing, input);
            setEditing(null);
          }}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </section>
  );
}

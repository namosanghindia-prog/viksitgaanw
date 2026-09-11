import { useState } from 'react';
import type { InsuranceInput, InsurancePolicy, InsuranceScope } from '@viksitgaanw/shared';
import { insuranceCategoriesFor } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { InsuranceForm } from './InsuranceForm';
import { InsuranceRow } from './InsuranceRow';

type Target = { parcelId: string } | { requestId: string } | { onProfile: true };

interface InsuranceManagerProps {
  target: Target;
  scope: InsuranceScope;
  policies: InsurancePolicy[];
  /** A project's rule: these categories are listed even while empty. */
  required?: string[];
  recommended?: string[];
  currencyChoice?: boolean;
  onChanged: () => void;
}

/**
 * The saved policies on one plot, one profile or one request, with add, edit
 * and remove.
 *
 * On a request, each required category is always shown -- as a policy, as the
 * farmer's promise with a button to turn it into a policy, or as missing --
 * so nothing an investor will ask about is out of sight.
 */
export function InsuranceManager({
  target,
  scope,
  policies,
  required = [],
  recommended = [],
  currencyChoice = false,
  onChanged,
}: InsuranceManagerProps) {
  const { t } = useI18n();
  const [editing, setEditing] = useState<{ policy: InsurancePolicy | null; category?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const categories = insuranceCategoriesFor(scope);

  const save = async (input: InsuranceInput) => {
    if (editing?.policy) await api.updateInsurance(editing.policy.id, input);
    else await api.addInsurance({ ...input, ...target });
    setEditing(null);
    onChanged();
  };

  const remove = async (policy: InsurancePolicy) => {
    if (!window.confirm(t('insurance.confirmRemove'))) return;
    setError(null);
    try {
      await api.deleteInsurance(policy.id);
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const ruled = [...required, ...recommended.filter((code) => !required.includes(code))];
  const unruled = policies.filter((policy) => !ruled.includes(policy.category));

  const actions = (policy: InsurancePolicy) => (
    <>
      <button
        type="button"
        className={`button button--small ${policy.status === 'planned' ? 'button--primary' : 'button--ghost'}`}
        onClick={() => setEditing({ policy })}
      >
        {policy.status === 'planned' ? t('insurance.addPolicy') : t('common.edit')}
      </button>
      <button type="button" className="button button--ghost button--small" onClick={() => remove(policy)}>
        {t('common.delete')}
      </button>
    </>
  );

  return (
    <div className="covers">
      {policies.length === 0 && ruled.length === 0 ? <p className="muted small">{t('insurance.none')}</p> : null}

      <ul className="covers__list">
        {ruled.map((category) => {
          const held = policies.filter((policy) => policy.category === category);
          const tag = required.includes(category) ? t('insurance.required') : t('insurance.recommended');
          if (held.length === 0) {
            return (
              <InsuranceRow key={category} category={category} policy={null} tag={tag}>
                <button
                  type="button"
                  className="button button--small button--primary"
                  onClick={() => setEditing({ policy: null, category })}
                >
                  {t('insurance.addPolicy')}
                </button>
              </InsuranceRow>
            );
          }
          return held.map((policy) => (
            <InsuranceRow key={policy.id} category={category} policy={policy} tag={tag}>
              {actions(policy)}
            </InsuranceRow>
          ));
        })}
        {unruled.map((policy) => (
          <InsuranceRow key={policy.id} category={policy.category} policy={policy}>
            {actions(policy)}
          </InsuranceRow>
        ))}
      </ul>

      {error ? <p className="callout callout--error">{error}</p> : null}

      <button type="button" className="button button--ghost button--small" onClick={() => setEditing({ policy: null })}>
        + {t('insurance.add')}
      </button>

      {editing ? (
        <InsuranceForm
          categories={
            editing.policy || editing.category
              ? categories.filter((item) => item.code === (editing.policy?.category ?? editing.category))
              : categories
          }
          initial={editing.policy ?? (editing.category ? { category: editing.category } : null)}
          currencyChoice={currencyChoice}
          onSubmit={save}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </div>
  );
}

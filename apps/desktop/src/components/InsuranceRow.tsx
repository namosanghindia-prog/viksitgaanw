import type { ReactNode } from 'react';
import type { InsuranceInput, InsurancePolicy } from '@viksitgaanw/shared';
import { findItem, pickLabel } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { formatDate, formatMoneyShort, formatNumber } from '../lib/format';

type Policy = InsuranceInput & Partial<Pick<InsurancePolicy, 'isCurrent' | 'expired'>>;

/** Insured, promised, expired or missing -- in words and colour, never colour alone. */
export function InsuranceBadge({ policy }: { policy: Policy | null }) {
  const { t } = useI18n();
  if (!policy) return <span className="badge badge--status-declined">✕ {t('insurance.statusMissing')}</span>;
  if (policy.status === 'planned') return <span className="badge badge--status-sent">⏳ {t('insurance.statusPlanned')}</span>;
  if (policy.expired) return <span className="badge badge--status-declined">⚠ {t('insurance.statusExpired')}</span>;
  return <span className="badge badge--status-accepted">✓ {t('insurance.statusInsured')}</span>;
}

/** One policy as a readable line: what, with whom, for how much, until when. */
export function InsuranceRow({
  category,
  policy,
  tag,
  showWhy = false,
  children,
}: {
  category: string;
  policy: Policy | null;
  /** "Required" or "Recommended", when the row is part of a project's rule. */
  tag?: string;
  /** Explain what this cover protects, for someone deciding whether to take it. */
  showWhy?: boolean;
  children?: ReactNode;
}) {
  const { t, lang, rt } = useI18n();
  const money = (amount: number, currency = 'INR') =>
    currency === 'INR' ? `₹${formatMoneyShort(amount, lang, t)}` : `${currency} ${formatNumber(amount, lang, 0)}`;

  const facts = policy && policy.status === 'insured'
    ? [
        rt(findItem('insurance_schemes', policy.scheme)) || null,
        policy.insurer,
        policy.policyNumber ? `№ ${policy.policyNumber}` : null,
        policy.sumInsured ? `${t('insurance.sumInsured')} ${money(policy.sumInsured, policy.currency)}` : null,
        policy.season ? `${t(`season.${policy.season}`)} ${policy.seasonYear ?? ''}`.trim() : null,
        policy.validUntil ? t('insurance.until', { date: formatDate(policy.validUntil, lang) }) : null,
      ].filter(Boolean)
    : [];

  return (
    <li className="cover">
      <div className="cover__head">
        <strong>{rt(findItem('insurance_types', category))}</strong>
        {tag ? <span className="muted small"> · {tag}</span> : null}
        <InsuranceBadge policy={policy} />
      </div>
      {showWhy ? (
        <p className="cover__why">{pickLabel(findItem('insurance_types', category)?.note, lang)}</p>
      ) : null}
      {facts.length ? <p className="cover__facts">{facts.join(' · ')}</p> : null}
      {policy?.covered ? <p className="cover__facts muted">{policy.covered}</p> : null}
      {children ? <div className="cover__actions">{children}</div> : null}
    </li>
  );
}

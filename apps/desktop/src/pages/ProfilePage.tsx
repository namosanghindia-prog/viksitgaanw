import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { InsuranceScope, Profile } from '@viksitgaanw/shared';
import { findItem } from '@viksitgaanw/shared';

import { InsuranceManager } from '../components/InsuranceManager';
import { ProfileForm } from '../components/ProfileForm';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatLocationPath, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';
import { useProfile } from '../lib/profile';
import { SEGMENT_ICON, isInvestor, isPartner, ticketCurrency } from '../lib/segments';
import type { ReferenceKey } from '@viksitgaanw/shared';

/** The owner's own profile: what it says, how verified it is, and editing it. */
export function ProfilePage() {
  const { t, rt } = useI18n();
  const { profile, reload } = useProfile();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const states = useAsync((signal) => api.states(signal), []);
  // Personal cover for a farmer, trade cover for a partner; investors and
  // government offices do not record insurance.
  const insuranceScope: InsuranceScope | null = !profile
    ? null
    : profile.segment === 'farmer'
      ? 'farmer'
      : isPartner(profile.segment)
        ? 'partner'
        : null;
  const policies = useAsync((signal) => api.listInsurance(null, signal), [profile?.id], {
    enabled: insuranceScope !== null,
  });

  if (!profile) return null;

  const stateNames = (codes: unknown) =>
    ((codes as string[] | undefined) ?? [])
      .map((code) => states.data?.find((unit) => unit.code === code)?.name ?? code)
      .join(', ');

  const remove = async () => {
    if (!window.confirm(t('profile.confirmDelete'))) return;
    setDeleting(true);
    try {
      await api.deleteProfile();
      reload();
      navigate('/');
    } finally {
      setDeleting(false);
    }
  };

  const segmentLabel = rt(findItem('user_segments', profile.segment));

  if (editing) {
    return (
      <div className="page">
        <header className="page__header">
          <h2 className="page__title">{t('profile.edit')}</h2>
        </header>
        <ProfileForm
          segment={profile.segment}
          initial={profile}
          submitLabel={t('profile.saveChanges')}
          onCancel={() => setEditing(false)}
          onSaved={() => {
            reload();
            setEditing(false);
          }}
        />
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">
            <span aria-hidden="true">{SEGMENT_ICON[profile.segment]} </span>
            {profile.organisationName || profile.displayName}
          </h2>
          <p className="page__subtitle">
            {segmentLabel}
            {profile.organisationName ? ` · ${profile.displayName}` : ''}
          </p>
        </div>
        <button type="button" className="button button--primary" onClick={() => setEditing(true)}>
          {t('profile.edit')}
        </button>
      </header>

      <section className="card">
        <dl className="summary">
          {profileRows(profile, t, rt, stateNames).map(([term, value]) => (
            <div key={term} className="summary__row">
              <dt>{term}</dt>
              <dd>{value || '—'}</dd>
            </div>
          ))}
        </dl>
        <p className="muted small">{t('profile.syncNote')}</p>
      </section>

      {insuranceScope ? (
        <section className="card">
          <h3 className="card__title">{t('insurance.title')}</h3>
          <p className="card__help">
            {insuranceScope === 'farmer' ? t('insurance.profileFarmer') : t('insurance.profilePartner')}
          </p>
          <InsuranceManager
            target={{ onProfile: true }}
            scope={insuranceScope}
            policies={policies.data ?? []}
            currencyChoice={insuranceScope === 'partner'}
            onChanged={policies.reload}
          />
        </section>
      ) : null}

      <section className="card">
        <h3 className="card__title">{t('profile.kycTitle')}</h3>
        <p>
          <span className={`badge ${profile.kycStatus === 'verified' ? '' : 'badge--muted'}`}>
            {t(`kyc.${profile.kycStatus}`)}
          </span>
        </p>
        {profile.kycStatus !== 'verified' ? (
          <p className="card__help">
            {t('profile.kycSoon', {
              methods: profile.kycMethods.map((method) => kycLabel(method, t)).join(' / '),
            })}
          </p>
        ) : null}
      </section>

      <div className="actions">
        <span />
        <button type="button" className="button button--danger" onClick={remove} disabled={deleting}>
          {t('profile.delete')}
        </button>
      </div>
    </div>
  );
}

type Translate = ReturnType<typeof useI18n>['t'];
type LabelReference = ReturnType<typeof useI18n>['rt'];

function kycLabel(method: string, t: Translate): string {
  const key = `kyc.${method}` as Parameters<Translate>[0];
  return t(key);
}

/** The profile as label/value rows, in the order a reader would want them. */
function profileRows(
  profile: Profile,
  t: Translate,
  rt: LabelReference,
  stateNames: (codes: unknown) => string,
): Array<[string, string]> {
  const details = profile.details as Record<string, unknown>;
  const one = (key: ReferenceKey, code: unknown) => rt(findItem(key, typeof code === 'string' ? code : null));
  const many = (key: ReferenceKey, codes: unknown) =>
    ((codes as string[] | undefined) ?? []).map((code) => rt(findItem(key, code))).join(', ');
  const place =
    profile.countryCode !== 'IN'
      ? [profile.city, rt(findItem('countries', profile.countryCode))].filter(Boolean).join(', ')
      : formatLocationPath(profile.location);

  const rows: Array<[string, string]> = [
    [t('profile.type'), rt(findItem('user_segments', profile.segment))],
    [t('profile.sectionPlace'), place],
    [t('profile.phone'), profile.phone ?? ''],
    [t('profile.email'), profile.email ?? ''],
  ];

  if (profile.segment === 'farmer') {
    rows.push(
      [t('profile.needs'), many('farmer_needs', details.needs)],
      [t('profile.yearsFarming'), details.yearsFarming != null ? String(details.yearsFarming) : ''],
      [t('profile.hasKcc'), details.hasKcc ? '✓' : '—'],
      [t('profile.pmKisan'), details.pmKisan ? '✓' : '—'],
      [t('profile.fpoName'), details.fpoMember ? String(details.fpoName ?? '✓') : '—'],
    );
  } else if (isInvestor(profile.segment)) {
    const currency = ticketCurrency(profile.segment);
    const amount = (value: unknown) =>
      typeof value === 'number' ? `${currency === 'USD' ? '$' : '₹'}${formatNumber(value, 'en', 0)}` : '';
    const ticket = [amount(details.ticketMin), amount(details.ticketMax)].filter(Boolean).join(' – ');
    rows.push(
      [t('profile.investorType'), one('investor_types', details.investorType)],
      [t('profile.modes'), many('investment_modes', details.modes)],
      [t('profile.sectors'), many('opportunity_kinds', details.sectors)],
      [t('profile.preferredStates'), stateNames(details.preferredStates)],
      [t('profile.ticket', { currency: t(`currency.${currency}`) }), ticket],
      [t('profile.risk'), one('risk_appetites', details.riskAppetite)],
      [t('profile.horizon'), details.horizonYears != null ? String(details.horizonYears) : ''],
    );
    if (profile.segment === 'investor_india') rows.push([t('profile.pan'), String(details.pan ?? '')]);
  } else if (isPartner(profile.segment)) {
    rows.push(
      [t('profile.orgType'), one('organisation_types', details.organisationType)],
      [t('profile.partnershipTypes'), many('partnership_types', details.partnershipTypes)],
      [t('profile.crops'), many('crops', details.crops)],
      [t('profile.operatingStates'), stateNames(details.operatingStates)],
      [t('profile.registration'), String(details.registrationNumber ?? '')],
    );
    if (profile.segment === 'partner_national') {
      rows.push(
        [t('profile.gstin'), String(details.gstin ?? '')],
        [t('profile.memberFarmers'), details.memberFarmers != null ? String(details.memberFarmers) : ''],
      );
    } else {
      rows.push([t('profile.certifications'), many('certifications', details.certificationsRequired)]);
    }
  } else if (profile.segment === 'government') {
    rows.push(
      [t('profile.govLevel'), one('government_levels', details.level)],
      [t('profile.department'), String(details.department ?? '')],
      [t('profile.designation'), String(details.designation ?? '')],
    );
  }

  if (profile.about) rows.push([t('profile.about'), profile.about]);
  return rows;
}

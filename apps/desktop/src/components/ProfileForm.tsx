import { useMemo, useState } from 'react';
import type { AdminLevel, LocationSelection, Profile, ProfileInput, Segment } from '@viksitgaanw/shared';
import { REFERENCE, findItem, itemsForSegment } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { isInternational, isInvestor, isPartner, ticketCurrency } from '../lib/segments';
import { ChoiceGroup } from './ChoiceGroup';
import { LocationCascader } from './LocationCascader';
import { Picker } from './Picker';
import { StateChips } from './StateChips';
import { CheckField, TextField } from './TextField';

type Details = Record<string, unknown>;

interface FormState {
  displayName: string;
  organisationName: string;
  phone: string;
  email: string;
  countryCode: string;
  city: string;
  about: string;
  location: LocationSelection;
  details: Details;
}

interface ProfileFormProps {
  segment: Segment;
  /** The saved profile, when editing. */
  initial?: Profile | null;
  submitLabel: string;
  onSaved: (profile: Profile) => void;
  onCancel?: () => void;
  cancelLabel?: string;
}

const EMPTY_LOCATION: LocationSelection = {
  stateCode: null,
  districtCode: null,
  subdistrictCode: null,
  villageCode: null,
};

/** Investor types for which an organisation name makes no sense. */
const PERSONAL_INVESTOR_TYPES = ['individual', 'angel', 'nri'];

/** Detail fields typed as numbers; the form holds them as text while editing. */
const NUMERIC_DETAILS = new Set(['yearsFarming', 'ticketMin', 'ticketMax', 'horizonYears', 'memberFarmers']);

function defaultDetails(segment: Segment): Details {
  if (segment === 'farmer') {
    return { yearsFarming: '', needs: [], fpoMember: false, fpoName: '', hasKcc: false, pmKisan: false };
  }
  if (isInvestor(segment)) {
    return {
      investorType: null,
      sectors: [],
      modes: [],
      ticketMin: '',
      ticketMax: '',
      preferredStates: [],
      horizonYears: '',
      riskAppetite: null,
      pan: '',
      complianceAcknowledged: false,
    };
  }
  if (isPartner(segment)) {
    return {
      organisationType: null,
      registrationNumber: '',
      partnershipTypes: [],
      crops: [],
      operatingStates: [],
      gstin: '',
      memberFarmers: '',
      certificationsRequired: [],
    };
  }
  return { level: null, department: '', designation: '', employeeId: '' };
}

function initialState(segment: Segment, profile?: Profile | null): FormState {
  const details = defaultDetails(segment);
  for (const [key, value] of Object.entries(profile?.details ?? {})) {
    if (value === null || value === undefined) continue;
    details[key] = typeof value === 'number' ? String(value) : value;
  }
  return {
    displayName: profile?.displayName ?? '',
    organisationName: profile?.organisationName ?? '',
    phone: profile?.phone ?? '',
    email: profile?.email ?? '',
    countryCode: profile && profile.countryCode !== 'IN' ? profile.countryCode : '',
    city: profile?.city ?? '',
    about: profile?.about ?? '',
    location: profile
      ? {
          stateCode: profile.stateCode ?? null,
          districtCode: profile.districtCode ?? null,
          subdistrictCode: profile.subdistrictCode ?? null,
          villageCode: profile.villageCode ?? null,
        }
      : EMPTY_LOCATION,
    details,
  };
}

function cleanDetails(details: Details): Details {
  const out: Details = {};
  for (const [key, value] of Object.entries(details)) {
    if (NUMERIC_DETAILS.has(key)) {
      const text = String(value ?? '').trim();
      out[key] = text ? Number(text) : null;
    } else if (typeof value === 'string') {
      out[key] = value.trim() || null;
    } else {
      out[key] = value;
    }
  }
  return out;
}

/**
 * Which part of the LGD hierarchy a segment gives, and which of it is required.
 * Null means no Indian location at all (international profiles, central offices).
 */
function locationRule(
  segment: Segment,
  level: string | null,
): { depth: AdminLevel; required: AdminLevel[] } | null {
  switch (segment) {
    case 'farmer':
      return { depth: 'village', required: ['state', 'district'] };
    case 'investor_india':
      return { depth: 'district', required: [] };
    case 'partner_national':
      return { depth: 'district', required: ['state'] };
    case 'government': {
      const jurisdiction = findItem('government_levels', level)?.jurisdiction;
      if (jurisdiction === 'subdistrict') {
        return {
          depth: level === 'gram_panchayat' ? 'village' : 'subdistrict',
          required: ['state', 'district', 'subdistrict'],
        };
      }
      if (jurisdiction === 'district') return { depth: 'district', required: ['state', 'district'] };
      if (jurisdiction === 'state') return { depth: 'state', required: ['state'] };
      return null;
    }
    default:
      return null;
  }
}

/**
 * One form for all six kinds of profile.
 *
 * The common fields are the same for everyone; the section in the middle
 * changes with the segment. Only what a bank, an investor or a scheme officer
 * genuinely needs is required -- everything else can be filled in later.
 */
export function ProfileForm({
  segment,
  initial,
  submitLabel,
  onSaved,
  onCancel,
  cancelLabel,
}: ProfileFormProps) {
  const { t, lang, rt } = useI18n();
  const [form, setForm] = useState<FormState>(() => initialState(segment, initial));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const international = isInternational(segment);
  const investor = isInvestor(segment);
  const partner = isPartner(segment);
  const government = segment === 'government';
  const details = form.details;
  const level = (details.level as string | null) ?? null;
  const rule = locationRule(segment, level);

  // A red note disappears as soon as its field is touched, rather than
  // lingering beside an answer that is now correct.
  const clearErrors = (keys: string[]) =>
    setErrors((current) => {
      if (!keys.some((key) => key in current)) return current;
      const next = { ...current };
      for (const key of keys) delete next[key];
      return next;
    });
  const patch = (changes: Partial<FormState>) => {
    setForm((current) => ({ ...current, ...changes }));
    clearErrors(changes.location ? Object.keys(changes.location) : Object.keys(changes));
  };
  const setDetail = (key: string, value: unknown) => {
    setForm((current) => ({ ...current, details: { ...current.details, [key]: value } }));
    clearErrors([key]);
  };
  const text = (key: string) => String(details[key] ?? '');
  const list = (key: string) => (details[key] as string[] | undefined) ?? [];

  const countryOptions = useMemo(
    () =>
      REFERENCE.countries.items
        .filter((item) => item.code !== 'IN')
        .map((item) => ({
          value: item.code,
          label: rt(item),
          sublabel: lang === 'en' ? null : item.label.en,
        })),
    [rt, lang],
  );

  const investorType = (details.investorType as string | null) ?? null;
  const organisationRequired =
    partner ||
    government ||
    (investor && investorType !== null && !PERSONAL_INVESTOR_TYPES.includes(investorType));
  const phoneRequired = segment === 'farmer' || segment === 'investor_india' || segment === 'partner_national';
  const emailRequired = international || government;

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    const required = t('error.required');
    const chooseOne = t('error.chooseOne');

    if (!form.displayName.trim()) next.displayName = required;
    if (phoneRequired && !form.phone.trim()) next.phone = required;
    if (emailRequired && !form.email.trim()) next.email = required;
    if (organisationRequired && !form.organisationName.trim()) next.organisationName = required;
    if (international && !form.countryCode) next.countryCode = required;
    for (const needed of rule?.required ?? []) {
      const key = `${needed}Code` as keyof LocationSelection;
      if (!form.location[key]) next[key] = required;
    }

    if (investor) {
      if (!investorType) next.investorType = chooseOne;
      if (!list('modes').length) next.modes = chooseOne;
      const low = Number.parseFloat(text('ticketMin'));
      const high = Number.parseFloat(text('ticketMax'));
      if (Number.isFinite(low) && Number.isFinite(high) && low > high) {
        next.ticketMax = t('profile.ticketOrder');
      }
      if (international && !details.complianceAcknowledged) {
        next.complianceAcknowledged = t('profile.fdiAckRequired');
      }
    }
    if (partner) {
      if (!details.organisationType) next.organisationType = chooseOne;
      if (!list('partnershipTypes').length) next.partnershipTypes = chooseOne;
    }
    if (government) {
      if (!level) next.level = chooseOne;
      if (!text('department').trim()) next.department = required;
      if (!text('designation').trim()) next.designation = required;
    }

    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const save = async () => {
    if (!validate()) return;
    setSaving(true);
    setSaveError(null);

    const location = rule ? form.location : EMPTY_LOCATION;
    const payload: ProfileInput = {
      segment,
      displayName: form.displayName.trim(),
      organisationName: form.organisationName.trim() || null,
      phone: form.phone.trim() || null,
      email: form.email.trim() || null,
      preferredLanguage: initial?.preferredLanguage ?? lang,
      stateCode: location.stateCode,
      districtCode: location.districtCode,
      subdistrictCode: location.subdistrictCode,
      villageCode: location.villageCode,
      countryCode: international ? form.countryCode : 'IN',
      city: form.city.trim() || null,
      about: form.about.trim() || null,
      details: cleanDetails(details),
    };

    try {
      const saved = initial ? await api.replaceProfile(payload) : await api.createProfile(payload);
      onSaved(saved);
    } catch (error) {
      setSaveError(t('error.saveFailed', { detail: error instanceof Error ? error.message : String(error) }));
      setSaving(false);
    }
  };

  const nameLabel = partner || government || organisationRequired ? t('profile.contactName') : t('profile.displayName');
  const errorBelow = (key: string) => (errors[key] ? <p className="field__error">{errors[key]}</p> : null);

  return (
    <>
      {/* ---------------------------------------------------------------- */}
      {/* Who                                                               */}
      {/* ---------------------------------------------------------------- */}
      <section className="card">
        <h3 className="card__title">
          {government ? t('profile.sectionOffice') : partner ? t('profile.sectionOrg') : t('profile.sectionAbout')}
        </h3>

        {investor ? (
          <>
            <ChoiceGroup
              label={t('profile.investorType')}
              items={itemsForSegment('investor_types', segment)}
              value={investorType}
              onChange={(value) => setDetail('investorType', value)}
            />
            {errorBelow('investorType')}
          </>
        ) : null}

        {partner ? (
          <>
            <ChoiceGroup
              label={t('profile.orgType')}
              items={itemsForSegment('organisation_types', segment)}
              value={(details.organisationType as string | null) ?? null}
              onChange={(value) => setDetail('organisationType', value)}
            />
            {errorBelow('organisationType')}
          </>
        ) : null}

        {government ? (
          <>
            <ChoiceGroup
              label={t('profile.govLevel')}
              items={REFERENCE.government_levels.items}
              value={level}
              onChange={(value) => setDetail('level', value)}
            />
            {errorBelow('level')}
          </>
        ) : null}

        {organisationRequired || (investor && investorType === null) ? (
          <TextField
            id="organisationName"
            label={government ? t('profile.officeName') : t('profile.organisationName')}
            hint={government ? t('profile.officeHint') : undefined}
            value={form.organisationName}
            onChange={(organisationName) => patch({ organisationName })}
            required={organisationRequired}
            optional={!organisationRequired}
            error={errors.organisationName}
            maxLength={200}
          />
        ) : null}

        <TextField
          id="displayName"
          label={nameLabel}
          value={form.displayName}
          onChange={(displayName) => patch({ displayName })}
          required
          error={errors.displayName}
          maxLength={160}
        />

        {government ? (
          <div className="field-row">
            <TextField
              id="department"
              label={t('profile.department')}
              value={text('department')}
              onChange={(value) => setDetail('department', value)}
              required
              error={errors.department}
              maxLength={200}
            />
            <TextField
              id="designation"
              label={t('profile.designation')}
              value={text('designation')}
              onChange={(value) => setDetail('designation', value)}
              required
              error={errors.designation}
              maxLength={160}
            />
          </div>
        ) : null}

        {government ? (
          <TextField
            id="employeeId"
            label={t('profile.employeeId')}
            value={text('employeeId')}
            onChange={(value) => setDetail('employeeId', value)}
            optional
            maxLength={64}
          />
        ) : null}

        {partner ? (
          <div className="field-row">
            <TextField
              id="registrationNumber"
              label={t('profile.registration')}
              hint={international ? t('profile.registrationHintIntl') : t('profile.registrationHint')}
              value={text('registrationNumber')}
              onChange={(value) => setDetail('registrationNumber', value)}
              optional
              maxLength={64}
            />
            {!international ? (
              <TextField
                id="gstin"
                label={t('profile.gstin')}
                value={text('gstin')}
                onChange={(value) => setDetail('gstin', value.toUpperCase())}
                optional
                maxLength={15}
              />
            ) : null}
          </div>
        ) : null}

        {segment === 'investor_india' ? (
          <TextField
            id="pan"
            label={t('profile.pan')}
            hint={t('profile.panHint')}
            value={text('pan')}
            onChange={(value) => setDetail('pan', value.toUpperCase())}
            optional
            maxLength={10}
          />
        ) : null}

        <TextField
          id="about"
          label={t('profile.about')}
          hint={t('profile.aboutHint')}
          value={form.about}
          onChange={(about) => patch({ about })}
          optional
          multiline
          maxLength={2000}
        />
      </section>

      {/* ---------------------------------------------------------------- */}
      {/* Where                                                             */}
      {/* ---------------------------------------------------------------- */}
      {international ? (
        <section className="card">
          <h3 className="card__title">{t('profile.sectionPlace')}</h3>
          <div className="field-row">
            <Picker
              label={t('profile.country')}
              placeholder={t('profile.chooseCountry')}
              options={countryOptions}
              value={form.countryCode || null}
              onChange={(countryCode) => patch({ countryCode: countryCode ?? '' })}
              required
              error={errors.countryCode}
            />
            <TextField
              id="city"
              label={t('profile.city')}
              value={form.city}
              onChange={(city) => patch({ city })}
              optional
              maxLength={120}
            />
          </div>
        </section>
      ) : rule ? (
        <section className="card">
          <h3 className="card__title">
            {government
              ? t('profile.sectionJurisdiction')
              : segment === 'partner_national'
                ? t('profile.hqState')
                : t('profile.sectionPlace')}
          </h3>
          <LocationCascader
            value={form.location}
            onChange={(location) => patch({ location })}
            errors={errors}
            depth={rule.depth}
            requiredLevels={rule.required}
          />
        </section>
      ) : null}

      {/* ---------------------------------------------------------------- */}
      {/* What they do                                                      */}
      {/* ---------------------------------------------------------------- */}
      {segment === 'farmer' ? (
        <section className="card">
          <h3 className="card__title">{t('profile.sectionFarming')}</h3>
          <ChoiceGroup
            label={t('profile.needs')}
            items={REFERENCE.farmer_needs.items}
            multiple
            value={list('needs')}
            onChange={(value) => setDetail('needs', value)}
          />
          <div className="narrow">
            <TextField
              id="yearsFarming"
              label={t('profile.yearsFarming')}
              type="number"
              inputMode="numeric"
              min={0}
              value={text('yearsFarming')}
              onChange={(value) => setDetail('yearsFarming', value)}
              optional
            />
          </div>
          <CheckField
            label={t('profile.hasKcc')}
            checked={Boolean(details.hasKcc)}
            onChange={(value) => setDetail('hasKcc', value)}
          />
          <CheckField
            label={t('profile.pmKisan')}
            checked={Boolean(details.pmKisan)}
            onChange={(value) => setDetail('pmKisan', value)}
          />
          <CheckField
            label={t('profile.fpoMember')}
            checked={Boolean(details.fpoMember)}
            onChange={(value) => setDetail('fpoMember', value)}
          />
          {details.fpoMember ? (
            <TextField
              id="fpoName"
              label={t('profile.fpoName')}
              value={text('fpoName')}
              onChange={(value) => setDetail('fpoName', value)}
              optional
              maxLength={200}
            />
          ) : null}
        </section>
      ) : null}

      {investor ? (
        <section className="card">
          <h3 className="card__title">{t('profile.sectionInvest')}</h3>

          {segment === 'investor_india' ? (
            <p className="callout callout--info">{t('profile.landNote')}</p>
          ) : null}

          <ChoiceGroup
            label={t('profile.modes')}
            items={REFERENCE.investment_modes.items}
            multiple
            value={list('modes')}
            onChange={(value) => setDetail('modes', value)}
          />
          {errorBelow('modes')}

          <ChoiceGroup
            label={t('profile.sectors')}
            hint={t('profile.sectorsHint')}
            items={REFERENCE.opportunity_kinds.items}
            multiple
            value={list('sectors')}
            onChange={(value) => setDetail('sectors', value)}
          />

          <fieldset className="field">
            <legend className="field__label">
              {t('profile.ticket', { currency: t(`currency.${ticketCurrency(segment)}`) })}{' '}
              <span className="field__optional">({t('common.optional')})</span>
            </legend>
            <div className="field-row">
              <TextField
                id="ticketMin"
                label={t('profile.ticketMin')}
                type="number"
                inputMode="numeric"
                min={0}
                value={text('ticketMin')}
                onChange={(value) => setDetail('ticketMin', value)}
              />
              <TextField
                id="ticketMax"
                label={t('profile.ticketMax')}
                type="number"
                inputMode="numeric"
                min={0}
                value={text('ticketMax')}
                onChange={(value) => setDetail('ticketMax', value)}
                error={errors.ticketMax}
              />
            </div>
          </fieldset>

          <StateChips
            label={t('profile.preferredStates')}
            hint={t('profile.statesHint')}
            value={list('preferredStates')}
            onChange={(value) => setDetail('preferredStates', value)}
          />

          <ChoiceGroup
            label={t('profile.risk')}
            items={REFERENCE.risk_appetites.items}
            value={(details.riskAppetite as string | null) ?? null}
            onChange={(value) => setDetail('riskAppetite', value)}
          />

          <div className="narrow">
            <TextField
              id="horizonYears"
              label={t('profile.horizon')}
              type="number"
              inputMode="numeric"
              min={1}
              value={text('horizonYears')}
              onChange={(value) => setDetail('horizonYears', value)}
              optional
            />
          </div>

          {international ? (
            <div className="notice">
              <h4 className="notice__title">{t('profile.fdiTitle')}</h4>
              <p className="notice__text">{t('profile.fdiText')}</p>
              <CheckField
                label={t('profile.fdiAck')}
                checked={Boolean(details.complianceAcknowledged)}
                onChange={(value) => setDetail('complianceAcknowledged', value)}
                error={errors.complianceAcknowledged}
              />
            </div>
          ) : null}
        </section>
      ) : null}

      {partner ? (
        <section className="card">
          <h3 className="card__title">{t('profile.sectionPartner')}</h3>
          <ChoiceGroup
            label={t('profile.partnershipTypes')}
            items={REFERENCE.partnership_types.items}
            multiple
            value={list('partnershipTypes')}
            onChange={(value) => setDetail('partnershipTypes', value)}
          />
          {errorBelow('partnershipTypes')}

          {!international &&
          ['fpo', 'cooperative', 'shg'].includes(String(details.organisationType ?? '')) ? (
            <div className="narrow">
              <TextField
                id="memberFarmers"
                label={t('profile.memberFarmers')}
                type="number"
                inputMode="numeric"
                min={1}
                value={text('memberFarmers')}
                onChange={(value) => setDetail('memberFarmers', value)}
                optional
              />
            </div>
          ) : null}

          <ChoiceGroup
            label={t('profile.crops')}
            items={REFERENCE.crops.items}
            categories={REFERENCE.crops.categories}
            multiple
            value={list('crops')}
            onChange={(value) => setDetail('crops', value)}
          />

          <StateChips
            label={t('profile.operatingStates')}
            hint={t('profile.statesHint')}
            value={list('operatingStates')}
            onChange={(value) => setDetail('operatingStates', value)}
          />

          {international ? (
            <ChoiceGroup
              label={t('profile.certifications')}
              items={REFERENCE.certifications.items}
              multiple
              value={list('certificationsRequired')}
              onChange={(value) => setDetail('certificationsRequired', value)}
            />
          ) : null}
        </section>
      ) : null}

      {/* ---------------------------------------------------------------- */}
      {/* Contact                                                           */}
      {/* ---------------------------------------------------------------- */}
      <section className="card">
        <h3 className="card__title">{t('profile.sectionContact')}</h3>
        <p className="card__help">{t('profile.contactPrivate')}</p>
        <div className="field-row">
          <TextField
            id="phone"
            label={international ? t('profile.phoneIntl') : t('profile.phone')}
            type="tel"
            inputMode="tel"
            value={form.phone}
            onChange={(phone) => patch({ phone })}
            required={phoneRequired}
            optional={!phoneRequired}
            error={errors.phone}
            maxLength={20}
            placeholder={international ? '+44 20 7946 0958' : '98765 43210'}
          />
          <TextField
            id="email"
            label={government ? t('profile.officialEmail') : t('profile.email')}
            hint={government ? t('profile.officialEmailHint') : undefined}
            type="email"
            inputMode="email"
            value={form.email}
            onChange={(email) => patch({ email })}
            required={emailRequired}
            optional={!emailRequired}
            error={errors.email}
            maxLength={254}
          />
        </div>
      </section>

      {saveError ? <p className="callout callout--error">{saveError}</p> : null}
      {Object.keys(errors).length > 0 ? (
        <p className="callout callout--error">{t('error.checkForm')}</p>
      ) : null}

      <div className="actions">
        {onCancel ? (
          <button type="button" className="button button--ghost" onClick={onCancel} disabled={saving}>
            {cancelLabel ?? t('common.cancel')}
          </button>
        ) : (
          <span />
        )}
        <button type="button" className="button button--primary" onClick={save} disabled={saving}>
          {saving ? t('common.saving') : submitLabel}
        </button>
      </div>
    </>
  );
}

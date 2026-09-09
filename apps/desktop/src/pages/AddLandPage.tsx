import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { LandParcelInput, LocationSelection } from '@viksitgaanw/shared';
import {
  REFERENCE,
  findItem,
  hectaresToAcres,
  toHectares,
  toMetres,
} from '@viksitgaanw/shared';

import { ChoiceGroup } from '../components/ChoiceGroup';
import { LocationCascader } from '../components/LocationCascader';
import { LocationMap, type Coordinates } from '../components/LocationMap';
import { Picker } from '../components/Picker';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatLocationPath, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';

type Step = 'location' | 'details' | 'review';
const STEPS: Step[] = ['location', 'details', 'review'];

interface FormState {
  location: LocationSelection;
  label: string;
  areaValue: string;
  areaUnit: string;
  surveyNumber: string;
  ownershipType: string | null;
  soilType: string | null;
  waterSources: string[];
  waterType: string | null;
  waterDepthValue: string;
  waterDepthUnit: string;
  irrigationType: string | null;
  existingCrops: string[];
  coordinates: Coordinates | null;
  notes: string;
}

const INITIAL: FormState = {
  location: { stateCode: null, districtCode: null, subdistrictCode: null, villageCode: null },
  label: '',
  areaValue: '',
  areaUnit: 'acre',
  surveyNumber: '',
  ownershipType: null,
  soilType: null,
  waterSources: [],
  waterType: null,
  waterDepthValue: '',
  waterDepthUnit: 'foot',
  irrigationType: null,
  existingCrops: [],
  coordinates: null,
  notes: '',
};

/**
 * Three-step land intake.
 *
 * Splitting it up keeps each screen to a handful of questions, which matters a
 * lot more than saving clicks for a user who is reading slowly.
 */
export function AddLandPage() {
  const { t, lang, rt } = useI18n();
  const navigate = useNavigate();

  const [step, setStep] = useState<Step>('location');
  const [form, setForm] = useState<FormState>(INITIAL);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const patch = (changes: Partial<FormState>) => setForm((current) => ({ ...current, ...changes }));

  const areaNumber = Number.parseFloat(form.areaValue);
  const areaValid = Number.isFinite(areaNumber) && areaNumber > 0;
  const hectares = areaValid ? toHectares(areaNumber, form.areaUnit) : null;
  const unitItem = findItem('area_units', form.areaUnit);

  const depthNumber = Number.parseFloat(form.waterDepthValue);
  const depthValid = Number.isFinite(depthNumber) && depthNumber > 0;
  const depthMetres = depthValid ? toMetres(depthNumber, form.waterDepthUnit) : null;

  const depthUnitOptions = useMemo(
    () =>
      REFERENCE.depth_units.items.map((item) => ({
        value: item.code,
        label: rt(item),
      })),
    [rt],
  );

  const areaUnitOptions = useMemo(
    () =>
      REFERENCE.area_units.items.map((item) => ({
        value: item.code,
        label: rt(item),
      })),
    [rt],
  );

  const validateLocation = (): boolean => {
    const next: Record<string, string> = {};
    if (!form.location.stateCode) next.stateCode = t('error.stateRequired');
    if (!form.location.districtCode) next.districtCode = t('error.districtRequired');
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const validateDetails = (): boolean => {
    const next: Record<string, string> = {};
    if (!form.label.trim()) next.label = t('error.required');
    if (!areaValid) next.areaValue = t('error.areaPositive');
    // Depth is optional, but something typed into it must be a real number.
    if (form.waterDepthValue.trim() && !depthValid) {
      next.waterDepthValue = t('error.areaPositive');
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const goNext = () => {
    if (step === 'location' && validateLocation()) setStep('details');
    else if (step === 'details' && validateDetails()) setStep('review');
  };

  const goBack = () => {
    setErrors({});
    if (step === 'details') setStep('location');
    else if (step === 'review') setStep('details');
  };

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    const payload: LandParcelInput = {
      label: form.label.trim(),
      stateCode: form.location.stateCode!,
      districtCode: form.location.districtCode!,
      subdistrictCode: form.location.subdistrictCode,
      villageCode: form.location.villageCode,
      surveyNumber: form.surveyNumber.trim() || null,
      ownershipType: form.ownershipType,
      areaValue: areaNumber,
      areaUnit: form.areaUnit,
      soilType: form.soilType,
      waterSources: form.waterSources,
      waterType: form.waterType,
      waterDepthValue: depthValid ? depthNumber : null,
      waterDepthUnit: depthValid ? form.waterDepthUnit : null,
      irrigationType: form.irrigationType,
      existingCrops: form.existingCrops,
      latitude: form.coordinates?.latitude ?? null,
      longitude: form.coordinates?.longitude ?? null,
      notes: form.notes.trim() || null,
    };

    try {
      const created = await api.createParcel(payload);
      navigate('/', { state: { savedParcelId: created.id } });
    } catch (error) {
      setSaveError(
        t('error.saveFailed', { detail: error instanceof Error ? error.message : String(error) }),
      );
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <ol className="stepper" aria-label={t('common.step', { n: STEPS.indexOf(step) + 1, total: STEPS.length })}>
        {STEPS.map((entry, index) => (
          <li
            key={entry}
            className={`stepper__item ${entry === step ? 'stepper__item--active' : ''} ${
              STEPS.indexOf(step) > index ? 'stepper__item--done' : ''
            }`}
          >
            <span className="stepper__number">{index + 1}</span>
            <span className="stepper__label">
              {entry === 'location'
                ? t('location.title')
                : entry === 'details'
                  ? t('land.title')
                  : t('review.title')}
            </span>
          </li>
        ))}
      </ol>

      {step === 'location' ? (
        <section className="card">
          <h2 className="card__title">{t('location.title')}</h2>
          <p className="card__help">{t('location.help')}</p>
          <LocationCascader
            value={form.location}
            onChange={(location) => patch({ location })}
            errors={errors}
          />

          <LocationMap
            value={form.coordinates}
            onChange={(coordinates) => patch({ coordinates })}
          />
        </section>
      ) : null}

      {step === 'details' ? (
        <section className="card">
          <h2 className="card__title">{t('land.title')}</h2>
          <p className="card__help">{t('land.help')}</p>

          <div className="field">
            <label className="field__label" htmlFor="label">
              {t('land.label')}
              <span className="field__required"> *</span>
            </label>
            <p className="field__hint">{t('land.labelHint')}</p>
            <input
              id="label"
              className={`input ${errors.label ? 'input--error' : ''}`}
              value={form.label}
              onChange={(event) => patch({ label: event.target.value })}
              maxLength={160}
            />
            {errors.label ? <p className="field__error">{errors.label}</p> : null}
          </div>

          <div className="field-row">
            <div className="field field--area">
              <label className="field__label" htmlFor="area">
                {t('land.area')}
                <span className="field__required"> *</span>
              </label>
              <input
                id="area"
                className={`input ${errors.areaValue ? 'input--error' : ''}`}
                type="number"
                inputMode="decimal"
                min="0"
                step="0.01"
                value={form.areaValue}
                onChange={(event) => patch({ areaValue: event.target.value })}
              />
              {errors.areaValue ? <p className="field__error">{errors.areaValue}</p> : null}
            </div>

            <Picker
              label={t('land.areaUnit')}
              placeholder={t('land.areaUnit')}
              options={areaUnitOptions}
              value={form.areaUnit}
              onChange={(unit) => patch({ areaUnit: unit ?? 'acre' })}
              required
            />
          </div>

          {hectares !== null ? (
            <p className="callout callout--info">
              {t('land.areaEquivalent', {
                hectares: formatNumber(hectares, lang, 4),
                acres: formatNumber(hectaresToAcres(hectares), lang, 3),
              })}
            </p>
          ) : null}

          {unitItem?.regional ? (
            <p className="callout callout--warn">
              {t('land.areaRegionalWarning', {
                unit: rt(unitItem),
                hectares: formatNumber(unitItem.hectares ?? 0, lang, 4),
              })}
            </p>
          ) : null}

          <div className="field">
            <label className="field__label" htmlFor="survey">
              {t('land.surveyNumber')} <span className="field__optional">({t('common.optional')})</span>
            </label>
            <input
              id="survey"
              className="input"
              value={form.surveyNumber}
              onChange={(event) => patch({ surveyNumber: event.target.value })}
              maxLength={64}
            />
          </div>

          <ChoiceGroup
            label={t('land.ownership')}
            items={REFERENCE.ownership_types.items}
            value={form.ownershipType}
            onChange={(ownershipType) => patch({ ownershipType })}
          />

          <ChoiceGroup
            label={t('land.soil')}
            items={REFERENCE.soil_types.items}
            value={form.soilType}
            onChange={(soilType) => patch({ soilType })}
          />

          <ChoiceGroup
            label={t('land.water')}
            hint={t('land.waterHint')}
            items={REFERENCE.water_sources.items}
            multiple
            value={form.waterSources}
            onChange={(waterSources) => patch({ waterSources })}
          />

          <ChoiceGroup
            label={t('land.waterType')}
            hint={t('land.waterTypeHint')}
            items={REFERENCE.water_types.items}
            value={form.waterType}
            onChange={(waterType) => patch({ waterType })}
          />

          <div className="field-row">
            <div className="field field--area">
              <label className="field__label" htmlFor="waterDepth">
                {t('land.waterDepth')}{' '}
                <span className="field__optional">({t('common.optional')})</span>
              </label>
              <p className="field__hint">{t('land.waterDepthHint')}</p>
              <input
                id="waterDepth"
                className={`input ${errors.waterDepthValue ? 'input--error' : ''}`}
                type="number"
                inputMode="decimal"
                min="0"
                step="1"
                value={form.waterDepthValue}
                onChange={(event) => patch({ waterDepthValue: event.target.value })}
              />
              {errors.waterDepthValue ? (
                <p className="field__error">{errors.waterDepthValue}</p>
              ) : null}
            </div>

            <Picker
              label={t('land.waterDepthUnit')}
              placeholder={t('land.waterDepthUnit')}
              options={depthUnitOptions}
              value={form.waterDepthUnit}
              onChange={(unit) => patch({ waterDepthUnit: unit ?? 'foot' })}
            />
          </div>

          {depthMetres !== null ? (
            <p className="callout callout--info">
              {t('land.waterDepthEquivalent', {
                metres: formatNumber(depthMetres, lang, 2),
                feet: formatNumber(depthMetres / 0.3048, lang, 0),
              })}
            </p>
          ) : null}

          <ChoiceGroup
            label={t('land.irrigation')}
            items={REFERENCE.irrigation_types.items}
            value={form.irrigationType}
            onChange={(irrigationType) => patch({ irrigationType })}
          />

          <ChoiceGroup
            label={t('land.crops')}
            hint={t('land.cropsHint')}
            items={REFERENCE.crops.items}
            categories={REFERENCE.crops.categories}
            multiple
            value={form.existingCrops}
            onChange={(existingCrops) => patch({ existingCrops })}
          />

          <div className="field">
            <label className="field__label" htmlFor="notes">
              {t('land.notes')} <span className="field__optional">({t('common.optional')})</span>
            </label>
            <textarea
              id="notes"
              className="input input--textarea"
              rows={3}
              value={form.notes}
              onChange={(event) => patch({ notes: event.target.value })}
              maxLength={4000}
            />
          </div>
        </section>
      ) : null}

      {step === 'review' ? (
        <ReviewStep form={form} hectares={hectares} />
      ) : null}

      {saveError ? <p className="callout callout--error">{saveError}</p> : null}

      <div className="actions">
        {step !== 'location' ? (
          <button type="button" className="button button--ghost" onClick={goBack} disabled={saving}>
            {t('common.back')}
          </button>
        ) : (
          <button
            type="button"
            className="button button--ghost"
            onClick={() => navigate('/')}
            disabled={saving}
          >
            {t('common.cancel')}
          </button>
        )}

        {step === 'review' ? (
          <button type="button" className="button button--primary" onClick={save} disabled={saving}>
            {saving ? t('common.saving') : t('common.save')}
          </button>
        ) : (
          <button type="button" className="button button--primary" onClick={goNext}>
            {t('common.next')}
          </button>
        )}
      </div>
    </div>
  );
}

function ReviewStep({ form, hectares }: { form: FormState; hectares: number | null }) {
  const { t, lang, rt } = useI18n();

  const rows: Array<[string, string]> = [
    [t('land.label'), form.label],
    [
      t('land.area'),
      `${form.areaValue} ${rt(findItem('area_units', form.areaUnit))}${
        hectares !== null ? ` (${formatNumber(hectares, lang, 4)} ha)` : ''
      }`,
    ],
    [t('land.surveyNumber'), form.surveyNumber || '—'],
    [t('land.ownership'), rt(findItem('ownership_types', form.ownershipType)) || '—'],
    [t('land.soil'), rt(findItem('soil_types', form.soilType)) || '—'],
    [
      t('land.water'),
      form.waterSources.map((code) => rt(findItem('water_sources', code))).join(', ') || '—',
    ],
    [t('land.waterType'), rt(findItem('water_types', form.waterType)) || '—'],
    [
      t('land.waterDepth'),
      form.waterDepthValue && Number.parseFloat(form.waterDepthValue) > 0
        ? `${form.waterDepthValue} ${rt(findItem('depth_units', form.waterDepthUnit))}`
        : '—',
    ],
    [t('land.irrigation'), rt(findItem('irrigation_types', form.irrigationType)) || '—'],
    [
      t('land.crops'),
      form.existingCrops.map((code) => rt(findItem('crops', code))).join(', ') || '—',
    ],
    [
      t('map.title'),
      form.coordinates
        ? `${form.coordinates.latitude.toFixed(5)}, ${form.coordinates.longitude.toFixed(5)}`
        : '—',
    ],
    [t('land.notes'), form.notes || '—'],
  ];

  return (
    <section className="card">
      <h2 className="card__title">{t('review.title')}</h2>
      <p className="card__help">{t('review.help')}</p>

      <h3 className="card__subtitle">{t('review.location')}</h3>
      <ResolvedLocation location={form.location} />

      <h3 className="card__subtitle">{t('review.details')}</h3>
      <dl className="summary">
        {rows.map(([term, value]) => (
          <div key={term} className="summary__row">
            <dt>{term}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Turns the four selected codes into readable place names via the API. */
function ResolvedLocation({ location }: { location: LocationSelection }) {
  const { t } = useI18n();
  const resolved = useAsync(
    (signal) =>
      api.resolveLocation(
        {
          villageCode: location.villageCode ?? undefined,
          subdistrictCode: location.subdistrictCode ?? undefined,
          districtCode: location.districtCode ?? undefined,
          stateCode: location.stateCode ?? undefined,
        },
        signal,
      ),
    [
      location.villageCode,
      location.subdistrictCode,
      location.districtCode,
      location.stateCode,
    ],
  );

  const path = formatLocationPath(resolved.data ?? undefined);
  return <p className="summary__location">{path || t('common.loading')}</p>;
}

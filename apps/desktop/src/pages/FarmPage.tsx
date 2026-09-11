import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { DiaryEntry, DiaryInput, Weather } from '@viksitgaanw/shared';
import { REFERENCE, findItem } from '@viksitgaanw/shared';

import { ChoiceGroup } from '../components/ChoiceGroup';
import { PhotoButton } from '../components/PhotoButton';
import { Picker } from '../components/Picker';
import { ReadAloud } from '../components/ReadAloud';
import { TextField } from '../components/TextField';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate, formatMoneyShort, formatNumber, localeFor } from '../lib/format';
import { useAsync } from '../lib/hooks';

const today = () => new Date().toISOString().slice(0, 10);

/** One plot's working record: the week's weather, and the farm diary. */
export function FarmPage() {
  const { parcelId = '' } = useParams();
  const { t } = useI18n();
  const parcel = useAsync((signal) => api.getParcel(parcelId, signal), [parcelId]);

  return (
    <div className="page">
      <p>
        <Link to="/">← {t('farm.back')}</Link>
      </p>
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('farm.title')}</h2>
          {parcel.data ? <p className="page__subtitle">{parcel.data.label}</p> : null}
        </div>
      </header>
      <WeatherCard parcelId={parcelId} />
      <Diary parcelId={parcelId} crops={parcel.data?.existingCrops ?? []} />
    </div>
  );
}

function WeatherCard({ parcelId }: { parcelId: string }) {
  const { t, lang } = useI18n();
  const [refresh, setRefresh] = useState(0);
  const weather = useAsync((signal) => api.weather(parcelId, refresh > 0, signal), [parcelId, refresh]);
  const data: Weather | null = weather.data;

  const adviceText = (data?.advisories ?? [])
    .map((advice) => `${formatDate(advice.day, lang)}: ${t(`advice.${advice.code}` as 'advice.heat')}`)
    .join('. ');

  return (
    <section className="card">
      <div className="card__head">
        <h3 className="card__title">🌦️ {t('weather.title')}</h3>
        <div className="actions">
          {adviceText ? <ReadAloud text={adviceText} /> : null}
          <button type="button" className="button button--small" disabled={weather.loading} onClick={() => setRefresh((n) => n + 1)}>
            {weather.loading ? t('common.loading') : t('weather.refresh')}
          </button>
        </div>
      </div>

      {data && !data.available ? <p className="muted">{t('weather.offline')}</p> : null}
      {data?.stale && data.fetchedAt ? (
        <p className="callout callout--warn">{t('weather.stale', { date: formatDate(data.fetchedAt, lang) })}</p>
      ) : null}
      {data?.basis === 'state' ? <p className="muted small">{t('weather.basisState')}</p> : null}

      {data?.advisories.length ? (
        <ul className="advisories">
          {data.advisories.map((advice) => (
            <li key={`${advice.code}${advice.day}`} className={`advisory advisory--${advice.severity}`}>
              <strong>{formatDate(advice.day, lang)}</strong> · {t(`advice.${advice.code}` as 'advice.heat')}
            </li>
          ))}
        </ul>
      ) : null}

      {data?.days.length ? (
        <div className="forecast" role="table">
          {data.days.map((day) => (
            <div key={day.date} className="forecast__day" role="row">
              <strong>
                {new Intl.DateTimeFormat(localeFor(lang), { weekday: 'short', day: 'numeric', numberingSystem: 'latn' }).format(
                  new Date(day.date),
                )}
              </strong>
              <span className="forecast__temp">
                {day.tempMax !== null ? `${Math.round(day.tempMax)}°` : '–'}
                <span className="muted"> / {day.tempMin !== null ? `${Math.round(day.tempMin)}°` : '–'}</span>
              </span>
              <span title={t('weather.rain')}>
                💧 {day.rainMm !== null ? `${formatNumber(day.rainMm, lang, 0)} mm` : '–'}
                {day.rainChance !== null ? <span className="muted small"> ({Math.round(day.rainChance)}%)</span> : null}
              </span>
              <span title={t('weather.wind')} className="muted small">
                🌬 {day.windMaxKmh !== null ? `${Math.round(day.windMaxKmh)} km/h` : '–'}
              </span>
            </div>
          ))}
        </div>
      ) : null}
      {data?.attribution ? <p className="fineprint">{data.attribution}</p> : null}
    </section>
  );
}

function Diary({ parcelId, crops }: { parcelId: string; crops: string[] }) {
  const { t, rt, lang } = useI18n();
  const entries = useAsync((signal) => api.diary(parcelId, signal), [parcelId]);
  const summary = useAsync((signal) => api.diarySummary(parcelId, signal), [parcelId]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    entries.reload();
    summary.reload();
  };

  const remove = async (entry: DiaryEntry) => {
    if (!window.confirm(t('diary.confirmDelete'))) return;
    try {
      await api.deleteDiary(entry.id);
      reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const money = (rupees: number) => `₹${formatMoneyShort(rupees, lang, t)}`;
  const rows = entries.data ?? [];

  return (
    <section className="card">
      <div className="card__head">
        <h3 className="card__title">📒 {t('diary.title')}</h3>
        {!adding ? (
          <button type="button" className="button button--primary button--small" onClick={() => setAdding(true)}>
            + {t('diary.add')}
          </button>
        ) : null}
      </div>
      <p className="muted">{t('diary.lede')}</p>

      {summary.data && summary.data.entries > 0 ? (
        <dl className="request__figures">
          <div>
            <dt>{t('diary.entries')}</dt>
            <dd className="request__figure">{summary.data.entries}</dd>
          </div>
          <div>
            <dt>{t('diary.spent')}</dt>
            <dd className="request__figure">{money(summary.data.spent)}</dd>
          </div>
          <div>
            <dt>{t('diary.received')}</dt>
            <dd className="request__figure">{money(summary.data.received)}</dd>
          </div>
        </dl>
      ) : null}
      {summary.data?.notSafeToHarvest.length ? (
        <p className="callout callout--warn">
          ⚠️ {t('diary.notSafe', { crops: summary.data.notSafeToHarvest.map((code) => rt(findItem('crops', code))).join(', ') })}
        </p>
      ) : null}

      {adding ? (
        <DiaryForm
          parcelId={parcelId}
          crops={crops}
          onCancel={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            reload();
          }}
        />
      ) : null}
      {error ? <p className="callout callout--error">{error}</p> : null}

      {!entries.loading && rows.length === 0 && !adding ? <p className="muted">{t('diary.empty')}</p> : null}
      <ul className="diary">
        {rows.map((entry) => (
          <li key={entry.id} className={`diary__entry diary__entry--${entry.activity}`}>
            <div className="diary__head">
              <strong>{rt(findItem('diary_activities', entry.activity))}</strong>
              {entry.crop ? <span> · {rt(findItem('crops', entry.crop))}</span> : null}
              <span className="muted small"> · {formatDate(entry.entryDate, lang)}</span>
              {entry.lotCode ? <span className="badge">{t('diary.lot', { code: entry.lotCode })}</span> : null}
            </div>
            <p className="small">
              {[
                entry.quantity !== null && entry.quantity !== undefined
                  ? `${formatNumber(entry.quantity, lang, 2)} ${entry.unit ? rt(findItem('quantity_units', entry.unit)) : ''}`
                  : null,
                entry.product ? `${entry.product}${entry.dose ? ` (${entry.dose})` : ''}` : null,
                entry.amount ? money(entry.amount) : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
            {entry.notes ? <p>{entry.notes}</p> : null}
            {entry.safeToHarvestOn ? (
              <p className={`small ${entry.safeToHarvestOn > today() ? 'text-warn' : 'muted'}`}>
                {t('diary.safeOn', { date: formatDate(entry.safeToHarvestOn, lang) })}
              </p>
            ) : null}
            {entry.phiWarnings.map((warning) => (
              <p key={warning} className="callout callout--warn">
                ⚠️ {t('diary.phiWarning', { what: warning })}
              </p>
            ))}
            {entry.photos.length ? (
              <div className="machine__thumbs">
                {entry.photos.map((photo) => (
                  <img key={photo.id} className="machine__thumb" src={api.mediaUrl(photo.url) ?? undefined} alt="" />
                ))}
              </div>
            ) : null}
            <div className="actions">
              {entry.activity === 'harvest' ? (
                <a className="button button--small button--primary" href={api.traceabilityUrl(entry.id)} target="_blank" rel="noreferrer">
                  📄 {t('diary.certificate')}
                </a>
              ) : null}
              {entry.photos.length < 4 ? (
                <PhotoButton
                  label={t('diary.addPhoto')}
                  onPick={async (file) => {
                    await api.addDiaryPhoto(entry.id, file);
                    entries.reload();
                  }}
                />
              ) : null}
              <button type="button" className="button button--ghost button--small" onClick={() => remove(entry)}>
                {t('common.delete')}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DiaryForm({
  parcelId,
  crops,
  onCancel,
  onSaved,
}: {
  parcelId: string;
  crops: string[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const { t, rt } = useI18n();
  const [activity, setActivity] = useState<string | null>('sowing');
  const [date, setDate] = useState(today());
  const [crop, setCrop] = useState<string | null>(crops[0] ?? null);
  const [quantity, setQuantity] = useState('');
  const [unit, setUnit] = useState<string | null>(null);
  const [amount, setAmount] = useState('');
  const [product, setProduct] = useState('');
  const [ingredient, setIngredient] = useState('');
  const [dose, setDose] = useState('');
  const [phi, setPhi] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cropOptions = useMemo(() => {
    // The plot's own crops first, then everything else.
    const all = REFERENCE.crops.items.map((item) => ({ value: item.code, label: rt(item) }));
    return [...all.filter((o) => crops.includes(o.value)), ...all.filter((o) => !crops.includes(o.value))];
  }, [crops, rt]);
  const unitOptions = useMemo(
    () => REFERENCE.quantity_units.items.map((item) => ({ value: item.code, label: rt(item) })),
    [rt],
  );

  const spray = activity === 'spray';
  const inputs = spray || activity === 'fertiliser';
  const number = (value: string) => {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const save = async () => {
    if (!activity) return;
    setBusy(true);
    setError(null);
    const body: DiaryInput = {
      activity,
      entryDate: date,
      crop,
      quantity: number(quantity),
      unit: quantity ? unit : null,
      amount: number(amount),
      product: inputs ? product : null,
      activeIngredient: spray ? ingredient : null,
      dose: inputs ? dose : null,
      preHarvestDays: spray ? number(phi) : null,
      notes,
    };
    try {
      await api.addDiary(parcelId, body);
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  return (
    <div className="stack diary__form">
      <ChoiceGroup label={t('diary.activity')} items={REFERENCE.diary_activities.items} value={activity} onChange={setActivity} />
      <div className="field-row">
        <TextField id="diaryDate" label={t('diary.date')} type="date" value={date} onChange={setDate} />
        <Picker label={t('diary.crop')} placeholder={t('common.notSelected')} options={cropOptions} value={crop} onChange={setCrop} allowClear />
      </div>
      {inputs ? (
        <div className="field-row">
          <TextField id="diaryProduct" label={t('diary.product')} value={product} onChange={setProduct} maxLength={160} />
          <TextField id="diaryDose" label={t('diary.dose')} value={dose} onChange={setDose} optional maxLength={80} />
        </div>
      ) : null}
      {spray ? (
        <div className="field-row">
          <TextField id="diaryIngredient" label={t('diary.ingredient')} value={ingredient} onChange={setIngredient} optional maxLength={160} />
          <TextField
            id="diaryPhi"
            label={t('diary.phi')}
            hint={t('diary.phiHint')}
            type="number"
            inputMode="numeric"
            min={0}
            value={phi}
            onChange={setPhi}
            optional
          />
        </div>
      ) : null}
      <div className="field-row">
        <TextField id="diaryQuantity" label={t('diary.quantity')} type="number" inputMode="decimal" min={0} value={quantity} onChange={setQuantity} optional />
        <Picker label={t('diary.unit')} placeholder={t('common.notSelected')} options={unitOptions} value={unit} onChange={setUnit} allowClear />
      </div>
      <div className="narrow">
        <TextField
          id="diaryAmount"
          label={t('diary.amount')}
          hint={t('diary.amountHint')}
          type="number"
          inputMode="decimal"
          min={0}
          value={amount}
          onChange={setAmount}
          optional
        />
      </div>
      <TextField id="diaryNotes" label={t('diary.notes')} value={notes} onChange={setNotes} multiline optional maxLength={4000} />
      {error ? <p className="callout callout--error">{error}</p> : null}
      <div className="actions">
        <button type="button" className="button button--ghost" onClick={onCancel} disabled={busy}>
          {t('common.cancel')}
        </button>
        <button type="button" className="button button--primary" onClick={save} disabled={busy || !activity}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>
    </div>
  );
}

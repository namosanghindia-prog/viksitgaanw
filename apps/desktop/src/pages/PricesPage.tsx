import { useMemo, useRef, useState } from 'react';
import type { FxRates, PricePoint } from '@viksitgaanw/shared';
import { REFERENCE } from '@viksitgaanw/shared';

import { Picker } from '../components/Picker';
import { ReadAloud } from '../components/ReadAloud';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate, formatNumber } from '../lib/format';
import { invalidateFx } from '../lib/fx';
import { useAsync } from '../lib/hooks';
import { useProfile } from '../lib/profile';

const STORAGE_KEY = 'viksitgaanw.pricesCrop';
const WEEK_MS = 7 * 24 * 3600 * 1000;

function rememberedCrop(fallback: string | null): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? fallback;
  } catch {
    return fallback;
  }
}

/** Mandi prices for a crop, the owner's state first, and exchange rates. */
export function PricesPage() {
  const { t, rt, lang } = useI18n();
  const { profile } = useProfile();
  const parcels = useAsync((signal) => api.listParcels(signal), [], { enabled: profile?.segment === 'farmer' });
  const firstCrop = parcels.data?.flatMap((parcel) => parcel.existingCrops)[0] ?? 'onion';
  const [crop, setCropState] = useState<string | null>(() => rememberedCrop(null));
  const chosen = crop ?? firstCrop;
  const prices = useAsync((signal) => api.prices(chosen, 30, signal), [chosen]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const setCrop = (value: string | null) => {
    setCropState(value);
    try {
      if (value) localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // Remembering the crop is only a convenience.
    }
  };

  const cropOptions = useMemo(
    () => REFERENCE.crops.items.map((item) => ({ value: item.code, label: rt(item) })),
    [rt],
  );

  const run = async (action: () => Promise<{ imported: number }>) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await action();
      setMessage(t('prices.imported', { n: result.imported }));
      prices.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  const data = prices.data;
  const old = data?.dataAsOf ? Date.now() - new Date(data.dataAsOf).getTime() > WEEK_MS : false;
  const best = data?.latest[0];
  const spoken = best
    ? t('prices.spoken', {
        crop: rt(REFERENCE.crops.items.find((item) => item.code === chosen)),
        market: best.market,
        price: formatNumber(best.modalPrice, lang, 0),
      })
    : '';

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('prices.title')}</h2>
          <p className="page__subtitle">{t('prices.lede')}</p>
        </div>
        <div className="actions">
          <input
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void run(() => api.importPrices(file));
            }}
          />
          <button type="button" className="button" disabled={busy} onClick={() => fileInput.current?.click()}>
            {t('prices.import')}
          </button>
          <button type="button" className="button" disabled={busy} onClick={() => run(() => api.fetchPrices())}>
            {t('prices.fetch')}
          </button>
        </div>
      </header>

      <div className="filters">
        <Picker label={t('prices.crop')} placeholder={t('prices.pickCrop')} options={cropOptions} value={chosen} onChange={setCrop} />
      </div>

      {message ? <p className="callout callout--info">{message}</p> : null}
      {error ? <p className="callout callout--error">{error}</p> : null}
      {prices.loading && !data ? <p className="muted">{t('common.loading')}</p> : null}

      {data && data.rows === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('prices.empty')}</p>
          <p className="empty__help">{t('prices.emptyHelp')}</p>
        </div>
      ) : null}

      {data && data.rows > 0 ? (
        <section className="card">
          <div className="card__head">
            <p className="muted small">
              {data.dataAsOf ? t('prices.asOf', { date: formatDate(data.dataAsOf, lang) }) : null} · {t('prices.perQuintal')}
            </p>
            {spoken ? <ReadAloud text={spoken} /> : null}
          </div>
          {old ? <p className="callout callout--warn">{t('prices.oldData')}</p> : null}
          {data.trend.length > 1 ? <Sparkline points={data.trend} label={t('prices.trend', { days: 30 })} /> : null}
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('prices.market')}</th>
                  <th>{t('prices.date')}</th>
                  <th className="num">{t('prices.min')}</th>
                  <th className="num">{t('prices.max')}</th>
                  <th className="num">{t('prices.modal')}</th>
                </tr>
              </thead>
              <tbody>
                {data.latest.map((row) => (
                  <tr key={`${row.market}${row.commodity}${row.variety}${row.arrivalDate}`}>
                    <td>
                      <strong>{row.market}</strong>
                      <div className="muted small">
                        {row.districtName}, {row.stateName}
                        {row.variety ? ` · ${row.variety}` : ''}
                      </div>
                    </td>
                    <td>{formatDate(row.arrivalDate, lang)}</td>
                    <td className="num">{row.minPrice !== null ? formatNumber(row.minPrice, lang, 0) : '–'}</td>
                    <td className="num">{row.maxPrice !== null ? formatNumber(row.maxPrice, lang, 0) : '–'}</td>
                    <td className="num">
                      <strong>{formatNumber(row.modalPrice, lang, 0)}</strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="fineprint">{data.source}</p>
        </section>
      ) : null}

      <FxCard />
    </div>
  );
}

/** A small line of the average price per day, drawn without a chart library. */
function Sparkline({ points, label }: { points: PricePoint[]; label: string }) {
  const { lang } = useI18n();
  const width = 520;
  const height = 90;
  const values = points.map((point) => point.modalAverage);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * (width - 8) + 4;
      const y = height - 6 - ((point.modalAverage - min) / span) * (height - 12);
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  const first = values[0];
  const last = values[values.length - 1];
  const change = first ? ((last - first) / first) * 100 : 0;

  return (
    <figure className="sparkline">
      <figcaption className="muted small">
        {label}: ₹{formatNumber(first, lang, 0)} → ₹{formatNumber(last, lang, 0)}{' '}
        <strong className={change >= 0 ? 'text-good' : 'text-warn'}>
          ({change >= 0 ? '▲' : '▼'} {formatNumber(Math.abs(change), lang, 1)}%)
        </strong>
      </figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} preserveAspectRatio="none">
        <path d={path} fill="none" stroke="currentColor" strokeWidth="2.5" />
      </svg>
    </figure>
  );
}

/** Rupee rates for the currencies foreign investors use; editable by hand. */
function FxCard() {
  const { t, lang } = useI18n();
  const fx = useAsync((signal) => api.fx(signal), []);
  const [data, setData] = useState<FxRates | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const current = data ?? fx.data;

  const apply = async (action: () => Promise<FxRates>) => {
    setError(null);
    try {
      const next = await action();
      invalidateFx();
      setData(next);
      if (!next.refreshed && next.message) setError(next.message);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  return (
    <section className="card">
      <div className="card__head">
        <h3 className="card__title">💱 {t('fx.title')}</h3>
        <button type="button" className="button button--small" onClick={() => apply(() => api.refreshFx())}>
          {t('fx.refresh')}
        </button>
      </div>
      {current && current.rates.length === 0 ? <p className="muted">{t('fx.none')}</p> : null}
      <ul className="fx">
        {current?.rates.map((rate) => (
          <li key={rate.currency} className="fx__row">
            <span>
              {t('fx.rate', { currency: rate.currency, rate: formatNumber(rate.inrPerUnit, lang, 2) })}
              <span className="muted small">
                {' '}
                · {formatDate(rate.asOf, lang)}
                {rate.source === 'manual' ? ` · ${t('fx.manual')}` : ''}
              </span>
            </span>
            {editing === rate.currency ? (
              <span className="actions">
                <input
                  className="input input--small"
                  type="number"
                  min={0}
                  step="0.01"
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  aria-label={t('fx.set')}
                />
                <button
                  type="button"
                  className="button button--small button--primary"
                  onClick={async () => {
                    const parsed = Number.parseFloat(value);
                    if (!(parsed > 0)) return;
                    await apply(() => api.setFx(rate.currency, parsed));
                    setEditing(null);
                  }}
                >
                  {t('common.save')}
                </button>
              </span>
            ) : (
              <span className="actions">
                <button
                  type="button"
                  className="button button--ghost button--small"
                  onClick={() => {
                    setEditing(rate.currency);
                    setValue(String(rate.inrPerUnit));
                  }}
                >
                  {t('fx.set')}
                </button>
                {rate.source === 'manual' ? (
                  <button type="button" className="button button--ghost button--small" onClick={() => apply(() => api.clearFx(rate.currency))}>
                    {t('fx.clear')}
                  </button>
                ) : null}
              </span>
            )}
          </li>
        ))}
      </ul>
      {error ? <p className="callout callout--warn">{error}</p> : null}
    </section>
  );
}

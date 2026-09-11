import type { CountBucket } from '@viksitgaanw/shared';
import { findItem } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import type { StringKey } from '../i18n';
import { api } from '../lib/api';
import { formatDate, formatMoneyShort, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';

/**
 * Numbers for the owner's patch: a block officer sees their block, a partner
 * their state, an investor all of India. Only what this device knows is
 * counted -- the page says so.
 */
export function InsightsPage() {
  const { t, rt, lang } = useI18n();
  const insights = useAsync((signal) => api.insights(signal), []);
  const data = insights.data;
  const money = (rupees: number) => `₹${formatMoneyShort(rupees, lang, t)}`;

  if (insights.error) return <p className="page callout callout--error">{insights.error.message}</p>;
  if (!data) return <p className="page muted">{t('common.loading')}</p>;

  const tiles: Array<{ label: StringKey; value: string }> = [
    { label: 'insights.farmers', value: formatNumber(data.farmers, lang, 0) },
    { label: 'insights.requestsOpen', value: formatNumber(data.requestsOpen, lang, 0) },
    { label: 'insights.amountSought', value: money(data.amountSought) },
    { label: 'insights.interests', value: formatNumber(data.interests, lang, 0) },
    { label: 'insights.matches', value: formatNumber(data.matches, lang, 0) },
    { label: 'insights.dealsActive', value: formatNumber(data.dealsActive, lang, 0) },
    { label: 'insights.dealsCompleted', value: formatNumber(data.dealsCompleted, lang, 0) },
    { label: 'insights.amountReleased', value: money(data.amountReleased) },
    { label: 'insights.machines', value: formatNumber(data.machines, lang, 0) },
    { label: 'insights.rentals', value: formatNumber(data.rentalsAgreed, lang, 0) },
    { label: 'insights.groups', value: formatNumber(data.groups, lang, 0) },
    { label: 'insights.groupHectares', value: formatNumber(data.groupHectares, lang, 1) },
  ];

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('insights.title')}</h2>
          <p className="page__subtitle">
            {t(`insightsScope.${data.scope}`, { place: data.place ?? '' })} · {formatDate(data.generatedAt, lang)}
          </p>
        </div>
      </header>
      <div className="tiles">
        {tiles.map((tile) => (
          <div key={tile.label} className="tile">
            <span className="tile__value">{tile.value}</span>
            <span className="tile__label">{t(tile.label)}</span>
          </div>
        ))}
      </div>
      <div className="insight-columns">
        <Bars
          title={t('insights.byKind')}
          rows={data.requestsByKind}
          label={(row) =>
            rt(findItem('opportunity_kinds', row.code)) || (row.code === 'other' ? t('insights.other') : row.label || row.code)
          }
        />
        {data.scope === 'national' || data.scope === 'state' ? (
          <Bars title={t('insights.byState')} rows={data.requestsByState} label={(row) => row.label || row.code} />
        ) : null}
        <Bars
          title={t('insights.byMachine')}
          rows={data.machinesByType}
          label={(row) => rt(findItem('equipment_types', row.code)) || row.label || row.code}
        />
      </div>
      <p className="fineprint">{t('insights.note')}</p>
    </div>
  );
}

function Bars({ title, rows, label }: { title: string; rows: CountBucket[]; label: (row: CountBucket) => string }) {
  const { lang } = useI18n();
  if (!rows.length) return null;
  const max = Math.max(...rows.map((row) => row.count), 1);
  return (
    <section className="card">
      <h3 className="card__title">{title}</h3>
      <ul className="bars">
        {rows.map((row) => (
          <li key={row.code} className="bars__row">
            <span className="bars__label">{label(row)}</span>
            <span className="bars__track">
              <span className="bars__fill" style={{ width: `${(row.count / max) * 100}%` }} />
            </span>
            <span className="bars__value">{formatNumber(row.count, lang, 0)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

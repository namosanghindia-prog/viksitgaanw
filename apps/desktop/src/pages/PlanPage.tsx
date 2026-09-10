import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { Opportunity, Verdict } from '@viksitgaanw/shared';

import { DprDialog } from '../components/DprDialog';
import { OpportunityCard } from '../components/OpportunityCard';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatLocationPath, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';

type Tab = 'all' | 'export';

/**
 * What this land could be used for.
 *
 * The whole intake form exists to get here: once the app knows where the land
 * is, how big it is, and what soil and water it has, it can say what could be
 * grown or built on it, what that would cost, and what it would earn -- and
 * then turn the chosen option into a report a bank will read.
 *
 * Options that do not suit the land are kept, not hidden, but collapsed behind
 * a disclosure. A farmer who wonders why the app did not suggest pomegranate
 * deserves to be told that the water is too salty for it.
 */
export function PlanPage() {
  const { parcelId = '' } = useParams();
  const { t, lang } = useI18n();

  const [tab, setTab] = useState<Tab>('all');
  const [showUnsuitable, setShowUnsuitable] = useState(false);
  const [chosen, setChosen] = useState<Opportunity | null>(null);

  const parcel = useAsync((signal) => api.getParcel(parcelId, signal), [parcelId], {
    enabled: Boolean(parcelId),
  });

  const plan = useAsync(
    (signal) => api.opportunities(parcelId, { lang, exportOnly: tab === 'export' }, signal),
    [parcelId, lang, tab],
    { enabled: Boolean(parcelId) },
  );

  const reports = useAsync(
    (signal) => api.parcelReports(parcelId, lang, signal),
    [parcelId, lang],
    { enabled: Boolean(parcelId) },
  );

  const grouped = useMemo(() => {
    const items = plan.data?.items ?? [];
    const by = (verdict: Verdict) => items.filter((item) => item.verdict === verdict);
    return {
      recommended: by('recommended'),
      possible: by('possible'),
      unsuitable: by('unsuitable'),
    };
  }, [plan.data]);

  if (!parcelId) return null;

  const land = parcel.data;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('plan.title')}</h2>
          {land ? (
            <p className="page__subtitle">
              {land.label} · {formatLocationPath(land.location)} ·{' '}
              {formatNumber(land.areaHectares, lang, 3)} ha
            </p>
          ) : null}
        </div>
        <Link className="button button--ghost" to="/">
          {t('nav.myLand')}
        </Link>
      </header>

      <p className="page__lede">{t('plan.lede')}</p>

      <div className="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'all'}
          className={`tab ${tab === 'all' ? 'tab--active' : ''}`}
          onClick={() => setTab('all')}
        >
          {t('plan.tabAll')}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'export'}
          className={`tab ${tab === 'export' ? 'tab--active' : ''}`}
          onClick={() => setTab('export')}
        >
          {t('plan.tabExport')}
        </button>
      </div>

      {tab === 'export' ? <p className="callout callout--info">{t('plan.exportLede')}</p> : null}

      {plan.loading ? <p className="muted">{t('common.loading')}</p> : null}
      {plan.error ? (
        <div className="callout callout--error">
          {t('plan.failed')}{' '}
          <button type="button" className="button button--small" onClick={plan.reload}>
            {t('common.retry')}
          </button>
        </div>
      ) : null}

      {reports.data && reports.data.length > 0 ? (
        <section className="card card--tight">
          <h3 className="card__subtitle">{t('plan.savedReports')}</h3>
          <ul className="reportlist">
            {reports.data.map((report) => (
              <li key={report.id} className="reportlist__item">
                <div>
                  <strong>{report.opportunityName}</strong>{' '}
                  <span className="muted small">
                    {report.reportNumber} · {report.languageLabel} ·{' '}
                    {Math.round(report.fileSize / 1024)} KB
                  </span>
                </div>
                <div className="reportlist__actions">
                  <a
                    className="button button--small button--primary"
                    href={api.reportFileUrl(report)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t('plan.openReport')}
                  </a>
                  <button
                    type="button"
                    className="button button--small button--danger"
                    onClick={async () => {
                      if (!window.confirm(t('plan.confirmDeleteReport'))) return;
                      await api.deleteReport(report.id);
                      reports.reload();
                    }}
                  >
                    {t('common.delete')}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {grouped.recommended.length > 0 ? (
        <section>
          <h3 className="section__title">
            {t('plan.recommended')}{' '}
            <span className="muted small">({grouped.recommended.length})</span>
          </h3>
          <div className="opportunities">
            {grouped.recommended.map((item) => (
              <OpportunityCard
                key={item.code}
                opportunity={item}
                onChoose={() => setChosen(item)}
              />
            ))}
          </div>
        </section>
      ) : null}

      {grouped.possible.length > 0 ? (
        <section>
          <h3 className="section__title">
            {t('plan.possible')} <span className="muted small">({grouped.possible.length})</span>
          </h3>
          <div className="opportunities">
            {grouped.possible.map((item) => (
              <OpportunityCard
                key={item.code}
                opportunity={item}
                onChoose={() => setChosen(item)}
              />
            ))}
          </div>
        </section>
      ) : null}

      {grouped.unsuitable.length > 0 ? (
        <section>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => setShowUnsuitable((value) => !value)}
            aria-expanded={showUnsuitable}
          >
            {showUnsuitable ? '▾' : '▸'}{' '}
            {t('plan.showUnsuitable', { n: grouped.unsuitable.length })}
          </button>
          {showUnsuitable ? (
            <div className="opportunities opportunities--muted">
              {grouped.unsuitable.map((item) => (
                <OpportunityCard key={item.code} opportunity={item} />
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {plan.data ? (
        <p className="fineprint">
          {plan.data.basis} <span className="muted">({plan.data.dataAsOf})</span>
        </p>
      ) : null}

      {chosen && land ? (
        <DprDialog
          parcel={land}
          opportunity={chosen}
          onClose={() => setChosen(null)}
          onCreated={() => {
            setChosen(null);
            reports.reload();
          }}
        />
      ) : null}
    </div>
  );
}

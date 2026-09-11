import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { Opportunity, Sector, Verdict } from '@viksitgaanw/shared';

import { DprDialog } from '../components/DprDialog';
import { OpportunityCard } from '../components/OpportunityCard';
import { useI18n } from '../i18n';
import type { StringKey } from '../i18n';
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
 * Farming projects (crops, orchards, livestock, fish) and non-farming ones
 * (processing, storage, services) stand side by side in two columns: the
 * second is often the answer for a family with little land.
 *
 * Options that do not suit the land are kept, not hidden, but collapsed behind
 * a disclosure. A farmer who wonders why the app did not suggest pomegranate
 * deserves to be told that the water is too salty for it.
 */
export function PlanPage() {
  const { parcelId = '' } = useParams();
  const { t, lang } = useI18n();

  const [tab, setTab] = useState<Tab>('all');
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

  const bySector = useMemo(() => {
    const items = plan.data?.items ?? [];
    return {
      farm: items.filter((item) => item.sector === 'farm'),
      nonfarm: items.filter((item) => item.sector === 'nonfarm'),
    };
  }, [plan.data]);

  if (!parcelId) return null;

  const land = parcel.data;

  return (
    <div className="page page--wide">
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
                  <Link
                    className="button button--small"
                    to={`/land/${parcelId}/invest?report=${report.id}`}
                  >
                    {t('nav.findInvestors')}
                  </Link>
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

      {plan.data ? (
        <div className="plan-columns">
          <PlanColumn
            sector="farm"
            items={bySector.farm}
            exportOnly={tab === 'export'}
            onChoose={setChosen}
          />
          <PlanColumn
            sector="nonfarm"
            items={bySector.nonfarm}
            exportOnly={tab === 'export'}
            onChoose={setChosen}
          />
        </div>
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

const COLUMN: Record<Sector, { icon: string; title: StringKey; hint: StringKey }> = {
  farm: { icon: '🌾', title: 'plan.farm', hint: 'plan.farmHint' },
  nonfarm: { icon: '🏭', title: 'plan.nonfarm', hint: 'plan.nonfarmHint' },
};

/**
 * One side of the plan: farming projects, or non-farming ones -- best suited
 * first, then worth considering, and what does not suit the land folded away.
 * Each side is ranked on its own, so a strong dal mill is not buried under
 * twenty crops, nor a strong crop under a cold room.
 */
function PlanColumn({
  sector,
  items,
  exportOnly,
  onChoose,
}: {
  sector: Sector;
  items: Opportunity[];
  exportOnly: boolean;
  onChoose: (item: Opportunity) => void;
}) {
  const { t } = useI18n();
  const [showUnsuitable, setShowUnsuitable] = useState(false);
  const by = (verdict: Verdict) => items.filter((item) => item.verdict === verdict);
  const recommended = by('recommended');
  const possible = by('possible');
  const unsuitable = by('unsuitable');
  const column = COLUMN[sector];

  const group = (title: StringKey, rows: Opportunity[]) =>
    rows.length > 0 ? (
      <section>
        <h4 className="section__title">
          {t(title)} <span className="muted small">({rows.length})</span>
        </h4>
        <div className="opportunities opportunities--column">
          {rows.map((item) => (
            <OpportunityCard key={item.code} opportunity={item} onChoose={() => onChoose(item)} />
          ))}
        </div>
      </section>
    ) : null;

  return (
    <section className={`plan-column plan-column--${sector}`} aria-labelledby={`plan-column-${sector}`}>
      <header className="plan-column__head">
        <h3 id={`plan-column-${sector}`} className="plan-column__title">
          <span aria-hidden="true">{column.icon}</span> {t(column.title)}{' '}
          <span className="plan-column__count">{recommended.length + possible.length}</span>
        </h3>
        <p className="muted small">{t(column.hint)}</p>
      </header>

      {recommended.length + possible.length === 0 ? (
        <p className="muted">{t(exportOnly && items.length === 0 ? 'plan.noneExport' : 'plan.noneSuit')}</p>
      ) : null}
      {group('plan.recommended', recommended)}
      {group('plan.possible', possible)}

      {unsuitable.length > 0 ? (
        <section>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => setShowUnsuitable((value) => !value)}
            aria-expanded={showUnsuitable}
          >
            {showUnsuitable ? '▾' : '▸'} {t('plan.showUnsuitable', { n: unsuitable.length })}
          </button>
          {showUnsuitable ? (
            <div className="opportunities opportunities--column opportunities--muted">
              {unsuitable.map((item) => (
                <OpportunityCard key={item.code} opportunity={item} />
              ))}
            </div>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}

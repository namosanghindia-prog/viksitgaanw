import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { LandParcel } from '@viksitgaanw/shared';
import { findItem } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate, formatLocationPath, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';

export function MyLandPage() {
  const { t, lang, rt } = useI18n();
  const parcels = useAsync((signal) => api.listParcels(signal), []);
  const [busyId, setBusyId] = useState<string | null>(null);

  const remove = async (parcel: LandParcel) => {
    if (!window.confirm(t('list.confirmDelete', { label: parcel.label }))) return;
    setBusyId(parcel.id);
    try {
      await api.deleteParcel(parcel.id);
      parcels.reload();
    } finally {
      setBusyId(null);
    }
  };

  const rows = parcels.data ?? [];
  const totalHectares = rows.reduce((sum, parcel) => sum + parcel.areaHectares, 0);

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('list.title')}</h2>
          {rows.length > 0 ? (
            <p className="page__subtitle">
              {t('list.parcelCount', { n: rows.length })} · {t('list.totalArea')}:{' '}
              {formatNumber(totalHectares, lang, 3)} ha
            </p>
          ) : null}
        </div>
        <Link className="button button--primary" to="/land/new">
          + {t('nav.addLand')}
        </Link>
      </header>

      {parcels.loading ? <p className="muted">{t('common.loading')}</p> : null}

      {!parcels.loading && rows.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('list.empty')}</p>
          <p className="empty__help">{t('list.emptyHelp')}</p>
          <Link className="button button--primary" to="/land/new">
            {t('list.addFirst')}
          </Link>
        </div>
      ) : null}

      <div className="parcels">
        {rows.map((parcel) => (
          <article key={parcel.id} className="parcel">
            <div className="parcel__main">
              <h3 className="parcel__label">{parcel.label}</h3>
              <p className="parcel__location">{formatLocationPath(parcel.location)}</p>

              <dl className="parcel__facts">
                <div>
                  <dt>{t('land.area')}</dt>
                  <dd>
                    {formatNumber(parcel.areaValue, lang, 2)}{' '}
                    {rt(findItem('area_units', parcel.areaUnit))}
                    <span className="muted">
                      {' '}
                      ({formatNumber(parcel.areaHectares, lang, 3)} ha)
                    </span>
                  </dd>
                </div>
                {parcel.soilType ? (
                  <div>
                    <dt>{t('land.soil')}</dt>
                    <dd>{rt(findItem('soil_types', parcel.soilType))}</dd>
                  </div>
                ) : null}
                {parcel.waterType ? (
                  <div>
                    <dt>{t('land.waterType')}</dt>
                    <dd>{rt(findItem('water_types', parcel.waterType))}</dd>
                  </div>
                ) : null}
                {parcel.waterDepthValue && parcel.waterDepthUnit ? (
                  <div>
                    <dt>{t('land.waterDepth')}</dt>
                    <dd>
                      {formatNumber(parcel.waterDepthValue, lang, 1)}{' '}
                      {rt(findItem('depth_units', parcel.waterDepthUnit))}
                      {parcel.waterDepthMetres !== null ? (
                        <span className="muted">
                          {' '}
                          ({formatNumber(parcel.waterDepthMetres, lang, 1)} m)
                        </span>
                      ) : null}
                    </dd>
                  </div>
                ) : null}
                {parcel.existingCrops.length ? (
                  <div>
                    <dt>{t('land.crops')}</dt>
                    <dd>
                      {parcel.existingCrops
                        .map((code) => rt(findItem('crops', code)))
                        .join(', ')}
                    </dd>
                  </div>
                ) : null}
              </dl>
            </div>

            <div className="parcel__side">
              <Link
                className="button button--primary button--small"
                to={`/land/${parcel.id}/plan`}
              >
                {t('plan.seeOptions')}
              </Link>
              <Link className="button button--small" to={`/land/${parcel.id}/invest`}>
                {t('nav.findInvestors')}
              </Link>
              <Link className="button button--small button--ghost" to={`/land/${parcel.id}/insurance`}>
                🛡 {t('insurance.title')}
              </Link>
              <span className="badge" title={t('review.savedHelp')}>
                {parcel.syncState === 'synced' ? '☁' : '💾'} {t('review.saved')}
              </span>
              <span className="muted small">{formatDate(parcel.createdAt, lang)}</span>
              <button
                type="button"
                className="button button--danger button--small"
                onClick={() => remove(parcel)}
                disabled={busyId === parcel.id}
              >
                {t('common.delete')}
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

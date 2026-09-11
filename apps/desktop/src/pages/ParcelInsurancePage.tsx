import { Link, useParams } from 'react-router-dom';

import { InsuranceManager } from '../components/InsuranceManager';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatLocationPath, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';

/** Crop cover season by season, and cover for anything built on the plot. */
export function ParcelInsurancePage() {
  const { parcelId = '' } = useParams();
  const { t, lang } = useI18n();

  const parcel = useAsync((signal) => api.getParcel(parcelId, signal), [parcelId], {
    enabled: Boolean(parcelId),
  });
  const policies = useAsync((signal) => api.listInsurance(parcelId, signal), [parcelId], {
    enabled: Boolean(parcelId),
  });

  const land = parcel.data;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('insurance.landTitle')}</h2>
          {land ? (
            <p className="page__subtitle">
              {land.label} · {formatLocationPath(land.location)} · {formatNumber(land.areaHectares, lang, 3)} ha
            </p>
          ) : null}
        </div>
        <Link className="button button--ghost" to="/">
          {t('nav.myLand')}
        </Link>
      </header>

      <p className="page__lede">{t('insurance.landLede')}</p>

      <section className="card">
        {policies.loading ? (
          <p className="muted">{t('common.loading')}</p>
        ) : (
          <InsuranceManager
            target={{ parcelId }}
            scope="parcel"
            policies={policies.data ?? []}
            recommended={['crop']}
            onChanged={policies.reload}
          />
        )}
      </section>
    </div>
  );
}

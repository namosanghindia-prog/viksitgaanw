import { useState } from 'react';

import { AddPartnerDialog } from '../components/AddPartnerDialog';
import { PartnershipList } from '../components/PartnershipList';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useAsync } from '../lib/hooks';

/**
 * A seller's partner network, with requests to join kept on top so none is
 * missed. The same page shows an organisation's own partnerships with other
 * sellers, if it is a distributor for someone else.
 */
export function PartnersPage() {
  const { t } = useI18n();
  const partnerships = useAsync((signal) => api.partnerships(signal), []);
  const [adding, setAdding] = useState(false);

  const rows = partnerships.data ?? [];
  const waiting = rows.filter((row) => row.isSeller && row.status === 'proposed' && row.initiatedBy === 'partner');
  const network = rows.filter((row) => row.isSeller && !waiting.includes(row));
  const theirs = rows.filter((row) => !row.isSeller);

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('partners.title')}</h2>
          <p className="page__subtitle">{t('partners.sellerLede')}</p>
        </div>
        <button type="button" className="button button--primary" onClick={() => setAdding(true)}>
          + {t('partners.add')}
        </button>
      </header>

      {partnerships.loading ? <p className="muted">{t('common.loading')}</p> : null}

      {waiting.length ? (
        <section className="card">
          <h3 className="card__title">{t('partners.requests', { n: waiting.length })}</h3>
          <PartnershipList partnerships={waiting} onChanged={partnerships.reload} />
        </section>
      ) : null}

      <section className="card">
        <h3 className="card__title">{t('partners.network')}</h3>
        <PartnershipList partnerships={network} onChanged={partnerships.reload} />
      </section>

      {theirs.length ? (
        <section className="card">
          <h3 className="card__title">{t('equipment.tabPartnerships')}</h3>
          <p className="card__help">{t('partners.farmerLede')}</p>
          <PartnershipList partnerships={theirs} onChanged={partnerships.reload} />
        </section>
      ) : null}

      {adding ? (
        <AddPartnerDialog
          onClose={() => setAdding(false)}
          onAdded={() => {
            setAdding(false);
            partnerships.reload();
          }}
        />
      ) : null}
    </div>
  );
}

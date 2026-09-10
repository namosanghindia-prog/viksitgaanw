import { useMemo, useState } from 'react';
import type { ReferenceItem } from '@viksitgaanw/shared';
import { REFERENCE } from '@viksitgaanw/shared';

import { ChoiceGroup } from '../components/ChoiceGroup';
import { EquipmentActions } from '../components/EquipmentActions';
import { EquipmentCard } from '../components/EquipmentCard';
import { PartnershipList } from '../components/PartnershipList';
import { Picker } from '../components/Picker';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useAsync } from '../lib/hooks';

type Tab = 'browse' | 'enquiries' | 'partnerships';

/**
 * Machines to rent or buy, the enquiries sent about them, and partnerships
 * with sellers -- the farmer's side of the equipment marketplace.
 */
export function MachinesPage() {
  const { t, rt } = useI18n();
  const [tab, setTab] = useState<Tab>('browse');
  const [type, setType] = useState<string | null>(null);
  const [offer, setOffer] = useState<string | null>(null);
  const [stateCode, setStateCode] = useState<string | null>(null);

  const states = useAsync((signal) => api.states(signal), []);
  const listings = useAsync(
    (signal) =>
      api.browseEquipment(
        { type: type ?? undefined, stateCode: stateCode ?? undefined, offer: (offer as 'rent' | 'sale' | null) ?? undefined },
        signal,
      ),
    [type, offer, stateCode],
    { enabled: tab === 'browse' },
  );
  const enquiries = useAsync((signal) => api.myEnquiries(signal), [tab], { enabled: tab === 'enquiries' });
  const partnerships = useAsync((signal) => api.partnerships(signal), [tab], { enabled: tab === 'partnerships' });

  const typeOptions = useMemo(
    () => REFERENCE.equipment_types.items.map((item) => ({ value: item.code, label: rt(item) })),
    [rt],
  );
  const stateOptions = useMemo(
    () => (states.data ?? []).map((unit) => ({ value: unit.code, label: unit.name, sublabel: unit.nameLocal })),
    [states.data],
  );
  const offerItems = useMemo<ReferenceItem[]>(
    () => [
      { code: 'rent', label: { en: t('equipment.forRent'), hi: t('equipment.forRent') } },
      { code: 'sale', label: { en: t('equipment.forSale'), hi: t('equipment.forSale') } },
    ],
    [t],
  );

  const rows = tab === 'browse' ? listings.data ?? [] : enquiries.data ?? [];
  const loading = tab === 'browse' ? listings.loading : tab === 'enquiries' ? enquiries.loading : partnerships.loading;
  const reload = tab === 'browse' ? listings.reload : enquiries.reload;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('equipment.title')}</h2>
          <p className="page__subtitle">{t('equipment.lede')}</p>
        </div>
      </header>

      <div className="tabs" role="tablist">
        {(['browse', 'enquiries', 'partnerships'] as const).map((entry) => (
          <button
            key={entry}
            type="button"
            role="tab"
            aria-selected={tab === entry}
            className={`tab ${tab === entry ? 'tab--active' : ''}`}
            onClick={() => setTab(entry)}
          >
            {entry === 'browse'
              ? t('equipment.tabBrowse')
              : entry === 'enquiries'
                ? t('equipment.tabEnquiries')
                : t('equipment.tabPartnerships')}
          </button>
        ))}
      </div>

      {tab === 'browse' ? (
        <>
          <div className="filters">
            <Picker label={t('equipment.type')} placeholder={t('equipment.allTypes')} options={typeOptions} value={type} onChange={setType} allowClear />
            <Picker label={t('location.state')} placeholder={t('browse.allStates')} options={stateOptions} value={stateCode} onChange={setStateCode} loading={states.loading} allowClear />
          </div>
          <ChoiceGroup label={t('equipment.offer')} items={offerItems} value={offer} onChange={setOffer} />
        </>
      ) : null}

      {loading ? <p className="muted">{t('common.loading')}</p> : null}

      {tab === 'partnerships' ? (
        partnerships.data ? (
          <PartnershipList partnerships={partnerships.data} onChanged={partnerships.reload} emptyText={t('equipment.noPartnerships')} />
        ) : null
      ) : !loading && rows.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{tab === 'browse' ? t('equipment.empty') : t('equipment.noEnquiries')}</p>
          {tab === 'browse' ? (
            <>
              <p className="empty__help">{t('browse.emptyHelp')}</p>
              <code>python scripts/seed_demo_marketplace.py</code>
            </>
          ) : null}
        </div>
      ) : (
        <div className="requests">
          {rows.map((item) => (
            <EquipmentCard key={item.id} item={item}>
              <EquipmentActions item={item} onChanged={reload} />
            </EquipmentCard>
          ))}
        </div>
      )}
    </div>
  );
}

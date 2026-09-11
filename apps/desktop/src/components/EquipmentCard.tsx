import { useState } from 'react';
import type { ReactNode } from 'react';
import type { Equipment } from '@viksitgaanw/shared';
import { findItem } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatMoneyShort, formatNumber } from '../lib/format';
import { PartyLine } from './RequestCard';
import { VideoPlayer } from './Video';

interface EquipmentCardProps {
  item: Equipment;
  /** Hide the seller line on the seller's own machines. */
  showSeller?: boolean;
  children?: ReactNode;
}

/** One machine: pictures, what it costs to rent or buy, and who offers it. */
export function EquipmentCard({ item, showSeller = true, children }: EquipmentCardProps) {
  const { t, lang, rt } = useI18n();
  const [shown, setShown] = useState(0);
  const photo = item.photos[Math.min(shown, item.photos.length - 1)];
  const type = findItem('equipment_types', item.equipmentType);
  const money = (rupees: number) => `₹${formatMoneyShort(rupees, lang, t)}`;

  return (
    <article className={`machine ${item.status !== 'active' ? 'machine--inactive' : ''}`}>
      <div className="machine__media">
        {photo ? (
          <img src={api.mediaUrl(photo.url) ?? undefined} alt={item.title} />
        ) : (
          <span className="machine__placeholder" aria-hidden="true">
            🚜
          </span>
        )}
        {item.photos.length > 1 ? (
          <div className="machine__thumbs">
            {item.photos.map((file, index) => (
              <button
                key={file.id}
                type="button"
                className={`machine__thumb ${index === shown ? 'machine__thumb--on' : ''}`}
                onClick={() => setShown(index)}
                aria-label={`${index + 1}`}
              >
                <img src={api.mediaUrl(file.url) ?? undefined} alt="" />
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="machine__body">
        <header className="machine__head">
          <div>
            <h3 className="machine__title">{item.title}</h3>
            <p className="machine__place">
              {rt(type)}
              {item.place ? <span className="muted"> · {item.place}</span> : null}
            </p>
          </div>
          <div className="request__badges">
            {item.forRent ? <span className="badge">{t('equipment.forRent')}</span> : null}
            {item.forSale ? <span className="badge badge--export">{t('equipment.forSale')}</span> : null}
            {item.status !== 'active' ? (
              <span className="badge badge--muted">{t(`equipment.status.${item.status}`)}</span>
            ) : null}
            {item.origin === 'demo' ? <span className="badge badge--sample">{t('card.sample')}</span> : null}
          </div>
        </header>
        {item.introVideo ? <VideoPlayer video={item.introVideo} title={item.title} compact /> : null}

        <dl className="request__figures">
          {item.forRent && item.rentRate ? (
            <div>
              <dt>{t('equipment.rent')}</dt>
              <dd className="request__figure request__figure--lead">
                {money(item.rentRate)}{' '}
                <span className="small muted">{rt(findItem('rent_units', item.rentUnit))}</span>
              </dd>
            </div>
          ) : null}
          {item.forSale && item.salePrice ? (
            <div>
              <dt>{t('equipment.price')}</dt>
              <dd className="request__figure request__figure--lead">{money(item.salePrice)}</dd>
            </div>
          ) : null}
          <div>
            <dt>{t('machineForm.condition')}</dt>
            <dd className="request__figure">{rt(findItem('equipment_conditions', item.condition))}</dd>
          </div>
          <div>
            <dt>{t('enquiry.quantity')}</dt>
            <dd className="request__figure">{t('equipment.available', { n: formatNumber(item.quantity, lang) })}</dd>
          </div>
        </dl>

        <div className="request__tags">
          {item.yearMade ? <span className="tag">{t('equipment.made', { year: item.yearMade })}</span> : null}
          {item.brand ? <span className="tag">{[item.brand, item.model].filter(Boolean).join(' ')}</span> : null}
          {item.withOperator ? <span className="tag tag--strong">👷 {t('equipment.withOperator')}</span> : null}
          {item.delivery ? <span className="tag tag--strong">🚚 {t('equipment.delivery')}</span> : null}
        </div>

        {item.description ? <p className="request__summary">{item.description}</p> : null}
        {showSeller ? <PartyLine party={item.seller} /> : null}
        {children}
      </div>
    </article>
  );
}

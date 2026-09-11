import { useState } from 'react';
import type { Equipment } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate } from '../lib/format';
import { useProfile } from '../lib/profile';
import { useSharing } from '../lib/sharing';
import { AskPartnerDialog } from './AskPartnerDialog';
import { EnquiryDialog } from './EnquiryDialog';
import { MessageLink } from './MessageLink';
import { ContactLine } from './RequestCard';
import { RateBox } from './Stars';

/**
 * What someone other than the seller can do with a machine: ask to rent it,
 * ask to buy it, or ask to become the seller's partner. Each first makes sure
 * the asker's own profile is shared, since the seller must see who is asking.
 */
export function EquipmentActions({ item, onChanged }: { item: Equipment; onChanged: () => void }) {
  const { t, lang } = useI18n();
  const { profile } = useProfile();
  const { ensureOnline } = useSharing();
  const [dialog, setDialog] = useState<'rent' | 'buy' | 'partner' | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!profile || item.isMine) return null;
  const enquiry = item.myEnquiry;
  const partnership = item.myPartnership;
  const canPartner = profile.segment === 'farmer' || profile.segment.startsWith('partner_');
  const available = item.status === 'active';

  const open = async (next: 'rent' | 'buy' | 'partner') => {
    setError(null);
    try {
      if (await ensureOnline()) setDialog(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const withdraw = async () => {
    if (!enquiry) return;
    try {
      await api.respondToEnquiry(enquiry.id, 'withdrawn');
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const markDone = async () => {
    if (!enquiry || !window.confirm(t('enquiry.confirmDone'))) return;
    try {
      await api.respondToEnquiry(enquiry.id, 'completed');
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const connected =
    enquiry?.status === 'accepted' || enquiry?.status === 'completed' || partnership?.status === 'active';
  const sellerName = item.seller.organisationName || item.seller.displayName;

  return (
    <div className="request__respond">
      {enquiry ? (
        <p className="request__mine">
          <span className={`badge badge--status-${enquiry.status}`}>
            {t('equipment.yourEnquiry', { status: t(`interestStatus.${enquiry.status}`) })}
          </span>{' '}
          <span className="muted small">
            {t(`enquiry.kind.${enquiry.kind}`)}
            {enquiry.startDate && enquiry.endDate
              ? ` · ${t('enquiry.dates', {
                  from: formatDate(enquiry.startDate, lang),
                  to: formatDate(enquiry.endDate, lang),
                })}`
              : ''}
          </span>
        </p>
      ) : null}
      {enquiry?.status === 'accepted' ? (
        <div className="request__actions">
          <button type="button" className="button button--small" onClick={markDone}>
            ✅ {t(enquiry.kind === 'buy' ? 'enquiry.markDoneBuy' : 'enquiry.markDoneRent')}
          </button>
          <span className="muted small">{t('enquiry.doneHint')}</span>
        </div>
      ) : null}
      {enquiry && (enquiry.canRate || enquiry.myRating) ? (
        <RateBox
          contextType="enquiry"
          contextId={enquiry.id}
          myRating={enquiry.myRating}
          title={t('rating.rateThem', { name: sellerName })}
          onRated={onChanged}
        />
      ) : null}
      {partnership ? (
        <p className="request__mine">
          <span className={`badge ${partnership.status === 'active' ? 'badge--status-accepted' : 'badge--status-sent'}`}>
            {t('equipment.partnershipStatus', { status: t(`partners.status.${partnership.status}`) })}
          </span>
        </p>
      ) : null}

      {connected ? (
        <>
          <p className="callout callout--info">{t('equipment.accepted')}</p>
          <ContactLine party={item.seller} />
        </>
      ) : null}
      {item.myEnquiry || partnership ? (
        <div className="actions">
          <MessageLink party={item.seller} className="button button--small button--ghost" />
        </div>
      ) : null}
      {connected ? null : (
        <p className="muted small">{t('equipment.contactHidden')}</p>
      )}

      {error ? <p className="callout callout--error">{error}</p> : null}

      <div className="request__actions">
        {available && item.forRent ? (
          <button type="button" className="button button--primary button--small" onClick={() => open('rent')}>
            {t('equipment.askRent')}
          </button>
        ) : null}
        {available && item.forSale ? (
          <button type="button" className="button button--primary button--small" onClick={() => open('buy')}>
            {t('equipment.askBuy')}
          </button>
        ) : null}
        {canPartner && !partnership ? (
          <button type="button" className="button button--small" onClick={() => open('partner')}>
            🤝 {t('equipment.becomePartner')}
          </button>
        ) : null}
        {enquiry && (enquiry.status === 'sent' || enquiry.status === 'accepted') ? (
          <button type="button" className="button button--ghost button--small" onClick={withdraw}>
            {t('browse.withdraw')}
          </button>
        ) : null}
      </div>

      {dialog === 'rent' || dialog === 'buy' ? (
        <EnquiryDialog
          item={item}
          kind={dialog}
          onClose={() => setDialog(null)}
          onSent={() => {
            setDialog(null);
            onChanged();
          }}
        />
      ) : null}
      {dialog === 'partner' ? (
        <AskPartnerDialog
          seller={item.seller}
          onClose={() => setDialog(null)}
          onSent={() => {
            setDialog(null);
            onChanged();
          }}
        />
      ) : null}
    </div>
  );
}

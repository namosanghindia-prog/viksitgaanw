import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { Enquiry, Equipment } from '@viksitgaanw/shared';

import { EquipmentCard } from '../components/EquipmentCard';
import { PhotoButton } from '../components/PhotoButton';
import { MessageLink } from '../components/MessageLink';
import { ContactLine, PartyLine } from '../components/RequestCard';
import { ShareControl } from '../components/ShareControl';
import { RateBox } from '../components/Stars';
import { VideoField } from '../components/Video';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate } from '../lib/format';
import { useAsync } from '../lib/hooks';

/**
 * A seller's own machines: pictures, sharing, and the enquiries that came in.
 * Agreeing to an enquiry is the step that hands over phone numbers, so it
 * asks first.
 */
export function MyMachinesPage() {
  const { t } = useI18n();
  const listings = useAsync((signal) => api.myEquipment(signal), []);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      listings.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const rows = listings.data ?? [];

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('myMachines.title')}</h2>
          <p className="page__subtitle">{t('myMachines.lede')}</p>
        </div>
        <Link className="button button--primary" to="/machines/new">
          + {t('myMachines.add')}
        </Link>
      </header>

      {listings.loading ? <p className="muted">{t('common.loading')}</p> : null}
      {error ? <p className="callout callout--error">{error}</p> : null}

      {!listings.loading && rows.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('myMachines.empty')}</p>
          <Link className="button button--primary" to="/machines/new">
            {t('myMachines.add')}
          </Link>
        </div>
      ) : null}

      <div className="requests">
        {rows.map((item) => (
          <EquipmentCard key={item.id} item={item} showSeller={false}>
            <ShareControl
              visibility={item.visibility}
              sharedAt={item.sharedAt}
              onShare={() => api.shareEquipment(item.id)}
              onUnshare={() => api.unshareEquipment(item.id)}
              onChanged={listings.reload}
            />
            <VideoField
              target="machine"
              entityId={item.id}
              video={item.introVideo}
              label={t('video.machine')}
              onChanged={listings.reload}
              showPlayer={false}
            />
            <div className="request__actions">
              <Link className="button button--small" to={`/machines/${item.id}/edit`}>
                {t('common.edit')}
              </Link>
              {item.photos.length < 4 ? (
                <PhotoButton label={t('photo.addMachine')} onPick={(file) => run(() => api.addEquipmentPhoto(item.id, file))} />
              ) : null}
              {item.photos.map((photo, index) => (
                <button
                  key={photo.id}
                  type="button"
                  className="button button--ghost button--small"
                  onClick={() => run(() => api.deleteEquipmentPhoto(item.id, photo.id))}
                >
                  ✕ {t('photo.remove')} {index + 1}
                </button>
              ))}
              <button
                type="button"
                className="button button--danger button--small"
                onClick={() => {
                  if (window.confirm(t('myMachines.confirmDelete'))) void run(() => api.deleteEquipment(item.id));
                }}
              >
                {t('common.delete')}
              </button>
            </div>
            <Enquiries
              item={item}
              onAnswer={(enquiry, status) => run(() => api.respondToEnquiry(enquiry.id, status))}
              onRated={listings.reload}
            />
          </EquipmentCard>
        ))}
      </div>
    </div>
  );
}

function Enquiries({
  item,
  onAnswer,
  onRated,
}: {
  item: Equipment;
  onAnswer: (enquiry: Enquiry, status: 'accepted' | 'declined' | 'completed') => void;
  onRated: () => void;
}) {
  const { t, lang } = useI18n();
  return (
    <section className="answers">
      <h4 className="answers__title">{t('myMachines.enquiries', { n: item.enquiries.length })}</h4>
      {item.enquiries.length === 0 ? <p className="muted small">{t('myMachines.noEnquiries')}</p> : null}
      <ul className="answers__list">
        {item.enquiries.map((enquiry) => (
          <li key={enquiry.id} className={`answer answer--${enquiry.status}`}>
            <PartyLine party={enquiry.enquirer} />
            <p className="answer__offer">
              <strong>{t(`enquiry.kind.${enquiry.kind}`)}</strong> × {enquiry.quantity}
              {enquiry.startDate && enquiry.endDate
                ? ` · ${t('enquiry.dates', { from: formatDate(enquiry.startDate, lang), to: formatDate(enquiry.endDate, lang) })}`
                : ''}
              {enquiry.areaAcres ? ` · ${enquiry.areaAcres} ${t('enquiry.acres').split(' (')[0]}` : ''}
            </p>
            {enquiry.message ? <blockquote className="answer__message">{enquiry.message}</blockquote> : null}
            <ContactLine party={enquiry.enquirer} />
            <div className="answer__foot">
              <span className={`badge badge--status-${enquiry.status}`}>{t(`interestStatus.${enquiry.status}`)}</span>
              <MessageLink party={enquiry.enquirer} className="button button--small button--ghost" />
              {enquiry.status === 'sent' ? (
                <span className="answer__actions">
                  <button
                    type="button"
                    className="button button--primary button--small"
                    onClick={() => {
                      const name = enquiry.enquirer.organisationName || enquiry.enquirer.displayName;
                      if (window.confirm(t('myMachines.confirmAgree', { name }))) onAnswer(enquiry, 'accepted');
                    }}
                  >
                    {t('myMachines.agree')}
                  </button>
                  <button type="button" className="button button--ghost button--small" onClick={() => onAnswer(enquiry, 'declined')}>
                    {t('requests.decline')}
                  </button>
                </span>
              ) : null}
              {enquiry.status === 'accepted' ? (
                <span className="answer__actions">
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() => {
                      if (window.confirm(t('enquiry.confirmDone'))) onAnswer(enquiry, 'completed');
                    }}
                  >
                    ✅ {t(enquiry.kind === 'buy' ? 'enquiry.markDoneBuy' : 'enquiry.markDoneRent')}
                  </button>
                </span>
              ) : null}
            </div>
            {enquiry.canRate || enquiry.myRating ? (
              <RateBox
                contextType="enquiry"
                contextId={enquiry.id}
                myRating={enquiry.myRating}
                title={t('rating.rateThem', { name: enquiry.enquirer.organisationName || enquiry.enquirer.displayName })}
                onRated={onRated}
              />
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

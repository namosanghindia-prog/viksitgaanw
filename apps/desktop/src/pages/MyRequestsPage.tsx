import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { Interest, InvestmentRequest } from '@viksitgaanw/shared';
import { findItem } from '@viksitgaanw/shared';

import { InsuranceManager } from '../components/InsuranceManager';
import { MessageLink } from '../components/MessageLink';
import { ContactLine, PartyLine, RequestCard } from '../components/RequestCard';
import { ShareControl } from '../components/ShareControl';
import { VideoField } from '../components/Video';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate, formatMoneyShort } from '../lib/format';
import { useAsync } from '../lib/hooks';

/**
 * The farmer's requests, and every investor or partner who answered.
 *
 * Accepting is the one consequential act on this screen -- it hands the
 * farmer's phone number to someone -- so it asks first, and says so plainly.
 */
export function MyRequestsPage() {
  const { t, lang } = useI18n();
  const requests = useAsync((signal) => api.myRequests(signal), []);
  // Just published from the request form: offer promotion as the next step.
  const [searchParams] = useSearchParams();
  const published = searchParams.get('published');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = async (key: string, action: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await action();
      requests.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  const rows = requests.data ?? [];

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('requests.title')}</h2>
          <p className="page__subtitle">{t('requests.lede')}</p>
        </div>
      </header>

      {requests.loading ? <p className="muted">{t('common.loading')}</p> : null}
      {error ? <p className="callout callout--error">{error}</p> : null}

      {!requests.loading && rows.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('requests.empty')}</p>
          <p className="empty__help">{t('requests.emptyHelp')}</p>
          <Link className="button button--primary" to="/">
            {t('requests.goToLand')}
          </Link>
        </div>
      ) : null}

      <div className="requests">
        {/* The one just published first, where its promote offer is seen. */}
        {[...rows].sort((a, b) => Number(b.id === published) - Number(a.id === published)).map((request) => (
          <RequestCard key={request.id} request={request} showRequester={false}>
            <ShareControl
              visibility={request.visibility}
              sharedAt={request.sharedAt}
              onShare={() => api.shareRequest(request.id)}
              onUnshare={() => api.unshareRequest(request.id)}
              onChanged={requests.reload}
            />
            <VideoField
              target="request"
              entityId={request.id}
              video={request.introVideo}
              label={t('video.request')}
              hint={t('video.requestHint')}
              onChanged={requests.reload}
              showPlayer={false}
            />
            {request.visibility === 'offline' ? <p className="muted small">{t('share.draftNote')}</p> : null}
            {request.status === 'open' && request.visibility === 'online' ? (
              <div className={`promote-row ${published === request.id ? 'promote-row--new' : ''}`}>
                <span className="promote-row__text">
                  {request.featured && request.promotedUntil
                    ? `⭐ ${t('promote.featuredUntil', { date: formatDate(request.promotedUntil, lang) })}`
                    : published === request.id
                      ? `✓ ${t('promote.justPublished')}`
                      : t('promote.nudge')}
                </span>
                <Link className="button button--small button--promote" to={`/requests/${request.id}/promote`}>
                  ⭐ {request.featured ? t('promote.extend') : t('promote.button')}
                </Link>
              </div>
            ) : null}
            <section className="answers">
              <h4 className="answers__title">{t('insurance.requestTitle')}</h4>
              <InsuranceManager
                target={{ requestId: request.id }}
                scope="request"
                policies={request.insurance}
                required={request.insuranceRequired}
                recommended={request.insuranceRecommended}
                onChanged={requests.reload}
              />
            </section>
            <Answers
              request={request}
              busy={busy}
              onRespond={(interest, status) => {
                const who = interest.responder.organisationName || interest.responder.displayName;
                if (status === 'accepted' && !window.confirm(t('requests.confirmAccept', { name: who }))) return;
                void act(interest.id, () => api.respondToInterest(interest.id, status));
              }}
            />
            <div className="request__actions">
              {request.status === 'open' ? (
                <button
                  type="button"
                  className="button button--ghost button--small"
                  disabled={busy === request.id}
                  onClick={() => {
                    if (!window.confirm(t('requests.confirmClose'))) return;
                    void act(request.id, () => api.updateRequest(request.id, { status: 'closed' }));
                  }}
                >
                  {t('requests.close')}
                </button>
              ) : (
                <button
                  type="button"
                  className="button button--ghost button--small"
                  disabled={busy === request.id}
                  onClick={() => act(request.id, () => api.updateRequest(request.id, { status: 'open' }))}
                >
                  {t('requests.reopen')}
                </button>
              )}
            </div>
          </RequestCard>
        ))}
      </div>
    </div>
  );
}

function Answers({
  request,
  busy,
  onRespond,
}: {
  request: InvestmentRequest;
  busy: string | null;
  onRespond: (interest: Interest, status: 'accepted' | 'declined') => void;
}) {
  const { t, lang, rt } = useI18n();

  if (request.interests.length === 0) {
    return <p className="muted small">{t('requests.noInterests')}</p>;
  }

  const anyAccepted = request.interests.some((interest) => interest.status === 'accepted');

  return (
    <section className="answers">
      <h4 className="answers__title">{t('requests.answers', { n: request.interests.length })}</h4>
      {anyAccepted ? <p className="callout callout--warn">{t('requests.safety')}</p> : null}
      <ul className="answers__list">
        {request.interests.map((interest) => (
          <li key={interest.id} className={`answer answer--${interest.status}`}>
            <PartyLine party={interest.responder} />
            <p className="answer__offer">
              <strong>{t('card.offered')}:</strong>{' '}
              {interest.kind === 'investment'
                ? [
                    interest.amountOffered ? `₹${formatMoneyShort(interest.amountOffered, lang, t)}` : null,
                    rt(findItem('investment_modes', interest.mode)),
                  ]
                    .filter(Boolean)
                    .join(' · ')
                : rt(findItem('partnership_types', interest.partnershipType))}
              <span className="muted small"> · {formatDate(interest.createdAt, lang)}</span>
            </p>
            {interest.message ? <blockquote className="answer__message">{interest.message}</blockquote> : null}
            <ContactLine party={interest.responder} />
            <div className="answer__foot">
              <span className={`badge badge--status-${interest.status}`}>
                {t(`interestStatus.${interest.status}`)}
              </span>
              <span className="answer__actions">
                <MessageLink party={interest.responder} className="button button--small button--ghost" />
                {interest.status === 'accepted' && interest.kind === 'investment' ? (
                  <Link className="button button--small button--primary" to={`/deals/new/${interest.id}`}>
                    📜 {t('deals.planOrOpen')}
                  </Link>
                ) : null}
              </span>
              {interest.status === 'sent' && request.status === 'open' ? (
                <span className="answer__actions">
                  <button
                    type="button"
                    className="button button--primary button--small"
                    disabled={busy === interest.id}
                    onClick={() => onRespond(interest, 'accepted')}
                  >
                    {t('requests.accept')}
                  </button>
                  <button
                    type="button"
                    className="button button--ghost button--small"
                    disabled={busy === interest.id}
                    onClick={() => onRespond(interest, 'declined')}
                  >
                    {t('requests.decline')}
                  </button>
                </span>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

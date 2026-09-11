import { useState } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import type { Deal, Interest, InvestmentRequest, ProfileCard } from '@viksitgaanw/shared';

import { DealPlanEditor } from '../components/DealPlanEditor';
import { PartyLine } from '../components/RequestCard';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatMoneyShort } from '../lib/format';
import { useAsync } from '../lib/hooks';
import { useProfile } from '../lib/profile';

interface Candidate {
  interest: Interest;
  request: InvestmentRequest;
  /** The other side: the investor for a farmer, the farmer for an investor. */
  other: ProfileCard;
}

/** Accepted investment offers the owner is part of: the ones a deal can be planned for. */
function useCandidates() {
  const { profile } = useProfile();
  const farmer = profile?.segment === 'farmer';
  return useAsync<Candidate[]>(
    async (signal) => {
      if (farmer) {
        const requests = await api.myRequests(signal);
        return requests.flatMap((request) =>
          request.interests
            .filter((interest) => interest.status === 'accepted' && interest.kind === 'investment')
            .map((interest) => ({ interest, request, other: interest.responder })),
        );
      }
      const answered = await api.myInterests(signal);
      return answered
        .filter((request) => request.myInterest?.status === 'accepted' && request.myInterest.kind === 'investment')
        .map((request) => ({ interest: request.myInterest!, request, other: request.requester }));
    },
    [farmer],
    { enabled: Boolean(profile) },
  );
}

export function dealStatusBadge(status: Deal['status']) {
  return {
    drafting: 'badge--status-sent',
    active: 'badge--status-accepted',
    disputed: 'badge--status-declined',
    completed: 'badge--status-accepted',
    cancelled: 'badge--status-withdrawn',
  }[status];
}

/** Deals in progress and done, and accepted offers waiting for a plan. */
export function DealsPage() {
  const { t, lang } = useI18n();
  const deals = useAsync((signal) => api.deals(signal), []);
  const candidates = useCandidates();
  const planned = new Set((deals.data ?? []).map((deal) => deal.interestId));
  const waiting = (candidates.data ?? []).filter((candidate) => !planned.has(candidate.interest.id));
  const rows = deals.data ?? [];
  const money = (rupees: number) => `₹${formatMoneyShort(rupees, lang, t)}`;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('deals.title')}</h2>
          <p className="page__subtitle">{t('deals.lede')}</p>
        </div>
      </header>

      {waiting.length > 0 ? (
        <section className="card">
          <h3 className="card__title">{t('deals.ready')}</h3>
          <ul className="answers__list">
            {waiting.map(({ interest, request, other }) => (
              <li key={interest.id} className="answer">
                <PartyLine party={other} />
                <p className="answer__offer">
                  <strong>{request.title}</strong>
                  {interest.amountOffered ? <span className="muted"> · {money(interest.amountOffered)}</span> : null}
                </p>
                <div className="answer__foot">
                  <Link className="button button--primary button--small" to={`/deals/new/${interest.id}`}>
                    {t('deals.plan')}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {deals.loading && !deals.data ? <p className="muted">{t('common.loading')}</p> : null}
      {!deals.loading && rows.length === 0 && waiting.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('deals.empty')}</p>
        </div>
      ) : null}

      <div className="requests">
        {rows.map((deal) => {
          const other = deal.iAm === 'farmer' ? deal.investor : deal.farmer;
          const share = deal.amountTotal > 0 ? Math.round((deal.amountReleased / deal.amountTotal) * 100) : 0;
          return (
            <Link key={deal.id} to={`/deals/${deal.id}`} className="request deal-card">
              <header className="request__head">
                <div className="request__heading">
                  <h3 className="request__title">{deal.requestTitle}</h3>
                  <p className="request__place">{t('deals.with', { name: other.organisationName || other.displayName })}</p>
                </div>
                <span className={`badge ${dealStatusBadge(deal.status)}`}>{t(`dealStatus.${deal.status}`)}</span>
              </header>
              <div className="progress" aria-label={`${share}%`}>
                <span className="progress__bar" style={{ width: `${share}%` }} />
              </div>
              <p className="muted small">
                {t('deals.released', { released: money(deal.amountReleased), total: money(deal.amountTotal) })}
              </p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

/** Draw up the first plan for an accepted offer; an existing deal opens instead. */
export function DealPlanPage() {
  const { interestId = '' } = useParams();
  const { t } = useI18n();
  const navigate = useNavigate();
  const deals = useAsync((signal) => api.deals(signal), []);
  const candidates = useCandidates();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const existing = deals.data?.find((deal) => deal.interestId === interestId);
  if (existing) return <Navigate to={`/deals/${existing.id}`} replace />;
  if (deals.loading || candidates.loading) return <p className="page muted">{t('common.loading')}</p>;

  const candidate = candidates.data?.find((entry) => entry.interest.id === interestId);
  if (!candidate) {
    return (
      <div className="page">
        <p className="callout callout--error">{t('deals.notReady')}</p>
        <Link to="/deals">← {t('deal.back')}</Link>
      </div>
    );
  }

  return (
    <div className="page page--narrow">
      <p>
        <Link to="/deals">← {t('deal.back')}</Link>
      </p>
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('dealPlan.title')}</h2>
          <p className="page__subtitle">{candidate.request.title}</p>
        </div>
      </header>
      <PartyLine party={candidate.other} />
      {error ? <p className="callout callout--error">{error}</p> : null}
      <DealPlanEditor
        offered={candidate.interest.amountOffered}
        busy={busy}
        submitLabel={t('dealPlan.save')}
        initialMilestones={
          candidate.interest.amountOffered
            ? [{ title: t('dealPlan.firstStage'), amount: candidate.interest.amountOffered }]
            : undefined
        }
        onSubmit={async (plan) => {
          setBusy(true);
          setError(null);
          try {
            const deal = await api.createDeal({ interestId, ...plan });
            navigate(`/deals/${deal.id}`, { replace: true });
          } catch (cause) {
            setError(cause instanceof Error ? cause.message : String(cause));
            setBusy(false);
          }
        }}
      />
    </div>
  );
}

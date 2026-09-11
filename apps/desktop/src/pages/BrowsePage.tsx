import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { InvestmentRequest, Seeking } from '@viksitgaanw/shared';
import { REFERENCE } from '@viksitgaanw/shared';

import { InterestDialog } from '../components/InterestDialog';
import { MessageLink } from '../components/MessageLink';
import { Picker } from '../components/Picker';
import { ContactLine, RequestCard } from '../components/RequestCard';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useAsync } from '../lib/hooks';
import { useProfile } from '../lib/profile';
import { responderKinds } from '../lib/segments';
import { useSharing } from '../lib/sharing';

/**
 * Open requests the owner's segment has been shown, best match first.
 *
 * Investors and partners can answer; a government officer sees only the
 * requests in their own jurisdiction whose farmers asked for scheme help, and
 * cannot answer at all.
 */
export function BrowsePage() {
  const { t, rt } = useI18n();
  const { profile } = useProfile();
  const [stateCode, setStateCode] = useState<string | null>(null);
  const [kind, setKind] = useState<string | null>(null);
  const [answering, setAnswering] = useState<{ request: InvestmentRequest; kind: Seeking } | null>(null);

  const states = useAsync((signal) => api.states(signal), []);
  const requests = useAsync(
    (signal) =>
      api.browseRequests({ stateCode: stateCode ?? undefined, kind: kind ?? undefined }, signal),
    [stateCode, kind],
  );

  const stateOptions = useMemo(
    () => (states.data ?? []).map((unit) => ({ value: unit.code, label: unit.name, sublabel: unit.nameLocal })),
    [states.data],
  );
  const kindOptions = useMemo(
    () => REFERENCE.opportunity_kinds.items.map((item) => ({ value: item.code, label: rt(item) })),
    [rt],
  );

  if (!profile) return null;
  const government = profile.segment === 'government';
  const kinds = responderKinds(profile);
  const rows = requests.data ?? [];

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{government ? t('browse.govTitle') : t('browse.title')}</h2>
          <p className="page__subtitle">{government ? t('browse.govLede') : t('browse.lede')}</p>
        </div>
      </header>

      {profile.segment === 'investor_international' ? (
        <p className="callout callout--warn">{t('browse.fdiReminder')}</p>
      ) : null}

      <div className="filters">
        <Picker
          label={t('location.state')}
          placeholder={t('browse.allStates')}
          options={stateOptions}
          value={stateCode}
          onChange={setStateCode}
          loading={states.loading}
          allowClear
        />
        <Picker
          label={t('browse.sector')}
          placeholder={t('browse.allSectors')}
          options={kindOptions}
          value={kind}
          onChange={setKind}
          allowClear
        />
      </div>

      {requests.loading ? <p className="muted">{t('common.loading')}</p> : null}
      {requests.error ? <p className="callout callout--error">{requests.error.message}</p> : null}

      {!requests.loading && !requests.error && rows.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('browse.empty')}</p>
          <p className="empty__help">{t('browse.emptyHelp')}</p>
          <code>python scripts/seed_demo_marketplace.py</code>
        </div>
      ) : null}

      <div className="requests">
        {rows.map((request) => (
          <RequestCard key={request.id} request={request}>
            {government ? null : (
              <ResponderActions
                request={request}
                kinds={kinds}
                onAnswer={(kind) => setAnswering({ request, kind })}
                onChanged={requests.reload}
              />
            )}
          </RequestCard>
        ))}
      </div>

      {answering ? (
        <InterestDialog
          request={answering.request}
          kind={answering.kind}
          onClose={() => setAnswering(null)}
          onSent={() => {
            setAnswering(null);
            requests.reload();
          }}
        />
      ) : null}
    </div>
  );
}

/**
 * What an investor or partner can do with one request, given their answer so
 * far. Answering needs the responder's own profile shared, so the farmer can
 * see who is offering; that is asked for on the way.
 */
export function ResponderActions({
  request,
  kinds,
  onAnswer,
  onChanged,
}: {
  request: InvestmentRequest;
  kinds: Seeking[];
  onAnswer: (kind: Seeking) => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const { ensureOnline } = useSharing();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mine = request.myInterest;
  const offerable = kinds.filter((kind) => request.seeking.includes(kind));
  const canAnswer = request.status === 'open' && offerable.length > 0;

  const answer = async (kind: Seeking) => {
    setError(null);
    try {
      if (await ensureOnline()) onAnswer(kind);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const withdraw = async () => {
    if (!mine) return;
    setBusy(true);
    setError(null);
    try {
      await api.respondToInterest(mine.id, 'withdrawn');
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="request__respond">
      {mine ? (
        <p className="request__mine">
          <span className={`badge badge--status-${mine.status}`}>
            {t('browse.yourAnswer', { status: t(`interestStatus.${mine.status}`) })}
          </span>
        </p>
      ) : null}

      {mine?.status === 'accepted' ? (
        <>
          <p className="callout callout--info">{t('interests.accepted')}</p>
          <ContactLine party={request.requester} />
        </>
      ) : mine ? null : (
        <p className="muted small">{t('card.contactHidden')}</p>
      )}

      {error ? <p className="callout callout--error">{error}</p> : null}

      <div className="request__actions">
        {canAnswer && (!mine || mine.status === 'sent' || mine.status === 'withdrawn')
          ? (mine && mine.status === 'sent' ? [mine.kind] : offerable).map((kind) => (
              <button
                key={kind}
                type="button"
                className="button button--primary button--small"
                onClick={() => answer(kind)}
              >
                {mine && mine.status === 'sent'
                  ? t('browse.changeOffer')
                  : kind === 'investment'
                    ? t('browse.showInterest')
                    : t('browse.offerPartnership')}
              </button>
            ))
          : null}
        {mine?.status === 'accepted' && mine.kind === 'investment' ? (
          <Link className="button button--primary button--small" to={`/deals/new/${mine.id}`}>
            📜 {t('deals.planOrOpen')}
          </Link>
        ) : null}
        {mine && mine.status !== 'withdrawn' ? (
          <MessageLink party={request.requester} className="button button--small button--ghost" />
        ) : null}
        {mine && (mine.status === 'sent' || mine.status === 'accepted') ? (
          <button type="button" className="button button--ghost button--small" onClick={withdraw} disabled={busy}>
            {t('browse.withdraw')}
          </button>
        ) : null}
      </div>
    </div>
  );
}

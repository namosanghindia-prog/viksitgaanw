import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { InvestmentRequest, InvestorListing } from '@viksitgaanw/shared';
import { findItem } from '@viksitgaanw/shared';

import { Picker } from '../components/Picker';
import { MessageLink } from '../components/MessageLink';
import { PartyLine } from '../components/RequestCard';
import { VideoPlayer } from '../components/Video';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatMoneyShort, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';

/**
 * Investors -- and companies that also invest -- who have shared their
 * profile, best match for the farmer's own projects first. A farmer can put
 * any of their shared projects in front of one, the way investors already
 * browse projects from their side.
 */
export function FindInvestorsPage() {
  const { t } = useI18n();
  const [stateCode, setStateCode] = useState<string | null>(null);
  const listings = useAsync((signal) => api.findInvestors(stateCode, signal), [stateCode]);
  const requests = useAsync((signal) => api.myRequests(signal), []);
  const states = useAsync((signal) => api.states(signal), []);

  const stateOptions = useMemo(
    () => (states.data ?? []).map((unit) => ({ value: unit.code, label: unit.name, sublabel: unit.nameLocal })),
    [states.data],
  );
  const stateNames = useMemo(
    () => Object.fromEntries((states.data ?? []).map((unit) => [unit.code, unit.name])),
    [states.data],
  );
  const shared = (requests.data ?? []).filter((r) => r.status === 'open' && r.visibility === 'online');
  const rows = listings.data ?? [];

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('investors.title')}</h2>
          <p className="page__subtitle">{t('investors.lede')}</p>
        </div>
        <Link className="button" to="/requests">
          {t('investors.myProjects')} ({(requests.data ?? []).length})
        </Link>
      </header>

      {requests.data && shared.length === 0 ? (
        <p className="callout callout--info">
          {t('investors.noProjects')} <Link to="/">{t('investors.makeRequest')}</Link>
        </p>
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
      </div>

      {listings.loading ? <p className="muted">{t('common.loading')}</p> : null}
      {listings.error ? <p className="callout callout--error">{listings.error.message}</p> : null}
      {!listings.loading && !listings.error && rows.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('investors.none')}</p>
          <p className="empty__help">{t('investors.noneHelp')}</p>
        </div>
      ) : null}

      <div className="requests">
        {rows.map((listing) => (
          <InvestorCard
            key={listing.profile.id}
            listing={listing}
            requests={shared}
            stateNames={stateNames}
            onSent={listings.reload}
          />
        ))}
      </div>
    </div>
  );
}

function InvestorCard({
  listing,
  requests,
  stateNames,
  onSent,
}: {
  listing: InvestorListing;
  requests: InvestmentRequest[];
  stateNames: Record<string, string>;
  onSent: () => void;
}) {
  const { t, rt, lang } = useI18n();
  const [sending, setSending] = useState(false);
  const [choice, setChoice] = useState<string>(listing.sendableRequestIds[0] ?? '');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // After a send the list shrinks: never keep pointing at a project already sent.
  const selected = listing.sendableRequestIds.includes(choice) ? choice : (listing.sendableRequestIds[0] ?? '');
  const title = (id: string) => requests.find((r) => r.id === id)?.title ?? '';
  const amount = (value: number) =>
    listing.currency === 'USD' ? `$${formatNumber(value, lang, 0)}` : `₹${formatMoneyShort(value, lang, t)}`;
  const ticket =
    listing.ticketMin == null && listing.ticketMax == null
      ? t('investors.anyAmount')
      : [listing.ticketMin, listing.ticketMax].map((v) => (v == null ? '…' : amount(v))).join(' – ');

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.sendProject(listing.profile.id, selected, note.trim() || null);
      setSending(false);
      setNote('');
      onSent();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="request investor-card">
      <header className="request__head">
        <div className="request__heading">
          <PartyLine party={listing.profile} />
          {/* Free once there is something between you; otherwise one message from a pack. */}
          <div className="request__actions">
            <MessageLink party={listing.profile} />
          </div>
        </div>
        {listing.fit ? (
          <span className={`badge badge--fit ${listing.fit.score >= 70 ? 'badge--fit-good' : ''}`}>
            {t('investors.match', { n: listing.fit.score })}
          </span>
        ) : null}
      </header>
      {listing.fit && listing.fit.reasons.length ? (
        <p className="request__fit">✓ {listing.fit.reasons.map((code) => t(`theirFit.${code}`)).join(' · ')}</p>
      ) : null}
      {listing.about ? <p>{listing.about}</p> : null}
      {listing.introVideo ? <VideoPlayer video={listing.introVideo} title={t('video.intro')} compact /> : null}

      <dl className="request__figures">
        <div>
          <dt>{t('investors.amount')}</dt>
          <dd className="request__figure">{ticket}</dd>
        </div>
        <div>
          <dt>{t('investors.states')}</dt>
          <dd>
            {listing.preferredStates.length
              ? listing.preferredStates.map((code) => stateNames[code] ?? code).join(', ')
              : t('investors.anywhere')}
          </dd>
        </div>
      </dl>
      <div className="request__tags">
        {listing.sectors.map((code) => (
          <span key={code} className="tag tag--strong">
            {rt(findItem('opportunity_kinds', code))}
          </span>
        ))}
        {listing.modes.map((code) => (
          <span key={code} className="tag">
            {rt(findItem('investment_modes', code))}
          </span>
        ))}
      </div>

      {listing.invitedRequestIds.length ? (
        <p className="muted small">
          📨 {t('investors.sentTo')}: {listing.invitedRequestIds.map(title).filter(Boolean).join(', ')}
        </p>
      ) : null}

      {listing.sendableRequestIds.length ? (
        sending ? (
          <div className="invite-form">
            <label className="field__label" htmlFor={`project-${listing.profile.id}`}>
              {t('investors.chooseProject')}
            </label>
            <select
              id={`project-${listing.profile.id}`}
              className="input"
              value={selected}
              onChange={(event) => setChoice(event.target.value)}
            >
              {listing.sendableRequestIds.map((id) => (
                <option key={id} value={id}>
                  {title(id)}
                </option>
              ))}
            </select>
            <textarea
              className="input input--textarea"
              rows={2}
              maxLength={1000}
              value={note}
              placeholder={t('investors.note')}
              onChange={(event) => setNote(event.target.value)}
            />
            <div className="request__actions">
              <button type="button" className="button button--primary button--small" disabled={busy || !selected} onClick={send}>
                📨 {busy ? t('common.saving') : t('investors.send')}
              </button>
              <button type="button" className="button button--ghost button--small" onClick={() => setSending(false)}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        ) : (
          <div className="request__actions">
            <button type="button" className="button button--primary button--small" onClick={() => setSending(true)}>
              📨 {t('investors.sendProject')}
            </button>
          </div>
        )
      ) : listing.answeredRequestIds.length ? (
        <p className="muted small">✓ {t('investors.answered')}</p>
      ) : requests.length > 0 && listing.invitedRequestIds.length === 0 ? (
        <p className="muted small">{t('investors.notShown')}</p>
      ) : null}
      {error ? <p className="field__error">{error}</p> : null}
    </article>
  );
}

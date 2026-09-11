import { useState } from 'react';
import type { Connection } from '@viksitgaanw/shared';

import { MessageLink } from '../components/MessageLink';
import { ContactLine, PartyLine } from '../components/RequestCard';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useAsync } from '../lib/hooks';
import { useInbox } from '../lib/inbox';
import { useProfile } from '../lib/profile';

/**
 * The people whose farm news the owner follows, and who follow theirs.
 *
 * Connections see each other's shared land and farm updates on the timeline,
 * can message, and see each other's phone number. People already working
 * together -- a deal, an accepted offer, a rental, a partnership, a group --
 * are listed as connected without having to ask.
 */
export function ConnectionsPage() {
  const { t } = useI18n();
  const { profile } = useProfile();
  const { refresh } = useInbox();
  const state = useAsync((signal) => api.connections(signal), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const data = state.data;

  const act = async (key: string, action: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await action();
      state.reload();
      refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  const linkText = (row: Connection) =>
    row.via === 'work' || row.links.length
      ? row.links.map((link) => t(`connect.link.${link}`)).join(' · ')
      : t('connect.viaRequest');

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('connect.title')}</h2>
          <p className="page__subtitle">{t('connect.lede')}</p>
        </div>
      </header>

      {profile?.visibility !== 'online' ? <p className="callout callout--warn">{t('connect.goOnline')}</p> : null}
      {error ? <p className="callout callout--error">{error}</p> : null}
      {state.loading && !data ? <p className="muted">{t('common.loading')}</p> : null}

      {data?.incoming.length ? (
        <section className="card">
          <h3 className="card__title">{t('connect.incoming', { n: data.incoming.length })}</h3>
          <ul className="answers__list">
            {data.incoming.map((row) => (
              <li key={row.id} className="answer answer--sent">
                <PartyLine party={{ ...row.other, connection: null }} />
                {row.message ? <blockquote className="answer__message">{row.message}</blockquote> : null}
                <div className="answer__foot">
                  <span className="answer__actions">
                    <button
                      type="button"
                      className="button button--primary button--small"
                      disabled={busy === row.id}
                      onClick={() => act(row.id!, () => api.answerConnection(row.id!, 'accepted'))}
                    >
                      ✓ {t('connect.accept')}
                    </button>
                    <button
                      type="button"
                      className="button button--ghost button--small"
                      disabled={busy === row.id}
                      onClick={() => act(row.id!, () => api.answerConnection(row.id!, 'declined'))}
                    >
                      {t('requests.decline')}
                    </button>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <h3 className="section__title">{t('connect.mine', { n: data?.connected.length ?? 0 })}</h3>
      {data && data.connected.length === 0 ? <p className="muted">{t('connect.none')}</p> : null}
      <ul className="answers__list">
        {data?.connected.map((row) => (
          <li key={row.other.id} className="answer answer--accepted">
            <PartyLine party={{ ...row.other, connection: null }} />
            <p className="muted small">{linkText(row)}</p>
            <ContactLine party={row.other} />
            <div className="answer__foot">
              <span className="answer__actions">
                <MessageLink party={row.other} className="button button--small" />
                {row.via === 'request' && row.id ? (
                  <button
                    type="button"
                    className="button button--ghost button--small"
                    disabled={busy === row.id}
                    onClick={() => {
                      const name = row.other.organisationName || row.other.displayName;
                      if (!window.confirm(t('connect.confirmRemove', { name }))) return;
                      void act(row.id!, () => api.removeConnection(row.id!));
                    }}
                  >
                    {t('connect.remove')}
                  </button>
                ) : null}
              </span>
            </div>
          </li>
        ))}
      </ul>

      {data?.outgoing.length ? (
        <>
          <h3 className="section__title">{t('connect.outgoing', { n: data.outgoing.length })}</h3>
          <ul className="answers__list">
            {data.outgoing.map((row) => (
              <li key={row.id} className="answer">
                <PartyLine party={{ ...row.other, connection: null }} />
                <div className="answer__foot">
                  <span className="badge badge--status-sent">{t('connect.sent')}</span>
                  <button
                    type="button"
                    className="button button--ghost button--small"
                    disabled={busy === row.id}
                    onClick={() => act(row.id!, () => api.removeConnection(row.id!))}
                  >
                    {t('connect.withdraw')}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {data?.suggestions.length ? (
        <>
          <h3 className="section__title">{t('connect.suggestions')}</h3>
          <p className="muted small">{t('connect.suggestionsHelp')}</p>
          <ul className="answers__list">
            {data.suggestions.map((party) => (
              <li key={party.id} className="answer">
                <PartyLine party={party} />
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

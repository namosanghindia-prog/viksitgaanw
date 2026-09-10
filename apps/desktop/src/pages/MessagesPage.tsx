import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import type { ProfileCard } from '@viksitgaanw/shared';

import { PartyLine } from '../components/RequestCard';
import { ReadAloud } from '../components/ReadAloud';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate } from '../lib/format';
import { useAsync } from '../lib/hooks';
import { useInbox } from '../lib/inbox';

/** Every conversation, most recent first. */
export function MessagesPage() {
  const { t, lang } = useI18n();
  const conversations = useAsync((signal) => api.conversations(signal), []);
  const rows = conversations.data ?? [];

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('messages.title')}</h2>
          <p className="page__subtitle">{t('messages.lede')}</p>
        </div>
      </header>

      {conversations.loading && !conversations.data ? <p className="muted">{t('common.loading')}</p> : null}
      {!conversations.loading && rows.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('messages.empty')}</p>
        </div>
      ) : null}

      <ul className="conversations">
        {rows.map((conversation) => (
          <li key={conversation.other.id}>
            <Link className="conversation" to={`/messages/${conversation.other.id}`}>
              <PartyLine party={conversation.other} />
              <div className="conversation__last">
                {conversation.lastMessage ? (
                  <>
                    <span className="muted small">
                      {conversation.lastMessage.mine ? `${t('messages.you')}: ` : ''}
                      {conversation.lastMessage.body.slice(0, 120)}
                    </span>
                    <span className="muted small"> · {formatDate(conversation.lastMessage.createdAt, lang)}</span>
                  </>
                ) : null}
                {conversation.unread > 0 ? <span className="count">{conversation.unread}</span> : null}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One conversation. Opening it marks what arrived as read. */
export function ThreadPage() {
  const { profileId = '' } = useParams();
  const location = useLocation();
  const { t, lang } = useI18n();
  const { refresh } = useInbox();
  const thread = useAsync((signal) => api.thread(profileId, signal), [profileId]);
  const conversations = useAsync((signal) => api.conversations(signal), [profileId]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  // A first message has no conversation yet: the page that linked here passes the card.
  const other =
    conversations.data?.find((conversation) => conversation.other.id === profileId)?.other ??
    (location.state as { party?: ProfileCard } | null)?.party ??
    null;
  const rows = thread.data ?? [];

  useEffect(() => {
    if (thread.data) refresh();
    bottom.current?.scrollIntoView({ block: 'end' });
  }, [thread.data, refresh]);

  const send = async () => {
    const body = draft.trim();
    if (!body) return;
    setBusy(true);
    setError(null);
    try {
      await api.sendMessage(profileId, body);
      setDraft('');
      thread.reload();
      conversations.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <p>
        <Link to="/messages">← {t('messages.back')}</Link>
      </p>
      {other ? <PartyLine party={other} /> : null}
      {thread.error ? <p className="callout callout--error">{thread.error.message}</p> : null}

      <div className="thread">
        {!thread.loading && rows.length === 0 ? <p className="muted">{t('messages.threadEmpty')}</p> : null}
        {rows.map((message) => (
          <div key={message.id} className={`bubble ${message.mine ? 'bubble--mine' : ''}`}>
            <p className="bubble__body">{message.body}</p>
            <p className="bubble__meta muted small">
              {formatDate(message.createdAt, lang)}
              {!message.mine ? <ReadAloud text={message.body} className="button button--ghost button--tiny" /> : null}
            </p>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <div className="composer">
        <textarea
          className="input input--textarea"
          rows={2}
          maxLength={4000}
          value={draft}
          placeholder={t('messages.placeholder')}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) void send();
          }}
        />
        <button type="button" className="button button--primary" disabled={busy || !draft.trim()} onClick={send}>
          {t('messages.send')}
        </button>
      </div>
      <p className="muted small">{t('messages.deliveryNote')}</p>
      {error ? <p className="callout callout--error">{error}</p> : null}
    </div>
  );
}

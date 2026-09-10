import { Link } from 'react-router-dom';

import { ReadAloud } from '../components/ReadAloud';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate } from '../lib/format';
import { useAsync } from '../lib/hooks';
import { useInbox } from '../lib/inbox';
import { describeNotification, noteIcon } from '../lib/notifications';

/** Everything that happened to the owner's projects, machines and deals. */
export function InboxPage() {
  const { t, rt, lang } = useI18n();
  const notes = useAsync((signal) => api.notifications(signal), []);
  const { refresh } = useInbox();
  const rows = notes.data ?? [];
  const unread = rows.filter((note) => !note.read);

  const markRead = async (ids: string[]) => {
    await api.markRead(ids);
    notes.reload();
    refresh();
  };

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('inbox.title')}</h2>
          <p className="page__subtitle">{t('inbox.lede')}</p>
        </div>
        {unread.length > 0 ? (
          <button type="button" className="button" onClick={() => markRead([])}>
            {t('inbox.markAll')}
          </button>
        ) : null}
      </header>

      {notes.loading && !notes.data ? <p className="muted">{t('common.loading')}</p> : null}
      {notes.error ? <p className="callout callout--error">{notes.error.message}</p> : null}
      {!notes.loading && rows.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('inbox.empty')}</p>
        </div>
      ) : null}

      <ul className="notes">
        {rows.map((note) => {
          const text = describeNotification(note, t, rt, lang);
          return (
            <li key={note.id} className={`note ${note.read ? '' : 'note--unread'}`}>
              <span className="note__icon" aria-hidden="true">
                {noteIcon(note.kind)}
              </span>
              <div className="note__main">
                <p className="note__text">{text}</p>
                <p className="muted small">{formatDate(note.createdAt, lang)}</p>
              </div>
              <div className="note__actions">
                <ReadAloud text={text} />
                {note.link ? (
                  <Link
                    className="button button--small button--primary"
                    to={note.link}
                    onClick={() => (note.read ? undefined : void markRead([note.id]))}
                  >
                    {t('inbox.open')}
                  </Link>
                ) : null}
                {!note.read ? (
                  <button type="button" className="button button--small button--ghost" onClick={() => markRead([note.id])}>
                    ✓
                  </button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

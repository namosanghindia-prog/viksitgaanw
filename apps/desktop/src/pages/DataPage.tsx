import { useRef, useState } from 'react';
import type { SyncStatus } from '@viksitgaanw/shared';

import { TextField } from '../components/TextField';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';
import { useInbox } from '../lib/inbox';
import { useProfile } from '../lib/profile';

const ERASE_PHRASE = 'DELETE MY DATA';

/**
 * The owner's data rights, in one place: keep a backup, restore one, take a
 * copy, erase everything -- and the optional sync that is the only way
 * anything leaves the device.
 */
export function DataPage() {
  const { t } = useI18n();
  return (
    <div className="page page--narrow">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('data.title')}</h2>
          <p className="page__subtitle">{t('data.lede')}</p>
        </div>
      </header>
      <SyncCard />
      <BackupCard />
      <ExportCard />
      <EraseCard />
    </div>
  );
}

function SyncCard() {
  const { t, lang } = useI18n();
  const { refresh } = useInbox();
  const status = useAsync((signal) => api.syncStatus(signal), []);
  const [local, setLocal] = useState<SyncStatus | null>(null);
  const [address, setAddress] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const current = local ?? status.data;
  const url = address ?? current?.serverUrl ?? '';

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h3 className="card__title">🔄 {t('sync.title')}</h3>
      <p>{t('sync.help')}</p>
      <p className="callout callout--warn">{t('sync.devNote')}</p>
      {current ? (
        <p>
          <strong>{current.enabled ? t('sync.on') : t('sync.off')}</strong>
          {current.enabled ? (
            <span className="muted">
              {' '}
              · {t('sync.pending', { n: current.pending })} ·{' '}
              {current.lastPullAt ? t('sync.last', { date: formatDate(current.lastPullAt, lang) }) : t('sync.never')}
            </span>
          ) : null}
        </p>
      ) : null}
      {current?.lastError ? <p className="callout callout--error">{t('sync.error', { error: current.lastError })}</p> : null}
      <TextField
        id="syncServer"
        label={t('sync.server')}
        value={url}
        onChange={setAddress}
        placeholder="http://127.0.0.1:8900"
        type="url"
      />
      <div className="actions">
        <button
          type="button"
          className="button button--primary"
          disabled={busy || !url.trim()}
          onClick={() =>
            run(async () => {
              setLocal(await api.configureSync(url.trim()));
              setAddress(null);
            })
          }
        >
          {current?.enabled ? t('common.save') : t('sync.enable')}
        </button>
        {current?.enabled ? (
          <>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  const result = await api.runSync();
                  setLocal(result.status);
                  if (result.errors.length) setError(result.errors.join('; '));
                  setMessage(t('sync.result', { pushed: result.pushed, pulled: result.pulled }));
                  refresh();
                })
              }
            >
              {busy ? t('common.loading') : t('sync.now')}
            </button>
            <button
              type="button"
              className="button button--ghost"
              disabled={busy}
              onClick={() => run(async () => setLocal(await api.configureSync(null)))}
            >
              {t('sync.disable')}
            </button>
          </>
        ) : null}
      </div>
      {message ? <p className="callout callout--info">{message}</p> : null}
      {error ? <p className="callout callout--error">{error}</p> : null}
    </section>
  );
}

function BackupCard() {
  const { t, lang } = useI18n();
  const backups = useAsync((signal) => api.backups(signal), []);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  return (
    <section className="card">
      <h3 className="card__title">💾 {t('backup.title')}</h3>
      <p>{t('backup.help')}</p>
      <div className="actions">
        <button
          type="button"
          className="button button--primary"
          disabled={busy}
          onClick={() =>
            run(async () => {
              await api.createBackup();
              backups.reload();
            })
          }
        >
          {busy ? t('common.saving') : t('backup.create')}
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".zip,application/zip"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            if (!window.confirm(t('backup.confirmRestore'))) {
              event.target.value = '';
              return;
            }
            void run(async () => {
              await api.restoreBackup(file);
              setMessage(t('backup.staged'));
            });
          }}
        />
        <button type="button" className="button" disabled={busy} onClick={() => fileInput.current?.click()}>
          {t('backup.restore')}
        </button>
      </div>
      <p className="muted small">{t('backup.restoreHelp')}</p>
      {message ? <p className="callout callout--info">{message}</p> : null}
      {error ? <p className="callout callout--error">{error}</p> : null}
      {backups.data && backups.data.length === 0 ? <p className="muted">{t('backup.none')}</p> : null}
      <ul className="reportlist">
        {(backups.data ?? []).map((backup) => (
          <li key={backup.name} className="reportlist__item">
            <span>
              {formatDate(backup.createdAt, lang)}
              <span className="muted small"> · {formatNumber(backup.sizeBytes / 1_048_576, lang, 1)} MB</span>
            </span>
            <a className="button button--small" href={api.backupUrl(backup)} target="_blank" rel="noreferrer">
              {t('backup.download')}
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ExportCard() {
  const { t } = useI18n();
  return (
    <section className="card">
      <h3 className="card__title">📦 {t('export.title')}</h3>
      <p>{t('export.help')}</p>
      <a className="button" href={api.myDataUrl()} target="_blank" rel="noreferrer">
        {t('export.download')}
      </a>
    </section>
  );
}

function EraseCard() {
  const { t } = useI18n();
  const { reload } = useProfile();
  const [phrase, setPhrase] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <section className="card card--danger">
      <h3 className="card__title">🗑 {t('erase.title')}</h3>
      <p>{t('erase.help')}</p>
      <TextField id="erasePhrase" label={t('erase.type', { phrase: ERASE_PHRASE })} value={phrase} onChange={setPhrase} />
      {error ? <p className="callout callout--error">{error}</p> : null}
      <button
        type="button"
        className="button button--danger"
        disabled={busy || phrase !== ERASE_PHRASE}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await api.eraseMyData(phrase);
            reload();
          } catch (cause) {
            setError(cause instanceof Error ? cause.message : String(cause));
            setBusy(false);
          }
        }}
      >
        {t('erase.button')}
      </button>
    </section>
  );
}

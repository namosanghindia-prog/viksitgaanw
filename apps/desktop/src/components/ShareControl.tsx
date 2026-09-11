import { useState } from 'react';
import type { Visibility } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { formatDate } from '../lib/format';
import { useSharing } from '../lib/sharing';

interface ShareControlProps {
  visibility: Visibility;
  sharedAt?: string | null;
  onShare: () => Promise<unknown>;
  onUnshare: () => Promise<unknown>;
  onChanged: () => void;
  /** Who sees the item once shared; land goes to connections only. */
  audience?: 'everyone' | 'connections';
}

/**
 * Where an item is -- only on this device, or on the common timeline -- and
 * the one button that moves it. The confirmation questions live in
 * useSharing, so every item asks them the same way.
 */
export function ShareControl({
  visibility,
  sharedAt,
  onShare,
  onUnshare,
  onChanged,
  audience = 'everyone',
}: ShareControlProps) {
  const { t, lang } = useI18n();
  const { shareItem, unshareItem } = useSharing();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<boolean>) => {
    setBusy(true);
    setError(null);
    try {
      if (await action()) onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const online = visibility === 'online';
  return (
    <div className="share">
      <span className={`share__state ${online ? 'share__state--online' : ''}`}>
        {online ? (audience === 'connections' ? '🤝' : '🌐') : '📱'}{' '}
        {online ? (audience === 'connections' ? t('share.withConnections') : t('share.online')) : t('share.offline')}
        {online && sharedAt ? <span className="muted small"> · {formatDate(sharedAt, lang)}</span> : null}
      </span>
      {online ? (
        <button
          type="button"
          className="button button--ghost button--small"
          disabled={busy}
          onClick={() => run(() => unshareItem(onUnshare))}
        >
          {t('share.takeOffline')}
        </button>
      ) : (
        <button
          type="button"
          className="button button--primary button--small"
          disabled={busy}
          onClick={() => run(() => shareItem(onShare, audience))}
        >
          {audience === 'connections' ? `🤝 ${t('share.toConnections')}` : `🌐 ${t('share.button')}`}
        </button>
      )}
      {error ? <p className="field__error">{error}</p> : null}
    </div>
  );
}

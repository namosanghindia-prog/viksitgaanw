import { useState } from 'react';
import type { ConnectionState, ProfileCard } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useSharing } from '../lib/sharing';

/**
 * Where the owner stands with someone, and the one step they can take:
 * connect, accept, or nothing while a request waits.
 */
export function ConnectButton({ party, onChanged }: { party: ProfileCard; onChanged?: () => void }) {
  const { t } = useI18n();
  const { ensureOnline } = useSharing();
  const [state, setState] = useState<ConnectionState | null>(party.connection);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!state) return null;

  const run = async (action: () => Promise<ConnectionState>) => {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      setState(next);
      if (next.state !== state.state) onChanged?.();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  if (state.state === 'connected') {
    return (
      <span className="badge badge--connected" title={state.via === 'work' ? t('connect.viaWork') : undefined}>
        ✓ {t('connect.connected')}
      </span>
    );
  }
  if (state.state === 'requested_by_me') {
    return <span className="badge badge--status-sent">{t('connect.sent')}</span>;
  }
  return (
    <span className="connect">
      <button
        type="button"
        className="button button--small button--primary"
        disabled={busy}
        onClick={() =>
          run(async () => {
            if (state.state === 'requested_by_them' && state.id) {
              await api.answerConnection(state.id, 'accepted');
              return { ...state, state: 'connected' };
            }
            if (!(await ensureOnline())) return state;
            const made = await api.askToConnect(party.id);
            return { state: made.status === 'accepted' ? 'connected' : 'requested_by_me', via: 'request', id: made.id };
          })
        }
      >
        {state.state === 'requested_by_them' ? `✓ ${t('connect.accept')}` : `+ ${t('connect.connect')}`}
      </button>
      {error ? <span className="field__error"> {error}</span> : null}
    </span>
  );
}

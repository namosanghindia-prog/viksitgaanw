import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { InboxCounts } from '@viksitgaanw/shared';

import { api } from './api';
import { useProfile } from './profile';

/** How often unread counts are re-read from the local service. */
const POLL_MS = 30_000;
/** How often a switched-on sync runs in the background. */
const SYNC_MS = 5 * 60_000;

interface InboxValue {
  counts: InboxCounts;
  refresh: () => void;
}

const InboxContext = createContext<InboxValue | null>(null);

/**
 * Unread notifications and messages for the top bar, and the background sync.
 *
 * Both only touch the local service. Sync reaches the network only when the
 * owner has switched it on with a server address; otherwise the call is
 * skipped and nothing leaves the device.
 */
export function InboxProvider({ children }: { children: ReactNode }) {
  const { profile } = useProfile();
  const [counts, setCounts] = useState<InboxCounts>({ notifications: 0, messages: 0 });
  const [nonce, setNonce] = useState(0);
  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!profile) return;
    let active = true;
    const load = () =>
      api
        .inboxCounts()
        .then((next) => {
          if (active) setCounts(next);
        })
        .catch(() => undefined);
    void load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [profile, nonce]);

  useEffect(() => {
    if (!profile) return;
    const tick = async () => {
      try {
        const status = await api.syncStatus();
        if (!status.enabled || !navigator.onLine) return;
        const result = await api.runSync();
        if (result.pulled > 0) refresh();
      } catch {
        // Offline or the server is down: the outbox keeps everything for next time.
      }
    };
    const timer = window.setInterval(tick, SYNC_MS);
    return () => window.clearInterval(timer);
  }, [profile, refresh]);

  const value = useMemo(() => ({ counts, refresh }), [counts, refresh]);
  return <InboxContext.Provider value={value}>{children}</InboxContext.Provider>;
}

export function useInbox(): InboxValue {
  const context = useContext(InboxContext);
  if (!context) throw new Error('useInbox must be used inside <InboxProvider>.');
  return context;
}

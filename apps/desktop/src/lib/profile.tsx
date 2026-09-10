import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import type { Profile } from '@viksitgaanw/shared';

import { api } from './api';
import { useAsync } from './hooks';

interface ProfileValue {
  /** This device's owner, or null before onboarding. */
  profile: Profile | null;
  loading: boolean;
  error: Error | null;
  reload: () => void;
}

const ProfileContext = createContext<ProfileValue | null>(null);

/**
 * Who this device belongs to.
 *
 * Loaded once at start-up and shared, because nearly every screen changes
 * with it: the navigation a farmer sees is not the one an investor sees.
 */
export function ProfileProvider({ children }: { children: ReactNode }) {
  const state = useAsync((signal) => api.profile(signal), []);

  const value = useMemo<ProfileValue>(
    () => ({
      profile: state.data ?? null,
      loading: state.loading,
      error: state.error,
      reload: state.reload,
    }),
    [state.data, state.loading, state.error, state.reload],
  );

  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>;
}

export function useProfile(): ProfileValue {
  const context = useContext(ProfileContext);
  if (!context) throw new Error('useProfile must be used inside <ProfileProvider>.');
  return context;
}

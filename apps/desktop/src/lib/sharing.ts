import { useCallback } from 'react';

import { useI18n } from '../i18n';
import { api } from './api';
import { useProfile } from './profile';

/**
 * The "Share online" rules, with the questions asked before each step.
 *
 * Nothing is shared without the person agreeing to it in words they can read,
 * and sharing a project or a machine always says plainly that the profile
 * card goes with it -- the backend refuses an item whose owner is invisible.
 */
export function useSharing() {
  const { t } = useI18n();
  const { profile, reload } = useProfile();

  /** Make sure the profile is online before acting on someone else's item. */
  const ensureOnline = useCallback(async (): Promise<boolean> => {
    if (!profile) return false;
    if (profile.visibility === 'online') return true;
    if (!window.confirm(t('share.confirmProfile'))) return false;
    await api.shareProfile();
    reload();
    return true;
  }, [profile, reload, t]);

  /** Share an item, and the profile with it if that is still offline. */
  const shareItem = useCallback(
    async (share: () => Promise<unknown>): Promise<boolean> => {
      if (!profile) return false;
      if (profile.visibility !== 'online') {
        if (!window.confirm(t('share.confirmItemAndProfile'))) return false;
        await api.shareProfile();
        reload();
      } else if (!window.confirm(t('share.confirmItem'))) {
        return false;
      }
      await share();
      return true;
    },
    [profile, reload, t],
  );

  const unshareItem = useCallback(
    async (unshare: () => Promise<unknown>): Promise<boolean> => {
      if (!window.confirm(t('share.confirmOffline'))) return false;
      await unshare();
      return true;
    },
    [t],
  );

  return { ensureOnline, shareItem, unshareItem };
}

import type { AppNotification, LanguageCode, ReferenceItem } from '@viksitgaanw/shared';
import { findItem } from '@viksitgaanw/shared';

import type { StringKey } from '../i18n';
import { formatDate } from './format';

/** Kinds the app has a sentence for; anything else reads as a generic change. */
const KNOWN = new Set([
  'interest_received',
  'interest_accepted',
  'interest_declined',
  'enquiry_received',
  'enquiry_accepted',
  'enquiry_declined',
  'partnership_requested',
  'partnership_answered',
  'dispute_opened',
  'dispute_updated',
  'rating_received',
  'group_join_requested',
  'group_join_answered',
  'deal_proposed',
  'deal_active',
  'deal_completed',
  'deal_disputed',
  'deal_cancelled',
  'milestone_submitted',
  'milestone_approved',
  'milestone_rejected',
  'message_received',
  'weather_alert',
  'insurance_expiring',
  'connection_requested',
  'connection_accepted',
  'land_shared',
  'update_posted',
  'project_invited',
  'video_ready',
  'enquiry_completed',
  'subscription_paid',
  'promotion_paid',
  'project_featured',
]);

export const NOTE_ICON: Record<string, string> = {
  interest_received: '💼',
  enquiry_received: '🚜',
  partnership_requested: '🤝',
  partnership_answered: '🤝',
  message_received: '💬',
  weather_alert: '🌧️',
  insurance_expiring: '🛡',
  rating_received: '★',
  dispute_opened: '⚠️',
  dispute_updated: '⚠️',
  group_join_requested: '👥',
  group_join_answered: '👥',
  connection_requested: '🤝',
  connection_accepted: '🤝',
  land_shared: '🌾',
  update_posted: '📣',
  project_invited: '📨',
  video_ready: '🎬',
  enquiry_completed: '✅',
  subscription_paid: '⭐',
  promotion_paid: '⭐',
  project_featured: '🔔',
};

/**
 * The sentence for a notification, in the reader's language.
 *
 * The backend stores only a kind and the names and figures that go in it, so
 * a notification written while the app was in English reads in Hindi later.
 */
export function describeNotification(
  note: AppNotification,
  t: (key: StringKey, vars?: Record<string, string | number>) => string,
  rt: (item: ReferenceItem | undefined) => string,
  lang: LanguageCode,
): string {
  const params: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(note.params)) {
    if (value !== null && value !== undefined) params[key] = value;
  }
  if (typeof params.date === 'string') params.date = formatDate(params.date, lang);
  if (note.kind === 'weather_alert' && typeof note.params.code === 'string') {
    params.what = t(`advice.${note.params.code}` as StringKey);
  }
  if (note.kind === 'insurance_expiring' && typeof note.params.category === 'string') {
    params.category = rt(findItem('insurance_types', note.params.category)) || note.params.category;
  }
  if (note.kind === 'enquiry_received') {
    params.kind = note.params.kind === 'buy' ? t('note.toBuy') : t('note.toRent');
  }
  if (!KNOWN.has(note.kind)) return t('note.generic');
  return t(`note.${note.kind}` as StringKey, params);
}

export function noteIcon(kind: string): string {
  if (NOTE_ICON[kind]) return NOTE_ICON[kind];
  if (kind.startsWith('deal_') || kind.startsWith('milestone_')) return '📜';
  if (kind.startsWith('interest_') || kind.startsWith('enquiry_')) return '✉️';
  return '🔔';
}

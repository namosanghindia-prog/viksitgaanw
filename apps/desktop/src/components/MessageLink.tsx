import { Link } from 'react-router-dom';
import type { ProfileCard } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';

/** "Message" -- opens the conversation with someone, even before the first message. */
export function MessageLink({ party, className = 'button button--small' }: { party: ProfileCard; className?: string }) {
  const { t } = useI18n();
  return (
    <Link className={className} to={`/messages/${party.id}`} state={{ party }}>
      💬 {t('messages.start')}
    </Link>
  );
}

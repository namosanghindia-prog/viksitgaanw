import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { InvestmentRequest } from '@viksitgaanw/shared';

import { InterestDialog } from '../components/InterestDialog';
import { RequestCard } from '../components/RequestCard';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useAsync } from '../lib/hooks';
import { useProfile } from '../lib/profile';
import { isInvestor } from '../lib/segments';
import { ResponderActions } from './BrowsePage';

/** Every request the owner has answered, with where each answer stands. */
export function MyInterestsPage() {
  const { t } = useI18n();
  const { profile } = useProfile();
  const requests = useAsync((signal) => api.myInterests(signal), []);
  const [answering, setAnswering] = useState<InvestmentRequest | null>(null);

  if (!profile) return null;
  const kind = isInvestor(profile.segment) ? 'investment' : 'partnership';
  const rows = requests.data ?? [];

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('interests.title')}</h2>
          <p className="page__subtitle">{t('interests.lede')}</p>
        </div>
      </header>

      {requests.loading ? <p className="muted">{t('common.loading')}</p> : null}

      {!requests.loading && rows.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('interests.empty')}</p>
          <Link className="button button--primary" to="/">
            {t('interests.browse')}
          </Link>
        </div>
      ) : null}

      <div className="requests">
        {rows.map((request) => (
          <RequestCard key={request.id} request={request}>
            <ResponderActions
              request={request}
              kind={kind}
              onAnswer={() => setAnswering(request)}
              onChanged={requests.reload}
            />
          </RequestCard>
        ))}
      </div>

      {answering ? (
        <InterestDialog
          request={answering}
          kind={kind}
          onClose={() => setAnswering(null)}
          onSent={() => {
            setAnswering(null);
            requests.reload();
          }}
        />
      ) : null}
    </div>
  );
}

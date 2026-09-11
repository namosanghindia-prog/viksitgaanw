import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { InvestmentRequest, ReferenceItem, Seeking } from '@viksitgaanw/shared';

import { ChoiceGroup } from '../components/ChoiceGroup';
import { EquipmentActions } from '../components/EquipmentActions';
import { EquipmentCard } from '../components/EquipmentCard';
import { InterestDialog } from '../components/InterestDialog';
import { Picker } from '../components/Picker';
import { RequestCard } from '../components/RequestCard';
import { LandShareCard, UpdateCard, UpdateComposer } from '../components/SocialCards';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate } from '../lib/format';
import { useAsync } from '../lib/hooks';
import { useProfile } from '../lib/profile';
import { responderKinds } from '../lib/segments';
import { ResponderActions } from './BrowsePage';

type Filter = 'all' | 'project' | 'equipment' | 'updates';

/**
 * The common timeline: farm projects and machines people have shared online,
 * and the land and farm updates of the owner's connections, newest first --
 * with the same actions as their own pages so nobody has to go looking
 * elsewhere to answer something they have just read.
 */
const ICON: Record<string, string> = { project: '🌱', equipment: '🚜', land: '🌾', update: '📣' };

export function TimelinePage() {
  const { t, lang } = useI18n();
  const { profile } = useProfile();
  const [filter, setFilter] = useState<Filter>('all');
  const [stateCode, setStateCode] = useState<string | null>(null);
  const [answering, setAnswering] = useState<{ request: InvestmentRequest; kind: Seeking } | null>(null);

  const states = useAsync((signal) => api.states(signal), []);
  const items = useAsync(
    (signal) =>
      api.timeline({ kind: filter === 'all' ? undefined : filter, stateCode: stateCode ?? undefined }, signal),
    [filter, stateCode],
  );
  // The owner's own plots shared with connections, to post an update about.
  const myLands = useAsync(
    async (signal) => (await api.listParcels(signal)).filter((parcel) => parcel.shareVisibility === 'online'),
    [],
    { enabled: profile?.segment === 'farmer' },
  );

  const filterItems = useMemo<ReferenceItem[]>(
    () =>
      (
        [
          ['all', 'timeline.all'],
          ['project', 'timeline.projects'],
          ['equipment', 'timeline.machines'],
          ['updates', 'timeline.connections'],
        ] as const
      ).map(([code, key]) => ({ code, label: { en: t(key), hi: t(key) } })),
    [t],
  );
  const stateOptions = useMemo(
    () => (states.data ?? []).map((unit) => ({ value: unit.code, label: unit.name, sublabel: unit.nameLocal })),
    [states.data],
  );

  if (!profile) return null;
  const kinds = responderKinds(profile);
  const rows = items.data ?? [];

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('timeline.title')}</h2>
          <p className="page__subtitle">{t('timeline.lede')}</p>
        </div>
      </header>

      {profile.visibility !== 'online' ? (
        <p className="callout callout--warn">
          {t('share.profileNote')} <Link to="/profile">{t('nav.profile')}</Link>
        </p>
      ) : null}

      {profile.visibility === 'online' ? (
        <UpdateComposer lands={myLands.data ?? []} onPosted={items.reload} />
      ) : null}

      <div className="filters">
        <ChoiceGroup label="" items={filterItems} value={filter} onChange={(value) => setFilter((value as Filter) ?? 'all')} />
        <Picker label={t('location.state')} placeholder={t('browse.allStates')} options={stateOptions} value={stateCode} onChange={setStateCode} loading={states.loading} allowClear />
      </div>

      {items.loading ? <p className="muted">{t('common.loading')}</p> : null}
      {items.error ? <p className="callout callout--error">{items.error.message}</p> : null}

      {!items.loading && !items.error && rows.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('timeline.empty')}</p>
          <p className="empty__help">{t('browse.emptyHelp')}</p>
          <code>python scripts/seed_demo_marketplace.py</code>
        </div>
      ) : null}

      <div className="requests">
        {rows.map((item) => (
          <div key={`${item.type}-${item.id}`} className="timeline__item">
            <p className="timeline__when">
              {ICON[item.type]}{' '}
              {item.sharedAt ? t('timeline.sharedOn', { date: formatDate(item.sharedAt, lang) }) : null}
              {item.land ? <span className="badge badge--connected">🤝 {t('timeline.forConnections')}</span> : null}
              {(item.project?.isMine || item.equipment?.isMine || item.land?.isMine || item.update?.isMine) ? (
                <span className="badge badge--status-accepted"> {t('timeline.yours')}</span>
              ) : null}
            </p>
            {item.project ? (
              <RequestCard request={item.project} showRequester={!item.project.isMine}>
                {item.project.isMine ? (
                  <Link className="button button--small" to="/requests">
                    {t('nav.findInvestors')}
                  </Link>
                ) : kinds.length ? (
                  <ResponderActions
                    request={item.project}
                    kinds={kinds}
                    onAnswer={(kind) => setAnswering({ request: item.project!, kind })}
                    onChanged={items.reload}
                  />
                ) : null}
              </RequestCard>
            ) : null}
            {item.equipment ? (
              <EquipmentCard item={item.equipment} showSeller={!item.equipment.isMine}>
                {item.equipment.isMine ? (
                  <Link className="button button--small" to="/my-machines">
                    {t('nav.myMachines')}
                  </Link>
                ) : (
                  <EquipmentActions item={item.equipment} onChanged={items.reload} />
                )}
              </EquipmentCard>
            ) : null}
            {item.land ? (
              <LandShareCard land={item.land}>
                {item.land.isMine ? (
                  <Link className="button button--small" to="/">
                    {t('nav.myLand')}
                  </Link>
                ) : null}
              </LandShareCard>
            ) : null}
            {item.update ? <UpdateCard update={item.update} onDeleted={items.reload} /> : null}
          </div>
        ))}
      </div>

      {answering ? (
        <InterestDialog
          request={answering.request}
          kind={answering.kind}
          onClose={() => setAnswering(null)}
          onSent={() => {
            setAnswering(null);
            items.reload();
          }}
        />
      ) : null}
    </div>
  );
}

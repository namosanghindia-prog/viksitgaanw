import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type { FarmerGroup, LocationSelection, Profile } from '@viksitgaanw/shared';
import { REFERENCE, findItem } from '@viksitgaanw/shared';

import { ChoiceGroup } from '../components/ChoiceGroup';
import { LocationCascader } from '../components/LocationCascader';
import { TextField } from '../components/TextField';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';
import { useProfile } from '../lib/profile';

const ORGANISER_TYPES = ['fpo', 'cooperative', 'shg'];

/** A farmer, or an FPO, cooperative or self-help group, may run a group. */
export function canOrganise(profile: Profile | null): boolean {
  if (!profile) return false;
  if (profile.segment === 'farmer') return true;
  const type = (profile.details as { organisationType?: string | null }).organisationType;
  return profile.segment === 'partner_national' && ORGANISER_TYPES.includes(type ?? '');
}

export function GroupSummary({ group }: { group: FarmerGroup }) {
  const { t, rt, lang } = useI18n();
  return (
    <Link to={`/groups/${group.id}`} className="request group-card">
      <header className="request__head">
        <div className="request__heading">
          <h3 className="request__title">{group.name}</h3>
          <p className="request__place">
            {rt(findItem('group_kinds', group.kind))}
            {group.place ? ` · ${group.place}` : ''}
          </p>
        </div>
        <div className="request__badges">
          {group.visibility === 'online' ? <span className="badge">🌐 {t('share.online')}</span> : null}
          {group.origin === 'demo' ? <span className="badge badge--sample">{t('card.sample')}</span> : null}
        </div>
      </header>
      <p>
        <strong>{t('groups.members', { n: group.memberCount, ha: formatNumber(group.totalHectares, lang, 2) })}</strong>
      </p>
      {group.crops.length ? (
        <div className="request__tags">
          {group.crops.map((code) => (
            <span key={code} className="tag">
              {rt(findItem('crops', code))}
            </span>
          ))}
        </div>
      ) : null}
    </Link>
  );
}

/** The owner's groups, and groups shared near them. */
export function GroupsPage() {
  const { t } = useI18n();
  const { profile } = useProfile();
  const mine = useAsync((signal) => api.myGroups(signal), []);
  const nearby = useAsync((signal) => api.groups(undefined, signal), []);
  const myIds = new Set((mine.data ?? []).map((group) => group.id));
  const others = (nearby.data ?? []).filter((group) => !myIds.has(group.id));

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('groups.title')}</h2>
          <p className="page__subtitle">{t('groups.lede')}</p>
        </div>
        {canOrganise(profile) ? (
          <Link className="button button--primary" to="/groups/new">
            + {t('groups.create')}
          </Link>
        ) : null}
      </header>

      <h3 className="section__title">{t('groups.mine')}</h3>
      {!mine.loading && (mine.data ?? []).length === 0 ? <p className="muted">{t('groups.emptyMine')}</p> : null}
      <div className="requests">
        {(mine.data ?? []).map((group) => (
          <GroupSummary key={group.id} group={group} />
        ))}
      </div>

      <h3 className="section__title">{t('groups.nearby')}</h3>
      {!nearby.loading && others.length === 0 ? <p className="muted">{t('groups.emptyNearby')}</p> : null}
      <div className="requests">
        {others.map((group) => (
          <GroupSummary key={group.id} group={group} />
        ))}
      </div>
    </div>
  );
}

/** Start a group, or change one. */
export function GroupFormPage() {
  const { groupId } = useParams();
  const { t } = useI18n();
  const { profile } = useProfile();
  const navigate = useNavigate();
  const existing = useAsync((signal) => api.group(groupId!, signal), [groupId], { enabled: Boolean(groupId) });

  const [name, setName] = useState('');
  const [kind, setKind] = useState<string | null>(profile?.segment === 'farmer' ? 'informal' : 'fpo');
  const [description, setDescription] = useState('');
  const [crops, setCrops] = useState<string[]>([]);
  const [place, setPlace] = useState<LocationSelection>({
    stateCode: profile?.stateCode ?? null,
    districtCode: profile?.districtCode ?? null,
    subdistrictCode: profile?.subdistrictCode ?? null,
    villageCode: null,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const group = existing.data;
    if (!group) return;
    setName(group.name);
    setKind(group.kind);
    setDescription(group.description ?? '');
    setCrops(group.crops);
    setPlace({ stateCode: group.stateCode, districtCode: group.districtCode, subdistrictCode: group.subdistrictCode, villageCode: null });
  }, [existing.data]);

  const save = async () => {
    if (!name.trim() || !kind || !place.stateCode || !place.districtCode) {
      setError(t('groups.needBasics'));
      return;
    }
    setBusy(true);
    setError(null);
    const body = {
      name: name.trim(),
      kind,
      description,
      stateCode: place.stateCode,
      districtCode: place.districtCode,
      subdistrictCode: place.subdistrictCode,
      crops,
    };
    try {
      const group = groupId ? await api.updateGroup(groupId, body) : await api.createGroup(body);
      navigate(`/groups/${group.id}`, { replace: true });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  return (
    <div className="page page--narrow">
      <p>
        <Link to="/groups">← {t('groups.back')}</Link>
      </p>
      <h2 className="page__title">{groupId ? t('groups.edit') : t('groups.create')}</h2>
      <div className="stack">
        <TextField id="groupName" label={t('groups.name')} value={name} onChange={setName} required maxLength={200} />
        <ChoiceGroup label={t('groups.kind')} items={REFERENCE.group_kinds.items} allowCustom value={kind} onChange={setKind} />
        <TextField id="groupAbout" label={t('groups.description')} value={description} onChange={setDescription} multiline optional maxLength={4000} />
        <LocationCascader value={place} onChange={setPlace} depth="subdistrict" requiredLevels={['state', 'district']} />
        <ChoiceGroup
          label={t('groups.crops')}
          items={REFERENCE.crops.items}
          allowCustom
          categories={REFERENCE.crops.categories}
          multiple
          value={crops}
          onChange={setCrops}
        />
        <p className="muted small">{t('share.draftNote')}</p>
        {error ? <p className="callout callout--error">{error}</p> : null}
        <div className="actions">
          <button type="button" className="button button--primary" disabled={busy} onClick={save}>
            {busy ? t('common.saving') : t('groups.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

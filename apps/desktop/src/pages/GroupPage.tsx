import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type { FarmerGroup, ReferenceItem, Seeking, Segment } from '@viksitgaanw/shared';
import { AUDIENCE_SEGMENTS, REFERENCE, findItem } from '@viksitgaanw/shared';

import { ChoiceGroup } from '../components/ChoiceGroup';
import { MessageLink } from '../components/MessageLink';
import { PartyLine } from '../components/RequestCard';
import { ShareControl } from '../components/ShareControl';
import { TextField } from '../components/TextField';
import { VideoField, VideoPlayer } from '../components/Video';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';
import { useProfile } from '../lib/profile';

/**
 * One group. Its organiser sees every member and can pool the members' land
 * into one investment request; anyone else sees the group and can ask to join.
 */
export function GroupPage() {
  const { groupId = '' } = useParams();
  const { t, rt, lang } = useI18n();
  const navigate = useNavigate();
  const state = useAsync((signal) => api.group(groupId, signal), [groupId]);
  const [local, setLocal] = useState<FarmerGroup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const group = local && local.id === groupId ? local : state.data;

  const act = async (action: () => Promise<FarmerGroup | void>) => {
    setError(null);
    try {
      const next = await action();
      if (next) setLocal(next);
      else {
        setLocal(null);
        state.reload();
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  if (state.error) return <p className="page callout callout--error">{state.error.message}</p>;
  if (!group) return <p className="page muted">{t('common.loading')}</p>;

  return (
    <div className="page">
      <p>
        <Link to="/groups">← {t('groups.back')}</Link>
      </p>
      <header className="page__header">
        <div>
          <h2 className="page__title">{group.name}</h2>
          <p className="page__subtitle">
            {rt(findItem('group_kinds', group.kind))}
            {group.place ? ` · ${group.place}` : ''}
          </p>
        </div>
        {group.isMine ? (
          <div className="actions">
            <Link className="button button--small" to={`/groups/${group.id}/edit`}>
              {t('common.edit')}
            </Link>
            <button
              type="button"
              className="button button--danger button--small"
              onClick={async () => {
                if (!window.confirm(t('groups.confirmDelete'))) return;
                try {
                  await api.deleteGroup(group.id);
                  navigate('/groups', { replace: true });
                } catch (cause) {
                  setError(cause instanceof Error ? cause.message : String(cause));
                }
              }}
            >
              {t('common.delete')}
            </button>
          </div>
        ) : null}
      </header>

      {error ? <p className="callout callout--error">{error}</p> : null}
      {group.description ? <p>{group.description}</p> : null}
      {group.isMine ? (
        <VideoField
          target="group"
          entityId={group.id}
          video={group.introVideo}
          label={t('video.group')}
          onChanged={() => {
            setLocal(null);
            state.reload();
          }}
        />
      ) : group.introVideo ? (
        <VideoPlayer video={group.introVideo} title={group.name} />
      ) : null}
      <p>
        <strong>{t('groups.pooled', { ha: formatNumber(group.totalHectares, lang, 2), n: group.memberCount })}</strong>
      </p>

      {group.isMine ? (
        <ShareControl
          visibility={group.visibility}
          sharedAt={group.sharedAt}
          onShare={() => api.shareGroup(group.id)}
          onUnshare={() => api.unshareGroup(group.id)}
          onChanged={() => {
            setLocal(null);
            state.reload();
          }}
        />
      ) : (
        <section className="card card--tight">
          <PartyLine party={group.owner} />
          <div className="actions">
            <MessageLink party={group.owner} />
          </div>
        </section>
      )}

      {group.isMine ? (
        <Members group={group} act={act} />
      ) : (
        <Membership group={group} act={act} />
      )}

      {group.isMine ? (
        <GroupRequest
          group={group}
          onMade={() => {
            setLocal(null);
            state.reload();
          }}
        />
      ) : null}
    </div>
  );
}

type Act = (action: () => Promise<FarmerGroup | void>) => Promise<void>;

function Members({ group, act }: { group: FarmerGroup; act: Act }) {
  const { t, rt, lang } = useI18n();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [land, setLand] = useState('');
  const [crops, setCrops] = useState<string[]>(group.crops);

  const add = async () => {
    const hectares = Number.parseFloat(land);
    if (!name.trim() || !Number.isFinite(hectares) || hectares < 0) return;
    await act(() => api.addMember(group.id, { name: name.trim(), phone: phone || null, landHectares: hectares, crops }));
    setName('');
    setPhone('');
    setLand('');
    setAdding(false);
  };

  const cropItems = REFERENCE.crops.items.filter((item) => group.crops.length === 0 || group.crops.includes(item.code));

  return (
    <section className="card">
      <div className="card__head">
        <h3 className="card__title">{t('groups.memberList', { n: group.members.length })}</h3>
        {!adding ? (
          <button type="button" className="button button--primary button--small" onClick={() => setAdding(true)}>
            + {t('groups.addMember')}
          </button>
        ) : null}
      </div>
      <p className="muted small">{t('groups.onlyOwnerSees')}</p>

      {adding ? (
        <div className="stack">
          <div className="field-row">
            <TextField id="memberName" label={t('groups.memberName')} value={name} onChange={setName} required maxLength={160} />
            <TextField id="memberPhone" label={t('groups.memberPhone')} value={phone} onChange={setPhone} optional inputMode="tel" maxLength={20} />
          </div>
          <div className="narrow">
            <TextField id="memberLand" label={t('groups.memberLand')} type="number" inputMode="decimal" min={0} value={land} onChange={setLand} required />
          </div>
          <ChoiceGroup label={t('groups.memberCrops')} items={cropItems} multiple value={crops} onChange={setCrops} />
          <div className="actions">
            <button type="button" className="button button--ghost" onClick={() => setAdding(false)}>
              {t('common.cancel')}
            </button>
            <button type="button" className="button button--primary" onClick={add} disabled={!name.trim() || !land}>
              {t('common.save')}
            </button>
          </div>
        </div>
      ) : null}

      <ul className="answers__list">
        {group.members.map((member) => {
          const who = member.profile?.displayName ?? member.name ?? '';
          return (
            <li key={member.id} className={`answer answer--${member.status === 'active' ? 'accepted' : member.status === 'left' ? 'withdrawn' : 'sent'}`}>
              {member.profile ? <PartyLine party={member.profile} /> : <strong>{who}</strong>}
              <p className="small">
                {formatNumber(member.landHectares, lang, 2)} ha
                {member.village ? ` · ${member.village}` : ''}
                {member.crops.length ? ` · ${member.crops.map((code) => rt(findItem('crops', code))).join(', ')}` : ''}
                {member.phone ? (
                  <>
                    {' · '}
                    <a href={`tel:${member.phone}`}>{member.phone}</a>
                  </>
                ) : null}
              </p>
              <div className="answer__foot">
                <span className="badge badge--muted">{t(`memberStatus.${member.status}`)}</span>
                <span className="answer__actions">
                  {member.status === 'requested' ? (
                    <button
                      type="button"
                      className="button button--primary button--small"
                      onClick={() => act(() => api.setMemberStatus(group.id, member.id, 'active'))}
                    >
                      {t('groups.approve')}
                    </button>
                  ) : null}
                  {member.profile ? <MessageLink party={member.profile} className="button button--small button--ghost" /> : null}
                  <button
                    type="button"
                    className="button button--ghost button--small"
                    onClick={() => {
                      if (!window.confirm(t('groups.confirmRemove', { name: who }))) return;
                      void act(() => api.removeMember(group.id, member.id));
                    }}
                  >
                    {t('groups.remove')}
                  </button>
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Membership({ group, act }: { group: FarmerGroup; act: Act }) {
  const { t } = useI18n();
  const { profile } = useProfile();
  const [land, setLand] = useState('');
  const membership = group.myMembership;

  if (profile?.segment !== 'farmer') return null;

  if (membership && membership.status !== 'left') {
    return (
      <section className="card card--tight">
        <p>{membership.status === 'active' ? t('groups.joined') : t('groups.requested')}</p>
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={() => act(() => api.leaveGroup(group.id))}
        >
          {t('groups.leave')}
        </button>
      </section>
    );
  }

  return (
    <section className="card">
      <h3 className="card__title">{t('groups.join')}</h3>
      <div className="narrow">
        <TextField id="joinLand" label={t('groups.joinLand')} type="number" inputMode="decimal" min={0} value={land} onChange={setLand} />
      </div>
      <button
        type="button"
        className="button button--primary"
        disabled={!(Number.parseFloat(land) >= 0)}
        onClick={() => act(() => api.joinGroup(group.id, { landHectares: Number.parseFloat(land), crops: group.crops }))}
      >
        {t('groups.join')}
      </button>
    </section>
  );
}

function GroupRequest({ group, onMade }: { group: FarmerGroup; onMade: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [amount, setAmount] = useState('');
  const [seeking, setSeeking] = useState<string[]>(['investment']);
  const [modes, setModes] = useState<string[]>(['loan', 'revenue_share']);
  const [partnershipTypes, setPartnershipTypes] = useState<string[]>([]);
  const [openTo, setOpenTo] = useState<string[]>(['investor_india', 'partner_national', 'government']);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const seekingItems = useMemo<ReferenceItem[]>(
    () =>
      (['investment', 'partnership'] as const).map((code) => ({
        code,
        label: { en: t(`seeking.${code}`), hi: t(`seeking.${code}`) },
      })),
    [t],
  );
  const audienceItems = useMemo(
    () => REFERENCE.user_segments.items.filter((item) => AUDIENCE_SEGMENTS.includes(item.code as Segment) && item.code !== 'farmer'),
    [],
  );

  const submit = async () => {
    const amountNumber = Number.parseFloat(amount);
    if (!title.trim() || !(amountNumber > 0) || !seeking.length || !openTo.length) {
      setError(t('groups.needRequestBasics'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.groupRequest(group.id, {
        title: title.trim(),
        summary,
        amountSought: amountNumber,
        seeking: seeking as Seeking[],
        modes: seeking.includes('investment') ? modes : [],
        partnershipTypes: seeking.includes('partnership') ? partnershipTypes : [],
        openTo: openTo as Segment[],
      });
      setDone(true);
      setOpen(false);
      onMade();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div className="card__head">
        <h3 className="card__title">💼 {t('groups.askInvestment')}</h3>
        {!open ? (
          <button
            type="button"
            className="button button--primary button--small"
            disabled={group.memberCount === 0}
            title={group.memberCount === 0 ? t('groups.needMembers') : undefined}
            onClick={() => setOpen(true)}
          >
            {t('groups.askInvestment')}
          </button>
        ) : null}
      </div>
      {group.requestIds.length ? (
        <p className="muted small">
          {t('groups.requests', { n: group.requestIds.length })} · <Link to="/requests">{t('nav.findInvestors')}</Link>
        </p>
      ) : null}
      {group.memberCount === 0 ? <p className="muted small">{t('groups.needMembers')}</p> : null}
      {done ? <p className="callout callout--info">{t('groups.requestSent')}</p> : null}
      {open ? (
        <div className="stack">
          <TextField id="groupReqTitle" label={t('request.headline')} value={title} onChange={setTitle} required maxLength={200} />
          <TextField id="groupReqSummary" label={t('request.summary')} value={summary} onChange={setSummary} multiline optional maxLength={4000} />
          <div className="narrow">
            <TextField id="groupReqAmount" label={t('request.amount')} type="number" inputMode="decimal" min={0} value={amount} onChange={setAmount} required />
          </div>
          <ChoiceGroup label={t('request.seeking')} items={seekingItems} multiple value={seeking} onChange={setSeeking} />
          {seeking.includes('investment') ? (
            <ChoiceGroup label={t('request.modes')} items={REFERENCE.investment_modes.items} multiple value={modes} onChange={setModes} />
          ) : null}
          {seeking.includes('partnership') ? (
            <ChoiceGroup
              label={t('request.partnershipTypes')}
              items={REFERENCE.partnership_types.items}
              multiple
              value={partnershipTypes}
              onChange={setPartnershipTypes}
            />
          ) : null}
          <ChoiceGroup label={t('request.openTo')} items={audienceItems} multiple value={openTo} onChange={setOpenTo} />
          {error ? <p className="callout callout--error">{error}</p> : null}
          <div className="actions">
            <button type="button" className="button button--ghost" onClick={() => setOpen(false)} disabled={busy}>
              {t('common.cancel')}
            </button>
            <button type="button" className="button button--primary" onClick={submit} disabled={busy}>
              {busy ? t('request.publishing') : t('request.publish')}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

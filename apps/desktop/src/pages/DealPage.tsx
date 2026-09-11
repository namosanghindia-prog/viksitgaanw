import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { Deal, Dispute, Milestone } from '@viksitgaanw/shared';
import { REFERENCE, findItem } from '@viksitgaanw/shared';

import { ChoiceGroup } from '../components/ChoiceGroup';
import { DealPlanEditor } from '../components/DealPlanEditor';
import { MessageLink } from '../components/MessageLink';
import { PhotoButton } from '../components/PhotoButton';
import { ReadAloud } from '../components/ReadAloud';
import { ContactLine, PartyLine } from '../components/RequestCard';
import { RateBox } from '../components/Stars';
import { TextField } from '../components/TextField';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate, formatMoneyShort } from '../lib/format';
import { useAsync } from '../lib/hooks';
import { dealStatusBadge } from './DealsPage';

/**
 * One deal: the plan both sides agreed, each stage's evidence and release,
 * any problem raised, and the ratings once it is done.
 *
 * No money moves through the app. The investor pays each stage bank to bank
 * and records the reference here, so both sides hold the same record.
 */
export function DealPage() {
  const { dealId = '' } = useParams();
  const { t, lang } = useI18n();
  const state = useAsync((signal) => api.deal(dealId, signal), [dealId]);
  const [deal, setDeal] = useState<Deal | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const current = deal && deal.id === dealId ? deal : state.data;
  const money = (rupees: number) => `₹${formatMoneyShort(rupees, lang, t)}`;

  const act = async (key: string, action: () => Promise<Deal | unknown>) => {
    setBusy(key);
    setError(null);
    try {
      const result = await action();
      if (result && typeof result === 'object' && 'milestones' in result) setDeal(result as Deal);
      else {
        setDeal(null);
        state.reload();
      }
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      return false;
    } finally {
      setBusy(null);
    }
  };

  if (state.error) return <p className="page callout callout--error">{state.error.message}</p>;
  if (!current) return <p className="page muted">{t('common.loading')}</p>;

  const other = current.iAm === 'farmer' ? current.investor : current.farmer;
  const openDispute = current.disputes.find((dispute) => dispute.status === 'open');
  const summary = [
    current.requestTitle,
    t(`dealStatus.${current.status}`),
    t('deals.released', { released: money(current.amountReleased), total: money(current.amountTotal) }),
  ].join('. ');

  return (
    <div className="page">
      <p>
        <Link to="/deals">← {t('deal.back')}</Link>
      </p>
      <header className="page__header">
        <div>
          <h2 className="page__title">{current.requestTitle}</h2>
          <p className="page__subtitle">
            <span className={`badge ${dealStatusBadge(current.status)}`}>{t(`dealStatus.${current.status}`)}</span>{' '}
            {t('deals.released', { released: money(current.amountReleased), total: money(current.amountTotal) })}
          </p>
        </div>
        <ReadAloud text={summary} />
      </header>

      <section className="card">
        <h3 className="card__title">{current.iAm === 'farmer' ? t('deal.investor') : t('deal.farmer')}</h3>
        <PartyLine party={other} />
        <ContactLine party={other} />
        <div className="actions">
          <MessageLink party={other} />
        </div>
      </section>

      <p className="callout callout--info">{t('deal.noMoneyHere')}</p>
      {error ? <p className="callout callout--error">{error}</p> : null}

      {current.status === 'drafting' ? (
        <section className="card">
          <h3 className="card__title">{t('dealPlan.title')}</h3>
          {current.canAgree ? (
            <p className="callout callout--warn">{t('deal.pleaseAgree')}</p>
          ) : (
            <p className="muted">{t('deal.waitingOther')}</p>
          )}
          {editing ? (
            <DealPlanEditor
              offered={null}
              initialTerms={current.terms}
              initialMilestones={current.milestones}
              busy={busy === 'plan'}
              submitLabel={t('dealPlan.save')}
              onCancel={() => setEditing(false)}
              onSubmit={async (plan) => {
                if (await act('plan', () => api.replacePlan(current.id, plan))) setEditing(false);
              }}
            />
          ) : (
            <div className="actions">
              {current.canAgree ? (
                <button
                  type="button"
                  className="button button--primary"
                  disabled={busy !== null}
                  onClick={() => {
                    if (!window.confirm(t('deal.confirmAgree'))) return;
                    void act('agree', () => api.agreeDeal(current.id));
                  }}
                >
                  {t('deal.agree')}
                </button>
              ) : null}
              <button type="button" className="button" onClick={() => setEditing(true)}>
                {t('dealPlan.edit')}
              </button>
            </div>
          )}
        </section>
      ) : null}

      {current.terms ? (
        <section className="card card--tight">
          <h3 className="card__title">{t('dealPlan.terms')}</h3>
          <p className="deal__terms">{current.terms}</p>
        </section>
      ) : null}

      <h3 className="section__title">{t('deal.stages')}</h3>
      <ol className="stages">
        {current.milestones.map((milestone) => (
          <StageRow
            key={milestone.id}
            deal={current}
            milestone={milestone}
            busy={busy}
            paused={Boolean(openDispute)}
            act={act}
          />
        ))}
      </ol>

      <DisputeSection deal={current} busy={busy} act={act} />

      {current.canRate || current.myRating ? <RatingSection deal={current} onRated={state.reload} /> : null}

      {current.status === 'drafting' || current.status === 'active' ? (
        <div className="actions">
          <button
            type="button"
            className="button button--danger button--small"
            disabled={busy !== null}
            onClick={() => {
              if (!window.confirm(t('deal.confirmCancel'))) return;
              void act('cancel', () => api.cancelDeal(current.id));
            }}
          >
            {t('deal.cancel')}
          </button>
        </div>
      ) : null}
    </div>
  );
}

type Act = (key: string, action: () => Promise<Deal | unknown>) => Promise<boolean>;

function StageRow({
  deal,
  milestone,
  busy,
  paused,
  act,
}: {
  deal: Deal;
  milestone: Milestone;
  busy: string | null;
  paused: boolean;
  act: Act;
}) {
  const { t, lang } = useI18n();
  const [note, setNote] = useState('');
  const [reviewNote, setReviewNote] = useState('');
  const [reference, setReference] = useState('');
  const running = deal.status === 'active' && !paused;
  const canSubmit = running && deal.iAm === 'farmer' && (milestone.status === 'planned' || milestone.status === 'rejected');
  const canReview = running && deal.iAm === 'investor' && milestone.status === 'submitted';

  return (
    <li className={`stage stage--${milestone.status}`}>
      <div className="stage__head">
        <strong>
          {milestone.position + 1}. {milestone.title}
        </strong>
        <span className="stage__amount">₹{formatMoneyShort(milestone.amount, lang, t)}</span>
        <span className={`badge badge--milestone-${milestone.status}`}>{t(`milestoneStatus.${milestone.status}`)}</span>
        {milestone.overdue ? <span className="badge badge--status-declined">{t('deal.overdue')}</span> : null}
      </div>
      {milestone.dueDate ? (
        <p className="muted small">
          {t('dealPlan.due')}: {formatDate(milestone.dueDate, lang)}
        </p>
      ) : null}
      {milestone.description ? <p>{milestone.description}</p> : null}
      {milestone.evidenceNote ? (
        <p>
          <strong>{t('deal.evidence')}:</strong> {milestone.evidenceNote}
        </p>
      ) : null}
      {milestone.photos.length > 0 ? (
        <div className="machine__thumbs">
          {milestone.photos.map((photo) => (
            <a key={photo.id} href={api.mediaUrl(photo.url) ?? undefined} target="_blank" rel="noreferrer">
              <img className="machine__thumb" src={api.mediaUrl(photo.url) ?? undefined} alt="" />
            </a>
          ))}
        </div>
      ) : null}
      {milestone.reviewNote ? <p className="muted">{t('deal.reviewedNote', { note: milestone.reviewNote })}</p> : null}
      {milestone.releasedAt ? (
        <p className="callout callout--info">
          ✓ {t('deal.releasedOn', { date: formatDate(milestone.releasedAt, lang) })}
          {milestone.releaseReference ? ` · ${milestone.releaseReference}` : ''}
        </p>
      ) : null}

      {canSubmit ? (
        <div className="stack">
          <TextField
            id={`evidence${milestone.id}`}
            label={t('deal.evidence')}
            hint={t('deal.evidenceHint')}
            value={note}
            onChange={setNote}
            multiline
            maxLength={4000}
          />
          <div className="actions">
            <PhotoButton
              label={t('deal.addPhoto')}
              onPick={(file) => act(`photo${milestone.id}`, () => api.addMilestonePhoto(milestone.id, file))}
            />
            <button
              type="button"
              className="button button--primary button--small"
              disabled={!note.trim() || busy !== null}
              onClick={async () => {
                if (await act(`submit${milestone.id}`, () => api.submitMilestone(milestone.id, note.trim()))) setNote('');
              }}
            >
              {t('deal.submit')}
            </button>
          </div>
        </div>
      ) : null}

      {canReview ? (
        <div className="stack">
          <TextField
            id={`review${milestone.id}`}
            label={t('deal.reviewNote')}
            value={reviewNote}
            onChange={setReviewNote}
            multiline
            optional
            maxLength={2000}
          />
          <TextField
            id={`ref${milestone.id}`}
            label={t('deal.releaseRef')}
            hint={t('deal.releaseRefHint')}
            value={reference}
            onChange={setReference}
            optional
            maxLength={120}
          />
          <div className="actions">
            <button
              type="button"
              className="button button--primary button--small"
              disabled={busy !== null}
              onClick={() =>
                act(`review${milestone.id}`, () =>
                  api.reviewMilestone(milestone.id, { approved: true, note: reviewNote, releaseReference: reference }),
                )
              }
            >
              {t('deal.approve')}
            </button>
            <button
              type="button"
              className="button button--small"
              disabled={busy !== null || !reviewNote.trim()}
              title={reviewNote.trim() ? undefined : t('deal.sendBackHint')}
              onClick={() =>
                act(`review${milestone.id}`, () => api.reviewMilestone(milestone.id, { approved: false, note: reviewNote }))
              }
            >
              {t('deal.sendBack')}
            </button>
          </div>
        </div>
      ) : null}
    </li>
  );
}

function DisputeSection({ deal, busy, act }: { deal: Deal; busy: string | null; act: Act }) {
  const { t } = useI18n();
  const [opening, setOpening] = useState(false);
  const [reason, setReason] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const canOpen = (deal.status === 'active' || deal.status === 'drafting') && !deal.disputes.some((d) => d.status === 'open');

  if (!deal.disputes.length && !canOpen) return null;

  return (
    <section className="card">
      <h3 className="card__title">{t('deal.problems')}</h3>
      {deal.disputes.map((dispute) => (
        <DisputeRow key={dispute.id} dispute={dispute} busy={busy} act={act} />
      ))}
      {canOpen && !opening ? (
        <button type="button" className="button button--small" onClick={() => setOpening(true)}>
          ⚠️ {t('deal.problem')}
        </button>
      ) : null}
      {opening ? (
        <div className="stack">
          <p className="callout callout--warn">{t('dispute.pausesDeal')}</p>
          <ChoiceGroup label={t('dispute.reason')} items={REFERENCE.dispute_reasons.items} value={reason} onChange={setReason} />
          <TextField
            id="disputeDescription"
            label={t('dispute.description')}
            value={description}
            onChange={setDescription}
            multiline
            maxLength={4000}
          />
          <div className="actions">
            <button type="button" className="button button--ghost" onClick={() => setOpening(false)}>
              {t('common.cancel')}
            </button>
            <button
              type="button"
              className="button button--danger"
              disabled={!reason || !description.trim() || busy !== null}
              onClick={async () => {
                const ok = await act('dispute', () =>
                  api.openDispute({ dealId: deal.id, reason: reason!, description: description.trim() }),
                );
                if (ok) {
                  setOpening(false);
                  setDescription('');
                  setReason(null);
                }
              }}
            >
              {t('dispute.open')}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function DisputeRow({ dispute, busy, act }: { dispute: Dispute; busy: string | null; act: Act }) {
  const { t, rt, lang } = useI18n();
  const [fix, setFix] = useState('');
  const open = dispute.status === 'open';

  return (
    <div className={`dispute dispute--${dispute.status}`}>
      <p>
        <strong>{rt(findItem('dispute_reasons', dispute.reason))}</strong>{' '}
        <span className="badge badge--muted">{t(`disputeStatus.${dispute.status}`)}</span>{' '}
        <span className="muted small">
          {dispute.openedByMe ? t('dispute.byYou') : t('dispute.byThem')} · {formatDate(dispute.createdAt, lang)}
        </span>
      </p>
      <p>{dispute.description}</p>
      {dispute.resolution ? (
        <p className="callout callout--info">{t('dispute.proposed', { text: dispute.resolution })}</p>
      ) : null}
      {open && dispute.resolutionProposedByMe ? <p className="muted small">{t('dispute.waiting')}</p> : null}
      {open ? (
        <div className="stack">
          {dispute.canConfirm ? (
            <div className="actions">
              <button
                type="button"
                className="button button--primary button--small"
                disabled={busy !== null}
                onClick={() => act(`d${dispute.id}`, () => api.updateDispute(dispute.id, { action: 'confirm' }))}
              >
                {t('dispute.confirm')}
              </button>
            </div>
          ) : null}
          <TextField
            id={`fix${dispute.id}`}
            label={t('dispute.propose')}
            hint={t('dispute.proposeHint')}
            value={fix}
            onChange={setFix}
            multiline
            maxLength={4000}
          />
          <div className="actions">
            <button
              type="button"
              className="button button--small"
              disabled={!fix.trim() || busy !== null}
              onClick={async () => {
                if (await act(`d${dispute.id}`, () => api.updateDispute(dispute.id, { action: 'propose', resolution: fix.trim() })))
                  setFix('');
              }}
            >
              {t('dispute.propose')}
            </button>
            {dispute.openedByMe ? (
              <button
                type="button"
                className="button button--ghost button--small"
                disabled={busy !== null}
                onClick={() => act(`d${dispute.id}`, () => api.updateDispute(dispute.id, { action: 'withdraw' }))}
              >
                {t('dispute.withdraw')}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function RatingSection({ deal, onRated }: { deal: Deal; onRated: () => void }) {
  const { t } = useI18n();
  return (
    <section className="card card--tight">
      <RateBox contextType="deal" contextId={deal.id} myRating={deal.myRating} title={t('rating.title')} onRated={onRated} />
    </section>
  );
}

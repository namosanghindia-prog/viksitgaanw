import { useState } from 'react';
import type { MilestoneInput } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { formatMoneyShort } from '../lib/format';
import { TextField } from './TextField';

interface Row {
  title: string;
  amount: string;
  dueDate: string;
  description: string;
}

interface DealPlanEditorProps {
  /** What the investor offered, as a guide for the total. */
  offered: number | null;
  initialTerms?: string | null;
  initialMilestones?: MilestoneInput[];
  busy: boolean;
  submitLabel: string;
  onSubmit: (plan: { terms: string | null; milestones: MilestoneInput[] }) => void;
  onCancel?: () => void;
}

const blank = (): Row => ({ title: '', amount: '', dueDate: '', description: '' });

/**
 * Split an investment into stages. Each stage says what work it pays for, so
 * the money follows the work instead of arriving all at once.
 */
export function DealPlanEditor({
  offered,
  initialTerms,
  initialMilestones,
  busy,
  submitLabel,
  onSubmit,
  onCancel,
}: DealPlanEditorProps) {
  const { t, lang } = useI18n();
  const [terms, setTerms] = useState(initialTerms ?? '');
  const [rows, setRows] = useState<Row[]>(
    initialMilestones?.length
      ? initialMilestones.map((m) => ({
          title: m.title,
          amount: String(m.amount),
          dueDate: m.dueDate ?? '',
          description: m.description ?? '',
        }))
      : [blank(), blank()],
  );
  const [error, setError] = useState<string | null>(null);

  const total = rows.reduce((sum, row) => sum + (Number.parseFloat(row.amount) || 0), 0);
  const update = (index: number, patch: Partial<Row>) =>
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  const submit = () => {
    const filled = rows.filter((row) => row.title.trim() || row.amount.trim());
    const bad = filled.some((row) => !row.title.trim() || !(Number.parseFloat(row.amount) > 0));
    if (!filled.length || bad) {
      setError(t('dealPlan.needStage'));
      return;
    }
    setError(null);
    onSubmit({
      terms: terms.trim() || null,
      milestones: filled.map((row) => ({
        title: row.title.trim(),
        amount: Number.parseFloat(row.amount),
        dueDate: row.dueDate || null,
        description: row.description.trim() || null,
      })),
    });
  };

  return (
    <div className="stack">
      <p className="muted">{t('dealPlan.lede')}</p>
      <TextField
        id="dealTerms"
        label={t('dealPlan.terms')}
        hint={t('dealPlan.termsHint')}
        value={terms}
        onChange={setTerms}
        multiline
        optional
        maxLength={4000}
      />
      <ol className="stages">
        {rows.map((row, index) => (
          <li key={index} className="stage stage--edit">
            <div className="stage__head">
              <strong>{t('dealPlan.stage', { n: index + 1 })}</strong>
              {rows.length > 1 ? (
                <button
                  type="button"
                  className="button button--ghost button--small"
                  onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
                >
                  {t('dealPlan.removeStage')}
                </button>
              ) : null}
            </div>
            <TextField
              id={`stageTitle${index}`}
              label={t('dealPlan.stageTitle')}
              value={row.title}
              onChange={(value) => update(index, { title: value })}
              maxLength={200}
            />
            <div className="field-row">
              <TextField
                id={`stageAmount${index}`}
                label={t('dealPlan.amount')}
                type="number"
                inputMode="decimal"
                min={0}
                value={row.amount}
                onChange={(value) => update(index, { amount: value })}
              />
              <TextField
                id={`stageDue${index}`}
                label={t('dealPlan.due')}
                type="date"
                value={row.dueDate}
                onChange={(value) => update(index, { dueDate: value })}
                optional
              />
            </div>
          </li>
        ))}
      </ol>
      {rows.length < 12 ? (
        <div>
          <button type="button" className="button button--small" onClick={() => setRows((current) => [...current, blank()])}>
            {t('dealPlan.addStage')}
          </button>
        </div>
      ) : null}
      <p className="deal__total">
        <strong>{t('dealPlan.total', { amount: formatMoneyShort(total, lang, t) })}</strong>
        {offered ? <span className="muted"> · {t('dealPlan.offered', { amount: formatMoneyShort(offered, lang, t) })}</span> : null}
      </p>
      <p className="callout callout--info">{t('deal.noMoneyHere')}</p>
      {error ? <p className="callout callout--error">{error}</p> : null}
      <div className="actions">
        {onCancel ? (
          <button type="button" className="button button--ghost" onClick={onCancel} disabled={busy}>
            {t('common.cancel')}
          </button>
        ) : null}
        <button type="button" className="button button--primary" onClick={submit} disabled={busy}>
          {busy ? t('common.saving') : submitLabel}
        </button>
      </div>
    </div>
  );
}

import { useMemo, useState } from 'react';
import type { LoanAction, LoanApplication, LoanProduct, LoanProductInput, ReferenceItem } from '@viksitgaanw/shared';
import { REFERENCE } from '@viksitgaanw/shared';

import { ChoiceGroup } from '../components/ChoiceGroup';
import { LoanAnswer, LoanProductCard, LoanSharedFacts, LoanStatusBadge, useLoanFormat } from '../components/LoanCards';
import { PartyLine } from '../components/RequestCard';
import { ShareControl } from '../components/ShareControl';
import { StateChips } from '../components/StateChips';
import { TextField } from '../components/TextField';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useAsync } from '../lib/hooks';

type Tab = 'applications' | 'loans';
const OPEN = ['submitted', 'under_review', 'documents_requested'];

/**
 * The lender's desk: applications to answer, and the loans it offers.
 *
 * The bank decides and pays out through its own systems; here it tells the
 * applicant each step -- and the sanctioned and disbursed amounts it records
 * are what the platform's commission is reckoned on.
 */
export function LoanDeskPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>('applications');
  const desk = useAsync((signal) => api.loanDesk(signal), []);
  const products = useAsync((signal) => api.myLoanProducts(signal), []);
  const [editing, setEditing] = useState<LoanProduct | 'new' | null>(null);
  const waiting = (desk.data ?? []).filter((a) => OPEN.includes(a.status)).length;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">🏦 {t('desk.title')}</h2>
          <p className="page__subtitle">{t('desk.lede')}</p>
        </div>
      </header>

      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'applications'}
          className={`tab ${tab === 'applications' ? 'tab--active' : ''}`} onClick={() => setTab('applications')}>
          {t('desk.applications')} {waiting ? <span className="badge">{waiting}</span> : null}
        </button>
        <button type="button" role="tab" aria-selected={tab === 'loans'}
          className={`tab ${tab === 'loans' ? 'tab--active' : ''}`} onClick={() => setTab('loans')}>
          {t('desk.ourLoans')}
        </button>
      </div>

      {tab === 'applications' ? (
        <>
          {desk.error ? <p className="callout callout--error">{desk.error.message}</p> : null}
          {desk.data && desk.data.length === 0 ? (
            <div className="empty">
              <p className="empty__title">{t('desk.noApplications')}</p>
              <p className="empty__help">{t('desk.noApplicationsHelp')}</p>
            </div>
          ) : null}
          <div className="stack">
            {desk.data?.map((application) => (
              <DeskApplication key={application.id} application={application} onChanged={desk.reload} />
            ))}
          </div>
        </>
      ) : editing ? (
        <ProductForm
          product={editing === 'new' ? null : editing}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            products.reload();
          }}
        />
      ) : (
        <>
          <div className="actions">
            <span />
            <button type="button" className="button button--primary" onClick={() => setEditing('new')}>
              ＋ {t('desk.addLoan')}
            </button>
          </div>
          {products.data && products.data.length === 0 ? <p className="muted">{t('desk.noLoans')}</p> : null}
          <div className="loans">
            {products.data?.map((product) => (
              <LoanProductCard key={product.id} product={product}>
                <ShareControl
                  visibility={product.visibility}
                  sharedAt={product.sharedAt}
                  onShare={() => api.shareLoanProduct(product.id)}
                  onUnshare={() => api.unshareLoanProduct(product.id)}
                  onChanged={products.reload}
                />
                <p className="muted small">
                  {product.status === 'paused' ? `⏸ ${t('desk.paused')} · ` : ''}
                  {Object.entries(product.applicationCounts)
                    .map(([status, n]) => `${t(`loanStatus.${status}` as Parameters<typeof t>[0])}: ${n}`)
                    .join(' · ') || t('desk.noApplicationsYet')}
                </p>
                <div className="request__actions">
                  <button type="button" className="button button--small" onClick={() => setEditing(product)}>
                    {t('common.edit')}
                  </button>
                </div>
              </LoanProductCard>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function DeskApplication({ application, onChanged }: { application: LoanApplication; onChanged: () => void }) {
  const { t, rt } = useI18n();
  const { money, date } = useLoanFormat();
  const [action, setAction] = useState<LoanAction | null>(null);
  const [note, setNote] = useState('');
  const [documents, setDocuments] = useState<string[]>([]);
  const [amount, setAmount] = useState('');
  const [rate, setRate] = useState('');
  const [tenure, setTenure] = useState('');
  const [when, setWhen] = useState(new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = OPEN.includes(application.status);

  const start = (next: LoanAction) => {
    setAction(next);
    setError(null);
    if (next === 'sanction') {
      setAmount(String(Math.round(application.amountRequested)));
      setTenure(application.tenureMonths ? String(application.tenureMonths) : '');
    }
    if (next === 'disburse') setAmount(String(Math.round(application.sanctionedAmount ?? application.amountRequested)));
  };

  const send = async (chosen: LoanAction) => {
    if (chosen === 'decline' && !window.confirm(t('desk.confirmDecline'))) return;
    setBusy(true);
    setError(null);
    const number = (text: string) => (text.trim() ? Number.parseFloat(text) : null);
    try {
      await api.decideLoan(application.id, {
        action: chosen,
        note: note.trim() || null,
        documents: chosen === 'documents' ? documents : [],
        amount: chosen === 'sanction' || chosen === 'disburse' ? number(amount) : null,
        rate: chosen === 'sanction' ? number(rate) : null,
        tenureMonths: chosen === 'sanction' && tenure.trim() ? Number.parseInt(tenure, 10) : null,
        disbursedOn: chosen === 'disburse' ? when : null,
      });
      setAction(null);
      setNote('');
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className={`loan loan--application ${open ? 'loan--open' : ''}`}>
      <header className="loan__head">
        <div>
          <h4 className="loan__title">
            {money(application.amountRequested)} · {application.productTitle}
          </h4>
          <p className="muted small">
            {rt(REFERENCE.loan_purposes.items.find((item) => item.code === application.purpose))} ·{' '}
            {date(application.createdAt)}
            {application.tenureMonths ? ` · ${application.tenureMonths} ${t('loans.months')}` : ''}
          </p>
        </div>
        <LoanStatusBadge status={application.status} />
      </header>
      <PartyLine party={application.applicant} />
      <LoanSharedFacts application={application} />
      {application.applicantNote ? <blockquote className="answer__message">{application.applicantNote}</blockquote> : null}
      <LoanAnswer application={application} />

      {action === 'documents' ? (
        <ChoiceGroup label={t('desk.whichDocuments')} items={REFERENCE.loan_documents.items} allowCustom multiple
          value={documents} onChange={setDocuments} />
      ) : null}
      {action === 'sanction' ? (
        <div className="field-row">
          <TextField id={`sanctionAmount-${application.id}`} label={t('desk.sanctionAmount')} type="number" inputMode="numeric" min={0} value={amount} onChange={setAmount} required />
          <TextField id={`sanctionRate-${application.id}`} label={t('desk.rate')} type="number" min={0} value={rate} onChange={setRate} optional />
          <TextField id={`sanctionTenure-${application.id}`} label={t('loans.tenureAsked')} type="number" inputMode="numeric" min={1} value={tenure} onChange={setTenure} optional />
        </div>
      ) : null}
      {action === 'disburse' ? (
        <div className="field-row">
          <TextField id={`disburseAmount-${application.id}`} label={t('desk.disbursedAmount')} type="number" inputMode="numeric" min={0} value={amount} onChange={setAmount} required />
          <TextField id={`disburseOn-${application.id}`} label={t('desk.disbursedOn')} type="date" value={when} onChange={setWhen} required />
        </div>
      ) : null}
      {action ? (
        <>
          <TextField id={`deskNote-${application.id}`} label={t('desk.noteToApplicant')} value={note} onChange={setNote} multiline optional maxLength={2000} />
          <div className="request__actions">
            <button type="button" className="button button--ghost button--small" onClick={() => setAction(null)} disabled={busy}>
              {t('common.cancel')}
            </button>
            <button type="button" className="button button--primary button--small" onClick={() => send(action)} disabled={busy}>
              {busy ? t('common.saving') : t(`desk.do.${action}` as Parameters<typeof t>[0])}
            </button>
          </div>
        </>
      ) : (
        <div className="request__actions">
          {application.status === 'submitted' ? (
            <button type="button" className="button button--small" disabled={busy} onClick={() => send('review')}>
              {t('desk.do.review')}
            </button>
          ) : null}
          {open ? (
            <>
              <button type="button" className="button button--small" onClick={() => start('documents')}>{t('desk.do.documents')}</button>
              <button type="button" className="button button--primary button--small" onClick={() => start('sanction')}>{t('desk.do.sanction')}</button>
              <button type="button" className="button button--ghost button--small" onClick={() => start('decline')}>{t('desk.do.decline')}</button>
            </>
          ) : null}
          {application.status === 'sanctioned' ? (
            <button type="button" className="button button--primary button--small" onClick={() => start('disburse')}>{t('desk.do.disburse')}</button>
          ) : null}
        </div>
      )}
      {error ? <p className="callout callout--error">{error}</p> : null}
    </article>
  );
}

function ProductForm({ product, onCancel, onSaved }: { product: LoanProduct | null; onCancel: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const text = (value: number | null | undefined) => (value == null ? '' : String(value));
  const [purpose, setPurpose] = useState<string | null>(product?.purpose ?? null);
  const [title, setTitle] = useState(product?.title ?? '');
  const [summary, setSummary] = useState(product?.summary ?? '');
  const [minAmount, setMinAmount] = useState(text(product?.minAmount));
  const [maxAmount, setMaxAmount] = useState(text(product?.maxAmount));
  const [rateMin, setRateMin] = useState(text(product?.rateMin));
  const [rateMax, setRateMax] = useState(text(product?.rateMax));
  const [tenureMin, setTenureMin] = useState(text(product?.tenureMinMonths));
  const [tenureMax, setTenureMax] = useState(text(product?.tenureMaxMonths));
  const [collateral, setCollateral] = useState(product?.collateral ?? '');
  const [fee, setFee] = useState(product?.processingFee ?? '');
  const [documents, setDocuments] = useState<string[]>(product?.documents ?? ['aadhaar', 'land_record', 'project_report']);
  const [states, setStates] = useState<string[]>(product?.states ?? []);
  const [segments, setSegments] = useState<string[]>(product?.segments ?? ['farmer']);
  const [status, setStatus] = useState<string | null>(product?.status ?? 'active');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const segmentItems = useMemo<ReferenceItem[]>(
    () => [
      { code: 'farmer', label: { en: t('desk.forFarmers'), hi: t('desk.forFarmers') } },
      { code: 'partner_national', label: { en: t('desk.forFpos'), hi: t('desk.forFpos') } },
    ],
    [t],
  );
  const statusItems = useMemo<ReferenceItem[]>(
    () => [
      { code: 'active', label: { en: t('desk.active'), hi: t('desk.active') } },
      { code: 'paused', label: { en: t('desk.paused'), hi: t('desk.paused') } },
    ],
    [t],
  );

  const save = async () => {
    const number = (value: string) => (value.trim() ? Number.parseFloat(value) : null);
    if (!purpose || !title.trim() || !minAmount || !maxAmount) {
      setError(t('error.required'));
      return;
    }
    const body: LoanProductInput = {
      purpose,
      title: title.trim(),
      summary: summary.trim() || null,
      minAmount: Number.parseFloat(minAmount),
      maxAmount: Number.parseFloat(maxAmount),
      rateMin: number(rateMin),
      rateMax: number(rateMax),
      tenureMinMonths: number(tenureMin),
      tenureMaxMonths: number(tenureMax),
      collateral: collateral.trim() || null,
      processingFee: fee.trim() || null,
      documents,
      states,
      segments,
      status: status === 'paused' ? 'paused' : 'active',
    };
    setBusy(true);
    setError(null);
    try {
      if (product) await api.updateLoanProduct(product.id, body);
      else await api.createLoanProduct(body);
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h3 className="card__title">{product ? t('desk.editLoan') : t('desk.addLoan')}</h3>
      <ChoiceGroup label={t('desk.purpose')} items={REFERENCE.loan_purposes.items} value={purpose} onChange={setPurpose} />
      <TextField id="loanTitle" label={t('desk.loanName')} hint={t('desk.loanNameHint')} value={title} onChange={setTitle} required maxLength={200} />
      <TextField id="loanSummary" label={t('desk.summary')} value={summary} onChange={setSummary} multiline optional maxLength={4000} />
      <div className="field-row">
        <TextField id="loanMin" label={t('desk.minAmount')} type="number" inputMode="numeric" min={0} value={minAmount} onChange={setMinAmount} required />
        <TextField id="loanMax" label={t('desk.maxAmount')} type="number" inputMode="numeric" min={0} value={maxAmount} onChange={setMaxAmount} required />
      </div>
      <div className="field-row">
        <TextField id="loanRateMin" label={t('desk.rateMin')} type="number" min={0} value={rateMin} onChange={setRateMin} optional />
        <TextField id="loanRateMax" label={t('desk.rateMax')} type="number" min={0} value={rateMax} onChange={setRateMax} optional />
      </div>
      <div className="field-row">
        <TextField id="loanTenureMin" label={t('desk.tenureMin')} type="number" inputMode="numeric" min={1} value={tenureMin} onChange={setTenureMin} optional />
        <TextField id="loanTenureMax" label={t('desk.tenureMax')} type="number" inputMode="numeric" min={1} value={tenureMax} onChange={setTenureMax} optional />
      </div>
      <TextField id="loanCollateral" label={t('loans.collateral')} hint={t('desk.collateralHint')} value={collateral} onChange={setCollateral} optional maxLength={200} />
      <TextField id="loanFee" label={t('loans.processingFee')} value={fee} onChange={setFee} optional maxLength={120} />
      <ChoiceGroup label={t('loans.documents')} items={REFERENCE.loan_documents.items} allowCustom multiple value={documents} onChange={setDocuments} />
      <StateChips label={t('desk.states')} hint={t('desk.statesHint')} value={states} onChange={setStates} />
      <ChoiceGroup label={t('desk.whoMayApply')} items={segmentItems} multiple value={segments} onChange={setSegments} />
      <ChoiceGroup label={t('desk.status')} items={statusItems} value={status} onChange={setStatus} />
      {error ? <p className="callout callout--error">{error}</p> : null}
      <div className="actions">
        <button type="button" className="button button--ghost" onClick={onCancel} disabled={busy}>{t('common.cancel')}</button>
        {product ? (
          <button type="button" className="button button--danger" disabled={busy} onClick={async () => {
            if (!window.confirm(t('desk.confirmDelete'))) return;
            try {
              await api.deleteLoanProduct(product.id);
              onSaved();
            } catch (cause) {
              setError(cause instanceof Error ? cause.message : String(cause));
            }
          }}>
            {t('common.delete')}
          </button>
        ) : null}
        <button type="button" className="button button--primary" onClick={save} disabled={busy}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>
    </section>
  );
}

import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { LoanApplication, LoanProduct, ProjectReport, ReferenceItem } from '@viksitgaanw/shared';

import { LoanAnswer, LoanProductCard, LoanStatusBadge, LoanSteps, useLoanFormat } from '../components/LoanCards';
import { ChoiceGroup } from '../components/ChoiceGroup';
import { PartyLine } from '../components/RequestCard';
import { CheckField, TextField } from '../components/TextField';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useAsync } from '../lib/hooks';
import { useProfile } from '../lib/profile';

const NO_REPORT = '__none__';
const OPEN = ['submitted', 'under_review', 'documents_requested'];

/**
 * Loans, for a farmer or an FPO: their applications and where each stands,
 * then the loans banks and lenders offer -- best suited to the chosen project
 * report first. Applying shares only what the applicant ticks; the lender
 * decides, and pays out itself.
 */
export function LoansPage() {
  const { t, lang } = useI18n();
  const { profile } = useProfile();
  const [searchParams] = useSearchParams();
  const [reportId, setReportId] = useState<string>(searchParams.get('report') ?? NO_REPORT);
  const reports = useAsync((signal) => api.allReports(lang, signal), [lang]);
  const offers = useAsync(
    (signal) => api.loans({ reportId: reportId === NO_REPORT ? null : reportId }, signal),
    [reportId],
  );
  const applications = useAsync((signal) => api.myLoanApplications(signal), []);
  const [applying, setApplying] = useState<string | null>(null);

  // A report the link pointed at that is not there (deleted since) is not a choice.
  useEffect(() => {
    if (reports.data && reportId !== NO_REPORT && !reports.data.some((r) => r.id === reportId)) setReportId(NO_REPORT);
  }, [reports.data, reportId]);

  const report = reports.data?.find((r) => r.id === reportId) ?? null;
  const reportItems = useMemo<ReferenceItem[]>(() => {
    const items: ReferenceItem[] = (reports.data ?? []).map((r) => {
      const text = `${r.opportunityName} · ${r.reportNumber}`;
      return { code: r.id, label: { en: text, hi: text } };
    });
    items.push({ code: NO_REPORT, label: { en: t('loans.withoutReport'), hi: t('loans.withoutReport') } });
    return items;
  }, [reports.data, t]);

  const reload = () => {
    applications.reload();
    offers.reload();
  };

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">🏦 {t('loans.title')}</h2>
          <p className="page__subtitle">{t('loans.lede')}</p>
        </div>
      </header>

      {applications.data?.length ? (
        <section className="card">
          <h3 className="card__title">{t('loans.myApplications')}</h3>
          <div className="stack">
            {applications.data.map((application) => (
              <MyApplication key={application.id} application={application} onChanged={reload} />
            ))}
          </div>
        </section>
      ) : null}

      <section className="card">
        <h3 className="card__title">{t('loans.find')}</h3>
        <p className="card__help">{t('loans.findHelp')}</p>
        {reports.data && reports.data.length === 0 ? (
          <p className="callout callout--warn">
            {t('loans.noReports')} <Link to="/">{t('nav.myLand')} →</Link>
          </p>
        ) : null}
        <ChoiceGroup label={t('loans.withReport')} items={reportItems} value={reportId} onChange={(v) => setReportId(v ?? NO_REPORT)} />
        {profile?.visibility !== 'online' ? <p className="callout callout--info">{t('loans.shareProfileFirst')}</p> : null}
      </section>

      {offers.loading && !offers.data ? <p className="muted">{t('common.loading')}</p> : null}
      {offers.error ? <p className="callout callout--error">{offers.error.message}</p> : null}
      {offers.data && offers.data.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('loans.noneYet')}</p>
          <p className="empty__help">{t('loans.noneYetHelp')}</p>
        </div>
      ) : null}

      <div className="loans">
        {offers.data?.map((product) => (
          <LoanProductCard key={product.id} product={product}>
            {product.myApplicationId ? (
              <p className="muted small">✓ {t('loans.alreadyApplied')}</p>
            ) : applying === product.id ? (
              <ApplyForm
                product={product}
                report={report}
                onCancel={() => setApplying(null)}
                onDone={() => {
                  setApplying(null);
                  reload();
                }}
              />
            ) : (
              <div className="request__actions">
                <button type="button" className="button button--primary" onClick={() => setApplying(product.id)}>
                  {t('loans.apply')}
                </button>
              </div>
            )}
          </LoanProductCard>
        ))}
      </div>
    </div>
  );
}

function ApplyForm({
  product,
  report,
  onCancel,
  onDone,
}: {
  product: LoanProduct;
  report: ProjectReport | null;
  onCancel: () => void;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const { money } = useLoanFormat();
  // What the report says the project needs, kept inside what this lender lends.
  const suggested = report?.termLoan
    ? Math.min(Math.max(Math.round(report.termLoan), product.minAmount), product.maxAmount)
    : product.minAmount;
  const [amount, setAmount] = useState(String(suggested));
  const [tenure, setTenure] = useState(product.tenureMinMonths ? String(product.tenureMinMonths) : '');
  const [note, setNote] = useState('');
  const [shareReport, setShareReport] = useState(true);
  const [shareLand, setShareLand] = useState(true);
  const [shareContact, setShareContact] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const tenureNumber = Number.parseInt(tenure, 10);
      await api.applyForLoan({
        productId: product.id,
        reportId: report?.id ?? null,
        amountRequested: Number.parseFloat(amount),
        tenureMonths: Number.isFinite(tenureNumber) ? tenureNumber : null,
        applicantNote: note.trim() || null,
        shareReport,
        shareLand,
        shareContact,
      });
      onDone();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  return (
    <div className="loan-apply">
      <div className="field-row">
        <TextField
          id={`loanAmount-${product.id}`}
          label={t('loans.amountAsked')}
          hint={t('loans.between', { low: money(product.minAmount), high: money(product.maxAmount) })}
          type="number"
          inputMode="numeric"
          min={0}
          value={amount}
          onChange={setAmount}
          required
        />
        <TextField
          id={`loanTenure-${product.id}`}
          label={t('loans.tenureAsked')}
          type="number"
          inputMode="numeric"
          min={1}
          value={tenure}
          onChange={setTenure}
          optional
        />
      </div>
      <TextField
        id={`loanNote-${product.id}`}
        label={t('loans.noteToLender')}
        value={note}
        onChange={setNote}
        multiline
        optional
        maxLength={2000}
      />
      <fieldset className="field">
        <legend className="field__label">{t('loans.consentTitle')}</legend>
        {report ? (
          <CheckField label={t('loans.consentReport', { number: report.reportNumber })} checked={shareReport} onChange={setShareReport} />
        ) : (
          <p className="muted small">{t('loans.consentNoReport')}</p>
        )}
        {report ? <CheckField label={t('loans.consentLand')} checked={shareLand} onChange={setShareLand} /> : null}
        <CheckField label={t('loans.consentContact')} checked={shareContact} onChange={setShareContact} />
        {!shareContact ? <p className="field__error">{t('loans.contactNeeded')}</p> : null}
        <p className="muted small">{t('loans.consentNote')}</p>
      </fieldset>
      {error ? <p className="callout callout--error">{error}</p> : null}
      <div className="actions">
        <button type="button" className="button button--ghost" onClick={onCancel} disabled={busy}>
          {t('common.cancel')}
        </button>
        <button type="button" className="button button--primary" onClick={submit} disabled={busy || !shareContact || !amount}>
          {busy ? t('common.saving') : t('loans.send')}
        </button>
      </div>
    </div>
  );
}

function MyApplication({ application, onChanged }: { application: LoanApplication; onChanged: () => void }) {
  const { t } = useI18n();
  const { money, date } = useLoanFormat();
  const [reply, setReply] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = OPEN.includes(application.status);

  const act = async (action: 'withdraw' | 'reply') => {
    if (action === 'withdraw' && !window.confirm(t('loans.confirmWithdraw'))) return;
    setBusy(true);
    setError(null);
    try {
      await api.decideLoan(application.id, { action, note: action === 'reply' ? reply : null });
      setReply('');
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="loan loan--application">
      <header className="loan__head">
        <div>
          <h4 className="loan__title">{application.productTitle}</h4>
          <p className="muted small">
            {t('loans.askedFor', { amount: money(application.amountRequested) })} · {date(application.createdAt)}
          </p>
        </div>
        <LoanStatusBadge status={application.status} />
      </header>
      <PartyLine party={application.lender} />
      <LoanSteps status={application.status} />
      <LoanAnswer application={application} />
      {application.applicantNote ? (
        <p className="small">
          <strong>{t('loans.yourNote')}:</strong> {application.applicantNote}
        </p>
      ) : null}
      {open ? (
        <div className="loan-apply">
          {application.status === 'documents_requested' ? (
            <TextField
              id={`loanReply-${application.id}`}
              label={t('loans.replyLabel')}
              hint={t('loans.replyHint')}
              value={reply}
              onChange={setReply}
              multiline
              maxLength={2000}
            />
          ) : null}
          <div className="request__actions">
            {application.status === 'documents_requested' ? (
              <button type="button" className="button button--primary button--small" disabled={busy || !reply.trim()} onClick={() => act('reply')}>
                {t('loans.sendReply')}
              </button>
            ) : null}
            <button type="button" className="button button--ghost button--small" disabled={busy} onClick={() => act('withdraw')}>
              {t('loans.withdraw')}
            </button>
          </div>
        </div>
      ) : null}
      {error ? <p className="callout callout--error">{error}</p> : null}
    </article>
  );
}

import type { ReactNode } from 'react';
import type { LoanApplication, LoanProduct, LoanStatus } from '@viksitgaanw/shared';
import { findItem, pickLabel } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import type { StringKey } from '../i18n';
import { formatDate, formatMoneyShort, formatNumber } from '../lib/format';
import { MessageLink } from './MessageLink';
import { PartyLine } from './RequestCard';

const STATUS_BADGE: Record<LoanStatus, string> = {
  submitted: 'badge--status-sent',
  under_review: 'badge--status-sent',
  documents_requested: 'badge--status-sent',
  sanctioned: 'badge--status-accepted',
  disbursed: 'badge--status-accepted',
  declined: 'badge--status-declined',
  withdrawn: 'badge--muted',
};

/** The steps an application goes through, in order, for the progress line. */
const STEPS: LoanStatus[] = ['submitted', 'under_review', 'sanctioned', 'disbursed'];

export function LoanStatusBadge({ status }: { status: LoanStatus }) {
  const { t } = useI18n();
  return <span className={`badge ${STATUS_BADGE[status]}`}>{t(`loanStatus.${status}` as StringKey)}</span>;
}

/** Submitted → being reviewed → sanctioned → money received, with where it stands. */
export function LoanSteps({ status }: { status: LoanStatus }) {
  const { t } = useI18n();
  if (status === 'declined' || status === 'withdrawn') return null;
  const at = STEPS.indexOf(status === 'documents_requested' ? 'under_review' : status);
  return (
    <ol className="loan-steps" aria-label={t('loans.progress')}>
      {STEPS.map((step, index) => (
        <li
          key={step}
          className={`loan-steps__item ${index < at ? 'loan-steps__item--done' : ''} ${index === at ? 'loan-steps__item--now' : ''}`}
        >
          {index < at ? '✓ ' : ''}
          {t(`loanStatus.${step}` as StringKey)}
        </li>
      ))}
    </ol>
  );
}

export function useLoanFormat() {
  const { t, lang } = useI18n();
  const money = (rupees: number | null | undefined) => (rupees == null ? '—' : `₹${formatMoneyShort(rupees, lang, t)}`);
  const range = (low: number | null | undefined, high: number | null | undefined, unit = '') =>
    low == null && high == null
      ? '—'
      : low === high || high == null
        ? `${formatNumber(low ?? 0, lang, 1)}${unit}`
        : `${formatNumber(low ?? 0, lang, 1)}–${formatNumber(high, lang, 1)}${unit}`;
  return { money, range, date: (iso: string | null) => (iso ? formatDate(iso, lang) : '—') };
}

/** One loan on offer: who lends, for what, how much, at what rate. */
export function LoanProductCard({ product, children }: { product: LoanProduct; children?: ReactNode }) {
  const { t, rt } = useI18n();
  const { money, range } = useLoanFormat();
  const match = product.match;
  return (
    <article className={`loan ${match && match.score >= 70 ? 'loan--fits' : ''}`}>
      <header className="loan__head">
        <div>
          <h3 className="loan__title">{product.title}</h3>
          <p className="muted small">{rt(findItem('loan_purposes', product.purpose))}</p>
        </div>
        {match ? (
          <span className={`badge badge--fit ${match.score >= 70 ? 'badge--fit-good' : ''}`}>
            {t('card.fit', { score: match.score })}
          </span>
        ) : null}
      </header>
      {!product.isMine ? (
        <>
          <PartyLine party={product.lender} />
          {/* A question before applying: free once there is an application, otherwise from a message pack. */}
          <div className="request__actions">
            <MessageLink party={product.lender} />
          </div>
        </>
      ) : null}
      {match && (match.reasons.length || match.misses.length) ? (
        <p className="small">
          {match.reasons.map((code) => `✓ ${t(`loans.match.${code}` as StringKey)}`).join(' · ')}
          {match.misses.length ? (
            <span className="muted">
              {match.reasons.length ? ' · ' : ''}
              {match.misses.map((code) => `✗ ${t(`loans.miss.${code}` as StringKey)}`).join(' · ')}
            </span>
          ) : null}
        </p>
      ) : null}
      {product.summary ? <p>{product.summary}</p> : null}
      <dl className="loan__figures">
        <div>
          <dt>{t('loans.amount')}</dt>
          <dd>
            {money(product.minAmount)} – {money(product.maxAmount)}
          </dd>
        </div>
        <div>
          <dt>{t('loans.rate')}</dt>
          <dd>{range(product.rateMin, product.rateMax, '%')}</dd>
        </div>
        <div>
          <dt>{t('loans.tenure')}</dt>
          <dd>{range(product.tenureMinMonths, product.tenureMaxMonths, ` ${t('loans.months')}`)}</dd>
        </div>
      </dl>
      {product.collateral ? (
        <p className="small">
          <strong>{t('loans.collateral')}:</strong> {product.collateral}
        </p>
      ) : null}
      {product.processingFee ? (
        <p className="small">
          <strong>{t('loans.processingFee')}:</strong> {product.processingFee}
        </p>
      ) : null}
      {product.documents.length ? (
        <p className="small">
          <strong>{t('loans.documents')}:</strong>{' '}
          {product.documents.map((code) => rt(findItem('loan_documents', code))).join(', ')}
        </p>
      ) : null}
      <p className="muted small">
        {product.states.length ? t('loans.someStates', { n: product.states.length }) : t('loans.allIndia')}
      </p>
      {children}
    </article>
  );
}

/** What the applicant shared: the plan's figures, the land, how to reach them. */
export function LoanSharedFacts({ application }: { application: LoanApplication }) {
  const { t, lang, rt } = useI18n();
  const { money } = useLoanFormat();
  const { plan, land, contact, place } = application.snapshot;
  return (
    <div className="loan-facts">
      {place ? <p className="small">📍 {place}</p> : null}
      {plan ? (
        <dl className="loan__figures">
          <div>
            <dt>{t('loans.project')}</dt>
            <dd>{plan.opportunity ? pickLabel(plan.opportunity, lang) : '—'}</dd>
          </div>
          <div>
            <dt>{t('plan.startupCost')}</dt>
            <dd>{money(plan.totalProjectCost)}</dd>
          </div>
          <div>
            <dt>{t('loans.loanInReport')}</dt>
            <dd>{money(plan.termLoan)}</dd>
          </div>
          <div>
            <dt>{t('plan.netPerYear')}</dt>
            <dd>{money(plan.netPerYear)}</dd>
          </div>
        </dl>
      ) : (
        <p className="muted small">{t('loans.noReportShared')}</p>
      )}
      {plan ? <p className="muted small">{t('loans.reportNumber', { number: plan.reportNumber })}</p> : null}
      {land ? (
        <p className="small">
          🌾 {land.areaHectares != null ? `${formatNumber(land.areaHectares, lang, 2)} ha` : ''}
          {land.soilType ? ` · ${rt(findItem('soil_types', land.soilType))}` : ''}
          {land.existingCrops?.length
            ? ` · ${land.existingCrops.map((code) => rt(findItem('crops', code))).join(', ')}`
            : ''}
        </p>
      ) : null}
      {contact?.phone || contact?.email ? (
        <p className="contact">
          <strong>{t('card.contact')}:</strong>{' '}
          {contact.phone ? <a href={`tel:${contact.phone}`}>{contact.phone}</a> : null}
          {contact.phone && contact.email ? ' · ' : null}
          {contact.email ? <a href={`mailto:${contact.email}`}>{contact.email}</a> : null}
        </p>
      ) : null}
    </div>
  );
}

/** The lender's answer so far: documents asked for, the sanction, the money paid out. */
export function LoanAnswer({ application }: { application: LoanApplication }) {
  const { t, rt } = useI18n();
  const { money, date } = useLoanFormat();
  return (
    <>
      {application.status === 'documents_requested' && application.documentsRequested.length ? (
        <p className="callout callout--warn">
          📄 {t('loans.needsDocuments')}:{' '}
          {application.documentsRequested.map((code) => rt(findItem('loan_documents', code))).join(', ')}
        </p>
      ) : null}
      {application.sanctionedAmount != null ? (
        <p className="callout callout--info">
          ✓ {t('loans.sanctionedLine', {
            amount: money(application.sanctionedAmount),
            rate: application.interestRate ?? '—',
            months: application.sanctionedTenureMonths ?? '—',
          })}
        </p>
      ) : null}
      {application.disbursedAmount != null ? (
        <p className="callout callout--info">
          💰 {t('loans.disbursedLine', { amount: money(application.disbursedAmount), date: date(application.disbursedOn) })}
        </p>
      ) : null}
      {application.lenderNote ? <blockquote className="answer__message">{application.lenderNote}</blockquote> : null}
    </>
  );
}

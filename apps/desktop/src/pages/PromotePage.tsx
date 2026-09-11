import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { PromotionPlan, SubscriptionPayment } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import type { StringKey } from '../i18n';
import { api } from '../lib/api';
import { formatDate, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';

/** How often the page asks whether a payment went through, and for how long. */
const CHECK_EVERY_MS = 5000;
const STOP_CHECKING_AFTER_MS = 15 * 60 * 1000;

const REASON: Record<string, StringKey> = {
  sync_off: 'promote.reason.syncOff',
  offline: 'promote.reason.offline',
  not_shared: 'promote.reason.notShared',
  closed: 'promote.reason.closed',
  payments_off: 'promote.reason.paymentsOff',
  no_plans: 'promote.reason.noPlans',
};

const STATUS_BADGE: Record<SubscriptionPayment['status'], string> = {
  created: 'badge--status-sent',
  paid: 'badge--status-accepted',
  expired: 'badge--status-declined',
  cancelled: 'badge--status-declined',
};

/**
 * Promoting one project: a paid place at the top of investors' and partners'
 * lists and the common timeline, marked "Promoted" wherever it appears.
 * Paying happens on the payment provider's page in the browser -- UPI, a card
 * or netbanking -- and this page checks by itself until it has gone through.
 */
export function PromotePage() {
  const { requestId = '' } = useParams();
  const { t, lang } = useI18n();
  const state = useAsync((signal) => api.promotion(requestId, signal), [requestId]);
  const requests = useAsync((signal) => api.myRequests(signal), []);
  const [waiting, setWaiting] = useState<SubscriptionPayment | null>(null);
  const [justPaid, setJustPaid] = useState<SubscriptionPayment | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const data = state.data;
  const project = requests.data?.find((entry) => entry.id === requestId) ?? null;
  const rupees = (paise: number) => `₹${formatNumber(paise / 100, lang, paise % 100 ? 2 : 0)}`;
  const open = waiting ?? data?.payments.find((p) => p.status === 'created' && p.url) ?? null;

  const settle = (payment: SubscriptionPayment) => {
    setWaiting(null);
    if (payment.status === 'paid') setJustPaid(payment);
    state.reload();
  };

  // While a payment page is open in the browser, ask every few seconds.
  useEffect(() => {
    if (!waiting) return undefined;
    const started = Date.now();
    let timer: number | undefined;
    let active = true;
    const tick = async () => {
      try {
        const now = await api.checkPayment(waiting.id);
        if (!active) return;
        if (now.status !== 'created') {
          settle(now);
          return;
        }
      } catch {
        // Offline for a moment: keep trying until the time is up.
      }
      if (active && Date.now() - started < STOP_CHECKING_AFTER_MS) timer = window.setTimeout(tick, CHECK_EVERY_MS);
    };
    timer = window.setTimeout(tick, CHECK_EVERY_MS);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- follow one payment at a time
  }, [waiting?.id]);

  const openPage = (payment: SubscriptionPayment) => {
    // The desktop app opens this in the real browser, where UPI apps and saved cards are.
    if (payment.url) window.open(payment.url, '_blank', 'noopener');
  };

  const buy = async (plan: PromotionPlan) => {
    setBusy(plan.code);
    setError(null);
    setJustPaid(null);
    try {
      const payment = await api.promote(requestId, plan.code);
      openPage(payment);
      setWaiting(payment);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  const checkNow = async (payment: SubscriptionPayment) => {
    setBusy(payment.id);
    setError(null);
    try {
      const now = await api.checkPayment(payment.id);
      if (now.status === 'created') {
        setError(t('sub.notYet'));
        setWaiting(now);
      } else {
        settle(now);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  const canBuy = data && data.reason === null;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">⭐ {t('promote.title')}</h2>
          <p className="page__subtitle">{project ? project.title : t('promote.lede')}</p>
        </div>
        <Link className="button button--ghost" to="/requests">
          ← {t('requests.title')}
        </Link>
      </header>

      <section className="card promote-what">
        <ul className="promote-what__list">
          <li>🔝 {t('promote.whatTop')}</li>
          <li>⭐ {t('promote.whatLabel')}</li>
          <li>🔔 {t('promote.whatAlert')}</li>
        </ul>
        <p className="muted small">{t('promote.honest')}</p>
      </section>

      {state.loading && !data ? <p className="muted">{t('common.loading')}</p> : null}
      {state.error ? <p className="callout callout--error">{state.error.message}</p> : null}

      {data?.featured && data.promotedUntil ? (
        <p className="callout callout--info">⭐ {t('promote.featuredUntil', { date: formatDate(data.promotedUntil, lang) })}</p>
      ) : null}
      {justPaid ? (
        <p className="callout callout--info">
          ✓ {t('promote.paid', { date: justPaid.until ? formatDate(justPaid.until, lang) : '' })}
        </p>
      ) : null}

      {data?.reason && REASON[data.reason] ? (
        <p className="callout callout--info">
          {t(REASON[data.reason])}{' '}
          {data.reason === 'sync_off' ? <Link to="/settings">{t('nav.myData')} →</Link> : null}
          {data.reason === 'not_shared' || data.reason === 'closed' ? <Link to="/requests">{t('requests.title')} →</Link> : null}
        </p>
      ) : null}

      {open ? (
        <section className="card sub-waiting">
          <h3 className="card__title">{t('sub.waitingTitle', { plan: open.planName, amount: rupees(open.amountPaise) })}</h3>
          <p>{t('sub.waitingHelp')}</p>
          {waiting ? <p className="muted small">⏳ {t('sub.checking')}</p> : null}
          <div className="request__actions">
            <button type="button" className="button button--primary" disabled={busy === open.id} onClick={() => checkNow(open)}>
              {busy === open.id ? t('common.loading') : t('sub.checkNow')}
            </button>
            <button type="button" className="button" onClick={() => openPage(open)}>
              {t('sub.openAgain')} ↗
            </button>
          </div>
        </section>
      ) : null}

      {canBuy && data.plans.length ? (
        <section className="plan-grid" aria-label={t('promote.packages')}>
          {data.plans.map((plan) => (
            <article key={plan.code} className={`plan-card ${plan.alert ? 'plan-card--spotlight' : ''}`}>
              {plan.alert ? <p className="plan-card__ribbon">🔔 {t('promote.withAlert')}</p> : null}
              <h3 className="plan-card__name">{plan.name}</h3>
              <p className="plan-card__price">{rupees(plan.amountPaise)}</p>
              <p className="muted">{t(plan.days === 1 ? 'promote.forDay' : 'promote.forDays', { n: plan.days })}</p>
              <p className="small">{plan.alert ? t('promote.alertHelp') : t('promote.topHelp')}</p>
              {data.featured ? <p className="small">{t('promote.addsOn')}</p> : null}
              <button type="button" className="button button--primary" disabled={busy !== null} onClick={() => buy(plan)}>
                {busy === plan.code ? t('common.loading') : t('sub.pay', { amount: rupees(plan.amountPaise) })}
              </button>
            </article>
          ))}
        </section>
      ) : null}
      {canBuy ? <p className="muted small">{t('sub.howToPay')}</p> : null}

      {error ? <p className="callout callout--error">{error}</p> : null}

      {data?.payments.length ? (
        <section className="card">
          <h3 className="card__title">{t('sub.payments')}</h3>
          <ul className="receipts">
            {data.payments.map((payment) => (
              <li key={payment.id} className="receipts__row">
                <span>{formatDate(payment.paidAt ?? payment.createdAt, lang)}</span>
                <span>{payment.planName}</span>
                <strong>{rupees(payment.amountPaise)}</strong>
                <span className={`badge ${STATUS_BADGE[payment.status]}`}>{t(`sub.status.${payment.status}` as StringKey)}</span>
                {payment.status === 'paid' && payment.until ? (
                  <span className="muted small">{t('sub.until', { date: formatDate(payment.until, lang) })}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

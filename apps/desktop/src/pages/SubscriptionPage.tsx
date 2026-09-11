import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { MessagePack, SubscriptionPayment, SubscriptionPlan } from '@viksitgaanw/shared';

import { forgetVideoPlan } from '../components/Video';
import { useI18n } from '../i18n';
import type { StringKey } from '../i18n';
import { api } from '../lib/api';
import { formatDate, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';

/** How often the page asks whether a payment went through, and for how long. */
const CHECK_EVERY_MS = 5000;
const STOP_CHECKING_AFTER_MS = 15 * 60 * 1000;

const REASON: Record<string, StringKey> = {
  sync_off: 'sub.reason.syncOff',
  offline: 'sub.reason.offline',
  payments_off: 'sub.reason.paymentsOff',
  no_plans: 'sub.reason.noPlans',
  no_end: 'sub.reason.noEnd',
};

const STATUS_BADGE: Record<SubscriptionPayment['status'], string> = {
  created: 'badge--status-sent',
  paid: 'badge--status-accepted',
  expired: 'badge--status-declined',
  cancelled: 'badge--status-declined',
};

/**
 * Buying a subscription: what it gives, the plans on sale, and the owner's
 * payments. Paying happens on the payment provider's page in the browser --
 * UPI, a card or netbanking -- and this page checks by itself until it has
 * gone through. The core app stays free; this is only for uploading videos
 * directly.
 */
export function SubscriptionPage() {
  const { t, lang } = useI18n();
  const state = useAsync((signal) => api.subscription(signal), []);
  const [waiting, setWaiting] = useState<SubscriptionPayment | null>(null);
  const [justPaid, setJustPaid] = useState<SubscriptionPayment | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const rupees = (paise: number) => `₹${formatNumber(paise / 100, lang, paise % 100 ? 2 : 0)}`;
  const data = state.data;
  // A payment left open earlier -- say the app was closed before it went through.
  const open = waiting ?? data?.payments.find((p) => p.status === 'created' && p.url) ?? null;

  // A payment seen during a sync counts too: let the video boxes ask again.
  const subscribed = state.data?.status.subscribed;
  useEffect(() => {
    if (subscribed) forgetVideoPlan();
  }, [subscribed]);

  /** A payment is no longer open: paid, or lapsed. */
  const settle = (payment: SubscriptionPayment) => {
    setWaiting(null);
    if (payment.status === 'paid') {
      setJustPaid(payment);
      forgetVideoPlan();
    }
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

  const buy = async (plan: SubscriptionPlan | MessagePack) => {
    setBusy(plan.code);
    setError(null);
    setJustPaid(null);
    try {
      const payment = await api.checkout(plan.code);
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

  const status = data?.status;
  const canBuy = data && data.reason === null;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">⭐ {t('sub.title')}</h2>
          <p className="page__subtitle">{t('sub.lede')}</p>
        </div>
      </header>

      {state.loading && !data ? <p className="muted">{t('common.loading')}</p> : null}
      {state.error ? <p className="callout callout--error">{state.error.message}</p> : null}

      {status ? (
        <section className="card sub-status">
          {status.subscribed ? (
            <p className="sub-status__line">
              ⭐{' '}
              {status.until
                ? t('sub.activeUntil', { date: formatDate(status.until, lang) })
                : t('sub.activeNoEnd')}
            </p>
          ) : (
            <p className="sub-status__line">{t('sub.notSubscribed')}</p>
          )}
          <p className="muted small">{t('sub.gives')}</p>
        </section>
      ) : null}

      {justPaid ? (
        <p className="callout callout--info">
          ✓{' '}
          {justPaid.kind === 'messages'
            ? t('packs.paid', { n: justPaid.credits ?? 0 })
            : t('sub.paid', { date: justPaid.until ? formatDate(justPaid.until, lang) : '' })}
        </p>
      ) : null}

      {data?.reason && REASON[data.reason] ? (
        <p className="callout callout--info">
          {t(REASON[data.reason])}{' '}
          {data.reason === 'sync_off' ? <Link to="/settings">{t('nav.myData')} →</Link> : null}
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
        <section className="plan-grid" aria-label={t('sub.plans')}>
          {data.plans.map((plan) => (
            <article key={plan.code} className="plan-card">
              <h3 className="plan-card__name">{plan.name}</h3>
              <p className="plan-card__price">{rupees(plan.amountPaise)}</p>
              <p className="muted">{t(plan.months === 1 ? 'sub.forMonth' : 'sub.forMonths', { n: plan.months })}</p>
              {status?.subscribed && status.until ? (
                <p className="small">{t('sub.addsOn')}</p>
              ) : null}
              <button
                type="button"
                className="button button--primary"
                disabled={busy !== null}
                onClick={() => buy(plan)}
              >
                {busy === plan.code ? t('common.loading') : t('sub.pay', { amount: rupees(plan.amountPaise) })}
              </button>
            </article>
          ))}
        </section>
      ) : null}
      {canBuy ? <p className="muted small">{t('sub.howToPay')}</p> : null}

      {data && (data.messagePacks.length > 0 || (data.messageCredits ?? 0) > 0) ? (
        <section className="card" aria-label={t('packs.title')}>
          <h3 className="card__title">💬 {t('packs.title')}</h3>
          <p className="card__help">{t('packs.lede')}</p>
          {data.messageCredits !== null ? (
            <p className="sub-status__line">{t('packs.left', { n: data.messageCredits })}</p>
          ) : null}
          {data.paymentsAvailable && data.messagePacks.length ? (
            <div className="plan-grid">
              {data.messagePacks.map((pack) => (
                <article key={pack.code} className="plan-card">
                  <h3 className="plan-card__name">{t('packs.messages', { n: pack.credits })}</h3>
                  <p className="plan-card__price">{rupees(pack.amountPaise)}</p>
                  <p className="muted">{t('packs.each', { amount: rupees(Math.round(pack.amountPaise / pack.credits)) })}</p>
                  <button type="button" className="button button--primary" disabled={busy !== null} onClick={() => buy(pack)}>
                    {busy === pack.code ? t('common.loading') : t('sub.pay', { amount: rupees(pack.amountPaise) })}
                  </button>
                </article>
              ))}
            </div>
          ) : null}
          <p className="muted small">{t('packs.free')}</p>
        </section>
      ) : null}

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

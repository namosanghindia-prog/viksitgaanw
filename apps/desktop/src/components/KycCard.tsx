import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Profile } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import type { StringKey } from '../i18n';
import { api } from '../lib/api';
import { formatDate } from '../lib/format';
import { useAsync } from '../lib/hooks';

/** How often the card asks whether the check is done, and for how long (the link lasts 15 minutes). */
const CHECK_EVERY_MS = 5000;
const STOP_CHECKING_AFTER_MS = 15 * 60 * 1000;

/**
 * The owner's identity check. Signing in happens on the provider's own site in
 * the browser -- DigiLocker -- and the sync server alone decides; this card
 * opens the page, then asks every few seconds until the check is done. Only
 * the name, and whether the account is linked to Aadhaar, is ever kept.
 */
export function KycCard({ profile, onChanged }: { profile: Profile; onChanged: () => void }) {
  const { t, lang } = useI18n();
  // A new name can win or lose the tick: ask again when it changes.
  const state = useAsync((signal) => api.kyc(signal), [profile.id, profile.displayName]);
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const kyc = state.data;
  const status = kyc?.status ?? profile.kycStatus;
  const label = (method: string) => t(`kyc.${method}` as StringKey);
  const available = (kyc?.methods ?? []).filter((method) => method.available);
  const needsCheck = status !== 'verified';

  /** The check is no longer open: show what the server decided. */
  const settle = () => {
    setLink(null);
    state.reload();
    onChanged();
  };

  // While the provider's page is open in the browser, ask every few seconds.
  useEffect(() => {
    if (!link) return undefined;
    const started = Date.now();
    let timer: number | undefined;
    let active = true;
    const tick = async () => {
      try {
        const now = await api.kyc();
        if (!active) return;
        if (now.status !== 'pending') {
          settle();
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- follow one check at a time
  }, [link]);

  const begin = async (method: string) => {
    setBusy(true);
    setError(null);
    try {
      const started = await api.startKyc(method);
      // The desktop app opens this in the real browser, where DigiLocker's sign-in is.
      window.open(started.url, '_blank', 'noopener');
      setLink(started.url);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const checkNow = async () => {
    setBusy(true);
    setError(null);
    try {
      const now = await api.kyc();
      if (now.status === 'pending') setError(t('kyc.notYet'));
      else settle();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h3 className="card__title">{t('profile.kycTitle')}</h3>
      <p>
        <span className={`badge ${status === 'verified' ? '' : 'badge--muted'}`}>
          {status === 'verified' ? '✓ ' : ''}
          {t(`kyc.${status}`)}
        </span>
      </p>

      {status === 'verified' && kyc?.method && kyc.verifiedAt ? (
        <p>
          {t('kyc.verifiedWith', { method: label(kyc.method), date: formatDate(kyc.verifiedAt, lang) })}
          {kyc.aadhaarBacked ? ` ${t('kyc.aadhaarBacked')}` : ''}
        </p>
      ) : null}

      {kyc?.nameMatches === false && kyc.registeredName && kyc.method ? (
        <p className="callout callout--error">
          {t('kyc.nameMismatch', { method: label(kyc.method), name: kyc.registeredName })}
        </p>
      ) : null}

      {kyc?.reason === 'sync_off' ? (
        <p className="callout callout--info">
          {t('kyc.syncOff')} <Link to="/settings">{t('nav.myData')} →</Link>
        </p>
      ) : null}
      {kyc?.reason === 'offline' ? <p className="callout callout--info">{t('kyc.offline')}</p> : null}
      {kyc?.sandbox ? <p className="muted small">⚠ {t('kyc.sandboxNote')}</p> : null}

      {link ? (
        <div className="sub-waiting">
          <p>{t('kyc.waiting')}</p>
          <p className="muted small">⏳ {t('sub.checking')}</p>
          <div className="request__actions">
            <button type="button" className="button button--primary" disabled={busy} onClick={checkNow}>
              {busy ? t('common.loading') : t('kyc.checkNow')}
            </button>
            <button type="button" className="button" onClick={() => window.open(link, '_blank', 'noopener')}>
              {t('kyc.openAgain')} ↗
            </button>
          </div>
        </div>
      ) : needsCheck && available.length ? (
        profile.visibility !== 'online' ? (
          <p className="card__help">{t('kyc.shareFirst')}</p>
        ) : (
          <>
            <p className="card__help">
              {t('kyc.intro', { method: available.map((method) => label(method.code)).join(' / ') })}
            </p>
            <div className="request__actions">
              {available.map((method) => (
                <button
                  key={method.code}
                  type="button"
                  className="button button--primary"
                  disabled={busy}
                  onClick={() => begin(method.code)}
                >
                  {busy ? t('common.loading') : t('kyc.verifyWith', { method: label(method.code) })} ↗
                </button>
              ))}
            </div>
          </>
        )
      ) : needsCheck && kyc && !kyc.reason ? (
        <p className="card__help">
          {t('profile.kycSoon', { methods: kyc.planned.map(label).join(' / ') })}
        </p>
      ) : null}

      {error ? <p className="callout callout--error">{error}</p> : null}
    </section>
  );
}

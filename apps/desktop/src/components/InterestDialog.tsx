import { useEffect, useMemo, useState } from 'react';
import type { InvestmentRequest, Seeking } from '@viksitgaanw/shared';
import { REFERENCE } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { ChoiceGroup } from './ChoiceGroup';
import { TextField } from './TextField';

interface InterestDialogProps {
  request: InvestmentRequest;
  kind: Seeking;
  onClose: () => void;
  onSent: (request: InvestmentRequest) => void;
}

/**
 * Answer a farmer's request: an investment offer or a partnership offer,
 * following the responder's own profile type.
 *
 * Only the ways the farmer said they would accept are offered, so an
 * investor cannot propose an equity stake to someone who asked for a loan.
 */
export function InterestDialog({ request, kind, onClose, onSent }: InterestDialogProps) {
  const { t } = useI18n();
  const existing = request.myInterest;

  const [amount, setAmount] = useState(existing?.amountOffered ? String(existing.amountOffered) : '');
  const [mode, setMode] = useState<string | null>(existing?.mode ?? null);
  const [partnershipType, setPartnershipType] = useState<string | null>(existing?.partnershipType ?? null);
  const [message, setMessage] = useState(existing?.message ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  const modes = useMemo(
    () => REFERENCE.investment_modes.items.filter((item) => request.modes.includes(item.code)),
    [request.modes],
  );
  const partnerships = useMemo(
    () => REFERENCE.partnership_types.items.filter((item) => request.partnershipTypes.includes(item.code)),
    [request.partnershipTypes],
  );

  const submit = async () => {
    if (kind === 'investment' && !mode) {
      setError(`${t('interest.mode')}: ${t('error.chooseOne')}`);
      return;
    }
    if (kind === 'partnership' && !partnershipType) {
      setError(`${t('interest.partnershipType')}: ${t('error.chooseOne')}`);
      return;
    }
    const amountNumber = Number.parseFloat(amount);
    setBusy(true);
    setError(null);
    try {
      const updated = await api.sendInterest(request.id, {
        kind,
        amountOffered: kind === 'investment' && Number.isFinite(amountNumber) && amountNumber > 0 ? amountNumber : null,
        mode: kind === 'investment' ? mode : null,
        partnershipType: kind === 'partnership' ? partnershipType : null,
        message: message.trim() || null,
      });
      onSent(updated);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  const title = kind === 'investment' ? t('interest.title') : t('interest.partnerTitle');

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal__backdrop" onClick={() => (busy ? undefined : onClose())} />
      <div className="modal__panel">
        <header className="modal__head">
          <div>
            <h3 className="modal__title">{title}</h3>
            <p className="modal__subtitle">{request.title}</p>
          </div>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={onClose}
            disabled={busy}
            aria-label={t('common.cancel')}
          >
            ✕
          </button>
        </header>

        <div className="modal__body stack">
          {kind === 'investment' ? (
            <>
              <ChoiceGroup label={t('interest.mode')} items={modes} value={mode} onChange={setMode} />
              <TextField
                id="interestAmount"
                label={t('interest.amount')}
                type="number"
                inputMode="numeric"
                min={0}
                value={amount}
                onChange={setAmount}
                optional
              />
            </>
          ) : (
            <ChoiceGroup
              label={t('interest.partnershipType')}
              items={partnerships}
              value={partnershipType}
              onChange={setPartnershipType}
            />
          )}

          <TextField
            id="interestMessage"
            label={t('interest.message')}
            hint={t('interest.messageHint')}
            value={message}
            onChange={setMessage}
            multiline
            optional
            maxLength={2000}
          />

          <p className="callout callout--info">{t('interest.noMoney')}</p>
          {error ? <p className="callout callout--error">{error}</p> : null}
        </div>

        <footer className="modal__foot">
          <button type="button" className="button button--ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </button>
          <button type="button" className="button button--primary" onClick={submit} disabled={busy}>
            {busy ? t('interest.sending') : t('interest.send')}
          </button>
        </footer>
      </div>
    </div>
  );
}

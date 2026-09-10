import { useEffect, useState } from 'react';
import type { Equipment } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { TextField } from './TextField';

interface EnquiryDialogProps {
  item: Equipment;
  kind: 'rent' | 'buy';
  onClose: () => void;
  onSent: (item: Equipment) => void;
}

/** Ask a seller to rent or sell a machine. Nothing is paid here. */
export function EnquiryDialog({ item, kind, onClose, onSent }: EnquiryDialogProps) {
  const { t } = useI18n();
  const pending = item.myEnquiry?.status === 'sent' && item.myEnquiry.kind === kind ? item.myEnquiry : null;

  const [quantity, setQuantity] = useState(String(pending?.quantity ?? 1));
  const [from, setFrom] = useState(pending?.startDate ?? '');
  const [to, setTo] = useState(pending?.endDate ?? '');
  const [acres, setAcres] = useState(pending?.areaAcres ? String(pending.areaAcres) : '');
  const [message, setMessage] = useState(pending?.message ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const count = Number.parseInt(quantity, 10);
    const area = Number.parseFloat(acres);
    try {
      const updated = await api.sendEnquiry(item.id, {
        kind,
        quantity: Number.isFinite(count) && count > 0 ? count : 1,
        startDate: kind === 'rent' ? from || null : null,
        endDate: kind === 'rent' ? to || null : null,
        areaAcres: kind === 'rent' && Number.isFinite(area) && area > 0 ? area : null,
        message: message.trim() || null,
      });
      onSent(updated);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  const title = kind === 'rent' ? t('enquiry.rentTitle') : t('enquiry.buyTitle');

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal__backdrop" onClick={() => (busy ? undefined : onClose())} />
      <div className="modal__panel">
        <header className="modal__head">
          <div>
            <h3 className="modal__title">{title}</h3>
            <p className="modal__subtitle">{item.title}</p>
          </div>
          <button type="button" className="button button--ghost button--small" onClick={onClose} disabled={busy} aria-label={t('common.cancel')}>
            ✕
          </button>
        </header>

        <div className="modal__body stack">
          {item.quantity > 1 ? (
            <div className="narrow">
              <TextField id="enquiryQuantity" label={t('enquiry.quantity')} type="number" inputMode="numeric" min={1} value={quantity} onChange={setQuantity} />
            </div>
          ) : null}
          {kind === 'rent' ? (
            <>
              <div className="field-row">
                <TextField id="enquiryFrom" label={t('enquiry.from')} type="date" value={from} onChange={setFrom} optional />
                <TextField id="enquiryTo" label={t('enquiry.to')} type="date" value={to} onChange={setTo} optional />
              </div>
              {item.rentUnit === 'acre' ? (
                <div className="narrow">
                  <TextField id="enquiryAcres" label={t('enquiry.acres')} type="number" inputMode="decimal" min={0} value={acres} onChange={setAcres} optional />
                </div>
              ) : null}
            </>
          ) : null}
          <TextField
            id="enquiryMessage"
            label={t('enquiry.message')}
            hint={t('interest.messageHint')}
            value={message}
            onChange={setMessage}
            multiline
            optional
            maxLength={2000}
          />
          <p className="callout callout--info">{t('enquiry.noMoney')}</p>
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

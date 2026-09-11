import { useEffect, useMemo, useState } from 'react';
import type { ProfileCard } from '@viksitgaanw/shared';
import { REFERENCE } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useProfile } from '../lib/profile';
import { ChoiceGroup } from './ChoiceGroup';
import { TextField } from './TextField';

interface AskPartnerDialogProps {
  seller: ProfileCard;
  onClose: () => void;
  onSent: () => void;
}

/**
 * A farmer (or a distributor organisation) asking an equipment seller to take
 * them on: to keep machines for hire in their village, run them, sell them.
 */
export function AskPartnerDialog({ seller, onClose, onSent }: AskPartnerDialogProps) {
  const { t } = useI18n();
  const { profile } = useProfile();
  const farmer = profile?.segment === 'farmer';

  const roles = useMemo(
    () =>
      REFERENCE.partner_roles.items.filter((item) =>
        farmer ? item.code !== 'distributor' : ['distributor', 'sales_agent', 'service_centre'].includes(item.code),
      ),
    [farmer],
  );
  const [role, setRole] = useState<string | null>(roles[0]?.code ?? null);
  const [types, setTypes] = useState<string[]>([]);
  const [message, setMessage] = useState('');
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
    if (!role) {
      setError(`${t('askPartner.role')}: ${t('error.chooseOne')}`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.askToPartner(seller.id, { role, equipmentTypes: types, message: message.trim() || null });
      onSent();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  const name = seller.organisationName || seller.displayName;
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={t('askPartner.title', { seller: name })}>
      <div className="modal__backdrop" onClick={() => (busy ? undefined : onClose())} />
      <div className="modal__panel">
        <header className="modal__head">
          <h3 className="modal__title">{t('askPartner.title', { seller: name })}</h3>
          <button type="button" className="button button--ghost button--small" onClick={onClose} disabled={busy} aria-label={t('common.cancel')}>
            ✕
          </button>
        </header>
        <div className="modal__body stack">
          <ChoiceGroup label={t('askPartner.role')} items={roles} allowCustom value={role} onChange={setRole} />
          <ChoiceGroup
            label={t('askPartner.types')}
            hint={t('addPartner.typesHint')}
            items={REFERENCE.equipment_types.items}
            allowCustom
            categories={REFERENCE.equipment_types.categories}
            multiple
            value={types}
            onChange={setTypes}
          />
          <TextField id="askMessage" label={t('askPartner.message')} value={message} onChange={setMessage} multiline optional maxLength={2000} />
          <p className="callout callout--info">{t('askPartner.note')}</p>
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

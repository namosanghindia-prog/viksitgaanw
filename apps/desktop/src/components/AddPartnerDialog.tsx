import { useEffect, useMemo, useState } from 'react';
import type { AdminLevel, LocationSelection, PartnerKind, ReferenceItem, Segment } from '@viksitgaanw/shared';
import { REFERENCE } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useAsync } from '../lib/hooks';
import { useProfile } from '../lib/profile';
import { ChoiceGroup } from './ChoiceGroup';
import { LocationCascader } from './LocationCascader';
import { Picker } from './Picker';
import { TextField } from './TextField';

const KINDS: PartnerKind[] = ['farmer', 'village', 'district', 'distributor'];

/** Who may be picked from the platform for each kind of partner. */
const SEGMENTS_FOR: Record<PartnerKind, Segment[]> = {
  farmer: ['farmer'],
  distributor: ['partner_national', 'partner_international'],
  village: ['farmer', 'government', 'partner_national'],
  district: ['farmer', 'government', 'partner_national'],
};

/** The area a kind of partner needs: a village, a district, or nothing. */
const AREA: Record<PartnerKind, { depth: AdminLevel; required: AdminLevel[] }> = {
  farmer: { depth: 'village', required: [] },
  village: { depth: 'village', required: ['state', 'district', 'subdistrict', 'village'] },
  district: { depth: 'district', required: ['state', 'district'] },
  distributor: { depth: 'district', required: [] },
};

const DEFAULT_ROLE: Record<PartnerKind, string> = {
  farmer: 'rental_point',
  village: 'rental_point',
  district: 'distributor',
  distributor: 'distributor',
};

/**
 * A seller adds someone to their network.
 *
 * Many village partners will never install the app, so a partner can be
 * recorded by name and phone as well as picked from the platform. Only the
 * second kind has to accept.
 */
export function AddPartnerDialog({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const { t } = useI18n();
  const { profile } = useProfile();

  const [kind, setKind] = useState<PartnerKind>('village');
  const [onPlatform, setOnPlatform] = useState(false);
  const [partnerId, setPartnerId] = useState<string | null>(null);
  const [contactName, setContactName] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [area, setArea] = useState<LocationSelection>({
    stateCode: profile?.stateCode ?? null,
    districtCode: profile?.districtCode ?? null,
    subdistrictCode: null,
    villageCode: null,
  });
  const [role, setRole] = useState<string | null>(DEFAULT_ROLE.village);
  const [types, setTypes] = useState<string[]>([]);
  const [commission, setCommission] = useState('');
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

  const known = useAsync((signal) => api.knownProfiles(SEGMENTS_FOR[kind], signal), [kind], {
    enabled: onPlatform,
  });

  const kindItems = useMemo<ReferenceItem[]>(
    () => KINDS.map((code) => ({ code, label: { en: t(`partners.kind.${code}`), hi: t(`partners.kind.${code}`) } })),
    [t],
  );
  const whereItems = useMemo<ReferenceItem[]>(
    () => [
      { code: 'yes', label: { en: t('addPartner.onPlatform'), hi: t('addPartner.onPlatform') } },
      { code: 'no', label: { en: t('addPartner.offPlatform'), hi: t('addPartner.offPlatform') } },
    ],
    [t],
  );

  const pickKind = (next: string | null) => {
    if (!next) return;
    const value = next as PartnerKind;
    setKind(value);
    setRole(DEFAULT_ROLE[value]);
    setPartnerId(null);
    // Farmers and distributors are usually on the platform; a village or a
    // district partner usually is not.
    setOnPlatform(value === 'farmer' || value === 'distributor');
  };

  const submit = async () => {
    if (!role) {
      setError(`${t('addPartner.role')}: ${t('error.chooseOne')}`);
      return;
    }
    if (onPlatform ? !partnerId : !contactName.trim()) {
      setError(onPlatform ? t('addPartner.pick') : `${t('addPartner.contactName')}: ${t('error.required')}`);
      return;
    }
    const percent = Number.parseFloat(commission);
    setBusy(true);
    setError(null);
    try {
      await api.addPartner({
        partnerKind: kind,
        partnerProfileId: onPlatform ? partnerId : null,
        contactName: onPlatform ? null : contactName.trim(),
        contactPhone: onPlatform ? null : contactPhone.trim() || null,
        ...area,
        role,
        equipmentTypes: types,
        commissionPercent: Number.isFinite(percent) ? percent : null,
        message: message.trim() || null,
      });
      onAdded();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  const options = (known.data ?? []).map((card) => ({
    value: card.id,
    label: card.organisationName || card.displayName,
    sublabel: card.place,
  }));

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={t('addPartner.title')}>
      <div className="modal__backdrop" onClick={() => (busy ? undefined : onClose())} />
      <div className="modal__panel modal__panel--wide">
        <header className="modal__head">
          <h3 className="modal__title">{t('addPartner.title')}</h3>
          <button type="button" className="button button--ghost button--small" onClick={onClose} disabled={busy} aria-label={t('common.cancel')}>
            ✕
          </button>
        </header>
        <div className="modal__body stack">
          <ChoiceGroup label={t('addPartner.kind')} items={kindItems} value={kind} onChange={pickKind} />
          <ChoiceGroup
            label={t('addPartner.who')}
            items={whereItems}
            value={onPlatform ? 'yes' : 'no'}
            onChange={(value) => setOnPlatform(value === 'yes')}
          />

          {onPlatform ? (
            options.length || known.loading ? (
              <Picker
                label={t('addPartner.pick')}
                placeholder={t('addPartner.pick')}
                options={options}
                value={partnerId}
                onChange={setPartnerId}
                loading={known.loading}
                required
              />
            ) : (
              <p className="callout callout--warn">{t('addPartner.noneKnown')}</p>
            )
          ) : (
            <div className="field-row">
              <TextField id="partnerName" label={t('addPartner.contactName')} value={contactName} onChange={setContactName} required maxLength={160} />
              <TextField id="partnerPhone" label={t('addPartner.contactPhone')} type="tel" inputMode="tel" value={contactPhone} onChange={setContactPhone} optional maxLength={20} />
            </div>
          )}

          <fieldset className="field">
            <legend className="field__label">{t('addPartner.area')}</legend>
            <LocationCascader value={area} onChange={setArea} depth={AREA[kind].depth} requiredLevels={AREA[kind].required} />
          </fieldset>

          <ChoiceGroup label={t('addPartner.role')} items={REFERENCE.partner_roles.items} value={role} onChange={setRole} />
          <ChoiceGroup
            label={t('addPartner.types')}
            hint={t('addPartner.typesHint')}
            items={REFERENCE.equipment_types.items}
            categories={REFERENCE.equipment_types.categories}
            multiple
            value={types}
            onChange={setTypes}
          />
          <div className="narrow">
            <TextField id="commission" label={t('addPartner.commission')} type="number" inputMode="decimal" min={0} value={commission} onChange={setCommission} optional />
          </div>
          <TextField id="partnerMessage" label={t('interest.message')} value={message} onChange={setMessage} multiline optional maxLength={2000} />
          <p className="callout callout--info">{t('addPartner.offPlatformNote')}</p>
          {error ? <p className="callout callout--error">{error}</p> : null}
        </div>
        <footer className="modal__foot">
          <button type="button" className="button button--ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </button>
          <button type="button" className="button button--primary" onClick={submit} disabled={busy}>
            {busy ? t('common.saving') : t('common.save')}
          </button>
        </footer>
      </div>
    </div>
  );
}

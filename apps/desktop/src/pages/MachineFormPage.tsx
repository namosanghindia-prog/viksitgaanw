import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import type { EquipmentInput, ListingStatus, LocationSelection, ReferenceItem, RentUnit } from '@viksitgaanw/shared';
import { REFERENCE } from '@viksitgaanw/shared';

import { ChoiceGroup } from '../components/ChoiceGroup';
import { LocationCascader } from '../components/LocationCascader';
import { CheckField, TextField } from '../components/TextField';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useAsync } from '../lib/hooks';
import { useProfile } from '../lib/profile';

/** Add a machine, or change one. It is saved offline; sharing is a separate step. */
export function MachineFormPage() {
  const { listingId } = useParams();
  const { t } = useI18n();
  const { profile } = useProfile();
  const navigate = useNavigate();
  const existing = useAsync((signal) => api.getEquipment(listingId!, signal), [listingId], {
    enabled: Boolean(listingId),
  });

  const [type, setType] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [brand, setBrand] = useState('');
  const [model, setModel] = useState('');
  const [year, setYear] = useState('');
  const [condition, setCondition] = useState<string | null>('new');
  const [description, setDescription] = useState('');
  const [offers, setOffers] = useState<string[]>(['rent']);
  const [salePrice, setSalePrice] = useState('');
  const [rentRate, setRentRate] = useState('');
  const [rentUnit, setRentUnit] = useState<string | null>('hour');
  const [quantity, setQuantity] = useState('1');
  const [withOperator, setWithOperator] = useState(false);
  const [delivery, setDelivery] = useState(false);
  const [status, setStatus] = useState<string | null>('active');
  const [place, setPlace] = useState<LocationSelection>({
    stateCode: profile?.stateCode ?? null,
    districtCode: profile?.districtCode ?? null,
    subdistrictCode: null,
    villageCode: null,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const item = existing.data;
    if (!item) return;
    setType(item.equipmentType);
    setTitle(item.title);
    setBrand(item.brand ?? '');
    setModel(item.model ?? '');
    setYear(item.yearMade ? String(item.yearMade) : '');
    setCondition(item.condition);
    setDescription(item.description ?? '');
    setOffers([...(item.forRent ? ['rent'] : []), ...(item.forSale ? ['sale'] : [])]);
    setSalePrice(item.salePrice ? String(item.salePrice) : '');
    setRentRate(item.rentRate ? String(item.rentRate) : '');
    setRentUnit(item.rentUnit ?? 'hour');
    setQuantity(String(item.quantity));
    setWithOperator(item.withOperator);
    setDelivery(item.delivery);
    setStatus(item.status);
    setPlace({ stateCode: item.stateCode, districtCode: item.districtCode ?? null, subdistrictCode: item.subdistrictCode ?? null, villageCode: null });
  }, [existing.data]);

  const offerItems = useMemo<ReferenceItem[]>(
    () => [
      { code: 'rent', label: { en: t('equipment.forRent'), hi: t('equipment.forRent') } },
      { code: 'sale', label: { en: t('equipment.forSale'), hi: t('equipment.forSale') } },
    ],
    [t],
  );
  const statusItems = useMemo<ReferenceItem[]>(
    () =>
      (['active', 'paused', 'sold'] as const).map((code) => ({
        code,
        label: { en: t(`equipment.status.${code}`), hi: t(`equipment.status.${code}`) },
      })),
    [t],
  );

  const save = async () => {
    const number = (text: string) => {
      const value = Number.parseFloat(text);
      return Number.isFinite(value) && value > 0 ? value : null;
    };
    if (!type || !title.trim() || !place.stateCode || offers.length === 0) {
      setError(t('error.checkForm'));
      return;
    }
    const body: EquipmentInput = {
      equipmentType: type,
      title: title.trim(),
      brand: brand.trim() || null,
      model: model.trim() || null,
      yearMade: number(year),
      condition: condition ?? 'new',
      description: description.trim() || null,
      forSale: offers.includes('sale'),
      salePrice: offers.includes('sale') ? number(salePrice) : null,
      forRent: offers.includes('rent'),
      rentRate: offers.includes('rent') ? number(rentRate) : null,
      rentUnit: offers.includes('rent') ? ((rentUnit as RentUnit | null) ?? null) : null,
      quantity: Math.max(1, Math.round(number(quantity) ?? 1)),
      withOperator,
      delivery,
      stateCode: place.stateCode,
      districtCode: place.districtCode,
      subdistrictCode: place.subdistrictCode,
      status: (status as ListingStatus | null) ?? 'active',
    };
    setBusy(true);
    setError(null);
    try {
      if (listingId) await api.updateEquipment(listingId, body);
      else await api.createEquipment(body);
      navigate('/my-machines');
    } catch (cause) {
      setError(t('error.saveFailed', { detail: cause instanceof Error ? cause.message : String(cause) }));
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <header className="page__header">
        <h2 className="page__title">{listingId ? t('machineForm.editTitle') : t('machineForm.newTitle')}</h2>
      </header>

      <section className="card">
        <ChoiceGroup
          label={t('machineForm.type')}
          items={REFERENCE.equipment_types.items}
          allowCustom
          categories={REFERENCE.equipment_types.categories}
          value={type}
          onChange={setType}
        />
        <TextField id="machineTitle" label={t('machineForm.title')} hint={t('machineForm.titleHint')} value={title} onChange={setTitle} required maxLength={200} />
        <div className="field-row">
          <TextField id="brand" label={t('machineForm.brand')} value={brand} onChange={setBrand} optional maxLength={80} />
          <TextField id="model" label={t('machineForm.model')} value={model} onChange={setModel} optional maxLength={80} />
        </div>
        <div className="field-row">
          <TextField id="year" label={t('machineForm.year')} type="number" inputMode="numeric" min={1950} value={year} onChange={setYear} optional />
          <TextField id="quantity" label={t('machineForm.quantity')} type="number" inputMode="numeric" min={1} value={quantity} onChange={setQuantity} />
        </div>
        <ChoiceGroup label={t('machineForm.condition')} items={REFERENCE.equipment_conditions.items} allowCustom value={condition} onChange={setCondition} />
        <TextField id="machineDescription" label={t('machineForm.description')} value={description} onChange={setDescription} multiline optional maxLength={4000} />
      </section>

      <section className="card">
        <ChoiceGroup label={t('machineForm.offer')} items={offerItems} multiple value={offers} onChange={setOffers} />
        {offers.includes('rent') ? (
          <div className="field-row">
            <TextField id="rentRate" label={t('machineForm.rentRate')} type="number" inputMode="numeric" min={0} value={rentRate} onChange={setRentRate} required />
            <ChoiceGroup label={t('machineForm.rentUnit')} items={REFERENCE.rent_units.items} value={rentUnit} onChange={setRentUnit} />
          </div>
        ) : null}
        {offers.includes('sale') ? (
          <div className="narrow">
            <TextField id="salePrice" label={t('machineForm.salePrice')} type="number" inputMode="numeric" min={0} value={salePrice} onChange={setSalePrice} required />
          </div>
        ) : null}
        <CheckField label={t('equipment.withOperator')} checked={withOperator} onChange={setWithOperator} />
        <CheckField label={t('equipment.delivery')} checked={delivery} onChange={setDelivery} />
        {listingId ? <ChoiceGroup label={t('machineForm.status')} items={statusItems} value={status} onChange={setStatus} /> : null}
      </section>

      <section className="card">
        <h3 className="card__title">{t('machineForm.where')}</h3>
        <LocationCascader value={place} onChange={setPlace} depth="subdistrict" requiredLevels={['state']} />
      </section>

      {!listingId ? <p className="callout callout--info">{t('machineForm.photosAfter')} {t('share.draftNote')}</p> : null}
      {error ? <p className="callout callout--error">{error}</p> : null}

      <div className="actions">
        <button type="button" className="button button--ghost" onClick={() => navigate('/my-machines')} disabled={busy}>
          {t('common.cancel')}
        </button>
        <button type="button" className="button button--primary" onClick={save} disabled={busy}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>
    </div>
  );
}

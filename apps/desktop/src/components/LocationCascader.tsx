import { useCallback, useMemo, useState } from 'react';
import type { AdminUnit, LocationSelection } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useAsync, useDebounced } from '../lib/hooks';
import { Picker, type PickerOption } from './Picker';

interface LocationCascaderProps {
  value: LocationSelection;
  onChange: (value: LocationSelection) => void;
  errors?: Partial<Record<keyof LocationSelection, string>>;
}

const EMPTY: AdminUnit[] = [];

function toOptions(units: AdminUnit[] | null): PickerOption[] {
  return (units ?? EMPTY).map((unit) => ({
    value: unit.code,
    label: unit.name,
    sublabel: unit.nameLocal,
  }));
}

/**
 * State -> district -> block/tehsil -> village, straight off the offline LGD
 * dataset.
 *
 * Choosing a level clears everything below it: keeping a stale village under a
 * newly-chosen district is how you end up with a project report addressed to a
 * place that does not exist.
 */
export function LocationCascader({ value, onChange, errors = {} }: LocationCascaderProps) {
  const { t } = useI18n();
  const [villageQuery, setVillageQuery] = useState('');
  const debouncedVillageQuery = useDebounced(villageQuery, 250);

  const states = useAsync((signal) => api.states(signal), []);

  const districts = useAsync(
    (signal) => api.districts(value.stateCode!, signal),
    [value.stateCode],
    { enabled: Boolean(value.stateCode) },
  );

  const subdistricts = useAsync(
    (signal) => api.subdistricts(value.districtCode!, signal),
    [value.districtCode],
    { enabled: Boolean(value.districtCode) },
  );

  const villages = useAsync(
    (signal) =>
      api.villages(
        {
          subdistrictCode: value.subdistrictCode!,
          q: debouncedVillageQuery.trim() || undefined,
        },
        signal,
      ),
    [value.subdistrictCode, debouncedVillageQuery],
    { enabled: Boolean(value.subdistrictCode) },
  );

  const setState = useCallback(
    (stateCode: string | null) => {
      onChange({
        stateCode,
        districtCode: null,
        subdistrictCode: null,
        villageCode: null,
      });
      setVillageQuery('');
    },
    [onChange],
  );

  const setDistrict = useCallback(
    (districtCode: string | null) => {
      onChange({ ...value, districtCode, subdistrictCode: null, villageCode: null });
      setVillageQuery('');
    },
    [onChange, value],
  );

  const setSubdistrict = useCallback(
    (subdistrictCode: string | null) => {
      onChange({ ...value, subdistrictCode, villageCode: null });
      setVillageQuery('');
    },
    [onChange, value],
  );

  const setVillage = useCallback(
    (villageCode: string | null) => onChange({ ...value, villageCode }),
    [onChange, value],
  );

  // A searched village may not be in the current page of results once picked,
  // so keep the chosen one in the option list to render its name.
  const villageOptions = useMemo(() => {
    const options = toOptions(villages.data);
    if (value.villageCode && !options.some((option) => option.value === value.villageCode)) {
      const chosen = (villages.data ?? EMPTY).find((unit) => unit.code === value.villageCode);
      if (chosen) options.unshift({ value: chosen.code, label: chosen.name });
    }
    return options;
  }, [villages.data, value.villageCode]);

  return (
    <div className="cascader">
      <Picker
        label={t('location.state')}
        placeholder={t('location.chooseState')}
        options={toOptions(states.data)}
        value={value.stateCode}
        onChange={setState}
        loading={states.loading}
        required
        error={errors.stateCode}
      />

      <Picker
        label={t('location.district')}
        placeholder={t('location.chooseDistrict')}
        options={toOptions(districts.data)}
        value={value.districtCode}
        onChange={setDistrict}
        disabled={!value.stateCode}
        disabledHint={t('location.pickParentFirst')}
        loading={districts.loading}
        required
        error={errors.districtCode}
      />

      <Picker
        label={t('location.subdistrict')}
        placeholder={t('location.chooseSubdistrict')}
        options={toOptions(subdistricts.data)}
        value={value.subdistrictCode}
        onChange={setSubdistrict}
        disabled={!value.districtCode}
        disabledHint={t('location.pickParentFirst')}
        loading={subdistricts.loading}
        allowClear
      />

      <Picker
        label={t('location.village')}
        placeholder={t('location.chooseVillage')}
        options={villageOptions}
        value={value.villageCode}
        onChange={setVillage}
        disabled={!value.subdistrictCode}
        disabledHint={t('location.pickParentFirst')}
        loading={villages.loading}
        hint={t('location.villageOptional')}
        searchValue={villageQuery}
        onSearchChange={setVillageQuery}
        searchPlaceholder={t('location.searchVillage')}
        allowClear
      />
    </div>
  );
}

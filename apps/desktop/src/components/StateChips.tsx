import { useMemo } from 'react';
import type { ReferenceItem } from '@viksitgaanw/shared';

import { api } from '../lib/api';
import { useAsync } from '../lib/hooks';
import { ChoiceGroup } from './ChoiceGroup';

interface StateChipsProps {
  label: string;
  hint?: string;
  value: string[];
  onChange: (value: string[]) => void;
}

/** Pick several Indian states, from the same offline LGD data as everything else. */
export function StateChips({ label, hint, value, onChange }: StateChipsProps) {
  const states = useAsync((signal) => api.states(signal), []);

  const items = useMemo<ReferenceItem[]>(
    () =>
      (states.data ?? []).map((unit) => ({
        code: unit.code,
        label: { en: unit.name, hi: unit.nameLocal || unit.name },
      })),
    [states.data],
  );

  return (
    <ChoiceGroup label={label} hint={hint} items={items} multiple value={value} onChange={onChange} />
  );
}

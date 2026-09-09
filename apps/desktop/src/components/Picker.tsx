import { useCallback, useMemo, useState } from 'react';

import { useI18n } from '../i18n';
import { useDismissable } from '../lib/hooks';

export interface PickerOption {
  value: string;
  label: string;
  /** Shown under the label -- the name in the local script, for instance. */
  sublabel?: string | null;
}

interface PickerProps {
  label: string;
  placeholder: string;
  options: PickerOption[];
  value: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
  disabledHint?: string;
  loading?: boolean;
  required?: boolean;
  hint?: string;
  error?: string | null;
  /** Search text is handled by the parent, so it can query the API instead. */
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  allowClear?: boolean;
}

/**
 * A searchable single-choice picker.
 *
 * A native <select> is unusable for 600 villages and hard to read at arm's
 * length on a shared laptop, so this renders a large touch target that opens a
 * filterable list. When `onSearchChange` is supplied the parent owns filtering
 * (used for village search, which hits the API); otherwise filtering is local.
 */
export function Picker({
  label,
  placeholder,
  options,
  value,
  onChange,
  disabled = false,
  disabledHint,
  loading = false,
  required = false,
  hint,
  error,
  searchValue,
  onSearchChange,
  searchPlaceholder,
  allowClear = false,
}: PickerProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [localQuery, setLocalQuery] = useState('');

  const close = useCallback(() => {
    setOpen(false);
    setLocalQuery('');
  }, []);
  const containerRef = useDismissable<HTMLDivElement>(open, close);

  const remoteSearch = typeof onSearchChange === 'function';
  const query = remoteSearch ? (searchValue ?? '') : localQuery;

  const visible = useMemo(() => {
    if (remoteSearch) return options;
    const needle = localQuery.trim().toLowerCase();
    if (!needle) return options;
    return options.filter(
      (option) =>
        option.label.toLowerCase().includes(needle) ||
        (option.sublabel ?? '').toLowerCase().includes(needle),
    );
  }, [options, localQuery, remoteSearch]);

  const selected = options.find((option) => option.value === value) ?? null;

  const handleSearch = (next: string) => {
    if (remoteSearch) onSearchChange?.(next);
    else setLocalQuery(next);
  };

  const select = (option: PickerOption) => {
    onChange(option.value);
    close();
  };

  return (
    <div className="field" ref={containerRef}>
      <label className="field__label" id={`picker-${label}`}>
        {label}
        {required ? <span className="field__required"> *</span> : null}
      </label>
      {hint ? <p className="field__hint">{hint}</p> : null}

      <button
        type="button"
        className={`picker__trigger ${error ? 'picker__trigger--error' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`picker-${label}`}
        disabled={disabled || loading}
        onClick={() => setOpen((current) => !current)}
      >
        <span className={selected ? 'picker__value' : 'picker__placeholder'}>
          {loading
            ? t('common.loading')
            : disabled && disabledHint
              ? disabledHint
              : (selected?.label ?? placeholder)}
        </span>
        {selected?.sublabel ? (
          <span className="picker__sublabel">{selected.sublabel}</span>
        ) : null}
        <span className="picker__chevron" aria-hidden="true">
          ▾
        </span>
      </button>

      {open ? (
        <div className="picker__panel" role="listbox">
          <input
            type="text"
            className="picker__search"
            value={query}
            autoFocus
            placeholder={searchPlaceholder ?? t('common.search')}
            onChange={(event) => handleSearch(event.target.value)}
          />

          {allowClear && value ? (
            <button
              type="button"
              className="picker__option picker__option--clear"
              onClick={() => {
                onChange(null);
                close();
              }}
            >
              {t('common.notSelected')}
            </button>
          ) : null}

          <div className="picker__list">
            {loading ? <p className="picker__empty">{t('common.loading')}</p> : null}
            {!loading && visible.length === 0 ? (
              <p className="picker__empty">{t('location.noResults')}</p>
            ) : null}
            {visible.map((option) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                className={`picker__option ${
                  option.value === value ? 'picker__option--selected' : ''
                }`}
                onClick={() => select(option)}
              >
                <span className="picker__option-label">{option.label}</span>
                {option.sublabel ? (
                  <span className="picker__option-sublabel">{option.sublabel}</span>
                ) : null}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {error ? <p className="field__error">{error}</p> : null}
    </div>
  );
}

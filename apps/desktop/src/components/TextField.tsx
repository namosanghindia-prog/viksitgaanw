import type { InputHTMLAttributes } from 'react';

import { useI18n } from '../i18n';

interface TextFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  error?: string | null;
  required?: boolean;
  optional?: boolean;
  multiline?: boolean;
  type?: InputHTMLAttributes<HTMLInputElement>['type'];
  inputMode?: InputHTMLAttributes<HTMLInputElement>['inputMode'];
  maxLength?: number;
  min?: number;
  placeholder?: string;
}

/** A labelled input with the same hint, error and required markers as every other field. */
export function TextField({
  id,
  label,
  value,
  onChange,
  hint,
  error,
  required = false,
  optional = false,
  multiline = false,
  type = 'text',
  inputMode,
  maxLength,
  min,
  placeholder,
}: TextFieldProps) {
  const { t } = useI18n();
  const className = `input ${multiline ? 'input--textarea' : ''} ${error ? 'input--error' : ''}`;

  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
        {required ? <span className="field__required"> *</span> : null}
        {optional ? <span className="field__optional"> ({t('common.optional')})</span> : null}
      </label>
      {hint ? <p className="field__hint">{hint}</p> : null}
      {multiline ? (
        <textarea
          id={id}
          className={className}
          rows={3}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          maxLength={maxLength}
          placeholder={placeholder}
        />
      ) : (
        <input
          id={id}
          className={className}
          type={type}
          inputMode={inputMode}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          maxLength={maxLength}
          min={min}
          placeholder={placeholder}
        />
      )}
      {error ? <p className="field__error">{error}</p> : null}
    </div>
  );
}

/** A plain checkbox with a large hit area, for yes/no facts. */
export function CheckField({
  label,
  checked,
  onChange,
  error,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  error?: string | null;
}) {
  return (
    <div className="field">
      <label className={`check ${checked ? 'check--on' : ''}`}>
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>{label}</span>
      </label>
      {error ? <p className="field__error">{error}</p> : null}
    </div>
  );
}

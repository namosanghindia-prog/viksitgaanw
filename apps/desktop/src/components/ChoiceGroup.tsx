import type { ReferenceItem } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';

interface ChoiceGroupProps {
  label: string;
  hint?: string;
  items: ReferenceItem[];
  /** Group chips under their category heading (used for the crop list). */
  categories?: ReferenceItem[];
}

interface SingleProps extends ChoiceGroupProps {
  multiple?: false;
  value: string | null;
  onChange: (value: string | null) => void;
}

interface MultiProps extends ChoiceGroupProps {
  multiple: true;
  value: string[];
  onChange: (value: string[]) => void;
}

/**
 * Big tappable chips instead of a dropdown.
 *
 * Everything is visible at once, which matters when the user is reading slowly
 * or having the screen read to them by a family member. Single-select chips
 * behave as radios; multi-select as checkboxes.
 */
export function ChoiceGroup(props: SingleProps | MultiProps) {
  const { rt } = useI18n();
  const { label, hint, items, categories } = props;

  const isSelected = (code: string) =>
    props.multiple ? props.value.includes(code) : props.value === code;

  const toggle = (code: string) => {
    if (props.multiple) {
      const next = props.value.includes(code)
        ? props.value.filter((entry) => entry !== code)
        : [...props.value, code];
      props.onChange(next);
    } else {
      // Tapping the chosen chip again clears it, so a mis-tap is recoverable.
      props.onChange(props.value === code ? null : code);
    }
  };

  const renderChips = (chips: ReferenceItem[]) => (
    <div className="choices">
      {chips.map((item) => (
        <button
          key={item.code}
          type="button"
          role={props.multiple ? 'checkbox' : 'radio'}
          aria-checked={isSelected(item.code)}
          className={`chip ${isSelected(item.code) ? 'chip--selected' : ''}`}
          onClick={() => toggle(item.code)}
        >
          {rt(item)}
        </button>
      ))}
    </div>
  );

  return (
    <fieldset className="field">
      <legend className="field__label">{label}</legend>
      {hint ? <p className="field__hint">{hint}</p> : null}

      {categories?.length ? (
        <div className="choices__grouped">
          {categories.map((category) => {
            const inCategory = items.filter((item) => item.category === category.code);
            if (!inCategory.length) return null;
            return (
              <div key={category.code} className="choices__group">
                <h4 className="choices__group-title">{rt(category)}</h4>
                {renderChips(inCategory)}
              </div>
            );
          })}
        </div>
      ) : (
        renderChips(items)
      )}
    </fieldset>
  );
}

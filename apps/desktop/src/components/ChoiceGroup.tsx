import { useState } from 'react';
import type { ReferenceItem } from '@viksitgaanw/shared';
import { CUSTOM_MAX_LENGTH, customCode, customItem, isCustom } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';

interface ChoiceGroupProps {
  label: string;
  hint?: string;
  items: ReferenceItem[];
  /** Group chips under their category heading (used for the crop list). */
  categories?: ReferenceItem[];
  /**
   * Offer "Other -- type your own" for when no chip fits. Only for lists the
   * server takes a typed choice on (``allowCustom`` in the reference file).
   */
  allowCustom?: boolean;
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

/** Folded for comparing what someone typed with a chip's name. */
const fold = (text: string) => text.trim().toLocaleLowerCase().replace(/\s+/g, ' ');

/**
 * Big tappable chips instead of a dropdown.
 *
 * Everything is visible at once, which matters when the user is reading slowly
 * or having the screen read to them by a family member. Single-select chips
 * behave as radios; multi-select as checkboxes. With ``allowCustom`` a last
 * chip opens a box to type a choice of one's own; it then shows as a chip too.
 */
export function ChoiceGroup(props: SingleProps | MultiProps) {
  const { t, rt } = useI18n();
  const { label, hint, items, categories, allowCustom = false } = props;
  const [typing, setTyping] = useState(false);
  const [draft, setDraft] = useState('');

  const chosen = props.multiple ? props.value : props.value ? [props.value] : [];
  const isSelected = (code: string) => chosen.includes(code);

  // A typed choice replaces the plain "Other" chip, which is kept only where
  // it was already picked.
  const offered = allowCustom ? items.filter((item) => item.code !== 'other' || isSelected(item.code)) : items;
  const typed = chosen.filter(isCustom).map(customItem);

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

  const add = () => {
    const wanted = fold(draft);
    if (!wanted) return;
    // Typed the name of a chip that is there already: pick that one instead.
    const existing = items.find((item) =>
      [rt(item), ...Object.values(item.label)].some((name) => fold(name) === wanted),
    );
    const code = existing?.code ?? customCode(draft);
    if (code) {
      if (props.multiple) {
        if (!props.value.includes(code)) props.onChange([...props.value, code]);
      } else {
        props.onChange(code);
      }
    }
    setDraft('');
    setTyping(false);
  };

  const chip = (item: ReferenceItem) => (
    <button
      key={item.code}
      type="button"
      role={props.multiple ? 'checkbox' : 'radio'}
      aria-checked={isSelected(item.code)}
      className={`chip ${isSelected(item.code) ? 'chip--selected' : ''} ${item.custom ? 'chip--custom' : ''}`}
      onClick={() => toggle(item.code)}
    >
      {rt(item)}
    </button>
  );

  const own = allowCustom ? (
    <>
      {typed.map(chip)}
      {typing ? (
        <span className="choice-own">
          <input
            type="text"
            className="choice-own__input"
            value={draft}
            maxLength={CUSTOM_MAX_LENGTH}
            autoFocus
            placeholder={t('choice.ownPlaceholder')}
            aria-label={t('choice.own')}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault(); // not the form's submit
                add();
              } else if (event.key === 'Escape') {
                setDraft('');
                setTyping(false);
              }
            }}
          />
          <button type="button" className="button button--primary button--small" onClick={add} disabled={!draft.trim()}>
            {t('choice.add')}
          </button>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => {
              setDraft('');
              setTyping(false);
            }}
          >
            {t('common.cancel')}
          </button>
        </span>
      ) : (
        <button type="button" className="chip chip--add" onClick={() => setTyping(true)}>
          ＋ {t('choice.own')}
        </button>
      )}
    </>
  ) : null;

  return (
    <fieldset className="field">
      <legend className="field__label">{label}</legend>
      {hint ? <p className="field__hint">{hint}</p> : null}

      {categories?.length ? (
        <div className="choices__grouped">
          {categories.map((category) => {
            const inCategory = offered.filter((item) => item.category === category.code);
            if (!inCategory.length) return null;
            return (
              <div key={category.code} className="choices__group">
                <h4 className="choices__group-title">{rt(category)}</h4>
                <div className="choices">{inCategory.map(chip)}</div>
              </div>
            );
          })}
          {own ? (
            <div className="choices__group">
              <h4 className="choices__group-title">{t('choice.ownGroup')}</h4>
              <div className="choices">{own}</div>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="choices">
          {offered.map(chip)}
          {own}
        </div>
      )}
    </fieldset>
  );
}

import type { Segment } from '@viksitgaanw/shared';
import { REFERENCE, pickLabel } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { SEGMENT_ICON } from '../lib/segments';

interface SegmentPickerProps {
  onPick: (segment: Segment) => void;
}

/**
 * The six kinds of user, as big picture cards.
 *
 * This is the first thing a new user sees, and some will not read either
 * language easily, so each choice leads with a picture and a short name.
 */
export function SegmentPicker({ onPick }: SegmentPickerProps) {
  const { rt, lang } = useI18n();

  return (
    <div className="segments">
      {REFERENCE.user_segments.items.map((item) => {
        const segment = item.code as Segment;
        return (
          <button
            key={segment}
            type="button"
            className="segment"
            onClick={() => onPick(segment)}
          >
            <span className="segment__icon" aria-hidden="true">
              {SEGMENT_ICON[segment]}
            </span>
            <span className="segment__name">{rt(item)}</span>
            <span className="segment__note">{pickLabel(item.note, lang)}</span>
          </button>
        );
      })}
    </div>
  );
}

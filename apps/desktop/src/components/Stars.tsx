import { useI18n } from '../i18n';
import { formatNumber } from '../lib/format';

/** "★ 4.5 (3)" -- nothing at all before the first rating. */
export function RatingBadge({ average, count }: { average: number | null; count: number }) {
  const { t, lang } = useI18n();
  if (!count || average === null) return null;
  return (
    <span className="badge badge--rating" title={t('rating.badgeTitle', { n: count })}>
      ★ {formatNumber(average, lang, 1)} ({count})
    </span>
  );
}

/** Five big stars to tap. */
export function StarPicker({ value, onChange }: { value: number; onChange: (stars: number) => void }) {
  const { t } = useI18n();
  return (
    <div className="stars" role="radiogroup" aria-label={t('rating.title')}>
      {[1, 2, 3, 4, 5].map((stars) => (
        <button
          key={stars}
          type="button"
          role="radio"
          aria-checked={value === stars}
          aria-label={t('rating.stars', { n: stars })}
          className={`stars__star ${stars <= value ? 'stars__star--on' : ''}`}
          onClick={() => onChange(stars)}
        >
          ★
        </button>
      ))}
    </div>
  );
}

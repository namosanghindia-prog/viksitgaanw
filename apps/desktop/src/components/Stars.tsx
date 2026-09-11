import { useState } from 'react';
import type { Rating } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import type { StringKey } from '../i18n';
import { api } from '../lib/api';
import { formatDate, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';
import { TextField } from './TextField';

/**
 * "★ 4.5 (3)" -- nothing at all before the first rating. With a profile id it
 * opens what those people said, because an average alone asks to be trusted.
 */
export function RatingBadge({
  average,
  count,
  profileId,
  name,
}: {
  average: number | null;
  count: number;
  profileId?: string;
  name?: string;
}) {
  const { t, lang } = useI18n();
  const [open, setOpen] = useState(false);
  if (!count || average === null) return null;
  const text = `★ ${formatNumber(average, lang, 1)} (${count})`;
  if (!profileId) {
    return (
      <span className="badge badge--rating" title={t('rating.badgeTitle', { n: count })}>
        {text}
      </span>
    );
  }
  return (
    <>
      <button
        type="button"
        className="badge badge--rating badge--button"
        title={t('rating.badgeTitle', { n: count })}
        onClick={() => setOpen(true)}
      >
        {text}
      </button>
      {open ? (
        <div className="video-dialog" role="dialog" aria-modal="true" onClick={() => setOpen(false)}>
          <div className="video-dialog__body reviews-dialog" onClick={(event) => event.stopPropagation()}>
            <div className="video-dialog__head">
              <strong>{t('rating.reviewsOf', { name: name ?? '' })}</strong>
              <button type="button" className="button button--ghost button--small" onClick={() => setOpen(false)}>
                ✕ {t('common.close')}
              </button>
            </div>
            <ReviewList profileId={profileId} />
          </div>
        </div>
      ) : null}
    </>
  );
}

/** Five big stars to tap. */
export function StarPicker({ value, onChange }: { value: number; onChange: (stars: number) => void }) {
  const { t } = useI18n();
  return (
    <div className="stars" role="radiogroup" aria-label={t('rating.stars', { n: value || 0 })}>
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

const shown = (stars: number) => '★'.repeat(stars) + '☆'.repeat(5 - stars);

/**
 * Rating the other side of finished work -- a deal, a hire or sale, a
 * partnership. Once given it shows what you gave, and can be changed: people
 * reconsider, and the API keeps one rating per piece of work either way.
 */
export function RateBox({
  contextType,
  contextId,
  myRating,
  title,
  onRated,
}: {
  contextType: 'deal' | 'enquiry' | 'partnership';
  contextId: string;
  myRating: Rating | null;
  title: string;
  onRated: () => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [stars, setStars] = useState(myRating?.stars ?? 0);
  const [comment, setComment] = useState(myRating?.comment ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (myRating && !editing) {
    return (
      <div className="rate-box rate-box--done">
        <span>
          {t('rating.yours', { stars: myRating.stars })} <span className="rate-box__stars">{shown(myRating.stars)}</span>
        </span>
        {myRating.comment ? <blockquote className="answer__message">{myRating.comment}</blockquote> : null}
        <button type="button" className="button button--ghost button--small" onClick={() => setEditing(true)}>
          {t('rating.change')}
        </button>
      </div>
    );
  }

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.rate({ contextType, contextId, stars, comment: comment.trim() || null });
      setEditing(false);
      onRated();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rate-box">
      <strong>{title}</strong>
      <StarPicker value={stars} onChange={setStars} />
      <TextField
        id={`rating-${contextId}`}
        label={t('rating.comment')}
        value={comment}
        onChange={setComment}
        multiline
        optional
        maxLength={1000}
      />
      <p className="muted small">{t('rating.public')}</p>
      <div className="request__actions">
        <button type="button" className="button button--primary button--small" disabled={!stars || busy} onClick={send}>
          {busy ? t('common.saving') : t('rating.send')}
        </button>
        {editing ? (
          <button type="button" className="button button--ghost button--small" onClick={() => setEditing(false)}>
            {t('common.cancel')}
          </button>
        ) : null}
      </div>
      {error ? <p className="field__error">{error}</p> : null}
    </div>
  );
}

/** What people said about someone after working with them, newest first. */
export function ReviewList({ profileId, emptyText }: { profileId: string; emptyText?: string }) {
  const { t, lang } = useI18n();
  const summary = useAsync((signal) => api.ratingsFor(profileId, signal), [profileId]);
  if (summary.loading) return <p className="muted">{t('common.loading')}</p>;
  if (summary.error) return <p className="callout callout--error">{summary.error.message}</p>;
  const data = summary.data;
  if (!data || data.count === 0) return <p className="muted">{emptyText ?? t('rating.noReviews')}</p>;
  return (
    <div className="reviews">
      <p className="reviews__summary">
        <span className="rate-box__stars">{shown(Math.round(data.average ?? 0))}</span>{' '}
        <strong>{formatNumber(data.average ?? 0, lang, 1)}</strong>{' '}
        <span className="muted">{data.count === 1 ? t('rating.fromOne') : t('rating.fromN', { n: data.count })}</span>
      </p>
      <ul className="reviews__list">
        {data.ratings.map((rating) => (
          <li key={rating.id} className="reviews__item">
            <div className="reviews__head">
              <span className="rate-box__stars">{shown(rating.stars)}</span>
              <strong>{rating.rater.organisationName || rating.rater.displayName}</strong>
              <span className="muted small">
                {t(`rating.context.${rating.contextType}` as StringKey)}
                {rating.about ? ` · ${rating.about}` : ''} · {formatDate(rating.createdAt, lang)}
              </span>
            </div>
            {rating.comment ? <p className="reviews__comment">{rating.comment}</p> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

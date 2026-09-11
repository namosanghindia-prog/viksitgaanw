import { useState } from 'react';
import type { FarmUpdate, LandParcel, LandShare } from '@viksitgaanw/shared';
import { findItem } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate, formatNumber } from '../lib/format';
import { PhotoButton } from './PhotoButton';
import { ReadAloud } from './ReadAloud';
import { PartyLine } from './RequestCard';

/** A plot a connection shared: where, how big, soil, water, crops, pictures. */
export function LandShareCard({ land, children }: { land: LandShare; children?: React.ReactNode }) {
  const { t, rt, lang } = useI18n();
  const facts = [
    land.areaValue && land.areaUnit
      ? `${formatNumber(land.areaValue, lang, 2)} ${rt(findItem('area_units', land.areaUnit))}`
      : land.areaHectares
        ? `${formatNumber(land.areaHectares, lang, 2)} ha`
        : null,
    land.soilType ? rt(findItem('soil_types', land.soilType)) : null,
    land.waterSources.length ? land.waterSources.map((code) => rt(findItem('water_sources', code))).join(', ') : null,
    land.irrigationType ? rt(findItem('irrigation_types', land.irrigationType)) : null,
  ].filter(Boolean);
  const crops = land.existingCrops.map((code) => rt(findItem('crops', code)));
  const spoken = [land.label, land.place, ...facts, crops.length ? `${t('card.grows')}: ${crops.join(', ')}` : '']
    .filter(Boolean)
    .join('. ');

  return (
    <article className="request land-card">
      <header className="request__head">
        <div className="request__heading">
          <h3 className="request__title">🌾 {land.label}</h3>
          {land.place ? <p className="request__place">{land.place}</p> : null}
        </div>
        <div className="request__badges">
          {land.changedAt ? <span className="badge badge--status-sent">{t('land.updatedBadge')}</span> : null}
          {land.origin === 'demo' ? <span className="badge badge--sample">{t('card.sample')}</span> : null}
        </div>
      </header>
      {land.photos.length ? (
        <div className="land-card__photos">
          {land.photos.map((photo) => (
            <img key={photo.id} src={api.mediaUrl(photo.url) ?? undefined} alt="" />
          ))}
        </div>
      ) : null}
      {facts.length ? <p className="land-card__facts">{facts.join(' · ')}</p> : null}
      {crops.length ? (
        <div className="request__tags">
          {crops.map((crop) => (
            <span key={crop} className="tag">
              {crop}
            </span>
          ))}
        </div>
      ) : null}
      {!land.isMine ? <PartyLine party={land.owner} /> : null}
      <div className="request__toolbar">
        <ReadAloud text={spoken} />
        {land.updates ? <span className="muted small">{t('land.updatesCount', { n: land.updates })}</span> : null}
        {land.changedAt ? (
          <span className="muted small">{t('land.changedOn', { date: formatDate(land.changedAt, lang) })}</span>
        ) : null}
      </div>
      {children}
    </article>
  );
}

/** A short post from a connection -- or the owner's own, with Delete. */
export function UpdateCard({ update, onDeleted }: { update: FarmUpdate; onDeleted?: () => void }) {
  const { t, lang } = useI18n();
  const [busy, setBusy] = useState(false);
  return (
    <article className="request update-card">
      <PartyLine party={update.owner} />
      {update.landLabel ? <p className="muted small">🌾 {update.landLabel}</p> : null}
      <p className="update-card__body">{update.body}</p>
      {update.photos.length ? (
        <div className="land-card__photos">
          {update.photos.map((photo) => (
            <img key={photo.id} src={api.mediaUrl(photo.url) ?? undefined} alt="" />
          ))}
        </div>
      ) : null}
      <div className="request__toolbar">
        <span className="muted small">{formatDate(update.createdAt, lang)}</span>
        <ReadAloud text={update.body} />
        {update.isMine ? (
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={busy}
            onClick={async () => {
              if (!window.confirm(t('updates.confirmDelete'))) return;
              setBusy(true);
              try {
                await api.deleteUpdate(update.id);
                onDeleted?.();
              } finally {
                setBusy(false);
              }
            }}
          >
            {t('common.delete')}
          </button>
        ) : null}
      </div>
    </article>
  );
}

/**
 * Write an update for connections, optionally about one shared plot, with a
 * picture. The picture is attached after the words are saved, so a slow
 * upload never loses what was typed.
 */
export function UpdateComposer({
  lands,
  fixedLandId,
  onPosted,
}: {
  /** The owner's plots shared with connections, to pick one from. */
  lands: Array<Pick<LandParcel, 'id' | 'label'>>;
  fixedLandId?: string;
  onPosted: () => void;
}) {
  const { t } = useI18n();
  const [body, setBody] = useState('');
  const [landId, setLandId] = useState<string>(fixedLandId ?? '');
  const [photo, setPhoto] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const post = async () => {
    setBusy(true);
    setError(null);
    try {
      const update = await api.postUpdate(body.trim(), landId || null);
      if (photo) await api.addUpdatePhoto(update.id, photo);
      setBody('');
      setPhoto(null);
      onPosted();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="composer-card">
      <textarea
        className="input input--textarea"
        rows={2}
        maxLength={2000}
        value={body}
        placeholder={t('updates.placeholder')}
        onChange={(event) => setBody(event.target.value)}
      />
      <div className="composer-card__foot">
        {!fixedLandId && lands.length ? (
          <select className="input input--small composer-card__land" value={landId} onChange={(event) => setLandId(event.target.value)}>
            <option value="">{t('updates.noLand')}</option>
            {lands.map((land) => (
              <option key={land.id} value={land.id}>
                🌾 {land.label}
              </option>
            ))}
          </select>
        ) : null}
        <PhotoButton label={photo ? t('updates.photoChosen') : t('updates.addPhoto')} onPick={async (file) => setPhoto(file)} />
        <span className="muted small composer-card__who">🤝 {t('updates.audience')}</span>
        <button type="button" className="button button--primary button--small" disabled={busy || !body.trim()} onClick={post}>
          {busy ? t('common.saving') : t('updates.post')}
        </button>
      </div>
      {error ? <p className="callout callout--error">{error}</p> : null}
    </div>
  );
}

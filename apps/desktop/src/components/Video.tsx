import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import type { Video, VideoPlan, VideoTarget, VideoUpload } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import type { StringKey } from '../i18n';
import { api } from '../lib/api';

/* ------------------------------------------------------------------ *
 * Playing
 * ------------------------------------------------------------------ */

const thumbnail = (video: Video) =>
  video.provider === 'youtube'
    ? `https://i.ytimg.com/vi/${video.id}/hqdefault.jpg`
    : `https://image.mux.com/${video.id}/thumbnail.jpg?width=640`;

export const watchUrl = (video: Video) =>
  video.provider === 'youtube' ? `https://www.youtube.com/watch?v=${video.id}` : `https://stream.mux.com/${video.id}.m3u8`;

/**
 * A video behind a picture of it: nothing is fetched from the internet until
 * someone presses play, which matters on a metered village connection. Both
 * YouTube and Mux need the internet; offline the player says so instead.
 */
export function VideoPlayer({ video, title, compact = false }: { video: Video; title?: string; compact?: boolean }) {
  const { t } = useI18n();
  const [playing, setPlaying] = useState(false);
  const [noPicture, setNoPicture] = useState(false);
  const online = typeof navigator === 'undefined' || navigator.onLine;

  if (playing) {
    return (
      <div className={`video ${compact ? 'video--compact' : ''}`}>
        {video.provider === 'youtube' ? (
          <iframe
            className="video__frame"
            src={`https://www.youtube-nocookie.com/embed/${video.id}?autoplay=1&rel=0&modestbranding=1`}
            title={title ?? t('video.title')}
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
          />
        ) : (
          <MuxVideo playbackId={video.id} title={title} />
        )}
      </div>
    );
  }

  return (
    <div className={`video ${compact ? 'video--compact' : ''}`}>
      <button
        type="button"
        className="video__poster"
        onClick={() => setPlaying(true)}
        disabled={!online}
        aria-label={title ? `${t('video.play')}: ${title}` : t('video.play')}
      >
        {!noPicture && online ? (
          <img src={thumbnail(video)} alt="" loading="lazy" onError={() => setNoPicture(true)} />
        ) : null}
        <span className="video__play">{online ? `▶ ${t('video.play')}` : `🎬 ${t('video.needsInternet')}`}</span>
      </button>
      {video.provider === 'youtube' ? (
        <a className="video__link small" href={watchUrl(video)} target="_blank" rel="noreferrer">
          {t('video.openYoutube')} ↗
        </a>
      ) : null}
    </div>
  );
}

/** A Mux video, streamed with HLS so it adapts to a slow connection. */
function MuxVideo({ playbackId, title }: { playbackId: string; title?: string }) {
  const element = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const media = element.current;
    if (!media) return;
    const source = `https://stream.mux.com/${playbackId}.m3u8`;
    let destroy: (() => void) | undefined;
    let cancelled = false;
    if (media.canPlayType('application/vnd.apple.mpegurl')) {
      media.src = source;
    } else {
      // Loaded only when a Mux video is actually played.
      void import('hls.js').then(({ default: Hls }) => {
        if (cancelled || !Hls.isSupported()) return;
        const hls = new Hls();
        hls.loadSource(source);
        hls.attachMedia(media);
        destroy = () => hls.destroy();
      });
    }
    return () => {
      cancelled = true;
      destroy?.();
    };
  }, [playbackId]);

  return (
    <video
      ref={element}
      className="video__frame"
      controls
      autoPlay
      playsInline
      title={title}
      poster={`https://image.mux.com/${playbackId}/thumbnail.jpg?width=640`}
    />
  );
}

/** A small button that plays someone's video in a window of its own. */
export function VideoButton({ video, label }: { video: Video; label: string }) {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();
  return (
    <>
      <button type="button" className="button button--ghost button--small" onClick={() => setOpen(true)}>
        🎬 {label}
      </button>
      {open ? (
        <div className="video-dialog" role="dialog" aria-modal="true" aria-label={label} onClick={() => setOpen(false)}>
          <div className="video-dialog__body" onClick={(event) => event.stopPropagation()}>
            <div className="video-dialog__head">
              <strong>{label}</strong>
              <button type="button" className="button button--ghost button--small" onClick={() => setOpen(false)}>
                ✕ {t('common.close')}
              </button>
            </div>
            <VideoPlayer video={video} title={label} />
          </div>
        </div>
      ) : null}
    </>
  );
}

/* ------------------------------------------------------------------ *
 * Adding one
 * ------------------------------------------------------------------ */

let planPromise: Promise<VideoPlan> | null = null;

/** Forget the remembered answer -- after a payment, uploads are open at once. */
export function forgetVideoPlan() {
  planPromise = null;
}

/** Whether the owner may upload video files, asked of the sync server once per session. */
export function useVideoPlan(): VideoPlan | null {
  const [plan, setPlan] = useState<VideoPlan | null>(null);
  useEffect(() => {
    let active = true;
    planPromise ??= api.videoPlan().catch(() => ({
      subscribed: false,
      plan: null,
      until: null,
      uploadsAvailable: false,
      reason: 'offline',
    }));
    void planPromise.then((value) => {
      if (active) setPlan(value);
    });
    return () => {
      active = false;
    };
  }, []);
  return plan;
}

const REASON: Record<string, StringKey> = {
  sync_off: 'video.reason.syncOff',
  offline: 'video.reason.offline',
  not_subscribed: 'video.reason.notSubscribed',
  no_profile: 'video.reason.notSubscribed',
  server_off: 'video.reason.serverOff',
};

const PENDING = new Set(['queued', 'uploading', 'processing']);

interface VideoFieldProps {
  target: VideoTarget;
  entityId: string;
  video: Video | null;
  /** Called when the video changed, so the page can reload. */
  onChanged: () => void;
  label: string;
  hint?: string;
  /** Show the link box straight away rather than behind a button. */
  startOpen?: boolean;
  /** Off where the card around it already plays the video. */
  showPlayer?: boolean;
}

/**
 * The owner's control for one item's video: paste a YouTube link, or -- for
 * subscribers -- upload a file, which carries on in the background.
 */
export function VideoField({
  target,
  entityId,
  video,
  onChanged,
  label,
  hint,
  startOpen = false,
  showPlayer = true,
}: VideoFieldProps) {
  const { t } = useI18n();
  const plan = useVideoPlan();
  const [open, setOpen] = useState(startOpen);
  const [link, setLink] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [upload, setUpload] = useState<VideoUpload | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const changed = useRef(onChanged);
  changed.current = onChanged;

  // Follow an upload for this item until it is ready or has failed.
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const check = async () => {
      try {
        const rows = await api.videoUploads();
        const mine = rows.find((row) => row.target === target && row.entityId === entityId);
        if (!active) return;
        setUpload(mine && (PENDING.has(mine.status) || mine.status === 'failed') ? mine : null);
        if (mine && PENDING.has(mine.status)) {
          timer = window.setTimeout(check, 3000);
        } else if (mine?.status === 'ready' && upload && PENDING.has(upload.status)) {
          changed.current();
        }
      } catch {
        // The list is a nicety; the video itself is on the item.
      }
    };
    void check();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run only when a new upload starts
  }, [target, entityId, upload?.id]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const saveLink = async (event: FormEvent) => {
    event.preventDefault();
    if (!link.trim()) return;
    if (await run(() => api.setVideo(target, entityId, link.trim()))) {
      setLink('');
      setOpen(false);
      setUpload(null);
      onChanged();
    }
  };

  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    await run(async () => setUpload(await api.uploadVideo(target, entityId, file)));
    if (fileInput.current) fileInput.current.value = '';
  };

  return (
    <div className="video-field">
      <div className="video-field__head">
        <strong>🎬 {label}</strong>
        {hint ? <span className="muted small"> {hint}</span> : null}
      </div>
      {video && showPlayer ? <VideoPlayer video={video} title={label} compact /> : null}

      {upload && PENDING.has(upload.status) ? (
        <div className="video-field__upload">
          <progress max={100} value={upload.status === 'processing' ? undefined : upload.progress} />
          <span className="small">
            {upload.status === 'processing'
              ? t('video.processing')
              : upload.status === 'queued'
                ? t('video.queued')
                : t('video.uploading', { n: upload.progress })}
            {upload.error && upload.status !== 'processing' ? ` · ${t('video.willRetry')}` : ''}
          </span>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => run(async () => {
              await api.cancelVideoUpload(upload.id);
              setUpload(null);
            })}
          >
            {t('common.cancel')}
          </button>
        </div>
      ) : null}
      {upload?.status === 'failed' && upload.error && upload.error !== 'Cancelled.' && !upload.error.startsWith('Replaced') ? (
        <p className="field__error">{t('video.failed', { reason: upload.error })}</p>
      ) : null}

      <div className="video-field__actions">
        {!open ? (
          <button type="button" className="button button--small" onClick={() => setOpen(true)}>
            {video ? t('video.change') : t('video.add')}
          </button>
        ) : null}
        {video ? (
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={busy}
            onClick={() => {
              if (!window.confirm(t('video.confirmRemove'))) return;
              void run(() => api.removeVideo(target, entityId)).then((ok) => ok && onChanged());
            }}
          >
            {t('common.delete')}
          </button>
        ) : null}
      </div>

      {open ? (
        <div className="video-field__editor">
          <form className="video-field__link" onSubmit={saveLink}>
            <input
              className="input"
              type="url"
              inputMode="url"
              value={link}
              placeholder={t('video.linkPlaceholder')}
              aria-label={t('video.linkLabel')}
              onChange={(event) => setLink(event.target.value)}
            />
            <button type="submit" className="button button--primary button--small" disabled={busy || !link.trim()}>
              {busy ? t('common.saving') : t('common.save')}
            </button>
            <button type="button" className="button button--ghost button--small" onClick={() => setOpen(false)}>
              {t('common.cancel')}
            </button>
          </form>
          <p className="muted small">{t('video.linkHelp')}</p>
          {plan?.subscribed && plan.uploadsAvailable ? (
            <span>
              <input
                ref={fileInput}
                type="file"
                accept="video/*"
                hidden
                onChange={(event) => pickFile(event.target.files?.[0])}
              />
              <button type="button" className="button button--small" disabled={busy} onClick={() => fileInput.current?.click()}>
                ⬆ {t('video.uploadFile')}
              </button>
              <span className="muted small"> {t('video.uploadHelp')}</span>
            </span>
          ) : plan ? (
            <p className="muted small">
              ⭐ {t(REASON[plan.reason ?? 'not_subscribed'] ?? 'video.reason.notSubscribed')}{' '}
              {plan.reason === 'not_subscribed' ? <Link to="/subscription">{t('video.subscribe')} →</Link> : null}
            </p>
          ) : null}
        </div>
      ) : null}
      {error ? <p className="field__error">{error}</p> : null}
    </div>
  );
}

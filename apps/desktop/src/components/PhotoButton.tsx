import { useRef, useState } from 'react';

import { useI18n } from '../i18n';

interface PhotoButtonProps {
  label: string;
  onPick: (file: File) => Promise<unknown>;
  className?: string;
}

/**
 * Pick a picture from the device and hand it over as it is. Resizing and
 * stripping location data happen on the backend, so they cannot be skipped.
 */
export function PhotoButton({ label, onPick, className = 'button button--small' }: PhotoButtonProps) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await onPick(file);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  };

  return (
    <span className="photo-button">
      <input
        ref={input}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        hidden
        onChange={(event) => pick(event.target.files?.[0])}
      />
      <button type="button" className={className} disabled={busy} onClick={() => input.current?.click()}>
        📷 {busy ? t('photo.uploading') : label}
      </button>
      {error ? <span className="field__error"> {error}</span> : null}
    </span>
  );
}

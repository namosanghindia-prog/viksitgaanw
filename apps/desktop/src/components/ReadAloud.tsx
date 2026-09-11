import { useState } from 'react';

import { useI18n } from '../i18n';
import { useSpeech } from '../lib/speech';

/** A small "Listen" button that reads the given text in the app's language. */
export function ReadAloud({ text, className = 'button button--ghost button--small' }: { text: string; className?: string }) {
  const { t, lang } = useI18n();
  const { speak, stop, speaking, available } = useSpeech(lang);
  const [missing, setMissing] = useState(false);

  if (!available) return null;

  return (
    <span className="read-aloud">
      <button
        type="button"
        className={className}
        aria-pressed={speaking}
        title={speaking ? t('speak.stop') : t('speak.listen')}
        onClick={() => {
          if (speaking) {
            stop();
            return;
          }
          setMissing(!speak(text));
        }}
      >
        {speaking ? '⏹' : '🔊'} {speaking ? t('speak.stop') : t('speak.listen')}
      </button>
      {missing ? <span className="muted small"> {t('speak.noVoice')}</span> : null}
    </span>
  );
}

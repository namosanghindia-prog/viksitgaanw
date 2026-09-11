import { useCallback, useEffect, useState } from 'react';
import type { LanguageCode } from '@viksitgaanw/shared';

const VOICE_LANG: Record<LanguageCode, string> = {
  en: 'en-IN',
  hi: 'hi-IN',
  bn: 'bn-IN',
  mr: 'mr-IN',
  ta: 'ta-IN',
  te: 'te-IN',
  kn: 'kn-IN',
};

/** Whether this device can read text aloud at all. */
export const canSpeak = () => typeof window !== 'undefined' && 'speechSynthesis' in window;

/**
 * Pick the voice for a language: an exact match (hi-IN), then any voice of the
 * language (hi-*). Without one the browser's default voice reads Hindi letters
 * as noise, so the caller is told there is none.
 */
function voiceFor(lang: LanguageCode): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices();
  const want = VOICE_LANG[lang];
  return (
    voices.find((voice) => voice.lang === want) ??
    voices.find((voice) => voice.lang.toLowerCase().startsWith(lang)) ??
    null
  );
}

/**
 * Read text aloud with the device's own voices -- nothing leaves the device.
 *
 * Many users read slowly or not at all; hearing a request, a scheme or a
 * weather warning in their own language is the difference between using the
 * app and asking a relative to.
 */
export function useSpeech(lang: LanguageCode) {
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    if (!canSpeak()) return;
    // Voices load asynchronously in Chromium; asking once starts the load.
    window.speechSynthesis.getVoices();
    return () => window.speechSynthesis.cancel();
  }, []);

  const stop = useCallback(() => {
    if (!canSpeak()) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  const speak = useCallback(
    (text: string): boolean => {
      if (!canSpeak() || !text.trim()) return false;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = VOICE_LANG[lang];
      const voice = voiceFor(lang);
      if (voice) utterance.voice = voice;
      else if (lang !== 'en') return false;
      utterance.rate = 0.9;
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);
      setSpeaking(true);
      window.speechSynthesis.speak(utterance);
      return true;
    },
    [lang],
  );

  return { speak, stop, speaking, available: canSpeak() };
}

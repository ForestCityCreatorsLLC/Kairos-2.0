import { VOICE_BASE, VoiceTtsPayload } from '../api/client.ts';

let activeAudioEl: HTMLAudioElement | null = null;
let activeAbortController: AbortController | null = null;
let voicesWarmed = false;
let activeSpeechToken = 0;
let globalSpeaking = false;
const speechListeners = new Set<(speaking: boolean) => void>();

function setGlobalSpeakingState(next: boolean): void {
  if (globalSpeaking === next) return;
  globalSpeaking = next;
  speechListeners.forEach((listener) => {
    try {
      listener(next);
    } catch {
      // ignore subscriber errors
    }
  });
}

export function isKairosSpeaking(): boolean {
  return globalSpeaking;
}

export function subscribeKairosSpeech(listener: (speaking: boolean) => void): () => void {
  speechListeners.add(listener);
  return () => {
    speechListeners.delete(listener);
  };
}

export function cleanMarkdownForSpeech(raw: string, maxChars = 480): string {
  if (!raw) return '';
  const stripped = raw
    .replace(/<think>[\s\S]*?<\/think>/gi, ' ')
    .replace(/<think>[\s\S]*$/gi, ' ')
    .replace(/<ui_nav>[\s\S]*?<\/ui_nav>/gi, '')
    .replace(/<kairos_op>[\s\S]*?<\/kairos_op>/gi, '')
    .replace(/\[(mutter|normal)\]/gi, ' ')
    .replace(/\[\[[^\]|]+\|([^\]]+)\]\]/g, '$1')
    .replace(/\[\[([^\]]+)\]\]/g, (_m, inner: string) => {
      const tail = inner.split('/').pop() || inner;
      return tail.replace(/_/g, ' ');
    })
    .replace(/`([A-Za-z0-9_\-/]+\.(?:md|canvas|base))`/g, (_m, pathStr: string) => {
      const tail = pathStr.split('/').pop() || pathStr;
      return tail.replace(/_/g, ' ');
    })
    .replace(/[`*_#>~[\]]+/g, ' ')
    .replace(/[•✓⚠️🔒🚨🚀💻📣📄🌐👕📥📎🧭🤖🏈🧠👤🪽📖📅🗓️⚡📂➕⛓💭]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (stripped.length <= maxChars) return stripped;
  const cut = stripped.slice(0, maxChars);
  const lastPeriod = cut.lastIndexOf('.');
  return lastPeriod > 80 ? cut.slice(0, lastPeriod + 1) : `${cut.trimEnd()}...`;
}

export function warmupSpeechVoices(): void {
  if (typeof window === 'undefined' || !('speechSynthesis' in window) || voicesWarmed) {
    return;
  }
  voicesWarmed = true;
  try {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => {
      try {
        window.speechSynthesis.getVoices();
      } catch {
        // ignore
      }
    };
  } catch {
    // ignore
  }
}

export function stopKairosSpeech(): void {
  activeSpeechToken += 1;
  if (activeAbortController) {
    try {
      activeAbortController.abort();
    } catch {
      // ignore
    }
    activeAbortController = null;
  }
  if (activeAudioEl) {
    try {
      activeAudioEl.pause();
      activeAudioEl.src = '';
    } catch {
      // ignore
    }
    activeAudioEl = null;
  }
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
    try {
      window.speechSynthesis.cancel();
    } catch {
      // ignore
    }
  }
  setGlobalSpeakingState(false);
}

function pickBestBrowserVoice(): SpeechSynthesisVoice | null {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return null;
  const voices = window.speechSynthesis.getVoices() || [];
  if (voices.length === 0) return null;
  const preferred = [
    'Microsoft Aria',
    'Microsoft Jenny',
    'Microsoft Guy',
    'Google US English',
    'Microsoft Zira',
    'Microsoft David',
  ];
  for (const name of preferred) {
    const match = voices.find((v) => v.name.toLowerCase().includes(name.toLowerCase()));
    if (match) return match;
  }
  return voices.find((v) => v.lang.toLowerCase().startsWith('en')) || voices[0];
}

function speakWithBrowserSynthesis(
  text: string,
  onDone?: () => void,
  prosodyMode: 'mutter' | 'normal' = 'normal'
): void {
  const clean = cleanMarkdownForSpeech(text);
  if (typeof window === 'undefined' || !('speechSynthesis' in window) || !clean) {
    onDone?.();
    return;
  }
  try {
    window.speechSynthesis.cancel();
    window.speechSynthesis.resume();
    const utter = new SpeechSynthesisUtterance(clean);
    const chosen = pickBestBrowserVoice();
    if (chosen) utter.voice = chosen;
    if (prosodyMode === 'mutter') {
      // Dual-prosody [mutter]: 1.12x cadence, -3.3 dB (0.68) gain, softer pitch
      utter.rate = 1.12;
      utter.pitch = 0.95;
      utter.volume = 0.68;
    } else {
      utter.rate = 1.04;
      utter.pitch = 1.0;
      utter.volume = 1.0;
    }
    utter.onend = () => onDone?.();
    utter.onerror = () => onDone?.();
    window.speechSynthesis.speak(utter);
  } catch {
    onDone?.();
  }
}

export async function speakKairosReply(options: {
  text: string;
  ttsEnabled: boolean;
  neuralTts: boolean;
  ttsVoice: string;
  isPrivate: boolean;
  activeNotePath?: string;
  prebuiltTts?: VoiceTtsPayload | null;
  prosodyMode?: 'mutter' | 'normal';
  onStart?: () => void;
  onDone?: () => void;
}): Promise<void> {
  const {
    text,
    ttsEnabled,
    neuralTts,
    ttsVoice,
    isPrivate,
    activeNotePath = '',
    prebuiltTts = null,
    prosodyMode,
    onStart,
    onDone,
  } = options;

  const detectedMutter =
    prosodyMode === 'mutter' ||
    (prosodyMode === undefined && text.includes('[mutter]') && !text.includes('[normal]'));
  const effectiveProsody: 'mutter' | 'normal' = detectedMutter ? 'mutter' : 'normal';

  const clean = cleanMarkdownForSpeech(text);
  if (!ttsEnabled || !clean) {
    onDone?.();
    return;
  }

  warmupSpeechVoices();
  stopKairosSpeech();
  const speechToken = ++activeSpeechToken;
  setGlobalSpeakingState(true);
  onStart?.();

  let finished = false;
  const finishSpeech = () => {
    if (finished) return;
    finished = true;
    if (speechToken === activeSpeechToken) {
      setGlobalSpeakingState(false);
    }
    onDone?.();
  };

  let ttsPayload: VoiceTtsPayload | null = prebuiltTts;

  if (!ttsPayload && neuralTts) {
    const controller = new AbortController();
    activeAbortController = controller;
    const timer = window.setTimeout(() => controller.abort(), 4200);
    try {
      const directivePrefix = effectiveProsody === 'mutter' ? '[mutter] ' : '[normal] ';
      const res = await fetch(`${VOICE_BASE}/api/voice/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: `${directivePrefix}${clean}`,
          active_note_path: activeNotePath,
          is_private: isPrivate,
          voice: ttsVoice || 'Kore',
        }),
        signal: controller.signal,
      });
      if (res.ok) {
        ttsPayload = (await res.json()) as VoiceTtsPayload;
      }
    } catch {
      ttsPayload = null;
    } finally {
      window.clearTimeout(timer);
      if (activeAbortController === controller) {
        activeAbortController = null;
      }
    }
  }

  if (speechToken !== activeSpeechToken) {
    finishSpeech();
    return;
  }

  if (ttsPayload?.ok && ttsPayload.audio_base64 && (!isPrivate || ttsPayload.provider === 'kokoro-82m-local')) {
    try {
      const audio = new Audio(
        `data:${ttsPayload.mime_type || 'audio/wav'};base64,${ttsPayload.audio_base64}`
      );
      // Server WAV already applied -3.3 dB + 1.12x + low-pass when prosody_mode === 'mutter';
      // apply client fallback volume if an older prebuilt normal WAV was passed in mutter mode
      if (effectiveProsody === 'mutter' && ttsPayload.prosody_mode !== 'mutter') {
        audio.volume = 0.68;
        audio.playbackRate = 1.12;
      }
      activeAudioEl = audio;
      audio.onended = () => {
        if (activeAudioEl === audio) activeAudioEl = null;
        finishSpeech();
      };
      audio.onerror = () => {
        if (activeAudioEl === audio) activeAudioEl = null;
        if (speechToken !== activeSpeechToken) {
          finishSpeech();
          return;
        }
        speakWithBrowserSynthesis(ttsPayload?.clean_text || clean, finishSpeech, effectiveProsody);
      };
      await audio.play();
      return;
    } catch {
      activeAudioEl = null;
    }
  }

  if (speechToken !== activeSpeechToken) {
    finishSpeech();
    return;
  }

  speakWithBrowserSynthesis(ttsPayload?.clean_text || clean, finishSpeech, effectiveProsody);
}

export async function speakCognitiveMutter(
  clause: string,
  options: {
    ttsEnabled: boolean;
    neuralTts: boolean;
    ttsVoice: string;
    isPrivate: boolean;
    activeNotePath?: string;
  }
): Promise<void> {
  if (!clause.trim() || !options.ttsEnabled) return;
  await speakKairosReply({
    text: `[mutter] ${clause}`,
    ttsEnabled: options.ttsEnabled,
    neuralTts: options.neuralTts,
    ttsVoice: options.ttsVoice,
    isPrivate: options.isPrivate,
    activeNotePath: options.activeNotePath,
    prosodyMode: 'mutter',
  });
}

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  BotMessageSquare,
  Brain,
  Compass,
  ExternalLink,
  Lock,
  Mic,
  Paperclip,
  Pause,
  Play,
  Send,
  Sparkles,
  Square,
  Volume2,
  VolumeOff,
  X,
} from 'lucide-react';
import {
  BrainMode,
  PaperclipSnapshot,
  PersonaRole,
  ToneMode,
  UIActionCommand,
  VOICE_WS,
  VoiceStateSnapshot,
  VoiceTtsPayload,
  kairosApi,
} from '../api/client.ts';
import {
  isKairosSpeaking,
  speakCognitiveMutter,
  speakKairosReply,
  stopKairosSpeech,
  subscribeKairosSpeech,
  warmupSpeechVoices,
} from '../utils/speech.ts';
import { VoiceNavigatorHUD } from './VoiceNavigatorHUD.tsx';

interface SpeechRecognitionInstance {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((ev: { results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((ev?: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

interface TopBarProps {
  brainMode: BrainMode;
  onChangeBrainMode: (mode: BrainMode) => void;
  activeNotePath: string;
  activeTaskId?: string;
  activeBrowserUrl?: string;
  activeBrowserTitle?: string;
  isPrivateContext: boolean;
  paperclipSnapshot: PaperclipSnapshot | null;
  hermesSkillCount?: number;
  onOpenPaperclip: () => void;
  onCommandCompleted: (sessionId?: string) => void;
  onExecuteUiCommands: (cmds: UIActionCommand[], summary?: string, agent?: string) => void;
  chatDrawerOpen: boolean;
  onToggleChatDrawer: () => void;
  activeSessionId: string;
  persona: PersonaRole;
  onChangePersona?: (persona: PersonaRole) => void;
  toneMode: ToneMode;
  onChangeToneMode?: (tone: ToneMode) => void;
  projectScope: string;
  departmentScope: string;
  currentTab: string;
  currentView: string;
  ttsEnabled: boolean;
  onToggleTtsEnabled: () => void;
  neuralTts: boolean;
  onChangeNeuralTts: (val: boolean) => void;
  ttsVoice: string;
  onChangeTtsVoice: (val: string) => void;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return window.btoa(binary);
}

const MEDIA_PLAYBACK_HOSTS = [
  'youtube.com',
  'youtu.be',
  'spotify.com',
  'twitch.tv',
  'soundcloud.com',
  'netflix.com',
];

function hasMediaPlaybackNavigation(cmds?: UIActionCommand[]): boolean {
  if (!cmds || cmds.length === 0) return false;
  return cmds.some((cmd) => {
    if (cmd.type !== 'browser_navigate' || !cmd.url) return false;
    const low = cmd.url.toLowerCase();
    return MEDIA_PLAYBACK_HOSTS.some((host) => low.includes(host));
  });
}

function normalizeKairosTranscript(raw: string): string {
  if (!raw) return '';
  let out = raw.replace(/\b(?:kros|kyros|kiros|cairos|kayros|karos|k[-']ros|kai[\s-]+ross?)\b/gi, 'KAIROS');
  if (/^\s*(?:(?:hey|hi|hello|yo|ok|okay)\s+cairo\b|cairo\s*[,:;!\-?])/i.test(out)) {
    out = out.replace(/^(\s*(?:(?:hey|hi|hello|yo|ok|okay)\s+)?)cairo(?=$|[\s,:;!\-?.])/i, '$1KAIROS');
  }
  return out;
}

export const TopBar: React.FC<TopBarProps> = ({
  brainMode,
  onChangeBrainMode,
  activeNotePath,
  activeTaskId = '',
  activeBrowserUrl = '',
  activeBrowserTitle = '',
  isPrivateContext,
  paperclipSnapshot,
  hermesSkillCount = 0,
  onOpenPaperclip,
  onCommandCompleted,
  onExecuteUiCommands,
  chatDrawerOpen,
  onToggleChatDrawer,
  activeSessionId,
  persona,
  onChangePersona,
  toneMode,
  onChangeToneMode,
  projectScope,
  departmentScope,
  currentTab,
  currentView,
  ttsEnabled,
  onToggleTtsEnabled,
  neuralTts,
  onChangeNeuralTts,
  ttsVoice,
  onChangeTtsVoice,
}) => {
  const [voice, setVoice] = useState<VoiceStateSnapshot>({
    status: 'IDLE',
    muted: false,
    hold_seconds: 1.5,
    hands_free: true,
    wake_word_only: false,
    neural_tts: true,
    tts_voice: 'Kore',
    last_transcript: 'Standing by on Canopy Vault.',
    last_reply: '',
    vu_level: 8,
  });
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [handsFree, setHandsFree] = useState(true);
  const [wakeWordOnly, setWakeWordOnly] = useState(false);
  const [liveVuLevel, setLiveVuLevel] = useState(0);
  const [mutterClause, setMutterClause] = useState('');
  const [showVoiceHud, setShowVoiceHud] = useState(false);
  const [showPaperclipPopover, setShowPaperclipPopover] = useState(false);
  const [replyCard, setReplyCard] = useState<{
    reply: string;
    agent: string;
    privacy_locked: boolean;
    retained?: boolean;
  } | null>(null);

  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const silenceTimerRef = useRef<number | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);

  const listeningWantedRef = useRef(false);
  const isSpeakingRef = useRef(false);
  const webSpeechDeliveredRef = useRef(false);
  const webSpeechInterimSeenRef = useRef(false);
  const relistenTimerRef = useRef<number | null>(null);
  const holdSecondsRef = useRef(1.5);
  holdSecondsRef.current = voice.hold_seconds;

  // Keep latest context in a ref so async VAD callbacks always read live UI state
  const liveCtxRef = useRef({
    brainMode,
    activeNotePath,
    activeTaskId,
    activeBrowserUrl,
    activeBrowserTitle,
    isPrivateContext,
    activeSessionId,
    persona,
    toneMode,
    projectScope,
    departmentScope,
    currentTab,
    currentView,
    handsFree,
    wakeWordOnly,
    neuralTts,
    ttsEnabled,
    ttsVoice,
    chatDrawerOpen,
  });
  liveCtxRef.current = {
    brainMode,
    activeNotePath,
    activeTaskId,
    activeBrowserUrl,
    activeBrowserTitle,
    isPrivateContext,
    activeSessionId,
    persona,
    toneMode,
    projectScope,
    departmentScope,
    currentTab,
    currentView,
    handsFree,
    wakeWordOnly,
    neuralTts,
    ttsEnabled,
    ttsVoice,
    chatDrawerOpen,
  };

  const stopMicrophoneCapture = useCallback(() => {
    if (relistenTimerRef.current !== null) {
      window.clearTimeout(relistenTimerRef.current);
      relistenTimerRef.current = null;
    }
    if (silenceTimerRef.current !== null) {
      window.clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    try {
      recognitionRef.current?.stop();
    } catch {
      // ignore
    }
    recognitionRef.current = null;

    if (rafIdRef.current !== null) {
      window.cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
    try {
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.onstop = null;
        mediaRecorderRef.current.stop();
      }
    } catch {
      // ignore
    }
    mediaRecorderRef.current = null;

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    setLiveVuLevel(0);
  }, []);

  const stopSpeechOutput = useCallback(() => {
    isSpeakingRef.current = false;
    setMutterClause('');
    if (audioElementRef.current) {
      audioElementRef.current.pause();
      audioElementRef.current.src = '';
      audioElementRef.current = null;
    }
    stopKairosSpeech();
  }, []);

  // Forward declare `startLiveListeningSession` via ref so `speakResponseAndMaybeRelisten` can resume listening
  const startListeningFnRef = useRef<() => void>(() => {});

  const scheduleHandsFreeRelisten = useCallback((delayMs = 450) => {
    if (relistenTimerRef.current !== null) {
      window.clearTimeout(relistenTimerRef.current);
      relistenTimerRef.current = null;
    }
    if (!listeningWantedRef.current || !liveCtxRef.current.handsFree) {
      setVoice((prev) => ({
        ...prev,
        status: prev.muted ? 'MUTED' : listeningWantedRef.current ? 'LISTENING' : 'IDLE',
      }));
      return;
    }
    setVoice((prev) => ({ ...prev, status: 'LISTENING' }));
    relistenTimerRef.current = window.setTimeout(() => {
      relistenTimerRef.current = null;
      if (listeningWantedRef.current && !isSpeakingRef.current && !isKairosSpeaking()) {
        startListeningFnRef.current();
      }
    }, delayMs);
  }, []);

  // Global Acoustic Ducking: Duck open mic whenever TTS starts from ANY surface (TopBar, ChatDrawer, Assistant, Ctrl+K)
  useEffect(() => {
    return subscribeKairosSpeech((speaking) => {
      isSpeakingRef.current = speaking;
      if (speaking) {
        stopMicrophoneCapture();
        setVoice((prev) => ({ ...prev, status: 'SPEAKING' }));
      } else if (listeningWantedRef.current && liveCtxRef.current.handsFree) {
        scheduleHandsFreeRelisten(450);
      } else {
        setVoice((prev) => ({
          ...prev,
          status: prev.muted ? 'MUTED' : listeningWantedRef.current ? 'LISTENING' : 'IDLE',
        }));
      }
    });
  }, [scheduleHandsFreeRelisten, stopMicrophoneCapture]);

  const speakResponseAndMaybeRelisten = useCallback(
    async (
      spokenText: string,
      prebuiltTts?: VoiceTtsPayload | null,
      forcePrivacyLock?: boolean
    ) => {
      const ctx = liveCtxRef.current;
      const finishSpeaking = () => {
        isSpeakingRef.current = false;
        if (listeningWantedRef.current && ctx.handsFree) {
          scheduleHandsFreeRelisten(450);
        } else {
          setVoice((prev) => ({
            ...prev,
            status: prev.muted ? 'MUTED' : listeningWantedRef.current ? 'LISTENING' : 'IDLE',
          }));
        }
      };

      if (!ctx.ttsEnabled || !spokenText.trim()) {
        finishSpeaking();
        return;
      }

      // Duck microphone while KAIROS speaks (100% Zero Acoustic Echo)
      stopMicrophoneCapture();
      stopSpeechOutput();
      isSpeakingRef.current = true;
      setVoice((prev) => ({ ...prev, status: 'SPEAKING' }));

      await speakKairosReply({
        text: spokenText,
        ttsEnabled: ctx.ttsEnabled,
        neuralTts: ctx.neuralTts,
        ttsVoice: ctx.ttsVoice,
        isPrivate: Boolean(forcePrivacyLock || ctx.isPrivateContext),
        activeNotePath: ctx.activeNotePath,
        prebuiltTts: prebuiltTts || null,
        onDone: finishSpeaking,
      });
    },
    [scheduleHandsFreeRelisten, stopMicrophoneCapture, stopSpeechOutput]
  );

  const executePromptText = useCallback(
    async (rawText: string, fromVoice = false) => {
      const ctx = liveCtxRef.current;
      let trimmed = normalizeKairosTranscript(rawText.trim());
      if (!trimmed || busy) return;

      // Client-side `"Hey Kairos"` wake-word filter for WebSpeech transcripts
      if (fromVoice && ctx.wakeWordOnly) {
        const mWake = trimmed.match(/^(?:(?:hey|hi|hello|ok|okay|yo)\s+)?kairos(?:[\s,:;-]+(.*))?$/i);
        if (!mWake) {
          if (listeningWantedRef.current && ctx.handsFree) {
            scheduleHandsFreeRelisten(300);
          }
          return;
        }
        trimmed = (mWake[1] || 'Hey KAIROS').trim();
      }

      setBusy(true);
      try {
        const effectiveMode: BrainMode = ctx.isPrivateContext ? 'gemma-4' : ctx.brainMode;
        const res = await kairosApi.sendKairosCommand(trimmed, effectiveMode, ctx.activeNotePath, {
          session_id: ctx.activeSessionId,
          persona: ctx.persona,
          tone_mode: ctx.toneMode,
          active_task_id: ctx.activeTaskId,
          active_browser_url: ctx.activeBrowserUrl,
          active_browser_title: ctx.activeBrowserTitle,
          project_scope: ctx.projectScope || 'KAIROS_2_0',
          department_scope: ctx.departmentScope || 'Software_Development',
          current_tab: ctx.currentTab,
          current_view: ctx.currentView,
        });

        setVoice((prev) => ({
          ...prev,
          last_transcript: trimmed,
          last_reply: res.reply,
          last_mutter_clauses: res.mutter_clauses || [],
        }));

        if (res.ui_commands && res.ui_commands.length > 0) {
          onExecuteUiCommands(res.ui_commands, res.spoken_reply || res.reply, res.agent);
          // Media Playback Guard: Auto-pause open-mic when opening YouTube/media sites without wake-word lock
          // so video audio from speakers never triggers continuous voice hallucination loops
          if (hasMediaPlaybackNavigation(res.ui_commands) && listeningWantedRef.current && !ctx.wakeWordOnly) {
            listeningWantedRef.current = false;
            kairosApi.voiceAction('pause').catch(() => {});
          }
        }

        if (!ctx.chatDrawerOpen && (!res.ui_commands || res.ui_commands.length === 0)) {
          setReplyCard({
            reply: res.reply,
            agent: res.agent,
            privacy_locked: res.privacy_locked,
          });
        }
        if (res.session?.persona && res.session.persona !== ctx.persona) {
          onChangePersona?.(res.session.persona);
        }
        if (res.session?.tone_mode && res.session.tone_mode !== ctx.toneMode) {
          onChangeToneMode?.(res.session.tone_mode);
        }
        setPrompt('');
        onCommandCompleted(res.session?.session_id);
        await speakResponseAndMaybeRelisten(
          res.spoken_reply || res.reply,
          null,
          res.privacy_locked
        );
      } catch (err) {
        setReplyCard({
          reply: err instanceof Error ? err.message : 'Unable to reach KAIROS Core API (:8420)',
          agent: 'Offline-Guard',
          privacy_locked: ctx.isPrivateContext,
        });
      } finally {
        setBusy(false);
      }
    },
    [
      busy,
      onChangePersona,
      onChangeToneMode,
      onCommandCompleted,
      onExecuteUiCommands,
      scheduleHandsFreeRelisten,
      speakResponseAndMaybeRelisten,
    ]
  );

  const dispatchRecordedAudioBlob = useCallback(
    async (blob: Blob) => {
      if (webSpeechDeliveredRef.current || blob.size < 2400) {
        if (listeningWantedRef.current && !isSpeakingRef.current) {
          scheduleHandsFreeRelisten(350);
        }
        return;
      }
      const ctx = liveCtxRef.current;
      setBusy(true);
      try {
        const buf = await blob.arrayBuffer();
        const b64 = arrayBufferToBase64(buf);
        const effectiveMode: BrainMode = ctx.isPrivateContext ? 'gemma-4' : ctx.brainMode;
        const voiceRes = await kairosApi.sendVoiceAudioCommand({
          audio_base64: b64,
          mime_type: blob.type || 'audio/webm',
          mode: effectiveMode,
          active_note_path: ctx.activeNotePath,
          active_task_id: ctx.activeTaskId,
          active_browser_url: ctx.activeBrowserUrl,
          active_browser_title: ctx.activeBrowserTitle,
          session_id: ctx.activeSessionId,
          persona: ctx.persona,
          tone_mode: ctx.toneMode,
          project_scope: ctx.projectScope || 'KAIROS_2_0',
          department_scope: ctx.departmentScope || 'Software_Development',
          current_tab: ctx.currentTab,
          current_view: ctx.currentView,
          synthesize_speech: ctx.ttsEnabled && ctx.neuralTts,
        });

        setVoice((prev) => ({
          ...voiceRes,
          status:
            isSpeakingRef.current
              ? 'SPEAKING'
              : listeningWantedRef.current && voiceRes.status === 'IDLE'
                ? 'LISTENING'
                : voiceRes.status || prev.status,
        }));
        if (voiceRes.wake_word_ignored || !voiceRes.core_response) {
          if (listeningWantedRef.current && ctx.handsFree) {
            scheduleHandsFreeRelisten(350);
          }
          return;
        }

        const core = voiceRes.core_response;
        if (core.session?.persona && core.session.persona !== ctx.persona) {
          onChangePersona?.(core.session.persona);
        }
        if (core.session?.tone_mode && core.session.tone_mode !== ctx.toneMode) {
          onChangeToneMode?.(core.session.tone_mode);
        }
        if (core.ui_commands && core.ui_commands.length > 0) {
          onExecuteUiCommands(core.ui_commands, core.spoken_reply || core.reply, core.agent);
          if (hasMediaPlaybackNavigation(core.ui_commands) && listeningWantedRef.current && !ctx.wakeWordOnly) {
            listeningWantedRef.current = false;
            kairosApi.voiceAction('pause').catch(() => {});
          }
        }
        if (!ctx.chatDrawerOpen && (!core.ui_commands || core.ui_commands.length === 0)) {
          setReplyCard({
            reply: core.reply,
            agent: core.agent,
            privacy_locked: core.privacy_locked,
          });
        }
        setPrompt('');
        onCommandCompleted(core.session?.session_id);
        await speakResponseAndMaybeRelisten(
          core.spoken_reply || core.reply,
          voiceRes.tts,
          core.privacy_locked
        );
      } catch {
        if (listeningWantedRef.current && !isSpeakingRef.current) {
          scheduleHandsFreeRelisten(450);
        }
      } finally {
        setBusy(false);
      }
    },
    [
      onChangePersona,
      onChangeToneMode,
      onCommandCompleted,
      onExecuteUiCommands,
      scheduleHandsFreeRelisten,
      speakResponseAndMaybeRelisten,
    ]
  );

  // Hard Privacy Guard: Immediately abort Chromium SpeechRecognition if entering a #private context
  useEffect(() => {
    if (isPrivateContext && recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {
        // ignore
      }
      recognitionRef.current = null;
    }
  }, [isPrivateContext]);

  const startLiveListeningSession = useCallback(async () => {
    stopMicrophoneCapture();
    if (!listeningWantedRef.current || isSpeakingRef.current || isKairosSpeaking()) return;
    webSpeechDeliveredRef.current = false;
    webSpeechInterimSeenRef.current = false;

    // Engine A: Fast Interim Browser SpeechRecognition (Chrome / Edge)
    // HARD PRIVACY FIREWALL: Disabled whenever `isPrivateContext` is active so audio NEVER streams to Google WebSpeech servers!
    const w = window as unknown as {
      SpeechRecognition?: new () => SpeechRecognitionInstance;
      webkitSpeechRecognition?: new () => SpeechRecognitionInstance;
    };
    const Ctor = !liveCtxRef.current.isPrivateContext
      ? w.SpeechRecognition || w.webkitSpeechRecognition
      : undefined;
    if (Ctor) {
      try {
        const rec = new Ctor();
        rec.continuous = true;
        rec.interimResults = true;
        rec.lang = 'en-US';
        rec.onresult = (ev) => {
          let combined = '';
          for (let i = 0; i < ev.results.length; i += 1) {
            combined += ev.results[i][0].transcript + ' ';
          }
          const clean = normalizeKairosTranscript(combined.trim());
          if (!clean || clean.length < 2) return;
          webSpeechInterimSeenRef.current = true;
          setPrompt(clean);
          setVoice((prev) => ({ ...prev, last_transcript: clean }));
          if (silenceTimerRef.current !== null) {
            window.clearTimeout(silenceTimerRef.current);
          }
          silenceTimerRef.current = window.setTimeout(() => {
            webSpeechDeliveredRef.current = true;
            stopMicrophoneCapture();
            executePromptText(clean, true);
          }, holdSecondsRef.current * 1000);
        };
        rec.onerror = () => {};
        rec.onend = () => {};
        rec.start();
        recognitionRef.current = rec;
      } catch {
        // Electron fallback handled by Engine B below
      }
    }

    // Engine B: Real WebAudio VU Meter + Sustained VAD + MediaRecorder -> Sidecar `:8421` (`gemini-3.5-transcribe`)
    if (navigator.mediaDevices?.getUserMedia) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        if (!listeningWantedRef.current || isSpeakingRef.current || isKairosSpeaking()) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        mediaStreamRef.current = stream;

        const audioCtx = new AudioContext();
        audioCtxRef.current = audioCtx;
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);

        const chunks: BlobPart[] = [];
        const mimeCandidate = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
          ? 'audio/webm;codecs=opus'
          : 'audio/webm';
        const recorder = new MediaRecorder(stream, { mimeType: mimeCandidate });
        mediaRecorderRef.current = recorder;

        let speechDetected = false;
        let sustainedSpeechConfirmed = false;
        let voicedFrames = 0;
        let peakRms = 0;
        let lastSpeechTs = performance.now();

        recorder.ondataavailable = (ev) => {
          if (ev.data && ev.data.size > 0) chunks.push(ev.data);
        };
        recorder.onstop = () => {
          if (webSpeechDeliveredRef.current || !sustainedSpeechConfirmed || chunks.length === 0) {
            return;
          }
          const recordedBlob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
          if (recordedBlob.size < 2400) {
            if (listeningWantedRef.current && !isSpeakingRef.current) {
              scheduleHandsFreeRelisten(350);
            }
            return;
          }
          dispatchRecordedAudioBlob(recordedBlob);
        };
        recorder.start(250);

        const dataArr = new Uint8Array(analyser.frequencyBinCount);

        const monitorAudio = () => {
          if (!listeningWantedRef.current || !audioCtxRef.current || isSpeakingRef.current) return;
          analyser.getByteTimeDomainData(dataArr);
          let sumSq = 0;
          for (let i = 0; i < dataArr.length; i += 1) {
            const norm = (dataArr[i] - 128) / 128;
            sumSq += norm * norm;
          }
          const rms = Math.sqrt(sumSq / dataArr.length);
          const scaledVu = Math.min(100, Math.round(rms * 380));
          setLiveVuLevel(scaledVu);

          const now = performance.now();
          if (rms > 0.036) {
            if (rms > peakRms) peakRms = rms;
            voicedFrames += 1;
            lastSpeechTs = now;
            // Require >= 10 frames (~170ms) of vocal energy + 0.045 peak RMS so desk taps / clicks never trigger STT
            if (voicedFrames >= 10 && peakRms >= 0.045) {
              speechDetected = true;
              sustainedSpeechConfirmed = true;
            }
          } else {
            if (!speechDetected && voicedFrames > 0) {
              voicedFrames = Math.max(0, voicedFrames - 1);
            }
            const engineAGraceMs = webSpeechInterimSeenRef.current ? 450 : 0;
            if (
              speechDetected &&
              !webSpeechDeliveredRef.current &&
              now - lastSpeechTs >= holdSecondsRef.current * 1000 + engineAGraceMs
            ) {
              speechDetected = false;
              if (recorder.state === 'recording') {
                recorder.stop();
              }
              stopMicrophoneCapture();
              return;
            }
          }
          rafIdRef.current = window.requestAnimationFrame(monitorAudio);
        };
        rafIdRef.current = window.requestAnimationFrame(monitorAudio);
      } catch {
        // Mic permission denied or no audio hardware
      }
    }
  }, [dispatchRecordedAudioBlob, executePromptText, scheduleHandsFreeRelisten, stopMicrophoneCapture]);

  startListeningFnRef.current = () => {
    startLiveListeningSession().catch(() => {});
  };

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: number | undefined;
    let alive = true;

    warmupSpeechVoices();

    kairosApi
      .updateVoiceConfig({
        neural_tts: liveCtxRef.current.neuralTts,
        tts_voice: liveCtxRef.current.ttsVoice,
      })
      .then((s) => {
        if (!alive) return;
        setVoice((prev) => ({
          ...s,
          status:
            isSpeakingRef.current
              ? 'SPEAKING'
              : listeningWantedRef.current && s.status === 'IDLE'
                ? 'LISTENING'
                : s.status || prev.status,
        }));
        if (s.hands_free !== undefined) setHandsFree(s.hands_free);
        if (s.wake_word_only !== undefined) setWakeWordOnly(s.wake_word_only);
      })
      .catch(() => {});

    const connectVoiceWs = () => {
      if (!alive) return;
      try {
        ws = new WebSocket(VOICE_WS);
        ws.onmessage = (ev) => {
          try {
            const parsed = JSON.parse(ev.data) as VoiceStateSnapshot;
            if (!alive) return;
            setVoice((prev) => ({
              ...parsed,
              status:
                parsed.event === 'voice_barge_in'
                  ? parsed.status
                  : isSpeakingRef.current
                    ? 'SPEAKING'
                    : listeningWantedRef.current && parsed.status === 'IDLE'
                      ? 'LISTENING'
                      : parsed.status || prev.status,
            }));
            if (parsed.event === 'voice_barge_in') {
              stopSpeechOutput();
              if (listeningWantedRef.current && liveCtxRef.current.handsFree) {
                startListeningFnRef.current();
              }
            } else if (
              parsed.event === 'cognitive_mutter' &&
              parsed.mutter_clauses &&
              parsed.mutter_clauses.length > 0
            ) {
              const firstClause = parsed.mutter_clauses[0];
              setMutterClause(firstClause);
              if (!isSpeakingRef.current) {
                const ctxNow = liveCtxRef.current;
                speakCognitiveMutter(firstClause, {
                  ttsEnabled: ctxNow.ttsEnabled,
                  neuralTts: ctxNow.neuralTts,
                  ttsVoice: ctxNow.ttsVoice,
                  isPrivate: ctxNow.isPrivateContext,
                  activeNotePath: ctxNow.activeNotePath,
                }).catch(() => {});
              }
            }
          } catch {
            // ignore malformed frames
          }
        };
        ws.onclose = () => {
          if (alive) {
            reconnectTimer = window.setTimeout(connectVoiceWs, 2500);
          }
        };
        ws.onerror = () => {
          try {
            ws?.close();
          } catch {
            // ignore
          }
        };
      } catch {
        if (alive) {
          reconnectTimer = window.setTimeout(connectVoiceWs, 2500);
        }
      }
    };

    connectVoiceWs();

    return () => {
      alive = false;
      listeningWantedRef.current = false;
      window.clearTimeout(reconnectTimer);
      ws?.close();
      stopMicrophoneCapture();
      stopSpeechOutput();
    };
  }, [stopMicrophoneCapture, stopSpeechOutput]);

  const triggerVoice = useCallback(
    async (action: 'play' | 'pause' | 'stop' | 'extend-hold') => {
      if (action === 'play') {
        listeningWantedRef.current = true;
        stopSpeechOutput();
        startLiveListeningSession().catch(() => {});
      } else if (action === 'pause') {
        listeningWantedRef.current = false;
        stopMicrophoneCapture();
        stopSpeechOutput();
      } else if (action === 'stop') {
        listeningWantedRef.current = false;
        stopMicrophoneCapture();
        stopSpeechOutput();
      }

      try {
        const updated = await kairosApi.voiceAction(action);
        setVoice(updated);
      } catch {
        setVoice((prev) => ({
          ...prev,
          status:
            action === 'play'
              ? 'LISTENING'
              : action === 'pause'
                ? 'MUTED'
                : action === 'stop'
                  ? 'IDLE'
                  : prev.status,
          hold_seconds:
            action === 'extend-hold' ? Math.min(5.5, prev.hold_seconds + 1) : prev.hold_seconds,
        }));
      }
    },
    [startLiveListeningSession, stopMicrophoneCapture, stopSpeechOutput]
  );

  // Global Push-to-Toggle (`Ctrl+Space`) & Barge-In (`Escape`) keyboard shortcuts
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.code === 'Space') {
        e.preventDefault();
        if (listeningWantedRef.current || voice.status === 'LISTENING') {
          triggerVoice('stop');
        } else {
          triggerVoice('play');
        }
      } else if (e.key === 'Escape' && (isSpeakingRef.current || Boolean(mutterClause))) {
        stopSpeechOutput();
        kairosApi
          .triggerVoiceBargeIn()
          .then((s) => {
            setVoice(s);
            if (listeningWantedRef.current && liveCtxRef.current.handsFree) {
              startListeningFnRef.current();
            }
          })
          .catch(() => triggerVoice('stop'));
      } else if (e.key === 'Escape' && (replyCard || showVoiceHud || showPaperclipPopover)) {
        setReplyCard(null);
        setShowVoiceHud(false);
        setShowPaperclipPopover(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [
    mutterClause,
    replyCard,
    showPaperclipPopover,
    showVoiceHud,
    stopSpeechOutput,
    triggerVoice,
    voice.status,
  ]);

  const syncVoiceSettings = async (patch: {
    hands_free?: boolean;
    wake_word_only?: boolean;
    neural_tts?: boolean;
    tts_voice?: string;
  }) => {
    try {
      const updated = await kairosApi.updateVoiceConfig(patch);
      setVoice(updated);
    } catch {
      // keep optimistic UI state
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await executePromptText(prompt, false);
  };

  const effectiveStatus = busy ? 'THINKING' : voice.status;
  const orbColor =
    effectiveStatus === 'LISTENING'
      ? 'bg-emerald-400 shadow-[0_0_14px_rgba(16,185,129,0.85)] animate-pulse'
      : effectiveStatus === 'SPEAKING'
        ? 'bg-cyan-400 shadow-[0_0_16px_rgba(34,211,238,0.9)] animate-pulse'
        : effectiveStatus === 'THINKING'
          ? 'bg-amber-400 shadow-[0_0_14px_rgba(245,158,11,0.85)] animate-ping'
          : effectiveStatus === 'MUTED'
            ? 'bg-rose-500'
            : 'bg-cyan-400 shadow-[0_0_10px_rgba(6,182,212,0.65)]';

  const activeCount = paperclipSnapshot?.active_count || 0;
  const displayVu = Math.max(voice.vu_level || 8, liveVuLevel);

  return (
    <header className="relative z-40 h-14 w-full shrink-0 border-b border-kairos-border bg-kairos-panel/95 px-3 backdrop-blur flex items-center justify-between gap-3 select-none">
      {/* Left: KAIROS Permanent Embedded Voice Deck */}
      <div className="flex items-center gap-2 shrink-0">
        <button
          type="button"
          onClick={() => setShowVoiceHud((v) => !v)}
          title="Open KAIROS Voice Co-Pilot & Platform Navigation HUD (Ctrl+Space to Talk)"
          className="flex items-center gap-2 pr-2.5 border-r border-kairos-border text-left group"
        >
          <span className={`h-3 w-3 rounded-full ${orbColor}`} />
          <div className="leading-tight">
            <div className="text-xs font-bold tracking-wider text-white flex items-center gap-1.5 group-hover:text-emerald-300 transition">
              KAIROS 2.0
              <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium text-emerald-300">
                {effectiveStatus}
              </span>
            </div>
            <div className="text-[10px] text-slate-400 flex items-center gap-1 max-w-[190px] truncate">
              {mutterClause || voice.is_thinking_aloud ? (
                <span className="text-amber-300 italic truncate">
                  💭 {mutterClause || 'Thinking aloud...'}
                </span>
              ) : (
                <>
                  <span>Voice Co-Pilot</span>
                  {wakeWordOnly && <span className="text-cyan-400">• Hey Kairos</span>}
                </>
              )}
            </div>
          </div>
        </button>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => triggerVoice('play')}
            title="Start Hands-Free Voice Listening (Ctrl+Space)"
            className={`flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition ${
              effectiveStatus === 'LISTENING'
                ? 'border-emerald-400 bg-emerald-500/25 text-emerald-200'
                : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'
            }`}
          >
            <Play className="h-3 w-3" /> Play
          </button>
          <button
            type="button"
            onClick={() => triggerVoice('pause')}
            title="Mute Mic & Output"
            className="flex items-center gap-1 rounded-md border border-kairos-border bg-kairos-card px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 transition"
          >
            <Pause className="h-3 w-3" /> Pause
          </button>
          <button
            type="button"
            onClick={() => triggerVoice('stop')}
            title="Immediate Barge-In / Stop Speech (Esc)"
            className="flex items-center gap-1 rounded-md border border-kairos-border bg-kairos-card px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 transition"
          >
            <Square className="h-3 w-3" /> Stop
          </button>
          <button
            type="button"
            onClick={() => triggerVoice('extend-hold')}
            title="Extend Thinking-Pause Silence Hold (+1s)"
            className="flex items-center gap-1 rounded-md border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-xs font-medium text-cyan-300 hover:bg-cyan-500/20 transition"
          >
            <Mic className="h-3 w-3" /> +1s ({voice.hold_seconds.toFixed(1)}s)
          </button>
          <button
            type="button"
            onClick={() => {
              if (ttsEnabled) stopSpeechOutput();
              onToggleTtsEnabled();
            }}
            title={
              ttsEnabled
                ? 'KAIROS Voice Output ON (Click to Mute)'
                : 'KAIROS Voice Output Muted (Click to Enable)'
            }
            className="rounded-md border border-kairos-border bg-kairos-card p-1.5 text-slate-300 hover:text-white transition"
          >
            {ttsEnabled ? (
              <Volume2 className="h-3.5 w-3.5 text-emerald-400" />
            ) : (
              <VolumeOff className="h-3.5 w-3.5 text-slate-500" />
            )}
          </button>
          <button
            type="button"
            onClick={() => setShowVoiceHud((v) => !v)}
            title="Open Voice Navigator HUD & Spoken Command Guide"
            className={`flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-semibold transition ${
              showVoiceHud
                ? 'border-emerald-400/60 bg-emerald-500/25 text-emerald-200'
                : 'border-kairos-border bg-kairos-card text-slate-300 hover:border-emerald-500/40 hover:text-emerald-300'
            }`}
          >
            <Compass className="h-3.5 w-3.5 text-emerald-400" />
            <span className="hidden 2xl:inline">Voice HUD</span>
          </button>
        </div>

        <div className="hidden xl:flex items-center gap-0.5 h-4 px-1.5 rounded bg-kairos-bg border border-kairos-border">
          {[18, 35, 55, 28, 70, 40].map((bar, idx) => {
            const active =
              (effectiveStatus === 'LISTENING' || effectiveStatus === 'SPEAKING') &&
              displayVu >= bar / 2;
            return (
              <span
                key={idx}
                style={{
                  height: `${Math.max(25, active ? Math.min(100, displayVu + (idx % 3) * 12) : 22)}%`,
                }}
                className={`w-1 rounded-sm transition-all duration-75 ${
                  effectiveStatus === 'SPEAKING'
                    ? 'bg-cyan-400'
                    : active
                      ? 'bg-emerald-400'
                      : 'bg-slate-700'
                }`}
              />
            );
          })}
        </div>
      </div>

      {/* Voice Co-Pilot & Platform Navigation HUD Popover */}
      <VoiceNavigatorHUD
        open={showVoiceHud}
        onClose={() => setShowVoiceHud(false)}
        voice={{ ...voice, status: effectiveStatus }}
        liveVuLevel={liveVuLevel}
        activeTaskId={activeTaskId}
        handsFree={handsFree}
        onToggleHandsFree={() => {
          const next = !handsFree;
          setHandsFree(next);
          syncVoiceSettings({ hands_free: next });
        }}
        wakeWordOnly={wakeWordOnly}
        onToggleWakeWordOnly={() => {
          const next = !wakeWordOnly;
          setWakeWordOnly(next);
          syncVoiceSettings({ wake_word_only: next });
        }}
        neuralTts={neuralTts}
        onToggleNeuralTts={() => {
          const next = !neuralTts;
          onChangeNeuralTts(next);
          syncVoiceSettings({ neural_tts: next });
        }}
        ttsVoice={ttsVoice}
        onChangeTtsVoice={(v) => {
          onChangeTtsVoice(v);
          syncVoiceSettings({ tts_voice: v });
        }}
        isPrivateContext={isPrivateContext}
        onRunSpokenPhrase={(phrase) => {
          executePromptText(phrase, false);
        }}
      />

      {/* Center: Live Voice & Text Command / Platform Navigator Bar */}
      <form onSubmit={handleSubmit} className="relative flex-1 max-w-2xl">
        <div className="flex items-center rounded-lg border border-kairos-border bg-kairos-bg px-3 py-1.5 focus-within:border-emerald-500/60">
          <Sparkles className="h-3.5 w-3.5 text-emerald-400 mr-2 shrink-0" />
          <input
            type="text"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder='Speak or type to navigate & command (e.g. "Open KAIROS and switch to Gantt" or "Show 3D Galaxy graph")'
            className="w-full bg-transparent text-xs text-slate-100 placeholder-slate-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={busy}
            className="ml-2 rounded bg-emerald-500/20 px-2 py-0.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-50 flex items-center gap-1"
          >
            <Send className="h-3 w-3" />
            Ask
          </button>
        </div>

        {replyCard && (
          <div className="absolute left-0 right-0 top-11 z-50 rounded-xl border border-emerald-500/50 bg-[#0B101B] p-3.5 shadow-[0_24px_64px_rgba(0,0,0,0.92)]">
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2 text-xs font-semibold text-emerald-300">
                <Brain className="h-3.5 w-3.5" />
                <span>{replyCard.agent}</span>
                {replyCard.privacy_locked && (
                  <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-300">
                    🔒 Local Privacy Enforced
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={Boolean(replyCard.retained)}
                  onClick={async () => {
                    try {
                      const prefix = replyCard.privacy_locked ? '[#private] ' : '';
                      const compact = replyCard.reply.replace(/\s+/g, ' ').trim().slice(0, 340);
                      await kairosApi.retainHermesMemory({
                        fact: `${prefix}${compact}`,
                        target: 'memory',
                        is_private: Boolean(replyCard.privacy_locked),
                      });
                      setReplyCard((prev) => (prev ? { ...prev, retained: true } : null));
                      onCommandCompleted();
                    } catch {
                      // keep replyCard mounted if backend is temporarily busy
                    }
                  }}
                  title="Retain this answer in Hermes Persistent Memory (MEMORY.md)"
                  className="rounded border border-purple-500/40 bg-[#11192B] px-2 py-0.5 text-[10.5px] font-semibold text-purple-200 hover:border-purple-400 disabled:opacity-70"
                >
                  {replyCard.retained ? '✓ Retained' : '🪽 Retain'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setReplyCard(null);
                    if (!chatDrawerOpen) onToggleChatDrawer();
                  }}
                  className="text-[11px] text-cyan-300 hover:underline"
                >
                  Continue in Chat Panel →
                </button>
                <button
                  type="button"
                  onClick={() => {
                    stopSpeechOutput();
                    setReplyCard(null);
                  }}
                  className="text-slate-400 hover:text-white"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
            <p className="text-xs leading-relaxed text-slate-200 whitespace-pre-wrap max-h-60 overflow-y-auto">
              {replyCard.reply}
            </p>
          </div>
        )}
      </form>

      {/* Right: Dual-AI Brain Selector + Docked KAIROS Chat Toggle + Paperclip Live Popover */}
      <div className="relative flex items-center gap-2 shrink-0">
        {isPrivateContext && (
          <span
            title="03_Personal/Finance or #private note active — Cloud LLMs & Cloud Audio blocked, locked to Local Gemma 4"
            className="flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/15 px-2 py-1 text-[11px] font-semibold text-amber-300"
          >
            <Lock className="h-3 w-3" /> Local-Only
          </span>
        )}

        <div className="flex items-center rounded-lg border border-kairos-border bg-kairos-bg p-0.5 text-[11px]">
          {(
            [
              { id: 'auto', label: 'Auto' },
              { id: 'gemma-4', label: 'Gemma 4' },
              { id: 'gemini', label: 'Gemini' },
              { id: 'hybrid', label: 'Hybrid' },
            ] as { id: BrainMode; label: string }[]
          ).map((opt) => {
            const disabled = isPrivateContext && opt.id !== 'gemma-4';
            const selected = (isPrivateContext ? 'gemma-4' : brainMode) === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                disabled={disabled}
                onClick={() => onChangeBrainMode(opt.id)}
                className={`rounded-md px-2 py-1 font-medium transition ${
                  selected
                    ? 'bg-emerald-500/25 text-emerald-300'
                    : 'text-slate-400 hover:text-slate-200'
                } ${disabled ? 'opacity-35 cursor-not-allowed' : ''}`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>

        {/* Collapsible KAIROS Chatbot Virtual Assistant Drawer Toggle */}
        <button
          type="button"
          onClick={onToggleChatDrawer}
          title="Toggle Docked KAIROS Chatbot Virtual Assistant Panel"
          className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold transition ${
            chatDrawerOpen
              ? 'border-emerald-500/50 bg-emerald-500/25 text-emerald-200'
              : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'
          }`}
        >
          <BotMessageSquare className="h-3.5 w-3.5" />
          <span>KAIROS Chat</span>
        </button>

        <button
          type="button"
          onClick={() => setShowPaperclipPopover((v) => !v)}
          title="View Live Paperclip Task Locks & CrewAI Progress"
          className="flex items-center gap-1.5 rounded-lg border border-purple-500/30 bg-purple-500/15 px-2.5 py-1 text-xs font-medium text-purple-200 hover:bg-purple-500/25 transition"
        >
          <Paperclip className="h-3.5 w-3.5 text-purple-300" />
          <span>Paperclip</span>
          <span className="rounded-full bg-purple-400/25 px-1.5 text-[10px] font-bold text-purple-200">
            {activeCount}
          </span>
        </button>

        {showPaperclipPopover && (
          <div className="absolute right-0 top-11 z-50 w-80 rounded-xl border border-purple-500/50 bg-[#0B101B] p-3.5 shadow-[0_24px_64px_rgba(0,0,0,0.92)] space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-purple-200">
                📎 Paperclip, CrewAI & Hermes ({activeCount} Active)
              </span>
              <button
                type="button"
                onClick={() => setShowPaperclipPopover(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>

            <div className="rounded-lg border border-cyan-500/30 bg-[#11192B] px-2.5 py-1.5 text-[11px] text-cyan-200 flex items-center justify-between">
              <span>🪽 Hermes Continuity</span>
              <span className="font-mono text-emerald-300">
                {hermesSkillCount} SKL-*.md skill{hermesSkillCount === 1 ? '' : 's'}
              </span>
            </div>

            {(paperclipSnapshot?.active_locks || []).length === 0 ? (
              <div className="rounded-lg border border-slate-700/80 bg-[#11192B] p-2.5 text-[11px] text-slate-300">
                No tasks currently locked. Assign a task to `Hermes-*` or `CrewAI-*` or dispatch
                from the Control Plane.
              </div>
            ) : (
              <div className="space-y-1.5">
                {paperclipSnapshot?.active_locks.map((lk) => (
                  <button
                    key={lk.lock_id}
                    type="button"
                    onClick={() => {
                      setShowPaperclipPopover(false);
                      onExecuteUiCommands(
                        [
                          { type: 'navigate_tab', tab: 'projects' },
                          { type: 'open_task_drawer', task_id: lk.task_id },
                        ],
                        `Inspecting locked task ${lk.task_id}`
                      );
                    }}
                    className="w-full text-left rounded-lg border border-amber-500/40 bg-[#1B1710] p-2 text-[11px] hover:border-amber-400 transition"
                  >
                    <div className="font-semibold text-amber-200">
                      {lk.task_id} • {lk.agent}
                    </div>
                    <div className="text-slate-300 truncate">{lk.step}</div>
                  </button>
                ))}
              </div>
            )}

            {(paperclipSnapshot?.recent_runs || []).slice(0, 2).map((r, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => {
                  setShowPaperclipPopover(false);
                  onExecuteUiCommands(
                    [
                      { type: 'navigate_tab', tab: 'projects' },
                      { type: 'open_task_drawer', task_id: r.task_id },
                    ],
                    `Opened completed run task ${r.task_id}`
                  );
                }}
                className="w-full text-left rounded border border-slate-700/80 bg-[#11192B] px-2.5 py-1.5 text-[11px] text-slate-200 hover:border-emerald-500/50 transition"
              >
                ✓ <span className="font-mono text-emerald-300">{r.task_id}</span> ({r.agent}) —{' '}
                {r.status}
              </button>
            ))}

            <button
              type="button"
              onClick={() => {
                setShowPaperclipPopover(false);
                onOpenPaperclip();
              }}
              className="w-full flex items-center justify-center gap-1 rounded-lg bg-purple-500/25 border border-purple-500/45 py-1.5 text-xs font-semibold text-purple-200 hover:bg-purple-500/35"
            >
              Open Full Paperclip, CrewAI & Hermes Hub <ExternalLink className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>
    </header>
  );
};

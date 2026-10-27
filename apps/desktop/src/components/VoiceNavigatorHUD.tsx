import React from 'react';
import {
  Compass,
  Cpu,
  Flame,
  Globe,
  Headphones,
  Kanban,
  Lock,
  Mic,
  Orbit,
  Radio,
  Sparkles,
  Volume2,
  X,
} from 'lucide-react';
import { VoiceStateSnapshot } from '../api/client.ts';

interface VoiceNavigatorHUDProps {
  open: boolean;
  onClose: () => void;
  voice: VoiceStateSnapshot;
  liveVuLevel: number;
  activeTaskId?: string;
  handsFree: boolean;
  onToggleHandsFree: () => void;
  wakeWordOnly: boolean;
  onToggleWakeWordOnly: () => void;
  neuralTts: boolean;
  onToggleNeuralTts: () => void;
  ttsVoice: string;
  onChangeTtsVoice: (voiceName: string) => void;
  isPrivateContext: boolean;
  onRunSpokenPhrase: (phrase: string) => void;
}

function buildVoiceGroups(activeTaskId: string): {
  title: string;
  icon: React.ReactNode;
  accent: string;
  commands: { label: string; phrase: string }[];
}[] {
  const cleanTask = activeTaskId.trim();
  return [
    {
      title: 'Projects, Rollup, Calendar, Gantt & Wiki',
      icon: <Kanban className="h-3.5 w-3.5 text-emerald-400" />,
      accent: 'hover:border-emerald-500/60',
      commands: [
        { label: 'Everything Rollup', phrase: 'Open Everything view and switch to Rollup' },
        { label: 'KAIROS Gantt Timeline', phrase: 'Open KAIROS and switch to Gantt' },
        { label: 'KAIROS Calendar Grid', phrase: 'Open KAIROS and switch to Calendar view' },
        { label: 'KAIROS Marketing Board', phrase: 'Open KAIROS Marketing and Branding and show Kanban board' },
        { label: 'KAIROS 2.0 Project Wiki', phrase: 'Open KAIROS 2.0 and switch to Documentation view' },
        cleanTask
          ? { label: `Inspect ${cleanTask}`, phrase: `Open task ${cleanTask}` }
          : { label: 'KAIROS 2.0 Task Base', phrase: 'Create task base for KAIROS 2.0' },
      ],
    },
    {
      title: 'Second Brain & 3D Galaxy',
      icon: <Orbit className="h-3.5 w-3.5 text-cyan-400" />,
      accent: 'hover:border-cyan-500/60',
      commands: [
        { label: '3D Galaxy Graph', phrase: 'Show the 3D Galaxy graph in Second Brain' },
        { label: '2D WikiLink Map', phrase: 'Switch Second Brain graph to 2D map' },
        { label: 'Today’s Daily Note', phrase: "Open today's daily note" },
        { label: 'Operating Constitution', phrase: 'Open AGENTS.md' },
        { label: 'KAIROS Architecture Canvas', phrase: 'Open KAIROS architecture diagram canvas' },
        { label: 'Private Finance Shield', phrase: 'Open Finance folder' },
      ],
    },
    {
      title: 'YouTube, Sports Highlights & Browser Controls',
      icon: <Globe className="h-3.5 w-3.5 text-purple-400" />,
      accent: 'hover:border-purple-500/60',
      commands: [
        { label: 'Game Highlights (Context)', phrase: 'Can you pull up highlights of the game?' },
        { label: 'Browns YouTube Highlights', phrase: 'Go to YouTube and pull up Cleveland Browns highlights' },
        { label: 'Score + Highlights Hybrid', phrase: "What's the score of the Browns game and can you pull up the highlights?" },
        { label: 'YouTube Video Tutorial', phrase: 'Watch Three.js shader tutorial on YouTube' },
        { label: 'Google Web Lookup', phrase: 'Google Printful heavyweight hoodie sizing' },
        { label: 'Browser Back', phrase: 'Go back in the browser' },
        { label: 'Refresh Browser Page', phrase: 'Refresh this page' },
        { label: 'Open New Browser Tab', phrase: 'Open a new browser tab' },
      ],
    },
    {
      title: 'Hermes, Paperclip, Personas & CODE RED',
      icon: <Flame className="h-3.5 w-3.5 text-rose-400" />,
      accent: 'hover:border-rose-500/60',
      commands: [
        { label: 'Paperclip, CrewAI & Hermes', phrase: 'Open Hermes memory' },
        cleanTask
          ? { label: `Dispatch Hermes (${cleanTask})`, phrase: `Dispatch Hermes-Agent on ${cleanTask}` }
          : { label: 'Open Music Studio Hub', phrase: 'Open Music Studio' },
        { label: 'Executive Daily Briefing', phrase: 'Give me my daily briefing' },
        { label: 'Activate CODE RED', phrase: 'Activate CODE RED' },
        {
          label: 'Schedule Calendar Event',
          phrase: 'Schedule calendar event Sprint Demo at 2 PM tomorrow in KAIROS 2.0',
        },
        {
          label: 'Voice Task + Open Drawer',
          phrase: 'Create high-priority task in KAIROS Website for interactive 3D hero demo and open it',
        },
        {
          label: 'Clip Active Browser Page',
          phrase: 'Clip this page to Inbox',
        },
        {
          label: 'Promote Latest Inbox Note',
          phrase: 'Promote latest inbox note to KAIROS Marketing',
        },
        {
          label: 'Append Daily Note Entry',
          phrase: "Append to today's daily note: Voice platform synergy verified",
        },
        {
          label: '1080p Screen Vision',
          phrase: 'Look at my screen and summarize what is open',
        },
      ],
    },
  ];
}

const TTS_VOICES = ['Kore', 'Puck', 'Charon', 'Fenrir', 'Aoede'];

export const VoiceNavigatorHUD: React.FC<VoiceNavigatorHUDProps> = ({
  open,
  onClose,
  voice,
  liveVuLevel,
  activeTaskId = '',
  handsFree,
  onToggleHandsFree,
  wakeWordOnly,
  onToggleWakeWordOnly,
  neuralTts,
  onToggleNeuralTts,
  ttsVoice,
  onChangeTtsVoice,
  isPrivateContext,
  onRunSpokenPhrase,
}) => {
  if (!open) return null;

  const effectiveVu = Math.max(voice.vu_level || 8, liveVuLevel);
  const voiceGroups = buildVoiceGroups(activeTaskId);

  return (
    <>
      {/* Solid Dimmed Backdrop so underlying workspace content never bleeds through */}
      <div
        onClick={onClose}
        className="fixed inset-0 top-14 z-[90] bg-black/75"
        style={{ backgroundColor: 'rgba(2, 6, 16, 0.78)' }}
      />

      <div
        style={{ backgroundColor: '#0B1220' }}
        className="fixed left-3 top-16 z-[100] w-[790px] max-w-[96vw] rounded-2xl border-2 border-emerald-500/60 bg-[#0B1220] p-4 text-slate-100 shadow-[0_28px_90px_rgba(0,0,0,0.96)] select-none"
      >
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-700/80 pb-3">
          <div className="flex items-center gap-2.5">
            <div
              style={{ backgroundColor: '#102624' }}
              className="flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-500/50"
            >
              <Compass className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <div className="flex items-center gap-2 text-sm font-bold text-white">
                <span>KAIROS Voice Co-Pilot & Platform Navigator</span>
                <span className="rounded-full bg-emerald-500/25 border border-emerald-400/50 px-2 py-0.5 text-[10px] font-bold text-emerald-200">
                  {voice.status}
                </span>
                <span
                  style={{ backgroundColor: '#162238' }}
                  className="rounded border border-slate-600 px-1.5 py-0.5 text-[10px] font-mono text-slate-200"
                >
                  Ctrl+Space Mic • Esc Stop
                </span>
              </div>
              <div className="text-[11px] text-slate-300">
                Dual-Engine STT (`WebSpeech` + `Gemini Audio` `:8421`) • Expressive `Gemini Neural TTS` + Instant Local Voice • Zero-Echo Auto-Ducking
              </div>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            style={{ backgroundColor: '#162238' }}
            className="rounded-lg border border-slate-600 p-1.5 text-slate-200 hover:border-emerald-400 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Live Audio Meter + Voice Engine Toggles */}
        <div className="mt-3 grid grid-cols-1 md:grid-cols-12 gap-3">
          <div
            style={{ backgroundColor: '#111B2E' }}
            className="md:col-span-5 rounded-xl border border-slate-700 p-3 flex flex-col justify-between gap-2"
          >
            <div className="flex items-center justify-between text-[11px]">
              <span className="font-bold text-white flex items-center gap-1.5">
                <Mic className="h-3.5 w-3.5 text-emerald-400" /> Live Microphone & Transcript
              </span>
              {isPrivateContext && (
                <span className="inline-flex items-center gap-1 rounded bg-amber-500/25 border border-amber-500/50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-200">
                  <Lock className="h-2.5 w-2.5" /> Cloud Audio Blocked
                </span>
              )}
            </div>

            {/* 16-bar live spectrum meter */}
            <div
              style={{ backgroundColor: '#080E1A' }}
              className="flex items-end gap-1 h-9 rounded-lg border border-slate-700 px-2.5 py-1.5"
            >
              {Array.from({ length: 16 }).map((_, idx) => {
                const wave = Math.sin((idx + 1) * 0.65) * 0.35 + 0.65;
                const barPct =
                  voice.status === 'LISTENING' || voice.status === 'SPEAKING'
                    ? Math.min(100, Math.max(20, Math.round(effectiveVu * wave)))
                    : 22;
                return (
                  <span
                    key={idx}
                    style={{ height: `${barPct}%` }}
                    className={`flex-1 rounded-sm transition-all duration-75 ${
                      voice.status === 'SPEAKING'
                        ? 'bg-cyan-400'
                        : voice.status === 'LISTENING'
                          ? 'bg-emerald-400'
                          : 'bg-slate-600'
                    }`}
                  />
                );
              })}
            </div>

            <div className="space-y-1 text-[11px]">
              <div className="truncate text-slate-200">
                <span className="text-slate-400 font-semibold">Heard: </span>
                <span className="font-semibold text-emerald-300">
                  &ldquo;{voice.last_transcript || 'Say any workspace, project, task, or live question...'}&rdquo;
                </span>
              </div>
              {voice.last_reply && (
                <div className="line-clamp-2 text-slate-200 text-[10.5px]">
                  <span className="text-cyan-300 font-semibold">KAIROS: </span>
                  {voice.last_reply}
                </div>
              )}
            </div>
          </div>

          <div
            style={{ backgroundColor: '#111B2E' }}
            className="md:col-span-7 rounded-xl border border-slate-700 p-3 grid grid-cols-2 gap-2 text-xs"
          >
            <button
              type="button"
              onClick={onToggleHandsFree}
              style={{ backgroundColor: handsFree ? '#0F2E28' : '#162238' }}
              className={`rounded-lg border p-2.5 text-left transition ${
                handsFree
                  ? 'border-emerald-400/60 text-emerald-100'
                  : 'border-slate-600 text-slate-200 hover:border-slate-400'
              }`}
            >
              <div className="font-bold flex items-center gap-1.5 text-[11px] text-white">
                <Headphones className="h-3.5 w-3.5 text-emerald-400" />
                Hands-Free Loop: {handsFree ? 'ON' : 'OFF'}
              </div>
              <div className="text-[10px] text-slate-300 mt-0.5">
                Auto-resumes listening after KAIROS finishes speaking (zero echo).
              </div>
            </button>

            <button
              type="button"
              onClick={onToggleWakeWordOnly}
              style={{ backgroundColor: wakeWordOnly ? '#0F2938' : '#162238' }}
              className={`rounded-lg border p-2.5 text-left transition ${
                wakeWordOnly
                  ? 'border-cyan-400/60 text-cyan-100'
                  : 'border-slate-600 text-slate-200 hover:border-slate-400'
              }`}
            >
              <div className="font-bold flex items-center gap-1.5 text-[11px] text-white">
                <Radio className="h-3.5 w-3.5 text-cyan-400" />
                &ldquo;Hey Kairos&rdquo; Filter: {wakeWordOnly ? 'ON' : 'OFF'}
              </div>
              <div className="text-[10px] text-slate-300 mt-0.5">
                Only executes utterances addressed to &ldquo;Hey Kairos&rdquo; or &ldquo;Kairos&rdquo;.
              </div>
            </button>

            <button
              type="button"
              onClick={onToggleNeuralTts}
              style={{ backgroundColor: neuralTts && !isPrivateContext ? '#24173B' : '#162238' }}
              className={`rounded-lg border p-2.5 text-left transition ${
                neuralTts && !isPrivateContext
                  ? 'border-purple-400/60 text-purple-100'
                  : 'border-slate-600 text-slate-200 hover:border-slate-400'
              }`}
            >
              <div className="font-bold flex items-center gap-1.5 text-[11px] text-white">
                <Volume2 className="h-3.5 w-3.5 text-purple-300" />
                Neural TTS:{' '}
                {voice.kokoro_local_ready
                  ? 'KOKORO-82M LOCAL'
                  : isPrivateContext
                    ? 'LOCAL LOCK'
                    : neuralTts
                      ? 'GEMINI NEURAL'
                      : 'LOCAL VOICE'}
              </div>
              <div className="text-[10px] text-slate-300 mt-0.5">
                Dual-Prosody `[mutter]` (1.12x / -3.3 dB) & `[normal]` 24kHz synthesis.
              </div>
            </button>

            <div
              style={{ backgroundColor: '#162238' }}
              className="rounded-lg border border-slate-600 p-2.5 flex flex-col justify-between"
            >
              <label className="text-[11px] font-bold text-white flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-amber-300" /> Neural Voice Profile
              </label>
              <select
                value={ttsVoice}
                onChange={(e) => onChangeTtsVoice(e.target.value)}
                style={{ backgroundColor: '#0B1220' }}
                className="mt-1 rounded border border-slate-500 px-2 py-1 text-[11px] font-medium text-white"
              >
                {TTS_VOICES.map((v) => (
                  <option key={v} value={v}>
                    {v} (Gemini Expressive Voice)
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Cognitive Full-Duplex Pipeline & 16 GB RTX 5070 Ti VRAM Envelope */}
        <div
          style={{ backgroundColor: '#0E1729' }}
          className="mt-2.5 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-700/90 px-3 py-2 text-[10.5px]"
        >
          <div className="flex items-center gap-1.5 font-semibold text-emerald-300">
            <Cpu className="h-3.5 w-3.5 text-emerald-400" />
            <span>KV Prefix Cache: PINNED (Idx 0)</span>
          </div>
          <div className="flex items-center gap-2 text-slate-200">
            <span className="rounded bg-slate-800 border border-slate-600 px-1.5 py-0.5 font-mono">
              Prosody: {(voice.prosody_mode || 'normal').toUpperCase()}
            </span>
            <span className="rounded bg-slate-800 border border-slate-600 px-1.5 py-0.5 font-mono">
              VAD: {(voice.vad_threshold ?? 0.5).toFixed(2)}
            </span>
            <span className="rounded bg-emerald-500/15 border border-emerald-500/40 px-1.5 py-0.5 font-mono text-emerald-200">
              VRAM: {(voice.vram_telemetry?.active_resident_vram_gb ?? 11.86).toFixed(2)} /{' '}
              {(voice.vram_telemetry?.vram_ceiling_gb ?? 11.86).toFixed(2)} GB (16 GB Cap)
            </span>
          </div>
        </div>

        {/* Interactive Spoken Navigation Matrix */}
        <div className="mt-3.5">
          <div className="text-[10.5px] font-bold uppercase tracking-wider text-emerald-300 mb-2">
            Say Any Phrase Out Loud — Or Click Any Card Below to Execute & Speak Immediately
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 max-h-[320px] overflow-y-auto pr-1">
            {voiceGroups.map((grp) => (
              <div
                key={grp.title}
                style={{ backgroundColor: '#111B2E' }}
                className="rounded-xl border border-slate-700 p-2.5 space-y-1.5"
              >
                <div className="flex items-center gap-1.5 text-xs font-bold text-white">
                  {grp.icon}
                  <span>{grp.title}</span>
                </div>
                <div className="grid grid-cols-1 gap-1.5">
                  {grp.commands.map((cmd) => (
                    <button
                      key={cmd.phrase}
                      type="button"
                      onClick={() => {
                        onRunSpokenPhrase(cmd.phrase);
                        onClose();
                      }}
                      style={{ backgroundColor: '#182540' }}
                      className={`flex items-center justify-between gap-2 rounded-lg border border-slate-600 px-2.5 py-1.5 text-left transition ${grp.accent} hover:brightness-110`}
                    >
                      <span className="text-[11px] font-bold text-white shrink-0">
                        {cmd.label}
                      </span>
                      <span className="text-[10.5px] text-slate-300 truncate italic">
                        &ldquo;{cmd.phrase}&rdquo;
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
};

export interface VoiceNavToastData {
  id: number;
  summary: string;
  agent: string;
}

export const VoiceNavToastBanner: React.FC<{
  toast: VoiceNavToastData | null;
  onDismiss: () => void;
}> = ({ toast, onDismiss }) => {
  if (!toast) return null;
  return (
    <div
      style={{ backgroundColor: '#0B1324' }}
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[110] flex items-center gap-2.5 rounded-full border-2 border-emerald-500/60 px-4 py-2 text-xs text-slate-100 shadow-[0_12px_36px_rgba(0,0,0,0.85)]"
    >
      <Compass className="h-4 w-4 text-emerald-400 animate-spin" style={{ animationDuration: '4s' }} />
      <span className="font-semibold text-emerald-300">{toast.agent}:</span>
      <span className="max-w-xl truncate text-white">{toast.summary}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="ml-1 rounded-full p-0.5 text-slate-300 hover:text-white"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
};

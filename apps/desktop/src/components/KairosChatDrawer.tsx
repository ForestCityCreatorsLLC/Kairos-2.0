import React, { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  Archive,
  BotMessageSquare,
  Edit3,
  ExternalLink,
  Flame,
  Lock,
  Maximize2,
  MessageSquarePlus,
  RefreshCw,
  Send,
  Sparkles,
  Volume2,
  VolumeOff,
  X,
  Zap,
} from 'lucide-react';
import {
  AssistantSessionDetail,
  AssistantSessionSummary,
  BrainMode,
  PersonaRole,
  ToneMode,
  UIActionCommand,
  kairosApi,
} from '../api/client.ts';
import { ToastKind } from './ToastCenter.tsx';
import { stopKairosSpeech } from '../utils/speech.ts';

const PERSONA_OPTIONS: { id: PersonaRole; label: string; short: string }[] = [
  { id: 'companion', label: 'KAIROS Companion', short: 'Companion' },
  { id: 'pm', label: 'Project Director', short: 'PM' },
  { id: 'dev', label: 'Systems Architect', short: 'Architect' },
  { id: 'creative', label: 'Brand & Merch', short: 'Creative' },
  { id: 'owner', label: 'Executive / Co-CEO', short: 'Executive' },
];

const QUICK_CHIPS = [
  'Give me my daily briefing',
  "What's the score of the Browns game?",
  'Can you pull up highlights of the game?',
  'Pull up Forest City Creators repositories',
  'Open KAIROS 2.0 and switch to Gantt',
  'Clip this page to Inbox',
  "Append to today's daily note: Sprint checkpoint green",
  'Hermes, remember that Projects always start on the Rollup view',
  'Create high-priority task in KAIROS 2.0 Marketing to draft launch reel and open it',
];

interface KairosChatDrawerProps {
  open: boolean;
  widthPx?: number;
  onResizeMouseDown?: (e: React.MouseEvent<HTMLDivElement>) => void;
  onClose: () => void;
  onExpandFullWorkspace: () => void;
  brainMode: BrainMode;
  persona: PersonaRole;
  onChangePersona: (p: PersonaRole) => void;
  toneMode: ToneMode;
  onChangeToneMode: (t: ToneMode) => void;
  activeSessionId: string;
  onSelectSessionId: (sid: string) => void;
  activeNotePath: string;
  activeTaskId?: string;
  activeBrowserUrl?: string;
  activeBrowserTitle?: string;
  isPrivateContext: boolean;
  projectScope: string;
  departmentScope: string;
  currentTab?: string;
  currentView?: string;
  refreshTick: number;
  onVaultMutated: () => void;
  onOpenNoteInSecondBrain: (relPath: string) => void;
  onExecuteUiCommands?: (cmds: UIActionCommand[], summary?: string, agent?: string) => void;
  ttsEnabled: boolean;
  onToggleTtsEnabled: () => void;
  onSpeakReply: (text: string, isPrivate?: boolean) => void;
  onNotify?: (kind: ToastKind, title: string, detail?: string) => void;
}

export const KairosChatDrawer: React.FC<KairosChatDrawerProps> = ({
  open,
  widthPx = 390,
  onResizeMouseDown,
  onClose,
  onExpandFullWorkspace,
  brainMode,
  persona,
  onChangePersona,
  toneMode,
  onChangeToneMode,
  activeSessionId,
  onSelectSessionId,
  activeNotePath,
  activeTaskId = '',
  activeBrowserUrl = '',
  activeBrowserTitle = '',
  isPrivateContext,
  projectScope,
  departmentScope,
  currentTab = '',
  currentView = '',
  refreshTick,
  onVaultMutated,
  onOpenNoteInSecondBrain,
  onExecuteUiCommands,
  ttsEnabled,
  onToggleTtsEnabled,
  onSpeakReply,
  onNotify,
}) => {
  const [sessions, setSessions] = useState<AssistantSessionSummary[]>([]);
  const [sessionDetail, setSessionDetail] = useState<AssistantSessionDetail | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameDraft, setRenameDraft] = useState('');
  const [input, setInput] = useState('');
  const [retainedTurns, setRetainedTurns] = useState<Record<string, boolean>>({});
  const [sending, setSending] = useState(false);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [lastFailedPrompt, setLastFailedPrompt] = useState<string>('');
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const loadSessionsAndActive = async () => {
    const listRes = await kairosApi.listAssistantSessions();
    setSessions(listRes.sessions);
    const fallbackSid = listRes.sessions[0]?.session_id || '';
    const sid = activeSessionId || fallbackSid;
    if (!sid) {
      setSessionDetail(null);
      return;
    }
    try {
      if (sid !== activeSessionId) {
        onSelectSessionId(sid);
      }
      const detail = await kairosApi.getAssistantSession(sid);
      setSessionDetail(detail);
    } catch {
      if (fallbackSid && fallbackSid !== sid) {
        onSelectSessionId(fallbackSid);
        const detail = await kairosApi.getAssistantSession(fallbackSid).catch(() => null);
        setSessionDetail(detail);
      } else {
        onSelectSessionId('');
        setSessionDetail(null);
      }
    }
  };

  useEffect(() => {
    if (!open) return;
    loadSessionsAndActive().catch(() => {});
  }, [open, activeSessionId, refreshTick]);

  useEffect(() => {
    if (open) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [sessionDetail?.turns.length, pendingPrompt, errorMsg, open]);

  useEffect(() => {
    setRenaming(false);
  }, [activeSessionId]);

  if (!open) return null;

  const handleNewSession = async () => {
    try {
      const created = await kairosApi.createAssistantSession({
        persona,
        tone_mode: toneMode,
      });
      onSelectSessionId(created.session_id);
      setSessionDetail(created);
      setErrorMsg(null);
      onVaultMutated();
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Unable to reach KAIROS Core API (:8420).'
      );
    }
  };

  const sendMessage = async (rawPrompt: string) => {
    const clean = rawPrompt.trim();
    if (!clean || sending) return;
    setSending(true);
    setPendingPrompt(clean);
    setErrorMsg(null);
    setLastFailedPrompt('');
    setInput('');
    try {
      const effectiveMode: BrainMode = isPrivateContext ? 'gemma-4' : brainMode;
      const res = await kairosApi.sendAssistantChat({
        prompt: clean,
        session_id: activeSessionId,
        mode: effectiveMode,
        persona,
        tone_mode: toneMode,
        active_note_path: activeNotePath,
        active_task_id: activeTaskId,
        active_browser_url: activeBrowserUrl,
        active_browser_title: activeBrowserTitle,
        project_scope: projectScope || 'KAIROS_2_0',
        department_scope: departmentScope || 'Software_Development',
        current_tab: currentTab,
        current_view: currentView,
      });
      if (res.session) {
        setSessionDetail(res.session);
        if (res.session.session_id !== activeSessionId) {
          onSelectSessionId(res.session.session_id);
        }
        if (res.session.persona && res.session.persona !== persona) {
          onChangePersona(res.session.persona);
        }
        if (res.session.tone_mode && res.session.tone_mode !== toneMode) {
          onChangeToneMode(res.session.tone_mode);
        }
      } else {
        // Fallback optimistic append if session persistence was skipped
        const nowIso = new Date().toISOString();
        setSessionDetail((prev) => ({
          session_id: prev?.session_id || activeSessionId || 'local',
          title: prev?.title || clean.slice(0, 48),
          persona,
          tone_mode: toneMode,
          updated_at: nowIso,
          rel_path: prev?.rel_path || '',
          turns: [
            ...(prev?.turns || []),
            { role: 'user', content: clean, timestamp: nowIso },
            {
              role: 'assistant',
              content: res.reply,
              timestamp: nowIso,
              agent: res.agent,
              persona,
              tone_mode: toneMode,
              privacy_locked: res.privacy_locked,
              actions: res.actions,
            },
          ],
        }));
      }
      if (res.ui_commands && res.ui_commands.length > 0) {
        onExecuteUiCommands?.(res.ui_commands, res.spoken_reply || res.reply, res.agent);
      }
      onSpeakReply(res.spoken_reply || res.reply, res.privacy_locked);
      onVaultMutated();
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : 'Failed to connect to KAIROS Core (:8420). Verify backend is online.'
      );
      setLastFailedPrompt(clean);
      setInput(clean);
    } finally {
      setPendingPrompt(null);
      setSending(false);
    }
  };

  const handleRenameActiveSession = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sessionDetail?.session_id || !renameDraft.trim()) return;
    try {
      const updated = await kairosApi.renameAssistantSession(
        sessionDetail.session_id,
        renameDraft.trim()
      );
      setSessionDetail(updated);
      setRenaming(false);
      onVaultMutated();
      loadSessionsAndActive().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Session Rename Failed',
        err instanceof Error ? err.message : 'Unable to rename session'
      );
    }
  };

  const handleArchiveActiveSession = async () => {
    if (!sessionDetail?.session_id) return;
    try {
      const res = await kairosApi.deleteAssistantSession(sessionDetail.session_id, false);
      onNotify?.(
        'info',
        `Archived ${res.session_id}`,
        `Moved transcript to ${res.archived_rel_path}`
      );
      setSessionDetail(null);
      onSelectSessionId('');
      onVaultMutated();
      loadSessionsAndActive().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Session Archive Failed',
        err instanceof Error ? err.message : 'Unable to archive session'
      );
    }
  };

  const handleRetainTurnInHermes = async (
    turnKey: string,
    content: string,
    isPriv?: boolean
  ) => {
    if (retainedTurns[turnKey]) return;
    const prefix = isPriv ? '[#private] ' : '';
    const compact = content.replace(/\s+/g, ' ').trim().slice(0, 340);
    if (!compact) return;
    try {
      await kairosApi.retainHermesMemory({
        fact: `${prefix}${compact}`,
        target: 'memory',
        is_private: Boolean(isPriv),
      });
      setRetainedTurns((prev) => ({ ...prev, [turnKey]: true }));
      onVaultMutated();
    } catch (err) {
      onNotify?.(
        'error',
        'Hermes Retain Failed',
        err instanceof Error ? err.message : 'Unable to retain turn in Hermes memory'
      );
    }
  };

  const turns = sessionDetail?.turns || [];
  const browserHost = (() => {
    if (!activeBrowserUrl) return '';
    try {
      return new URL(activeBrowserUrl).hostname.replace(/^www\./, '');
    } catch {
      return activeBrowserUrl.slice(0, 26);
    }
  })();

  const clampedWidth = Math.max(300, Math.min(640, Math.round(widthPx || 390)));

  return (
    <aside
      style={{ width: `${clampedWidth}px` }}
      className="relative shrink-0 border-l border-kairos-border bg-[#0B1220] flex flex-col min-h-0"
    >
      {onResizeMouseDown && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize KAIROS Chat Panel"
          title="Drag to resize KAIROS Chat Panel"
          onMouseDown={onResizeMouseDown}
          className="absolute left-0 top-0 bottom-0 z-20 w-1.5 -translate-x-1/2 cursor-col-resize select-none hover:bg-emerald-500/45 active:bg-emerald-400/70 transition-colors"
        />
      )}
      {/* Drawer Header */}
      <div className="flex items-center justify-between border-b border-kairos-border bg-kairos-panel px-3 py-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <BotMessageSquare className="h-4 w-4 text-emerald-400 shrink-0" />
          <div className="truncate">
            <div className="text-xs font-bold text-white flex items-center gap-1.5">
              <span>KAIROS Assistant</span>
              {isPrivateContext && (
                <span className="inline-flex items-center gap-0.5 rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] text-amber-300">
                  <Lock className="h-2.5 w-2.5" /> Local
                </span>
              )}
            </div>
            <div className="text-[10px] text-slate-400 truncate">
              Scope:{' '}
              {(projectScope || 'KAIROS_2_0')
                .replace(/_(\d+)_(\d+)(?=_|$)/g, ' $1.$2')
                .replace(/_/g, ' ')}{' '}
              • {(departmentScope || 'Software_Development').replace(/_/g, ' ')}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={() => {
              if (ttsEnabled) stopKairosSpeech();
              onToggleTtsEnabled();
            }}
            title={
              ttsEnabled
                ? 'KAIROS Spoken Voice Replies ON (Click to Mute)'
                : 'KAIROS Spoken Voice Replies Muted (Click to Enable)'
            }
            className={`rounded p-1 transition ${
              ttsEnabled
                ? 'bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25'
                : 'text-slate-400 hover:bg-kairos-card hover:text-white'
            }`}
          >
            {ttsEnabled ? (
              <Volume2 className="h-3.5 w-3.5" />
            ) : (
              <VolumeOff className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            type="button"
            onClick={handleNewSession}
            title="Start New Vault-Saved Chat Session"
            className="rounded p-1 text-slate-300 hover:bg-kairos-card hover:text-emerald-300"
          >
            <MessageSquarePlus className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onExpandFullWorkspace}
            title="Open Full KAIROS Assistant Workspace"
            className="rounded p-1 text-slate-300 hover:bg-kairos-card hover:text-cyan-300"
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onClose}
            title="Collapse Docked Chat Panel"
            className="rounded p-1 text-slate-400 hover:bg-kairos-card hover:text-white"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Live Platform Context Pill Strip */}
      {(activeTaskId || activeNotePath || browserHost) && (
        <div className="flex flex-wrap items-center gap-1 border-b border-kairos-border bg-[#080E1A] px-3 py-1.5 text-[10px]">
          <span className="text-slate-500 font-semibold uppercase tracking-wider mr-0.5">
            Live Context:
          </span>
          {activeTaskId && (
            <span
              title={`Deictic commands like "Mark this task Done" target ${activeTaskId}`}
              className="inline-flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-emerald-300 font-mono"
            >
              Task {activeTaskId}
            </span>
          )}
          {activeNotePath && (
            <span
              title={activeNotePath}
              className="inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-1.5 py-0.5 text-cyan-300 truncate max-w-[140px]"
            >
              {activeNotePath.split('/').pop()}
            </span>
          )}
          {browserHost && (
            <span
              title={activeBrowserTitle ? `${activeBrowserTitle} (${activeBrowserUrl})` : activeBrowserUrl}
              className="inline-flex items-center gap-1 rounded border border-purple-500/40 bg-purple-500/10 px-1.5 py-0.5 text-purple-300 truncate max-w-[130px]"
            >
              {browserHost}
            </span>
          )}
        </div>
      )}

      {/* Persona Selector + CODE_RED Toggle + Session Switcher */}
      <div className="border-b border-kairos-border bg-kairos-panel/60 px-3 py-2 space-y-2">
        <div className="flex items-center justify-between gap-1.5">
          <div className="flex flex-wrap gap-1">
            {PERSONA_OPTIONS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => onChangePersona(p.id)}
                title={p.label}
                className={`rounded px-2 py-0.5 text-[10px] font-medium transition ${
                  persona === p.id
                    ? 'bg-emerald-500/25 text-emerald-300 border border-emerald-500/40'
                    : 'bg-kairos-bg text-slate-400 hover:text-slate-200 border border-kairos-border'
                }`}
              >
                {p.short}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={() => onChangeToneMode(toneMode === 'CODE_RED' ? 'DEFAULT' : 'CODE_RED')}
            title="Toggle Tactical CODE RED Mode (Zero-Fluff Action Bullets)"
            className={`flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-bold border transition shrink-0 ${
              toneMode === 'CODE_RED'
                ? 'bg-rose-500/25 border-rose-500/50 text-rose-200 animate-pulse'
                : 'bg-kairos-bg border-kairos-border text-slate-400 hover:text-rose-300'
            }`}
          >
            <Flame className="h-3 w-3" />
            {toneMode === 'CODE_RED' ? 'CODE RED' : 'Normal'}
          </button>
        </div>

        <div className="flex items-center justify-between gap-1.5 text-[11px]">
          {renaming && sessionDetail ? (
            <form onSubmit={handleRenameActiveSession} className="flex-1 flex items-center gap-1">
              <input
                type="text"
                autoFocus
                value={renameDraft}
                onChange={(e) => setRenameDraft(e.target.value)}
                className="flex-1 rounded border border-emerald-500/50 bg-kairos-bg px-2 py-1 text-[11px] text-white focus:outline-none"
              />
              <button
                type="submit"
                className="rounded bg-emerald-500 px-2 py-0.5 text-[10px] font-bold text-slate-950"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => setRenaming(false)}
                className="text-[10px] text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </form>
          ) : (
            <select
              value={sessionDetail?.session_id || activeSessionId}
              onChange={(e) => onSelectSessionId(e.target.value)}
              className="flex-1 rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[11px] text-slate-200 truncate"
            >
              {sessions.length === 0 && <option value="">New KAIROS Session</option>}
              {sessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>
                  {s.title} ({s.turn_count})
                </option>
              ))}
            </select>
          )}

          {sessionDetail && !renaming && (
            <>
              <button
                type="button"
                onClick={() => {
                  setRenameDraft(sessionDetail.title);
                  setRenaming(true);
                }}
                title="Rename Session"
                className="rounded p-1 text-slate-400 hover:bg-kairos-card hover:text-emerald-300 shrink-0"
              >
                <Edit3 className="h-3 w-3" />
              </button>
              <button
                type="button"
                onClick={handleArchiveActiveSession}
                title="Archive Session to 05_Archives/Sessions/"
                className="rounded p-1 text-slate-400 hover:bg-amber-500/15 hover:text-amber-300 shrink-0"
              >
                <Archive className="h-3 w-3" />
              </button>
            </>
          )}

          {sessionDetail?.rel_path && !renaming && (
            <button
              type="button"
              onClick={() => onOpenNoteInSecondBrain(sessionDetail.rel_path)}
              title="Inspect Session Markdown Note in Second Brain"
              className="flex items-center gap-1 text-[10px] text-cyan-400 hover:underline shrink-0"
            >
              <ExternalLink className="h-3 w-3" /> `.md`
            </button>
          )}
        </div>
      </div>

      {/* Conversation Stream */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 select-text">
        {turns.length === 0 && !pendingPrompt ? (
          <div className="space-y-3 pt-2">
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-slate-200 space-y-1.5">
              <div className="font-bold text-emerald-300 flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5" /> KAIROS Virtual Assistant Online
              </div>
              <p className="text-[11px] text-slate-300 leading-relaxed">
                Connected to **Canopy Vault**, **Hermes Memory & Skills**, **Live Web & Sports
                Scores**, all **Project Categories**, and **Spoken Voice Output**.
              </p>
            </div>

            <div className="space-y-1.5">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                Try Asking KAIROS
              </div>
              {QUICK_CHIPS.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  onClick={() => sendMessage(chip)}
                  className="w-full text-left rounded-lg border border-kairos-border bg-kairos-panel px-2.5 py-2 text-[11px] text-slate-300 hover:border-emerald-500/40 hover:text-white transition"
                >
                  &ldquo;{chip}&rdquo;
                </button>
              ))}
            </div>
          </div>
        ) : (
          turns.map((turn, idx) => {
            const isUser = turn.role === 'user';
            return (
              <div
                key={`${turn.timestamp}-${idx}`}
                className={`flex flex-col ${isUser ? 'items-end' : 'items-start'}`}
              >
                <div
                  className={`max-w-[92%] rounded-xl px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap ${
                    isUser
                      ? 'bg-emerald-500/20 border border-emerald-500/35 text-emerald-50'
                      : 'bg-kairos-panel border border-kairos-border text-slate-200'
                  }`}
                >
                  {!isUser && (
                    <div className="flex flex-wrap items-center justify-between gap-1.5 mb-1 text-[10px]">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-bold text-emerald-300">
                          {turn.agent || 'KAIROS'}
                        </span>
                        {turn.persona && (
                          <span className="rounded bg-kairos-card px-1.5 py-0.2 text-slate-400">
                            {turn.persona}
                          </span>
                        )}
                        {turn.tone_mode === 'CODE_RED' && (
                          <span className="rounded bg-rose-500/20 px-1.5 py-0.2 text-rose-300 font-semibold">
                            CODE RED
                          </span>
                        )}
                        {turn.privacy_locked && (
                          <span className="rounded bg-amber-500/20 px-1.5 py-0.2 text-amber-300">
                            🔒 Local
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          disabled={Boolean(retainedTurns[`${turn.timestamp}-${idx}`])}
                          onClick={() =>
                            handleRetainTurnInHermes(
                              `${turn.timestamp}-${idx}`,
                              turn.content,
                              turn.privacy_locked
                            )
                          }
                          title="Retain this reply in Hermes Persistent Memory (MEMORY.md)"
                          className="rounded border border-purple-500/35 bg-purple-500/10 px-1.5 py-0.2 text-[9.5px] font-semibold text-purple-200 hover:bg-purple-500/20 disabled:opacity-70"
                        >
                          {retainedTurns[`${turn.timestamp}-${idx}`] ? '✓' : '🪽'}
                        </button>
                        <button
                          type="button"
                          onClick={() => onSpeakReply(turn.content, turn.privacy_locked)}
                          title="Speak this reply aloud"
                          className="rounded p-0.5 text-slate-400 hover:text-emerald-300"
                        >
                          <Volume2 className="h-3 w-3" />
                        </button>
                      </div>
                    </div>
                  )}

                  {turn.actions && turn.actions.length > 0 && (
                    <div className="mb-1.5 space-y-1">
                      {turn.actions.map((act, aIdx) => (
                        <div
                          key={aIdx}
                          className="flex items-center gap-1 rounded bg-cyan-500/15 border border-cyan-500/30 px-2 py-0.5 text-[10px] text-cyan-200"
                        >
                          <Zap className="h-2.5 w-2.5 shrink-0 text-cyan-300" />
                          <span>{act}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  <div>{turn.content}</div>
                </div>
              </div>
            );
          })
        )}

        {/* Optimistic User Turn while KAIROS is processing */}
        {pendingPrompt && (
          <div className="flex flex-col items-end">
            <div className="max-w-[92%] rounded-xl px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap bg-emerald-500/20 border border-emerald-500/35 text-emerald-50">
              {pendingPrompt}
            </div>
          </div>
        )}

        {sending && (
          <div className="rounded-xl border border-emerald-500/30 bg-kairos-panel px-3 py-2 text-xs text-emerald-300 animate-pulse w-fit">
            KAIROS is checking live feeds & Canopy Vault...
          </div>
        )}

        {errorMsg && (
          <div className="rounded-xl border border-rose-500/40 bg-rose-500/15 p-2.5 text-xs text-rose-200 space-y-1.5">
            <div className="flex items-center gap-1.5 font-bold text-rose-300">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              <span>Connection / Response Error</span>
            </div>
            <div className="text-[11px] text-rose-100 break-words">{errorMsg}</div>
            {lastFailedPrompt && (
              <button
                type="button"
                onClick={() => sendMessage(lastFailedPrompt)}
                className="inline-flex items-center gap-1 rounded bg-rose-500/25 border border-rose-400/40 px-2 py-1 text-[10.5px] font-semibold text-white hover:bg-rose-500/35"
              >
                <RefreshCw className="h-3 w-3" /> Retry Question
              </button>
            )}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Composer */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          sendMessage(input);
        }}
        className="border-t border-kairos-border bg-kairos-panel p-2.5 space-y-1.5"
      >
        <div className="flex items-end gap-1.5">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage(input);
              }
            }}
            rows={2}
            placeholder='Ask anything (live scores, Vault, code), "Hermes, remember...", or create tasks...'
            className="flex-1 resize-none rounded-lg border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-white placeholder-slate-500 focus:border-emerald-500/60 focus:outline-none"
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="rounded-lg bg-emerald-500 p-2 text-slate-950 hover:bg-emerald-400 disabled:opacity-40 transition"
          >
            <Send className="h-3.5 w-3.5" />
          </button>
        </div>
      </form>
    </aside>
  );
};

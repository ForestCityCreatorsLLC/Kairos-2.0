import React, { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  Archive,
  ArchiveRestore,
  BotMessageSquare,
  Brain,
  CloudSun,
  Edit3,
  ExternalLink,
  Flame,
  History,
  Lock,
  MessageSquarePlus,
  RefreshCw,
  Send,
  Sparkles,
  Volume2,
  VolumeOff,
  Zap,
} from 'lucide-react';
import {
  AssistantSessionDetail,
  AssistantSessionSummary,
  BrainMode,
  PersonaRole,
  ProjectTreeItem,
  STANDARD_DEPARTMENTS,
  ToneMode,
  UIActionCommand,
  kairosApi,
} from '../../api/client.ts';
import { formatProjectDisplayName } from '../../components/LeftSidebar.tsx';
import { ToastKind } from '../../components/ToastCenter.tsx';
import { stopKairosSpeech } from '../../utils/speech.ts';

const PERSONA_CARDS: {
  id: PersonaRole;
  label: string;
  desc: string;
}[] = [
  {
    id: 'companion',
    label: 'KAIROS Companion',
    desc: 'Daily executive partner, Vault memory & full life/business co-pilot.',
  },
  {
    id: 'pm',
    label: 'Project Director',
    desc: 'Cross-department sprint tracking across Software, Marketing, Docs, Website & Merch.',
  },
  {
    id: 'dev',
    label: 'Systems Architect',
    desc: 'Python, FastAPI, React/Electron, SQLite WAL & MCP engineering.',
  },
  {
    id: 'creative',
    label: 'Brand & Merch Director',
    desc: 'Marketing campaigns, website copy, social hooks & Printful merch.',
  },
  {
    id: 'owner',
    label: 'Executive Strategist',
    desc: 'Co-CEO prioritization, bottleneck removal & ROI focus.',
  },
];

interface AssistantWorkspaceProps {
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
  projects?: ProjectTreeItem[];
  hermesSkillCount?: number;
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

export const AssistantWorkspace: React.FC<AssistantWorkspaceProps> = ({
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
  projects = [],
  hermesSkillCount = 0,
  currentTab = 'assistant',
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
  const [archivedSessions, setArchivedSessions] = useState<AssistantSessionSummary[]>([]);
  const [sessionListTab, setSessionListTab] = useState<'active' | 'archived'>('active');
  const [sessionDetail, setSessionDetail] = useState<AssistantSessionDetail | null>(null);
  const [renamingSession, setRenamingSession] = useState(false);
  const [renameDraft, setRenameDraft] = useState('');
  const [prompt, setPrompt] = useState('');
  const [memoryDraft, setMemoryDraft] = useState('');
  const [hermesDraft, setHermesDraft] = useState('');
  const [retainedTurns, setRetainedTurns] = useState<Record<string, boolean>>({});
  const [sending, setSending] = useState(false);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [lastFailedPrompt, setLastFailedPrompt] = useState('');
  const endRef = useRef<HTMLDivElement | null>(null);

  const loadWorkspace = async () => {
    const [res, archRes] = await Promise.all([
      kairosApi.listAssistantSessions(),
      kairosApi.listArchivedAssistantSessions().catch(() => ({ sessions: [] })),
    ]);
    setSessions(res.sessions);
    setArchivedSessions(archRes.sessions);
    const fallbackSid = res.sessions[0]?.session_id || '';
    const sid = activeSessionId || fallbackSid;
    if (!sid) {
      setSessionDetail(null);
      return;
    }
    try {
      if (sid !== activeSessionId) {
        onSelectSessionId(sid);
      }
      const d = await kairosApi.getAssistantSession(sid);
      setSessionDetail(d);
    } catch {
      if (fallbackSid && fallbackSid !== sid) {
        onSelectSessionId(fallbackSid);
        const d = await kairosApi.getAssistantSession(fallbackSid).catch(() => null);
        setSessionDetail(d);
      } else {
        onSelectSessionId('');
        setSessionDetail(null);
      }
    }
  };

  useEffect(() => {
    setRenamingSession(false);
  }, [activeSessionId]);

  useEffect(() => {
    loadWorkspace().catch(() => {});
  }, [activeSessionId, refreshTick]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [sessionDetail?.turns.length, pendingPrompt, errorMsg]);

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
      setErrorMsg(err instanceof Error ? err.message : 'Unable to reach KAIROS Core (:8420).');
    }
  };

  const dispatchMessage = async (text: string) => {
    const clean = text.trim();
    if (!clean || sending) return;
    setSending(true);
    setPendingPrompt(clean);
    setErrorMsg(null);
    setLastFailedPrompt('');
    setPrompt('');
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
        const nowIso = new Date().toISOString();
        setSessionDetail((prev) => ({
          session_id: prev?.session_id || activeSessionId || 'SES-LOCAL',
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
          : 'Failed to reach KAIROS Core (:8420). Please verify backend is running.'
      );
      setLastFailedPrompt(clean);
      setPrompt(clean);
    } finally {
      setPendingPrompt(null);
      setSending(false);
    }
  };

  const handleSaveMemory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!memoryDraft.trim()) return;
    const fact = memoryDraft.trim();
    setMemoryDraft('');
    await dispatchMessage(`Remember that ${fact}`);
  };

  const handleSaveHermes = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hermesDraft.trim()) return;
    const fact = hermesDraft.trim();
    setHermesDraft('');
    await dispatchMessage(`Hermes, remember ${fact}`);
  };

  const handleRenameSession = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sessionDetail?.session_id || !renameDraft.trim()) return;
    try {
      const updated = await kairosApi.renameAssistantSession(
        sessionDetail.session_id,
        renameDraft.trim()
      );
      setSessionDetail(updated);
      setRenamingSession(false);
      onVaultMutated();
      loadWorkspace().catch(() => {});
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
      loadWorkspace().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Session Archive Failed',
        err instanceof Error ? err.message : 'Unable to archive session'
      );
    }
  };

  const handleRestoreArchivedSession = async (sid: string) => {
    if (!sid) return;
    try {
      const restored = await kairosApi.restoreAssistantSession(sid);
      setSessionListTab('active');
      setSessionDetail(restored);
      onSelectSessionId(restored.session_id);
      onNotify?.(
        'success',
        `Restored ${restored.session_id}`,
        `Returned "${restored.title}" to 01_Business/KAIROS_Sessions/`
      );
      onVaultMutated();
      loadWorkspace().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Session Restore Failed',
        err instanceof Error ? err.message : 'Unable to restore archived session'
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
    const compact = content.replace(/\s+/g, ' ').trim().slice(0, 360);
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
        err instanceof Error ? err.message : 'Unable to retain turn in Hermes'
      );
    }
  };

  const turns = sessionDetail?.turns || [];

  return (
    <div className="flex-1 flex min-w-0 bg-kairos-bg overflow-hidden">
      {/* Left Column: Vault Session History (`01_Business/KAIROS_Sessions/`) */}
      <div className="w-64 shrink-0 border-r border-kairos-border bg-kairos-panel/80 p-3 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-bold text-white">
            <History className="h-3.5 w-3.5 text-emerald-400" />
            <span>Vault Chat Sessions</span>
          </div>
          <button
            type="button"
            onClick={handleNewSession}
            className="flex items-center gap-1 rounded-md bg-emerald-500 px-2 py-1 text-[11px] font-semibold text-slate-950 hover:bg-emerald-400"
          >
            <MessageSquarePlus className="h-3 w-3" /> New
          </button>
        </div>

        <div className="grid grid-cols-2 gap-1 rounded-lg border border-kairos-border bg-kairos-bg p-0.5 text-[11px]">
          <button
            type="button"
            onClick={() => setSessionListTab('active')}
            className={`rounded-md py-1 font-semibold transition ${
              sessionListTab === 'active'
                ? 'bg-emerald-500/20 text-emerald-300'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Active ({sessions.length})
          </button>
          <button
            type="button"
            onClick={() => setSessionListTab('archived')}
            className={`rounded-md py-1 font-semibold transition ${
              sessionListTab === 'archived'
                ? 'bg-amber-500/20 text-amber-300'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Archived ({archivedSessions.length})
          </button>
        </div>

        <div className="text-[10px] text-slate-500">
          {sessionListTab === 'active'
            ? 'Saved as Markdown in `01_Business/KAIROS_Sessions/`'
            : 'Soft-archived in `05_Archives/Sessions/`'}
        </div>

        <div className="flex-1 overflow-y-auto space-y-1.5">
          {sessionListTab === 'active' ? (
            sessions.length === 0 ? (
              <div className="rounded-lg border border-kairos-border bg-kairos-bg p-3 text-[11px] text-slate-400">
                Send your first message to start a Vault-saved KAIROS conversation.
              </div>
            ) : (
              sessions.map((s) => {
                const selected = (sessionDetail?.session_id || activeSessionId) === s.session_id;
                return (
                  <button
                    key={s.session_id}
                    type="button"
                    onClick={() => onSelectSessionId(s.session_id)}
                    className={`w-full text-left rounded-lg border p-2.5 transition space-y-1 ${
                      selected
                        ? 'border-emerald-500/40 bg-emerald-500/15'
                        : 'border-kairos-border bg-kairos-card/60 hover:border-slate-600'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-xs font-semibold text-white truncate">{s.title}</span>
                      <span className="rounded bg-kairos-bg px-1.5 py-0.2 text-[10px] text-slate-400 shrink-0">
                        {s.turn_count}
                      </span>
                    </div>
                    <div className="text-[10px] text-slate-400 line-clamp-2">
                      {s.last_preview || 'Empty session'}
                    </div>
                  </button>
                );
              })
            )
          ) : archivedSessions.length === 0 ? (
            <div className="rounded-lg border border-kairos-border bg-kairos-bg p-3 text-[11px] text-slate-400">
              No archived sessions in `05_Archives/Sessions/`.
            </div>
          ) : (
            archivedSessions.map((s) => (
              <div
                key={s.session_id}
                className="rounded-lg border border-amber-500/30 bg-kairos-card/60 p-2.5 space-y-1.5"
              >
                <div className="flex items-center justify-between gap-1">
                  <span className="text-xs font-semibold text-amber-100 truncate">{s.title}</span>
                  <span className="rounded bg-kairos-bg px-1.5 py-0.2 text-[10px] text-slate-400 shrink-0">
                    {s.turn_count}
                  </span>
                </div>
                <div className="text-[10px] text-slate-400 line-clamp-2">
                  {s.last_preview || s.session_id}
                </div>
                <button
                  type="button"
                  onClick={() => handleRestoreArchivedSession(s.session_id)}
                  className="w-full flex items-center justify-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/15 py-1 text-[10.5px] font-semibold text-emerald-200 hover:bg-emerald-500/25 transition"
                >
                  <ArchiveRestore className="h-3 w-3" /> Restore Session
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Center Column: Full Conversational KAIROS Virtual Assistant */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-kairos-border bg-kairos-panel/70 px-5 py-3">
          <div className="flex items-center gap-2.5">
            <BotMessageSquare className="h-5 w-5 text-emerald-400" />
            <div>
              <div className="text-sm font-bold text-white flex items-center gap-2">
                {renamingSession && sessionDetail ? (
                  <form onSubmit={handleRenameSession} className="flex items-center gap-1.5">
                    <input
                      type="text"
                      autoFocus
                      value={renameDraft}
                      onChange={(e) => setRenameDraft(e.target.value)}
                      className="rounded border border-emerald-500/50 bg-kairos-bg px-2 py-0.5 text-xs text-white focus:outline-none"
                    />
                    <button
                      type="submit"
                      className="rounded bg-emerald-500 px-2 py-0.5 text-[11px] font-bold text-slate-950"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => setRenamingSession(false)}
                      className="text-[11px] text-slate-400 hover:text-white"
                    >
                      Cancel
                    </button>
                  </form>
                ) : (
                  <>
                    <span>{sessionDetail?.title || 'KAIROS 2.0 Virtual Assistant'}</span>
                    {sessionDetail && (
                      <>
                        <button
                          type="button"
                          onClick={() => {
                            setRenameDraft(sessionDetail.title);
                            setRenamingSession(true);
                          }}
                          title="Rename Session"
                          className="rounded p-1 text-slate-400 hover:bg-kairos-card hover:text-emerald-300"
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={handleArchiveActiveSession}
                          title="Archive Session to 05_Archives/Sessions/"
                          className="rounded p-1 text-slate-400 hover:bg-amber-500/15 hover:text-amber-300"
                        >
                          <Archive className="h-3.5 w-3.5" />
                        </button>
                      </>
                    )}
                  </>
                )}
                {toneMode === 'CODE_RED' && (
                  <span className="rounded bg-rose-500/20 border border-rose-500/40 px-2 py-0.5 text-[10px] font-bold text-rose-300">
                    🚨 CODE RED MODE
                  </span>
                )}
                {isPrivateContext && (
                  <span className="inline-flex items-center gap-1 rounded bg-amber-500/20 px-2 py-0.5 text-[10px] text-amber-300">
                    <Lock className="h-3 w-3" /> Local Gemma 4 Privacy Lock
                  </span>
                )}
              </div>
              <div className="text-[11px] text-slate-400">
                Multi-turn conversational assistant connected to Canopy Vault, Hermes Knowledge,
                Live Sports/Web, Projects, CrewAI, Weather & Printful
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                if (ttsEnabled) stopKairosSpeech();
                onToggleTtsEnabled();
              }}
              className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${
                ttsEnabled
                  ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                  : 'border-kairos-border bg-kairos-card text-slate-400 hover:text-white'
              }`}
            >
              {ttsEnabled ? (
                <>
                  <Volume2 className="h-3.5 w-3.5" /> Voice Replies ON
                </>
              ) : (
                <>
                  <VolumeOff className="h-3.5 w-3.5" /> Voice Muted
                </>
              )}
            </button>

            {sessionDetail?.rel_path && (
              <button
                type="button"
                onClick={() => onOpenNoteInSecondBrain(sessionDetail.rel_path)}
                className="flex items-center gap-1.5 rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs text-cyan-300 hover:bg-cyan-500/20"
              >
                <ExternalLink className="h-3.5 w-3.5" /> Open Transcript `.md`
              </button>
            )}
          </div>
        </div>

        {/* Live Deictic Platform Context Strip (Grounded Scope, Task, Note & Browser Page) */}
        {(projectScope || activeTaskId || activeNotePath || activeBrowserUrl) && (
          <div className="flex flex-wrap items-center gap-1.5 border-b border-kairos-border bg-kairos-bg/80 px-5 py-1.5 text-[11px]">
            <span className="font-semibold text-slate-500 uppercase tracking-wider text-[10px]">
              Grounded Context:
            </span>
            {projectScope && (
              <span className="inline-flex items-center gap-1 rounded border border-kairos-border bg-kairos-panel px-2 py-0.5 text-slate-300 font-mono">
                📂 {formatProjectDisplayName(projectScope)}
                {departmentScope ? ` / ${departmentScope.replace(/_/g, ' ')}` : ''}
              </span>
            )}
            {activeTaskId && (
              <button
                type="button"
                onClick={() =>
                  onExecuteUiCommands?.(
                    [
                      { type: 'navigate_tab', tab: 'projects' },
                      { type: 'open_task_drawer', task_id: activeTaskId },
                    ],
                    `Inspecting ${activeTaskId} in Projects Drawer`,
                    'KAIROS-Assistant'
                  )
                }
                title={`Jump to ${activeTaskId} in Projects Task Drawer`}
                className="inline-flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 font-mono text-emerald-300 hover:bg-emerald-500/20"
              >
                🎯 Task {activeTaskId}
              </button>
            )}
            {activeNotePath && (
              <button
                type="button"
                onClick={() => onOpenNoteInSecondBrain(activeNotePath)}
                title={`Open ${activeNotePath} in Second Brain`}
                className="inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 font-mono text-cyan-300 hover:bg-cyan-500/20 max-w-[220px] truncate"
              >
                📝 {activeNotePath.split('/').pop()}
              </button>
            )}
            {activeBrowserUrl && (
              <button
                type="button"
                onClick={() =>
                  onExecuteUiCommands?.(
                    [{ type: 'navigate_tab', tab: 'browser' }],
                    'Switched to Embedded Browser',
                    'KAIROS-Assistant'
                  )
                }
                title={
                  activeBrowserTitle
                    ? `${activeBrowserTitle} (${activeBrowserUrl})`
                    : activeBrowserUrl
                }
                className="inline-flex items-center gap-1 rounded border border-purple-500/40 bg-purple-500/10 px-2 py-0.5 font-mono text-purple-300 hover:bg-purple-500/20 max-w-[220px] truncate"
              >
                🌐 {activeBrowserTitle || activeBrowserUrl}
              </button>
            )}
          </div>
        )}

        {/* Message Canvas */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {turns.length === 0 && !pendingPrompt ? (
            <div className="max-w-2xl mx-auto pt-8 space-y-4">
              <div className="rounded-2xl border border-emerald-500/30 bg-kairos-panel p-5 space-y-2">
                <div className="flex items-center gap-2 text-sm font-bold text-emerald-300">
                  <Sparkles className="h-4 w-4" /> Welcome back, Jaime — KAIROS & Hermes are ready.
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  Ask me live sports scores, news, weather, or Second Brain questions, retain
                  durable knowledge in Hermes (`04_Resources/Hermes/`), or create/update tasks
                  across any project category.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                {[
                  'Give me my daily briefing',
                  "What's the score of the Browns game?",
                  'Create high-priority task in Website to design the KAIROS 2.0 showcase landing page',
                  'Hermes, remember that all project wikis live under each project Docs folder',
                ].map((sample) => (
                  <button
                    key={sample}
                    type="button"
                    onClick={() => dispatchMessage(sample)}
                    className="text-left rounded-xl border border-kairos-border bg-kairos-panel p-3 text-xs text-slate-200 hover:border-emerald-500/50 transition"
                  >
                    &ldquo;{sample}&rdquo;
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
                  className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-3xl rounded-2xl px-4 py-3 text-xs leading-relaxed whitespace-pre-wrap ${
                      isUser
                        ? 'bg-emerald-500/20 border border-emerald-500/35 text-emerald-50'
                        : 'bg-kairos-panel border border-kairos-border text-slate-100'
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5 text-[10px] text-slate-400">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-bold text-emerald-300">
                          {isUser ? 'Jaime' : `KAIROS (${turn.agent || 'AI'})`}
                        </span>
                        <span>{turn.timestamp.replace('T', ' ')}</span>
                        {!isUser && turn.persona && (
                          <span className="rounded bg-kairos-card px-1.5 py-0.5 text-cyan-300">
                            Role: {turn.persona}
                          </span>
                        )}
                        {turn.privacy_locked && (
                          <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-amber-300">
                            🔒 Local Privacy Locked
                          </span>
                        )}
                      </div>
                      {!isUser && (
                        <div className="flex items-center gap-1.5">
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
                            className="rounded border border-purple-500/35 bg-purple-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-purple-200 hover:bg-purple-500/20 disabled:opacity-70"
                          >
                            {retainedTurns[`${turn.timestamp}-${idx}`] ? '✓ Retained' : '🪽 Retain'}
                          </button>
                          <button
                            type="button"
                            onClick={() => onSpeakReply(turn.content, turn.privacy_locked)}
                            title="Speak this reply aloud"
                            className="rounded p-1 text-slate-400 hover:text-emerald-300"
                          >
                            <Volume2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      )}
                    </div>

                    {turn.actions && turn.actions.length > 0 && (
                      <div className="mb-2 space-y-1">
                        {turn.actions.map((act, i) => (
                          <div
                            key={i}
                            className="flex items-center gap-1.5 rounded-lg bg-cyan-500/15 border border-cyan-500/30 px-2.5 py-1 text-[11px] text-cyan-200"
                          >
                            <Zap className="h-3 w-3 text-cyan-300 shrink-0" />
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

          {pendingPrompt && (
            <div className="flex justify-end">
              <div className="max-w-3xl rounded-2xl px-4 py-3 text-xs leading-relaxed whitespace-pre-wrap bg-emerald-500/20 border border-emerald-500/35 text-emerald-50">
                {pendingPrompt}
              </div>
            </div>
          )}

          {sending && (
            <div className="rounded-xl border border-emerald-500/30 bg-kairos-panel px-4 py-2.5 text-xs text-emerald-300 animate-pulse w-fit">
              KAIROS is querying live feeds, Hermes memory & Canopy Vault...
            </div>
          )}

          {errorMsg && (
            <div className="max-w-2xl rounded-xl border border-rose-500/40 bg-rose-500/15 p-3 text-xs text-rose-200 space-y-2">
              <div className="flex items-center gap-1.5 font-bold text-rose-300">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>Assistant Request Error</span>
              </div>
              <div className="text-[11px] text-rose-100">{errorMsg}</div>
              {lastFailedPrompt && (
                <button
                  type="button"
                  onClick={() => dispatchMessage(lastFailedPrompt)}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500/25 border border-rose-400/40 px-3 py-1 text-xs font-semibold text-white hover:bg-rose-500/35"
                >
                  <RefreshCw className="h-3.5 w-3.5" /> Retry Prompt
                </button>
              )}
            </div>
          )}
          <div ref={endRef} />
        </div>

        {/* Bottom Composer */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            dispatchMessage(prompt);
          }}
          className="border-t border-kairos-border bg-kairos-panel p-4"
        >
          <div className="flex items-end gap-2.5 max-w-4xl mx-auto">
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  dispatchMessage(prompt);
                }
              }}
              rows={2}
              placeholder='Message KAIROS... (Enter to send, Shift+Enter for newline)'
              className="flex-1 resize-none rounded-xl border border-kairos-border bg-kairos-bg px-3.5 py-2.5 text-xs text-white placeholder-slate-500 focus:border-emerald-500/60 focus:outline-none"
            />
            <button
              type="submit"
              disabled={sending || !prompt.trim()}
              className="flex items-center gap-1.5 rounded-xl bg-emerald-500 px-4 py-2.5 text-xs font-bold text-slate-950 hover:bg-emerald-400 disabled:opacity-40 transition"
            >
              <Send className="h-3.5 w-3.5" /> Send
            </button>
          </div>
        </form>
      </div>

      {/* Right Column: Persona Engine, Tone Matrix, Hermes & Operator Memory */}
      <div className="w-72 shrink-0 border-l border-kairos-border bg-kairos-panel/80 p-3.5 overflow-y-auto space-y-4">
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-300">
            <Brain className="h-3.5 w-3.5" /> KAIROS Persona Role
          </div>
          <div className="space-y-1.5">
            {PERSONA_CARDS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => onChangePersona(p.id)}
                className={`w-full text-left rounded-lg border p-2 transition ${
                  persona === p.id
                    ? 'border-emerald-500/45 bg-emerald-500/15'
                    : 'border-kairos-border bg-kairos-bg hover:border-slate-600'
                }`}
              >
                <div className="text-xs font-semibold text-white">{p.label}</div>
                <div className="text-[10px] text-slate-400 leading-snug">{p.desc}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-kairos-border bg-kairos-bg p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-white flex items-center gap-1.5">
              <Flame className="h-3.5 w-3.5 text-rose-400" /> Tone Matrix
            </span>
            <button
              type="button"
              onClick={() => onChangeToneMode(toneMode === 'CODE_RED' ? 'DEFAULT' : 'CODE_RED')}
              className={`rounded px-2 py-0.5 text-[10px] font-bold border ${
                toneMode === 'CODE_RED'
                  ? 'bg-rose-500/25 border-rose-500/50 text-rose-200'
                  : 'bg-kairos-panel border-kairos-border text-emerald-300'
              }`}
            >
              {toneMode}
            </button>
          </div>
          <p className="text-[10px] text-slate-400">
            Switch to `CODE_RED` for tactical, zero-fluff execution bullets.
          </p>
        </div>

        <form
          onSubmit={handleSaveHermes}
          className="rounded-xl border border-purple-500/30 bg-purple-500/5 p-3 space-y-2"
        >
          <div className="text-xs font-bold text-purple-300">🪽 Hermes Knowledge Retention</div>
          <p className="text-[10px] text-slate-400">
            Retains curated architectural & procedural facts into `04_Resources/Hermes/MEMORY.md`.
          </p>
          <input
            type="text"
            value={hermesDraft}
            onChange={(e) => setHermesDraft(e.target.value)}
            placeholder="e.g. Always scaffold Docs wiki notes per project"
            className="w-full rounded border border-kairos-border bg-kairos-panel px-2.5 py-1.5 text-xs text-white"
          />
          <button
            type="submit"
            className="w-full rounded-lg bg-purple-500/20 border border-purple-500/40 py-1.5 text-xs font-semibold text-purple-200 hover:bg-purple-500/30"
          >
            Retain in Hermes Memory
          </button>
        </form>

        <form
          onSubmit={handleSaveMemory}
          className="rounded-xl border border-kairos-border bg-kairos-bg p-3 space-y-2"
        >
          <div className="text-xs font-bold text-cyan-300">Long-Term Operator Memory</div>
          <p className="text-[10px] text-slate-400">
            Saves personal preferences to `03_Personal/Personal_Growth/KAIROS_Operator_Memory.md`.
          </p>
          <input
            type="text"
            value={memoryDraft}
            onChange={(e) => setMemoryDraft(e.target.value)}
            placeholder="e.g. Prioritize KAIROS Website launch this week"
            className="w-full rounded border border-kairos-border bg-kairos-panel px-2.5 py-1.5 text-xs text-white"
          />
          <button
            type="submit"
            className="w-full rounded-lg bg-cyan-500/20 border border-cyan-500/40 py-1.5 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/30"
          >
            Save to Operator Memory
          </button>
        </form>

        <div className="rounded-xl border border-kairos-border bg-kairos-bg p-3 space-y-2 text-[11px]">
          <div className="font-bold text-amber-300 flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <CloudSun className="h-3.5 w-3.5" /> Active Projects & Portions
            </span>
            <span className="font-mono text-[10px] text-purple-300">
              🪽 {hermesSkillCount} skills
            </span>
          </div>
          {projects.length > 0 && (
            <div className="space-y-1 border-b border-kairos-border pb-2">
              {projects.map((proj) => {
                const stdSet = new Set<string>(STANDARD_DEPARTMENTS.map((d) => d.id));
                const customCats = proj.departments.filter((d) => !stdSet.has(d.name));
                return (
                  <div key={proj.name} className="space-y-0.5">
                    <div className="flex items-center justify-between text-slate-200 font-semibold">
                      <span>📂 {formatProjectDisplayName(proj.name)}</span>
                      <span className="font-mono text-[10px] text-emerald-300">
                        {proj.progress_pct}% ({proj.task_count})
                      </span>
                    </div>
                    {customCats.length > 0 && (
                      <div className="pl-4 text-[10px] text-cyan-300">
                        + Custom: {customCats.map((c) => c.name.replace(/_/g, ' ')).join(', ')}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          <div className="space-y-1">
            {STANDARD_DEPARTMENTS.map((d) => (
              <div key={d.id} className="text-slate-300 flex items-center gap-1.5">
                <span>{d.emoji}</span>
                <span>{d.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

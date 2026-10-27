import React, { useEffect, useState } from 'react';
import {
  BookMarked,
  Bot,
  Brain,
  CircleCheck,
  ExternalLink,
  Lock,
  Paperclip,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  ShieldAlert,
  Sparkles,
  Unlock,
  X,
} from 'lucide-react';
import {
  BrainMode,
  HermesStatusSnapshot,
  PaperclipSnapshot,
  PersonaRole,
  ProjectTreeItem,
  TaskSummary,
  ToneMode,
  UIActionCommand,
  kairosApi,
} from '../../api/client.ts';
import { ToastKind } from '../../components/ToastCenter.tsx';

interface PaperclipWorkspaceProps {
  projects: ProjectTreeItem[];
  refreshTick: number;
  activeSessionId?: string;
  persona?: PersonaRole;
  toneMode?: ToneMode;
  brainMode?: BrainMode;
  onSelectSessionId?: (sid: string) => void;
  onSpeakReply?: (text: string, forcePrivate?: boolean) => void;
  onVaultMutated: () => void;
  onOpenNoteInSecondBrain: (relPath: string) => void;
  onExecuteUiCommands: (cmds: UIActionCommand[], summary?: string, agent?: string) => void;
  onNotify?: (kind: ToastKind, title: string, detail?: string) => void;
}

export const PaperclipWorkspace: React.FC<PaperclipWorkspaceProps> = ({
  projects,
  refreshTick,
  activeSessionId = '',
  persona = 'companion',
  toneMode = 'DEFAULT',
  brainMode = 'auto',
  onSelectSessionId,
  onSpeakReply,
  onVaultMutated,
  onOpenNoteInSecondBrain,
  onExecuteUiCommands,
  onNotify,
}) => {
  const [snapshot, setSnapshot] = useState<PaperclipSnapshot | null>(null);
  const [hermes, setHermes] = useState<HermesStatusSnapshot | null>(null);
  const [auditLogs, setAuditLogs] = useState<Record<string, unknown>[]>([]);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [selectedTask, setSelectedTask] = useState('');
  const [selectedCrew, setSelectedCrew] = useState('Hermes-Agent');
  const [refUrl, setRefUrl] = useState('');
  const [dispatchMsg, setDispatchMsg] = useState('');

  // Hermes Memory & Skill Controls
  const [activeMemoryTab, setActiveMemoryTab] = useState<'MEMORY' | 'USER'>('MEMORY');
  const [editingMemory, setEditingMemory] = useState(false);
  const [memoryEditorDraft, setMemoryEditorDraft] = useState('');
  const [factDraft, setFactDraft] = useState('');
  const [factTarget, setFactTarget] = useState<'memory' | 'user'>('memory');
  const [skillFilterProject, setSkillFilterProject] = useState<string>('ALL');
  const [skillSearch, setSkillSearch] = useState<string>('');
  const [skillTitle, setSkillTitle] = useState('');
  const [skillCategory, setSkillCategory] = useState('Workflow');
  const [skillProject, setSkillProject] = useState('');
  const [skillTrigger, setSkillTrigger] = useState('');
  const [skillSteps, setSkillSteps] = useState('');
  const [hermesBanner, setHermesBanner] = useState('');
  const [dispatching, setDispatching] = useState(false);
  const [distilling, setDistilling] = useState(false);
  const [applyingSkillId, setApplyingSkillId] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const loadStatus = async () => {
    const [pRes, tRes] = await Promise.all([
      kairosApi.getPaperclipStatus(),
      kairosApi.listTasks({}),
    ]);
    setSnapshot(pRes.paperclip);
    setAuditLogs(pRes.audit_logs);
    if (pRes.hermes) {
      setHermes(pRes.hermes);
    } else {
      const hRes = await kairosApi.getHermesStatus();
      setHermes(hRes);
    }
    setTasks(tRes.tasks);
    setSelectedTask((prev) =>
      tRes.tasks.length > 0
        ? prev && tRes.tasks.some((t) => t.id === prev)
          ? prev
          : tRes.tasks[0].id
        : ''
    );
  };

  useEffect(() => {
    loadStatus().catch(() => {});
  }, [refreshTick]);

  // Auto-poll active Paperclip checkout locks every 4s while background CrewAI / Hermes runs are active
  useEffect(() => {
    if ((snapshot?.active_count || 0) <= 0) return;
    const timer = window.setInterval(() => {
      loadStatus().catch(() => {});
    }, 4000);
    return () => window.clearInterval(timer);
  }, [snapshot?.active_count]);

  const handleManualRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await loadStatus();
    } catch (err) {
      notifyError('Paperclip Refresh Failed', err);
    } finally {
      setRefreshing(false);
    }
  };

  const notifyError = (fallbackTitle: string, err: unknown) => {
    const msg = err instanceof Error ? err.message : fallbackTitle;
    const isConflict = msg.includes('409') || msg.toLowerCase().includes('paperclip');
    onNotify?.(
      isConflict ? 'warning' : 'error',
      isConflict ? 'Paperclip Lock Conflict' : fallbackTitle,
      msg
    );
  };

  const handleDispatch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTask || dispatching) return;
    setDispatching(true);
    try {
      await kairosApi.dispatchCrew(selectedTask, selectedCrew, refUrl.trim());
      setDispatchMsg(
        `Paperclip checked out ${selectedTask} → ${selectedCrew} running (recalling & distilling Hermes knowledge)...`
      );
      setRefUrl('');
      onVaultMutated();
      window.setTimeout(() => {
        loadStatus().catch(() => {});
      }, 900);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Crew dispatch failed';
      setDispatchMsg(msg);
      notifyError('Crew Dispatch Failed', err);
    } finally {
      setDispatching(false);
    }
  };

  const handleForceUnlock = async (taskId: string) => {
    try {
      const res = await kairosApi.releasePaperclipLock(
        taskId,
        'Manual force-unlock from Paperclip Control Plane'
      );
      setHermesBanner(
        res.released
          ? `Force-unlocked ${res.task_id} (released checkout held by ${res.previous_agent || 'agent'})`
          : `${res.task_id} was already unlocked`
      );
      window.setTimeout(() => setHermesBanner(''), 4000);
      onNotify?.(
        'info',
        `Unlocked ${res.task_id}`,
        res.released ? `Released lock from ${res.previous_agent || 'agent'}` : 'No active lock found'
      );
      onVaultMutated();
      await loadStatus();
    } catch (err) {
      notifyError('Force Unlock Failed', err);
    }
  };

  const handleDistillSelectedTask = async () => {
    if (!selectedTask || distilling) return;
    setDistilling(true);
    try {
      const res = await kairosApi.distillTaskWithHermes(selectedTask);
      setHermesBanner(`Distilled ${selectedTask} into reusable skill ${res.skill_id} (${res.rel_path})`);
      window.setTimeout(() => setHermesBanner(''), 4500);
      onVaultMutated();
      await loadStatus();
    } catch (err) {
      notifyError('Skill Distillation Failed', err);
    } finally {
      setDistilling(false);
    }
  };

  const handleRetainFact = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!factDraft.trim()) return;
    try {
      const res = await kairosApi.retainHermesMemory({
        fact: factDraft.trim(),
        target: factTarget,
        is_private: /#private\b/i.test(factDraft),
      });
      setFactDraft('');
      setHermesBanner(`Retained durable knowledge in ${res.rel_path}`);
      window.setTimeout(() => setHermesBanner(''), 4000);
      onVaultMutated();
      await loadStatus();
    } catch (err) {
      notifyError('Hermes Retain Failed', err);
    }
  };

  const handleSaveMemoryDoc = async () => {
    if (!hermes) return;
    try {
      const rel = activeMemoryTab === 'USER' ? hermes.user_rel : hermes.memory_rel;
      await kairosApi.writeNote(
        rel,
        {
          title:
            activeMemoryTab === 'USER'
              ? 'Hermes Operator Profile (USER.md)'
              : 'Hermes Curated Memory (MEMORY.md)',
          type: activeMemoryTab === 'USER' ? 'hermes_user_profile' : 'hermes_memory',
          updated_at: new Date().toISOString().slice(0, 19),
          tags: ['hermes', 'knowledge-retention'],
        },
        memoryEditorDraft,
        'overwrite'
      );
      setEditingMemory(false);
      setHermesBanner(`Saved ${rel}`);
      window.setTimeout(() => setHermesBanner(''), 3500);
      onVaultMutated();
      await loadStatus();
    } catch (err) {
      notifyError('Memory Save Failed', err);
    }
  };

  const handleCreateManualSkill = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!skillTitle.trim()) return;
    try {
      const created = await kairosApi.createHermesSkill({
        title: skillTitle.trim(),
        trigger: skillTrigger.trim(),
        steps_markdown: skillSteps.trim(),
        category: skillCategory,
        project: skillProject,
        is_private: /#private\b/i.test(skillTitle) || /#private\b/i.test(skillSteps),
      });
      setSkillTitle('');
      setSkillTrigger('');
      setSkillSteps('');
      setHermesBanner(`Created Hermes Skill ${created.skill_id} → ${created.rel_path}`);
      window.setTimeout(() => setHermesBanner(''), 4500);
      onVaultMutated();
      await loadStatus();
    } catch (err) {
      notifyError('Create Hermes Skill Failed', err);
    }
  };

  const openTaskInProjectsDrawer = (taskId: string) => {
    const cleanId = taskId.replace(/^\[\[|\]\]$/g, '').trim();
    if (!cleanId) return;
    onExecuteUiCommands(
      [
        { type: 'navigate_tab', tab: 'projects' },
        { type: 'open_task_drawer', task_id: cleanId },
      ],
      `Opened task ${cleanId} from Paperclip / Hermes Hub`
    );
  };

  const handleApplySkillWithKairos = async (sk: {
    skill_id: string;
    title: string;
    project: string;
    is_private: boolean;
  }) => {
    if (applyingSkillId) return;
    setApplyingSkillId(sk.skill_id);
    try {
      setHermesBanner(`Applying ${sk.skill_id} (${sk.title}) via KAIROS Co-Pilot...`);
      const res = await kairosApi.sendAssistantChat({
        prompt: `Apply Hermes skill ${sk.skill_id} ("${sk.title}") to project ${sk.project || 'KAIROS_2_0'} and outline concrete next steps.`,
        session_id: activeSessionId,
        mode: sk.is_private ? 'gemma-4' : brainMode,
        persona,
        tone_mode: toneMode,
        project_scope: sk.project || 'KAIROS_2_0',
        current_tab: 'paperclip',
      });
      if (res.session?.session_id) {
        onSelectSessionId?.(res.session.session_id);
      }
      setHermesBanner(`Executed Hermes skill ${sk.skill_id} in KAIROS Chat Drawer`);
      window.setTimeout(() => setHermesBanner(''), 4000);
      onVaultMutated();
      onExecuteUiCommands(
        [...(res.ui_commands || []), { type: 'set_chat_drawer', open: true }],
        `Applied Hermes Skill ${sk.skill_id} in KAIROS Chat`,
        res.agent || 'Hermes-Agent'
      );
      onSpeakReply?.(res.spoken_reply || res.reply, res.privacy_locked);
    } catch (err) {
      notifyError('Apply Hermes Skill Failed', err);
    } finally {
      setApplyingSkillId('');
    }
  };

  const displayedMemoryBody =
    activeMemoryTab === 'USER' ? hermes?.user_body || '' : hermes?.memory_body || '';

  const skillProjectOptions = Array.from(
    new Set([
      ...projects.map((p) => p.name),
      ...(hermes?.skills || []).map((s) => s.project).filter(Boolean),
    ])
  );

  const qSkill = skillSearch.trim().toLowerCase();
  const filteredSkills = (hermes?.skills || []).filter((sk) => {
    if (skillFilterProject !== 'ALL' && sk.project !== skillFilterProject) return false;
    if (!qSkill) return true;
    return (
      sk.title.toLowerCase().includes(qSkill) ||
      sk.skill_id.toLowerCase().includes(qSkill) ||
      (sk.trigger || '').toLowerCase().includes(qSkill) ||
      (sk.category || '').toLowerCase().includes(qSkill) ||
      (sk.excerpt || '').toLowerCase().includes(qSkill)
    );
  });

  return (
    <div className="flex-1 overflow-y-auto p-5 bg-kairos-bg space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-base font-bold text-white flex items-center gap-2">
            <Paperclip className="h-4 w-4 text-purple-400" />
            Paperclip Task Broker, CrewAI Swarms & Hermes Knowledge Retention
          </h1>
          <p className="text-xs text-slate-400">
            Paperclip enforces atomic task locks (`TSK-*.md`), CrewAI executes multi-agent sprints,
            and **Hermes** retains curated memory (`MEMORY.md` / `USER.md`) + reusable procedural
            skills (`04_Resources/Hermes/Skills/SKL-*.md`) that compound across every session.
          </p>
        </div>

        <button
          type="button"
          disabled={refreshing}
          onClick={handleManualRefresh}
          title="Refresh Paperclip checkout locks, CrewAI runs & Hermes skill library"
          className="flex items-center gap-1.5 rounded-lg border border-kairos-border bg-kairos-panel px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-kairos-card disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin text-purple-300' : ''}`} />
          Refresh
        </button>
      </div>

      {hermesBanner && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-4 py-2 text-xs font-medium text-emerald-200">
          ✓ {hermesBanner}
        </div>
      )}

      {/* Top Row: Paperclip + CrewAI / Hermes Dispatcher & Active Locks */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <form
          onSubmit={handleDispatch}
          className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-3"
        >
          <div className="flex items-center gap-2 text-xs font-bold text-emerald-300">
            <Bot className="h-4 w-4" /> Dispatch CrewAI or Hermes Agent
          </div>

          <div>
            <label className="block text-[10px] uppercase text-slate-400 mb-1">
              Target Project Task
            </label>
            <select
              value={selectedTask}
              onChange={(e) => setSelectedTask(e.target.value)}
              className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-white"
            >
              {tasks.length === 0 ? (
                <option value="">No active tasks available</option>
              ) : (
                tasks.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.id} — {t.title} ({t.status})
                  </option>
                ))
              )}
            </select>
          </div>

          <div>
            <label className="block text-[10px] uppercase text-slate-400 mb-1">
              Agent / Swarm Profile
            </label>
            <select
              value={selectedCrew}
              onChange={(e) => setSelectedCrew(e.target.value)}
              className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-purple-300"
            >
              <option value="Hermes-Agent">
                🪽 Hermes-Agent (Execute + Auto-Distill Reusable Skill)
              </option>
              <option value="Hermes-Synthesizer">
                🪽 Hermes-Synthesizer (Knowledge Curator + Memory Retention)
              </option>
              <option value="CrewAI-Research">
                CrewAI-Research (Lead Researcher + Vault Scribe)
              </option>
              <option value="CrewAI-Dev">
                CrewAI-Dev (Systems Architect + Verification Engineer)
              </option>
              <option value="CrewAI-PM">CrewAI-PM (Projects Technical PM Breakdown)</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] uppercase text-slate-400 mb-1">
              Optional Co-Browsing Reference URL
            </label>
            <input
              type="text"
              value={refUrl}
              onChange={(e) => setRefUrl(e.target.value)}
              placeholder="https://..."
              className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-white font-mono"
            />
          </div>

          <div className="flex gap-2">
            <button
              type="submit"
              disabled={!selectedTask || dispatching}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-lg bg-purple-500 py-2 text-xs font-semibold text-white hover:bg-purple-400 transition disabled:opacity-50"
            >
              <Play className="h-3.5 w-3.5" />{' '}
              {dispatching ? 'Dispatching...' : 'Run via Paperclip'}
            </button>
            <button
              type="button"
              disabled={!selectedTask || distilling}
              onClick={handleDistillSelectedTask}
              title="Immediately distill selected task into a reusable Hermes SKL-*.md skill"
              className="rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-3 py-2 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/25 transition disabled:opacity-50"
            >
              {distilling ? 'Distilling...' : '🪽 Distill Skill'}
            </button>
          </div>

          {dispatchMsg && <div className="text-[11px] text-emerald-300">{dispatchMsg}</div>}
        </form>

        {/* Active Paperclip Checkout Locks */}
        <div className="lg:col-span-2 rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-white flex items-center gap-1.5">
              <Lock className="h-3.5 w-3.5 text-amber-400" /> Active Paperclip Task Locks (
              {snapshot?.active_count || 0})
            </span>
          </div>

          {(snapshot?.active_locks || []).length === 0 ? (
            <div className="rounded-lg border border-kairos-border bg-kairos-card/60 p-4 text-xs text-slate-400">
              No active locks — all Canopy Vault tasks are unlocked and ready for human, CrewAI, or
              Hermes checkout.
            </div>
          ) : (
            <div className="space-y-2">
              {snapshot?.active_locks.map((lk) => {
                const elapsed = typeof lk.elapsed_sec === 'number' ? Math.round(lk.elapsed_sec) : null;
                const stale = elapsed !== null && elapsed > 180;
                return (
                  <div
                    key={lk.lock_id}
                    className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 flex flex-wrap items-center justify-between gap-2 text-xs"
                  >
                    <div>
                      <div className="font-semibold text-amber-200 flex flex-wrap items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => openTaskInProjectsDrawer(lk.task_id)}
                          className="font-mono underline hover:text-white"
                        >
                          {lk.task_id}
                        </button>
                        <span>
                          • Checked out by `{lk.agent}` (`{lk.lock_id}`)
                        </span>
                        {elapsed !== null && (
                          <span
                            className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                              stale
                                ? 'bg-rose-500/25 border border-rose-500/40 text-rose-200'
                                : 'bg-kairos-bg text-slate-300'
                            }`}
                          >
                            {elapsed}s{stale ? ' • STALE?' : ''}
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-300 mt-0.5">{lk.step}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="animate-pulse rounded bg-amber-500/25 px-2 py-0.5 text-[10px] text-amber-200">
                        LOCKED
                      </span>
                      <button
                        type="button"
                        onClick={() => handleForceUnlock(lk.task_id)}
                        title="Force-release hung or orphaned Paperclip lock"
                        className="flex items-center gap-1 rounded border border-rose-500/45 bg-rose-500/15 px-2 py-1 text-[10px] font-semibold text-rose-200 hover:bg-rose-500/30 transition"
                      >
                        <Unlock className="h-3 w-3" /> Force Unlock
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div className="pt-2">
            <div className="text-xs font-bold text-white mb-2 flex items-center gap-1.5">
              <CircleCheck className="h-3.5 w-3.5 text-emerald-400" /> Recent Completed Crew &
              Hermes Runs
            </div>
            <div className="space-y-1.5 max-h-44 overflow-y-auto">
              {(snapshot?.recent_runs || []).map((r, i) => (
                <div
                  key={i}
                  className="flex flex-wrap items-center justify-between gap-2 rounded border border-kairos-border bg-kairos-card px-3 py-2 text-xs"
                >
                  <div className="min-w-0">
                    <button
                      type="button"
                      onClick={() => openTaskInProjectsDrawer(r.task_id)}
                      title="Inspect Task in Projects Drawer"
                      className="font-mono text-emerald-300 hover:underline"
                    >
                      {r.task_id}
                    </button>{' '}
                    • <span className="text-purple-300 font-medium">{r.agent}</span> —{' '}
                    <span className="text-slate-300">{r.summary}</span>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {r.artifact_rel_path && (
                      <button
                        type="button"
                        onClick={() => onOpenNoteInSecondBrain(r.artifact_rel_path!)}
                        title={`Open Crew Deliverable (${r.artifact_rel_path})`}
                        className="rounded border border-cyan-500/40 bg-cyan-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-cyan-200 hover:bg-cyan-500/25"
                      >
                        📄 Report
                      </button>
                    )}
                    {r.hermes_skill_rel_path && (
                      <button
                        type="button"
                        onClick={() => onOpenNoteInSecondBrain(r.hermes_skill_rel_path!)}
                        title={`Open Distilled Hermes Skill (${r.hermes_skill_rel_path})`}
                        className="rounded border border-purple-500/40 bg-purple-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-purple-200 hover:bg-purple-500/25"
                      >
                        🪽 Skill
                      </button>
                    )}
                    <span className="text-[10px] text-slate-400">
                      {r.duration_ms}ms • {r.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Middle Row: HERMES KNOWLEDGE RETENTION & PROCEDURAL SKILL LIBRARY */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
        {/* Left 6 Cols: Curated MEMORY.md & USER.md Viewer/Editor + Quick Retain */}
        <div className="xl:col-span-6 rounded-xl border border-purple-500/35 bg-kairos-panel p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-bold text-purple-200">
              <Brain className="h-4 w-4 text-purple-400" />
              <span>🪽 Hermes Persistent Memory (`04_Resources/Hermes/`)</span>
            </div>

            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => {
                  setActiveMemoryTab('MEMORY');
                  setEditingMemory(false);
                }}
                className={`rounded px-2.5 py-1 text-[11px] font-semibold transition ${
                  activeMemoryTab === 'MEMORY'
                    ? 'bg-purple-500/25 text-purple-200 border border-purple-500/40'
                    : 'bg-kairos-bg text-slate-400 hover:text-white'
                }`}
              >
                MEMORY.md
              </button>
              <button
                type="button"
                onClick={() => {
                  setActiveMemoryTab('USER');
                  setEditingMemory(false);
                }}
                className={`rounded px-2.5 py-1 text-[11px] font-semibold transition ${
                  activeMemoryTab === 'USER'
                    ? 'bg-cyan-500/25 text-cyan-200 border border-cyan-500/40'
                    : 'bg-kairos-bg text-slate-400 hover:text-white'
                }`}
              >
                USER.md
              </button>
              {hermes && (
                <button
                  type="button"
                  onClick={() =>
                    onOpenNoteInSecondBrain(
                      activeMemoryTab === 'USER' ? hermes.user_rel : hermes.memory_rel
                    )
                  }
                  title="Open Markdown file in Second Brain"
                  className="flex items-center gap-1 rounded border border-kairos-border bg-kairos-card px-2 py-1 text-[11px] text-cyan-300 hover:border-cyan-400"
                >
                  <ExternalLink className="h-3 w-3" /> .md
                </button>
              )}
              {!editingMemory ? (
                <button
                  type="button"
                  onClick={() => {
                    setMemoryEditorDraft(displayedMemoryBody);
                    setEditingMemory(true);
                  }}
                  className="rounded border border-kairos-border bg-kairos-card px-2 py-1 text-[11px] text-slate-200 hover:border-purple-400"
                >
                  Edit
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setEditingMemory(false);
                      setMemoryEditorDraft(displayedMemoryBody);
                    }}
                    className="flex items-center gap-1 rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[11px] text-slate-300 hover:text-white"
                  >
                    <X className="h-3 w-3" /> Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleSaveMemoryDoc}
                    className="flex items-center gap-1 rounded bg-emerald-500 px-2.5 py-1 text-[11px] font-bold text-slate-950"
                  >
                    <Save className="h-3 w-3" /> Save
                  </button>
                </>
              )}
            </div>
          </div>

          {editingMemory ? (
            <textarea
              value={memoryEditorDraft}
              onChange={(e) => setMemoryEditorDraft(e.target.value)}
              rows={10}
              className="w-full rounded-xl border border-kairos-border bg-kairos-bg p-3 font-mono text-xs text-slate-100 focus:outline-none"
            />
          ) : (
            <div className="rounded-xl border border-kairos-border bg-kairos-bg p-3.5 max-h-60 overflow-y-auto">
              <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-slate-200">
                {displayedMemoryBody || 'Initializing Hermes memory...'}
              </pre>
            </div>
          )}

          <form onSubmit={handleRetainFact} className="flex items-center gap-2 pt-1">
            <select
              value={factTarget}
              onChange={(e) => setFactTarget(e.target.value as 'memory' | 'user')}
              className="rounded-lg border border-kairos-border bg-kairos-bg px-2 py-1.5 text-xs text-purple-300"
            >
              <option value="memory">MEMORY.md</option>
              <option value="user">USER.md</option>
            </select>
            <input
              type="text"
              value={factDraft}
              onChange={(e) => setFactDraft(e.target.value)}
              placeholder="Retain durable lesson, convention, or operator preference..."
              className="flex-1 rounded-lg border border-kairos-border bg-kairos-bg px-3 py-1.5 text-xs text-white"
            />
            <button
              type="submit"
              className="rounded-lg bg-purple-500/25 border border-purple-500/45 px-3 py-1.5 text-xs font-semibold text-purple-200 hover:bg-purple-500/35"
            >
              + Retain
            </button>
          </form>
        </div>

        {/* Right 6 Cols: Hermes Self-Generated Procedural Skills (`SKL-*.md`) */}
        <div className="xl:col-span-6 rounded-xl border border-cyan-500/35 bg-kairos-panel p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-bold text-cyan-200">
              <BookMarked className="h-4 w-4 text-cyan-400" />
              <span>
                Reusable Hermes Procedural Skills ({hermes?.skill_count || 0} in `Skills/SKL-*.md`)
              </span>
            </div>
            <span className="text-[10.5px] text-slate-400">
              Auto-recalled into KAIROS Chat & CrewAI runs
            </span>
          </div>

          <div className="flex items-center gap-1.5 rounded-lg border border-kairos-border bg-kairos-bg px-2.5 py-1.5">
            <Search className="h-3.5 w-3.5 text-slate-400 shrink-0" />
            <input
              type="text"
              value={skillSearch}
              onChange={(e) => setSkillSearch(e.target.value)}
              placeholder="Search Hermes skills by title, SKL-ID, trigger, or step..."
              className="w-full bg-transparent text-xs text-white focus:outline-none"
            />
          </div>

          {skillProjectOptions.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => setSkillFilterProject('ALL')}
                className={`rounded-md px-2 py-0.5 text-[10.5px] font-semibold transition ${
                  skillFilterProject === 'ALL'
                    ? 'bg-cyan-500/25 border border-cyan-500/45 text-cyan-200'
                    : 'bg-kairos-bg border border-kairos-border text-slate-400 hover:text-white'
                }`}
              >
                All Projects ({hermes?.skills.length || 0})
              </button>
              {skillProjectOptions.map((pname) => (
                <button
                  key={pname}
                  type="button"
                  onClick={() => setSkillFilterProject(pname)}
                  className={`rounded-md px-2 py-0.5 text-[10.5px] font-semibold transition ${
                    skillFilterProject === pname
                      ? 'bg-cyan-500/25 border border-cyan-500/45 text-cyan-200'
                      : 'bg-kairos-bg border border-kairos-border text-slate-400 hover:text-white'
                  }`}
                >
                  {pname.replace(/_/g, ' ')}
                </button>
              ))}
            </div>
          )}

          <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
            {filteredSkills.length === 0 ? (
              <div className="rounded-lg border border-kairos-border bg-kairos-bg p-3 text-xs text-slate-400">
                No procedural skills in this scope yet. Click <strong>🪽 Distill Skill</strong> on
                any task or author a reusable skill below!
              </div>
            ) : (
              filteredSkills.map((sk) => (
                <div
                  key={sk.skill_id}
                  className="rounded-xl border border-kairos-border bg-kairos-card/80 p-3 space-y-1.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-xs font-bold text-white flex items-center gap-1.5">
                        <Sparkles className="h-3 w-3 text-cyan-400" />
                        {sk.title}
                      </span>
                      {sk.category && (
                        <span className="rounded bg-purple-500/15 border border-purple-500/30 px-1.5 py-0.2 text-[10px] text-purple-200">
                          {sk.category}
                        </span>
                      )}
                      {sk.project && (
                        <span className="rounded bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.2 text-[10px] text-emerald-200">
                          {sk.project.replace(/_/g, ' ')}
                        </span>
                      )}
                      {sk.is_private && (
                        <span className="rounded bg-amber-500/20 px-1.5 py-0.2 text-[10px] text-amber-300">
                          🔒 Local
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {sk.source_task && (
                        <button
                          type="button"
                          onClick={() => openTaskInProjectsDrawer(sk.source_task)}
                          title="Inspect source task in Projects Drawer"
                          className="font-mono text-[10px] text-amber-300 hover:underline"
                        >
                          {sk.source_task.replace(/^\[\[|\]\]$/g, '')}
                        </button>
                      )}
                      <span className="font-mono text-[10px] text-emerald-300">{sk.skill_id}</span>
                      <button
                        type="button"
                        disabled={Boolean(applyingSkillId)}
                        onClick={() => handleApplySkillWithKairos(sk)}
                        title="Apply this procedural skill in KAIROS Co-Pilot"
                        className="rounded border border-purple-500/40 bg-purple-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-purple-200 hover:bg-purple-500/25 disabled:opacity-50"
                      >
                        {applyingSkillId === sk.skill_id ? 'Applying...' : '⚡ Apply'}
                      </button>
                      <button
                        type="button"
                        onClick={() => onOpenNoteInSecondBrain(sk.rel_path)}
                        title="Open Skill Markdown in Second Brain"
                        className="flex items-center gap-0.5 rounded border border-cyan-500/35 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] text-cyan-200 hover:bg-cyan-500/20"
                      >
                        <ExternalLink className="h-2.5 w-2.5" /> .md
                      </button>
                    </div>
                  </div>
                  {sk.trigger && (
                    <div className="text-[10.5px] text-cyan-300">Trigger: {sk.trigger}</div>
                  )}
                  <div className="text-[11px] text-slate-400 line-clamp-2">{sk.excerpt}</div>
                </div>
              ))
            )}
          </div>

          <form
            onSubmit={handleCreateManualSkill}
            className="rounded-xl border border-kairos-border bg-kairos-bg p-3 space-y-2"
          >
            <div className="text-[11px] font-bold text-cyan-300 flex items-center gap-1">
              <Plus className="h-3 w-3" /> Author Reusable Hermes Skill
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input
                type="text"
                required
                value={skillTitle}
                onChange={(e) => setSkillTitle(e.target.value)}
                placeholder="Skill Title (e.g. Printful Drop Launch)"
                className="rounded border border-kairos-border bg-kairos-panel px-2.5 py-1.5 text-xs text-white"
              />
              <input
                type="text"
                value={skillTrigger}
                onChange={(e) => setSkillTrigger(e.target.value)}
                placeholder="When to apply..."
                className="rounded border border-kairos-border bg-kairos-panel px-2.5 py-1.5 text-xs text-white"
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <select
                value={skillCategory}
                onChange={(e) => setSkillCategory(e.target.value)}
                className="rounded border border-kairos-border bg-kairos-panel px-2.5 py-1.5 text-xs text-purple-200"
              >
                <option value="Workflow">Category: Workflow</option>
                <option value="Software Development">Category: Software Development</option>
                <option value="Marketing & Launch">Category: Marketing & Launch</option>
                <option value="UI Verification">Category: UI Verification</option>
                <option value="Architecture">Category: Architecture</option>
                <option value="DevOps">Category: DevOps</option>
              </select>
              <select
                value={skillProject}
                onChange={(e) => setSkillProject(e.target.value)}
                className="rounded border border-kairos-border bg-kairos-panel px-2.5 py-1.5 text-xs text-emerald-200"
              >
                <option value="">Scope: Cross-Project (Global)</option>
                {projects.map((p) => (
                  <option key={p.name} value={p.name}>
                    Project: {p.name.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            </div>
            <textarea
              rows={2}
              value={skillSteps}
              onChange={(e) => setSkillSteps(e.target.value)}
              placeholder="1. Scaffold campaign tasks  2. Sync assets  3. Verify live APIs..."
              className="w-full rounded border border-kairos-border bg-kairos-panel px-2.5 py-1.5 text-xs text-white resize-none"
            />
            <button
              type="submit"
              className="w-full rounded-lg bg-cyan-500/20 border border-cyan-500/40 py-1.5 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/30"
            >
              Save `SKL-*.md` to Hermes Skill Library
            </button>
          </form>
        </div>
      </div>

      {/* Dual-AI Router Audit Log (`_System/Logs/AI_Audit_Log.jsonl`) */}
      <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-3">
        <div className="flex items-center gap-2 text-xs font-bold text-white">
          <ShieldAlert className="h-4 w-4 text-cyan-400" />
          Dual-AI Router Audit Trail (`_System/Logs/AI_Audit_Log.jsonl`)
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-kairos-border text-[10px] uppercase text-slate-400">
              <tr>
                <th className="py-2 pr-3">Timestamp</th>
                <th className="py-2 pr-3">Agent</th>
                <th className="py-2 pr-3">Route Reason</th>
                <th className="py-2 pr-3">Tool</th>
                <th className="py-2 pr-3">Target</th>
                <th className="py-2 pr-3">Latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-kairos-border/60 font-mono text-[11px]">
              {auditLogs.map((row, idx) => (
                <tr key={idx}>
                  <td className="py-1.5 pr-3 text-slate-400">{String(row.timestamp || '')}</td>
                  <td className="py-1.5 pr-3 text-emerald-300">{String(row.agent || '')}</td>
                  <td className="py-1.5 pr-3 text-cyan-300">{String(row.route_reason || '')}</td>
                  <td className="py-1.5 pr-3 text-slate-300">{String(row.tool || '')}</td>
                  <td className="py-1.5 pr-3 text-slate-400">{String(row.target || '—')}</td>
                  <td className="py-1.5 pr-3 text-slate-300">{String(row.latency_ms || 0)}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Archive,
  BookOpen,
  Bot,
  CalendarPlus,
  Clock,
  CornerDownRight,
  ExternalLink,
  Play,
  Plus,
  Save,
  Square,
  SquareCheck,
  Trash2,
  X,
} from 'lucide-react';
import {
  ProjectTreeItem,
  STANDARD_DEPARTMENTS,
  TaskStatus,
  TaskSummary,
  VaultNoteDetail,
  kairosApi,
} from '../../api/client.ts';
import { ToastKind } from '../../components/ToastCenter.tsx';

interface TaskDrawerProps {
  taskId: string | null;
  projectsTree?: ProjectTreeItem[];
  allTasks?: TaskSummary[];
  onClose: () => void;
  onUpdated: () => void;
  onOpenInSecondBrain: (relPath: string) => void;
  onSelectTaskId?: (tid: string) => void;
  onNotify?: (kind: ToastKind, title: string, detail?: string) => void;
}

const STATUS_OPTIONS: TaskStatus[] = [
  'Backlog',
  'To Do',
  'In Progress',
  'Review',
  'Blocked',
  'Done',
];

const AI_AGENTS = [
  'None',
  'Gemma-4',
  'Gemini-Pro',
  'Both',
  'CrewAI-Research',
  'CrewAI-Dev',
  'CrewAI-PM',
  'Hermes-Agent',
  'Hermes-Synthesizer',
];

function getTodayLocalIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export const TaskDrawer: React.FC<TaskDrawerProps> = ({
  taskId,
  projectsTree = [],
  allTasks = [],
  onClose,
  onUpdated,
  onOpenInSecondBrain,
  onSelectTaskId,
  onNotify,
}) => {
  const [detail, setDetail] = useState<VaultNoteDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [newCheckItem, setNewCheckItem] = useState('');
  const [newSubtaskTitle, setNewSubtaskTitle] = useState('');
  const [creatingSubtask, setCreatingSubtask] = useState(false);
  const [commentText, setCommentText] = useState('');
  const [timerStartMs, setTimerStartMs] = useState<number | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [bodyDraft, setBodyDraft] = useState('');
  const [editingBody, setEditingBody] = useState(false);
  const [hermesNotice, setHermesNotice] = useState('');
  const [errorBanner, setErrorBanner] = useState('');
  const [confirmPermanentDelete, setConfirmPermanentDelete] = useState(false);

  // Custom Category inline switcher state
  const [addingCustomDept, setAddingCustomDept] = useState(false);
  const [customDeptInput, setCustomDeptInput] = useState('');

  // Inline Monthly Calendar Time-Blocker state
  const [blockDate, setBlockDate] = useState<string>(getTodayLocalIso);
  const [blockTime, setBlockTime] = useState<string>('10:00');
  const [blockDurationHrs, setBlockDurationHrs] = useState<number>(1);
  const [schedulingBlock, setSchedulingBlock] = useState(false);

  const loadSeqRef = useRef(0);
  const editingBodyRef = useRef(false);
  editingBodyRef.current = editingBody;

  const loadTask = async (id: string, forceResetDraft = false) => {
    const seq = ++loadSeqRef.current;
    setLoading(true);
    try {
      const d = await kairosApi.getTaskDetail(id);
      if (seq !== loadSeqRef.current) return;
      setDetail(d);
      if (forceResetDraft || !editingBodyRef.current) {
        setBodyDraft(d.body);
      }
      const dueStr = String(d.frontmatter?.due_date || '').slice(0, 10);
      const startStr = String(d.frontmatter?.start_date || '').slice(0, 10);
      setBlockDate(dueStr || startStr || getTodayLocalIso());
    } catch (err) {
      if (seq !== loadSeqRef.current) return;
      setDetail(null);
      const msg = err instanceof Error ? err.message : `Unable to load task ${id}`;
      setErrorBanner(msg);
    } finally {
      if (seq === loadSeqRef.current) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    setTimerStartMs(null);
    if (taskId) {
      setDetail(null);
      setEditingBody(false);
      setAddingCustomDept(false);
      setErrorBanner('');
      setConfirmPermanentDelete(false);
      loadTask(taskId, true).catch(() => {});
    } else {
      loadSeqRef.current += 1;
      setDetail(null);
    }
  }, [taskId]);

  useEffect(() => {
    if (timerStartMs === null) {
      setElapsedSec(0);
      return;
    }
    const id = window.setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - timerStartMs) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [timerStartMs]);

  const fm = detail?.frontmatter ?? {};
  const taskProjectClean = String(fm.project || '')
    .replace(/^\[\[/, '')
    .replace(/\]\]$/, '')
    .trim();
  const currentDept = String(fm.department || 'Software_Development');

  const departmentOptions = useMemo(() => {
    const map = new Map<string, string>();
    for (const std of STANDARD_DEPARTMENTS) {
      map.set(std.id, `${std.emoji} ${std.label}`);
    }
    const projNode = projectsTree.find((p) => p.name === taskProjectClean);
    if (projNode) {
      for (const d of projNode.departments) {
        if (!map.has(d.name)) {
          map.set(d.name, `📂 ${d.name.replace(/_/g, ' ')}`);
        }
      }
    }
    if (currentDept && !map.has(currentDept)) {
      map.set(currentDept, `📂 ${currentDept.replace(/_/g, ' ')}`);
    }
    return Array.from(map.entries()).map(([id, label]) => ({ id, label }));
  }, [projectsTree, taskProjectClean, currentDept]);

  const parentTaskId = useMemo(() => {
    const raw = String(fm.parent_task || '')
      .replace(/^\[\[/, '')
      .replace(/\]\]$/, '')
      .split('|')[0]
      .trim();
    return /^TSK-\d{8}-\d{3}$/i.test(raw) ? raw.toUpperCase() : '';
  }, [fm.parent_task]);

  const childSubtasks = useMemo(() => {
    if (!taskId) return [];
    const upper = taskId.toUpperCase();
    return allTasks.filter((t) => {
      const p = (t.parent_task || '')
        .replace(/^\[\[/, '')
        .replace(/\]\]$/, '')
        .split('|')[0]
        .trim()
        .toUpperCase();
      return p === upper;
    });
  }, [allTasks, taskId]);

  if (!taskId) return null;

  const checklistItems: { index: number; checked: boolean; text: string }[] = [];
  if (detail) {
    let idx = 0;
    for (const ln of detail.body.split(/\r?\n/)) {
      const trimmed = ln.trim();
      if (trimmed.startsWith('- [ ]') || trimmed.startsWith('- [x]') || trimmed.startsWith('- [X]')) {
        const checked = !trimmed.startsWith('- [ ]');
        checklistItems.push({
          index: idx,
          checked,
          text: trimmed.slice(5).trim(),
        });
        idx += 1;
      }
    }
  }

  const reportError = (fallbackTitle: string, err: unknown) => {
    const msg = err instanceof Error ? err.message : fallbackTitle;
    const isConflict = msg.includes('409') || msg.toLowerCase().includes('paperclip');
    setErrorBanner(msg);
    onNotify?.(
      isConflict ? 'warning' : 'error',
      isConflict ? 'Paperclip Lock Active' : fallbackTitle,
      msg
    );
  };

  const patchField = async (patch: Parameters<typeof kairosApi.updateTask>[1]) => {
    if (!taskId) return;
    try {
      setErrorBanner('');
      const updated = await kairosApi.updateTask(taskId, patch);
      setDetail(updated);
      if (!editingBodyRef.current || patch.body !== undefined) {
        setBodyDraft(updated.body);
      }
      onUpdated();
    } catch (err) {
      reportError('Task Update Failed', err);
      await loadTask(taskId);
    }
  };

  const handleArchiveOrDeleteTask = async (permanent: boolean) => {
    if (!taskId) return;
    try {
      setErrorBanner('');
      const res = await kairosApi.deleteTask(taskId, permanent);
      onNotify?.(
        'info',
        permanent ? `Deleted ${res.task_id}` : `Archived ${res.task_id}`,
        permanent
          ? 'Task removed permanently from Canopy Vault.'
          : `Moved cleanly to ${res.archived_rel_path}`
      );
      onUpdated();
      onClose();
    } catch (err) {
      reportError(permanent ? 'Task Delete Failed' : 'Task Archive Failed', err);
    }
  };

  const handleApplyCustomDepartment = async (e: React.FormEvent) => {
    e.preventDefault();
    const clean = customDeptInput.trim().replace(/\s+/g, '_');
    if (!clean) return;
    await patchField({ department: clean });
    setCustomDeptInput('');
    setAddingCustomDept(false);
    setHermesNotice(`Moved task into category '${clean.replace(/_/g, ' ')}'`);
    window.setTimeout(() => setHermesNotice(''), 3500);
  };

  const handleScheduleCalendarBlock = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskId || !blockDate) return;
    setSchedulingBlock(true);
    try {
      setErrorBanner('');
      const isoStart = `${blockDate}T${blockTime || '10:00'}:00`;
      const ev = await kairosApi.timeBlockTask(taskId, isoStart, blockDurationHrs, 'Business');
      setHermesNotice(`Scheduled on Monthly Calendar → ${ev.rel_path}`);
      window.setTimeout(() => setHermesNotice(''), 4000);
      await loadTask(taskId);
      onUpdated();
    } catch (err) {
      reportError('Calendar Block Failed', err);
    } finally {
      setSchedulingBlock(false);
    }
  };

  const handleCreateSubtask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskId || !newSubtaskTitle.trim()) return;
    setCreatingSubtask(true);
    try {
      setErrorBanner('');
      const created = await kairosApi.createTask({
        title: newSubtaskTitle.trim(),
        project: taskProjectClean || projectsTree[0]?.name || 'KAIROS_2_0',
        department: currentDept || 'Software_Development',
        list: String(fm.list || 'Sprint_01'),
        status: 'To Do',
        priority: Number(fm.priority || 2),
        ai_agent: String(fm.ai_agent || 'None'),
        parent_task: taskId,
      });
      const subId = String(created.frontmatter?.id || '');
      setNewSubtaskTitle('');
      setHermesNotice(`Created child subtask ${subId || created.title} under ${taskId}`);
      window.setTimeout(() => setHermesNotice(''), 3500);
      onUpdated();
    } catch (err) {
      reportError('Create Subtask Failed', err);
    } finally {
      setCreatingSubtask(false);
    }
  };

  const handleStopAndLogTimer = async () => {
    if (timerStartMs === null) return;
    const hrs = Math.max(0.05, Number(((Date.now() - timerStartMs) / 3600000).toFixed(2)));
    setTimerStartMs(null);
    await patchField({
      time_logged_delta: hrs,
      log_entry: `Stopwatch session logged +${hrs}h`,
    });
  };

  const handleSaveRawBody = async () => {
    if (!detail) return;
    try {
      setErrorBanner('');
      const updated = await kairosApi.writeNote(
        detail.rel_path,
        detail.frontmatter,
        bodyDraft,
        'overwrite'
      );
      setDetail(updated);
      setEditingBody(false);
      onUpdated();
    } catch (err) {
      reportError('Save Markdown Failed', err);
    }
  };

  const handleRunCrew = async () => {
    if (!taskId) return;
    try {
      setErrorBanner('');
      const agent = String(fm.ai_agent || 'CrewAI-Research');
      const crew =
        agent.startsWith('CrewAI') || agent.startsWith('Hermes') ? agent : 'Hermes-Agent';
      await kairosApi.dispatchCrew(taskId, crew);
      setHermesNotice(`Dispatched ${crew} via Paperclip lock`);
      window.setTimeout(() => setHermesNotice(''), 3500);
      onUpdated();
    } catch (err) {
      reportError('Agent Dispatch Blocked', err);
    }
  };

  const handleDistillHermesSkill = async () => {
    if (!taskId) return;
    try {
      setErrorBanner('');
      const res = await kairosApi.distillTaskWithHermes(taskId);
      setHermesNotice(`Distilled Hermes Skill ${res.skill_id} → ${res.rel_path}`);
      window.setTimeout(() => setHermesNotice(''), 4500);
      onUpdated();
    } catch (err) {
      reportError('Distill Hermes Skill Failed', err);
    }
  };

  const handlePublishToProjectWiki = async () => {
    if (!taskId || !detail) return;
    try {
      setErrorBanner('');
      const proj = taskProjectClean || 'KAIROS_2_0';
      const slug = detail.title
        .replace(/[^A-Za-z0-9_\- ]+/g, '')
        .trim()
        .replace(/\s+/g, '_')
        .slice(0, 44);
      const relPath = `02_Projects/${proj}/Docs/${taskId}_${slug || 'Summary'}.md`;
      const today = getTodayLocalIso();
      const tags = ['project-wiki', proj.toLowerCase(), taskId.toLowerCase()];
      if (detail.is_private) {
        tags.push('private');
      }
      const wikiBody = [
        `# 📘 ${detail.title} (${taskId})`,
        '',
        `> **Project:** [[02_Projects/${proj}/_Project_Index|${proj.replace(/_/g, ' ')}]] • **Source Task:** [[${taskId}]] • **Published:** \`${today}\``,
        `> **Category:** \`${currentDept}\` • **Status:** \`${String(fm.status || 'To Do')}\` • **Time Logged:** \`${Number(fm.time_logged_hrs || 0).toFixed(2)}h\``,
        '',
        detail.body.trim(),
        '',
      ].join('\n');
      const saved = await kairosApi.writeNote(
        relPath,
        {
          title: `${detail.title} (${taskId})`,
          type: 'project_wiki',
          project: `[[${proj}]]`,
          department: currentDept,
          source_task: `[[${taskId}]]`,
          updated_at: new Date().toISOString().slice(0, 19),
          tags,
        },
        wikiBody,
        'overwrite'
      );
      setHermesNotice(`Published task summary to Project Wiki → ${saved.rel_path}`);
      window.setTimeout(() => setHermesNotice(''), 4500);
      onUpdated();
    } catch (err) {
      reportError('Publish to Project Wiki Failed', err);
    }
  };

  const currentParentClean = String(fm.parent_task || '')
    .replace(/^\[\[/, '')
    .replace(/\]\]$/, '')
    .trim();
  const currentDepsClean = Array.isArray(fm.depends_on)
    ? (fm.depends_on as unknown[]).map((d) =>
        String(d)
          .replace(/^\[\[/, '')
          .replace(/\]\]$/, '')
          .trim()
      ).filter(Boolean)
    : [];

  return (
    <div className="fixed inset-y-14 right-0 z-30 w-[540px] max-w-full border-l border-slate-700/90 bg-[#0B101B] shadow-[0_16px_64px_rgba(0,0,0,0.92)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 bg-[#0F1726] px-4 py-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="rounded bg-emerald-500/15 px-2 py-0.5 font-mono text-xs font-semibold text-emerald-300">
            {taskId}
          </span>
          {taskProjectClean && (
            <span className="rounded bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold text-amber-300 truncate">
              🚀 {taskProjectClean.replace(/_/g, ' ')}
            </span>
          )}
          {detail && (
            <button
              type="button"
              onClick={() => onOpenInSecondBrain(detail.rel_path)}
              className="flex items-center gap-1 text-[11px] text-cyan-400 hover:underline truncate"
            >
              <ExternalLink className="h-3 w-3" /> Open `.md` in Second Brain
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {loading ? (
        <div className="p-6 text-xs text-slate-400">Loading Obsidian task file...</div>
      ) : !detail ? (
        <div className="p-6 space-y-3">
          <div className="rounded-xl border border-amber-500/40 bg-amber-500/15 p-3.5 text-xs text-amber-100 space-y-1.5">
            <div className="font-bold text-amber-300 flex items-center gap-1.5">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>Task Unavailable ({taskId})</span>
            </div>
            <div className="text-slate-300 break-words">
              {errorBanner ||
                'This task could not be found in active Projects or may have been removed.'}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-kairos-border bg-kairos-card px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-800"
          >
            Close Drawer
          </button>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {errorBanner && (
            <div className="flex items-start gap-2 rounded-xl border border-amber-500/50 bg-amber-500/15 p-3 text-xs text-amber-100">
              <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
              <div className="flex-1 break-words">{errorBanner}</div>
              <button
                type="button"
                onClick={() => setErrorBanner('')}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}

          {/* Task Title */}
          <div>
            <input
              key={`${taskId}-title-${detail.title}`}
              type="text"
              defaultValue={detail.title}
              onBlur={(e) => {
                if (e.target.value.trim() && e.target.value !== detail.title) {
                  patchField({ title: e.target.value.trim() });
                }
              }}
              className="w-full rounded-lg border border-transparent hover:border-kairos-border focus:border-emerald-500/60 bg-transparent px-2 py-1 text-base font-bold text-white focus:outline-none"
            />
            <div className="px-2 text-[11px] text-slate-500 font-mono">{detail.rel_path}</div>
          </div>

          {/* Project Task YAML Properties Grid */}
          <div className="grid grid-cols-2 gap-2.5 rounded-xl border border-kairos-border bg-kairos-panel p-3 text-xs">
            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">Status</label>
              <select
                value={String(fm.status || 'To Do')}
                onChange={(e) => patchField({ status: e.target.value as TaskStatus })}
                className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-white"
              >
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">Priority</label>
              <select
                value={Number(fm.priority || 3)}
                onChange={(e) => patchField({ priority: Number(e.target.value) })}
                className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-white"
              >
                <option value={1}>P1 — Urgent</option>
                <option value={2}>P2 — High</option>
                <option value={3}>P3 — Normal</option>
                <option value={4}>P4 — Low</option>
              </select>
            </div>

            <div className="col-span-2">
              <label className="block text-[10px] uppercase text-slate-400 mb-1">
                Category (`02_Projects/{taskProjectClean || 'Project'}/[Category]/`)
              </label>
              {!addingCustomDept ? (
                <select
                  value={currentDept}
                  onChange={(e) => {
                    if (e.target.value === '__add_custom__') {
                      setAddingCustomDept(true);
                    } else {
                      patchField({ department: e.target.value });
                    }
                  }}
                  className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-emerald-300"
                >
                  {departmentOptions.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.label}
                    </option>
                  ))}
                  <option value="__add_custom__">➕ Move to New Custom Category...</option>
                </select>
              ) : (
                <form onSubmit={handleApplyCustomDepartment} className="flex items-center gap-1.5">
                  <input
                    type="text"
                    autoFocus
                    value={customDeptInput}
                    onChange={(e) => setCustomDeptInput(e.target.value)}
                    placeholder="New Category (e.g. Podcast_Studio or R_and_D)"
                    className="flex-1 rounded border border-emerald-500/50 bg-kairos-bg px-2 py-1 text-xs text-white"
                  />
                  <button
                    type="submit"
                    className="rounded bg-emerald-500 px-2.5 py-1 text-[11px] font-semibold text-slate-950"
                  >
                    Move
                  </button>
                  <button
                    type="button"
                    onClick={() => setAddingCustomDept(false)}
                    className="rounded border border-kairos-border px-2 py-1 text-[11px] text-slate-400 hover:text-white"
                  >
                    Cancel
                  </button>
                </form>
              )}
            </div>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">Assignee</label>
              <input
                key={`${taskId}-assignee-${String(fm.assignee || 'Jaime')}`}
                type="text"
                defaultValue={String(fm.assignee || 'Jaime')}
                onBlur={(e) => patchField({ assignee: e.target.value })}
                className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-white"
              />
            </div>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">AI Agent</label>
              <select
                value={String(fm.ai_agent || 'None')}
                onChange={(e) => patchField({ ai_agent: e.target.value })}
                className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-purple-300"
              >
                {AI_AGENTS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">Start Date</label>
              <input
                key={`${taskId}-start-${String(fm.start_date || '')}`}
                type="date"
                defaultValue={String(fm.start_date || '')}
                onChange={(e) => patchField({ start_date: e.target.value })}
                className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-white"
              />
            </div>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">Due Date</label>
              <input
                key={`${taskId}-due-${String(fm.due_date || '')}`}
                type="date"
                defaultValue={String(fm.due_date || '')}
                onChange={(e) => patchField({ due_date: e.target.value })}
                className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-white"
              />
            </div>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">
                Parent Task (Subtask Of)
              </label>
              {allTasks.length > 0 ? (
                <select
                  value={currentParentClean}
                  onChange={(e) => patchField({ parent_task: e.target.value })}
                  className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-cyan-300"
                >
                  <option value="">None (Top-Level Task)</option>
                  {allTasks
                    .filter((t) => t.id !== taskId)
                    .map((t) => (
                      <option key={t.id} value={t.id}>
                        ↳ {t.id} — {t.title.slice(0, 22)}
                      </option>
                    ))}
                </select>
              ) : (
                <input
                  type="text"
                  key={`parent-${taskId}-${currentParentClean}`}
                  defaultValue={currentParentClean}
                  placeholder="e.g. TSK-20261024-001"
                  onBlur={(e) => {
                    if (e.target.value.trim() !== currentParentClean) {
                      patchField({ parent_task: e.target.value.trim() });
                    }
                  }}
                  className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-cyan-300"
                />
              )}
            </div>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">
                Depends On (`TSK-*`, comma-sep)
              </label>
              <input
                type="text"
                key={`deps-${taskId}-${currentDepsClean.join(',')}`}
                defaultValue={currentDepsClean.join(', ')}
                placeholder="e.g. TSK-20261024-001"
                onBlur={(e) => {
                  const nextDeps = e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean);
                  if (nextDeps.join(',') !== currentDepsClean.join(',')) {
                    patchField({ depends_on: nextDeps });
                  }
                }}
                className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-amber-300 font-mono"
              />
            </div>
          </div>

          {/* Task Time Tracker + Paperclip / CrewAI / Hermes Trigger */}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-kairos-border bg-kairos-panel p-3 text-xs">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-cyan-400" />
              <div>
                <div className="font-semibold text-white">
                  {Number(fm.time_logged_hrs || 0).toFixed(2)}h{' '}
                  <span className="text-slate-400 font-normal">
                    / {Number(fm.time_estimate_hrs || 0).toFixed(1)}h est
                  </span>
                </div>
                <div className="text-[10px] text-slate-400">YAML `time_logged_hrs`</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              {timerStartMs === null ? (
                <button
                  type="button"
                  onClick={() => setTimerStartMs(Date.now())}
                  className="flex items-center gap-1 rounded-md bg-emerald-500/20 border border-emerald-500/40 px-2.5 py-1 text-xs font-medium text-emerald-300 hover:bg-emerald-500/30"
                >
                  <Play className="h-3 w-3" /> Start Timer
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleStopAndLogTimer}
                  className="flex items-center gap-1 rounded-md bg-rose-500/25 border border-rose-500/40 px-2.5 py-1 text-xs font-medium text-rose-200 animate-pulse"
                >
                  <Square className="h-3 w-3" /> Stop ({elapsedSec}s)
                </button>
              )}
              <button
                type="button"
                onClick={() => patchField({ time_logged_delta: 0.25 })}
                className="rounded border border-kairos-border bg-kairos-card px-2 py-1 text-[11px] text-slate-300 hover:text-white"
              >
                +15m
              </button>
              <button
                type="button"
                onClick={handleRunCrew}
                className="flex items-center gap-1 rounded-md border border-purple-500/40 bg-purple-500/20 px-2.5 py-1 text-xs font-medium text-purple-200 hover:bg-purple-500/30"
              >
                <Bot className="h-3.5 w-3.5" /> Run Crew / Hermes
              </button>
              <button
                type="button"
                onClick={handleDistillHermesSkill}
                title="Distill this task into a reusable Hermes SKL-*.md Skill"
                className="rounded-md border border-cyan-500/40 bg-cyan-500/15 px-2 py-1 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25"
              >
                🪽 Distill Skill
              </button>
              <button
                type="button"
                onClick={handlePublishToProjectWiki}
                title="Publish a clean deliverable summary of this task into 02_Projects/[Project]/Docs/"
                className="flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/15 px-2 py-1 text-[11px] font-semibold text-emerald-200 hover:bg-emerald-500/25"
              >
                <BookOpen className="h-3 w-3" /> Wiki
              </button>
            </div>
          </div>

          {/* Inline Monthly Calendar Time-Blocker (`03_Personal/Calendar/EVT-*.md`) */}
          <form
            onSubmit={handleScheduleCalendarBlock}
            className="rounded-xl border border-sky-500/30 bg-kairos-panel p-3 space-y-2 text-xs"
          >
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 font-semibold text-sky-300">
                <CalendarPlus className="h-3.5 w-3.5" /> Time-Block on Monthly Calendar (`EVT-*.md`)
              </span>
              {Boolean(fm.gcal_event_id) && (
                <button
                  type="button"
                  title="Open linked calendar event .md in Second Brain"
                  onClick={() =>
                    onOpenInSecondBrain(`03_Personal/Calendar/${String(fm.gcal_event_id)}.md`)
                  }
                  className="font-mono text-[10px] text-emerald-300 hover:underline"
                >
                  Linked: {String(fm.gcal_event_id)}
                </button>
              )}
            </div>
            <div className="grid grid-cols-4 gap-2">
              <input
                type="date"
                value={blockDate}
                onChange={(e) => setBlockDate(e.target.value)}
                className="col-span-2 rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-white"
              />
              <input
                type="time"
                value={blockTime}
                onChange={(e) => setBlockTime(e.target.value)}
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-white"
              />
              <select
                value={blockDurationHrs}
                onChange={(e) => setBlockDurationHrs(Number(e.target.value))}
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-white"
              >
                <option value={0.5}>30m</option>
                <option value={1}>1h</option>
                <option value={1.5}>1.5h</option>
                <option value={2}>2h</option>
                <option value={3}>3h</option>
              </select>
            </div>
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={schedulingBlock}
                className="rounded-md bg-sky-500/20 border border-sky-500/40 px-3 py-1 text-[11px] font-semibold text-sky-200 hover:bg-sky-500/30 disabled:opacity-50"
              >
                {schedulingBlock ? 'Scheduling...' : '📅 Add Time-Block to Calendar'}
              </button>
            </div>
          </form>

          {hermesNotice && (
            <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-xs text-emerald-200">
              ✓ {hermesNotice}
            </div>
          )}

          {/* Child Subtasks (`TSK-*`) Breakdown & Creator */}
          <div className="rounded-xl border border-cyan-500/25 bg-kairos-panel p-3 space-y-2">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-200">
              <span className="flex items-center gap-1.5">
                <CornerDownRight className="h-3.5 w-3.5 text-cyan-400" />
                Child Subtasks (`TSK-*`)
              </span>
              <div className="flex items-center gap-2">
                {parentTaskId && onSelectTaskId && (
                  <button
                    type="button"
                    onClick={() => onSelectTaskId(parentTaskId)}
                    className="rounded bg-cyan-500/15 border border-cyan-500/30 px-2 py-0.5 font-mono text-[10px] text-cyan-300 hover:bg-cyan-500/25"
                    title={`Jump up to parent task ${parentTaskId}`}
                  >
                    ↑ Parent {parentTaskId}
                  </button>
                )}
                <span className="text-[11px] text-slate-400">
                  {childSubtasks.filter((s) => s.status === 'Done').length}/{childSubtasks.length}
                </span>
              </div>
            </div>

            {childSubtasks.length > 0 && (
              <div className="space-y-1">
                {childSubtasks.map((sub) => (
                  <div
                    key={sub.id}
                    onClick={() => onSelectTaskId?.(sub.id)}
                    className="flex items-center justify-between gap-2 rounded-lg border border-kairos-border bg-kairos-bg/70 px-2.5 py-1.5 text-xs cursor-pointer hover:border-cyan-500/40"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-mono text-[10px] text-cyan-300 shrink-0">{sub.id}</span>
                      <span
                        className={`truncate ${
                          sub.status === 'Done' ? 'line-through text-slate-500' : 'text-slate-100'
                        }`}
                      >
                        {sub.title}
                      </span>
                    </div>
                    <span className="shrink-0 rounded bg-kairos-card px-1.5 py-0.5 text-[10px] text-emerald-300">
                      {sub.status}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <form onSubmit={handleCreateSubtask} className="flex items-center gap-1.5 pt-1">
              <input
                type="text"
                value={newSubtaskTitle}
                onChange={(e) => setNewSubtaskTitle(e.target.value)}
                placeholder="Create linked child TSK-*.md subtask..."
                className="flex-1 rounded border border-kairos-border bg-kairos-bg px-2.5 py-1 text-xs text-white"
              />
              <button
                type="submit"
                disabled={creatingSubtask}
                className="rounded bg-cyan-500/20 border border-cyan-500/35 px-2.5 py-1 text-xs font-medium text-cyan-200 hover:bg-cyan-500/30 flex items-center gap-1 disabled:opacity-50"
              >
                <Plus className="h-3 w-3" /> Subtask
              </button>
            </form>
          </div>

          {/* Subtasks / Action Items Checklist */}
          <div className="rounded-xl border border-kairos-border bg-kairos-panel p-3 space-y-2">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-200">
              <span className="flex items-center gap-1.5">
                <SquareCheck className="h-3.5 w-3.5 text-emerald-400" />
                Action Items (Obsidian Markdown Checklist)
              </span>
              <span className="text-[11px] text-slate-400">
                {checklistItems.filter((c) => c.checked).length}/{checklistItems.length}
              </span>
            </div>

            <div className="space-y-1.5">
              {checklistItems.map((item) => (
                <label
                  key={item.index}
                  className="flex items-start gap-2 rounded px-2 py-1 hover:bg-kairos-card cursor-pointer text-xs"
                >
                  <input
                    type="checkbox"
                    checked={item.checked}
                    onChange={() => patchField({ toggle_checklist_index: item.index })}
                    className="mt-0.5 accent-emerald-500"
                  />
                  <span className={item.checked ? 'line-through text-slate-500' : 'text-slate-200'}>
                    {item.text}
                  </span>
                </label>
              ))}
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!newCheckItem.trim()) return;
                patchField({ add_checklist_item: newCheckItem.trim() });
                setNewCheckItem('');
              }}
              className="flex items-center gap-1.5 pt-1"
            >
              <input
                type="text"
                value={newCheckItem}
                onChange={(e) => setNewCheckItem(e.target.value)}
                placeholder="Add checklist subtask..."
                className="flex-1 rounded border border-kairos-border bg-kairos-bg px-2.5 py-1 text-xs text-white"
              />
              <button
                type="submit"
                className="rounded bg-kairos-card border border-kairos-border px-2.5 py-1 text-xs text-emerald-300 hover:bg-emerald-500/20 flex items-center gap-1"
              >
                <Plus className="h-3 w-3" /> Add
              </button>
            </form>
          </div>

          {/* Markdown Body + Activity Log */}
          <div className="rounded-xl border border-kairos-border bg-kairos-panel p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-200">
                Markdown Body &amp; Activity Log
              </span>
              {!editingBody ? (
                <button
                  type="button"
                  onClick={() => setEditingBody(true)}
                  className="text-[11px] text-cyan-400 hover:underline"
                >
                  Edit Raw Markdown
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleSaveRawBody}
                  className="flex items-center gap-1 rounded bg-emerald-500/20 px-2 py-0.5 text-[11px] text-emerald-300"
                >
                  <Save className="h-3 w-3" /> Save `.md`
                </button>
              )}
            </div>

            {editingBody ? (
              <textarea
                value={bodyDraft}
                onChange={(e) => setBodyDraft(e.target.value)}
                rows={12}
                className="w-full rounded border border-kairos-border bg-kairos-bg p-2.5 font-mono text-xs text-slate-200 focus:outline-none"
              />
            ) : (
              <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-slate-300 max-h-64 overflow-y-auto">
                {detail.body}
              </pre>
            )}

            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!commentText.trim()) return;
                patchField({ log_entry: commentText.trim() });
                setCommentText('');
              }}
              className="flex items-center gap-1.5 pt-2 border-t border-kairos-border"
            >
              <input
                type="text"
                value={commentText}
                onChange={(e) => setCommentText(e.target.value)}
                placeholder="Append comment to Activity & AI Log..."
                className="flex-1 rounded border border-kairos-border bg-kairos-bg px-2.5 py-1 text-xs text-white"
              />
              <button
                type="submit"
                className="rounded bg-emerald-500/20 px-2.5 py-1 text-xs font-medium text-emerald-300 hover:bg-emerald-500/30"
              >
                Log
              </button>
            </form>
          </div>

          {/* Task Lifecycle: Soft-Archive (`05_Archives/Tasks/`) & Permanent Delete */}
          <div className="rounded-xl border border-kairos-border bg-kairos-panel p-3 flex flex-wrap items-center justify-between gap-2 text-xs">
            <div className="text-[11px] text-slate-400">
              Archive keeps `.md` searchable in `05_Archives/Tasks/` while clearing active boards.
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => handleArchiveOrDeleteTask(false)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/25"
              >
                <Archive className="h-3.5 w-3.5" /> Archive Task
              </button>

              {!confirmPermanentDelete ? (
                <button
                  type="button"
                  onClick={() => setConfirmPermanentDelete(true)}
                  title="Permanently delete task .md file from Canopy Vault"
                  className="inline-flex items-center gap-1 rounded-lg border border-rose-500/35 bg-rose-500/10 px-2.5 py-1.5 text-xs text-rose-300 hover:bg-rose-500/20"
                >
                  <Trash2 className="h-3.5 w-3.5" /> Delete
                </button>
              ) : (
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => handleArchiveOrDeleteTask(true)}
                    className="rounded-lg bg-rose-500 px-2.5 py-1.5 text-xs font-bold text-white hover:bg-rose-400"
                  >
                    Confirm Permanent Delete
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmPermanentDelete(false)}
                    className="rounded-lg border border-kairos-border px-2 py-1.5 text-[11px] text-slate-400 hover:text-white"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

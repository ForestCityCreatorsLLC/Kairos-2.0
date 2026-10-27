import React, { useEffect, useState } from 'react';
import {
  BarChart3,
  BookOpen,
  Bot,
  BotMessageSquare,
  Calendar,
  CalendarPlus,
  Command,
  Database,
  FileText,
  GanttChart,
  GitBranch,
  Globe,
  Inbox,
  Kanban,
  Layers,
  List,
  ListTodo,
  Lock,
  Maximize2,
  Search,
  Sparkles,
  X,
} from 'lucide-react';
import {
  ProjectsSubView,
  TaskSummary,
  UIActionCommand,
  VaultNoteSummary,
  VaultSectionHubSummary,
  kairosApi,
} from '../api/client.ts';
import { WorkspaceTab } from './LeftSidebar.tsx';

interface CommandPaletteProps {
  open: boolean;
  focusModeActive?: boolean;
  onClose: () => void;
  onNavigateTab: (tab: WorkspaceTab) => void;
  onOpenNote: (relPath: string) => void;
  onOpenDailyNote: () => void;
  onExecuteUiCommands?: (cmds: UIActionCommand[], summary?: string) => void;
  onRunCommandPrompt?: (promptText: string) => void;
}

const PROJECTS_SUBVIEW_JUMPS: {
  view: ProjectsSubView;
  label: string;
  icon: React.ReactNode;
}[] = [
  { view: 'rollup', label: '1. Rollup', icon: <BarChart3 className="h-3.5 w-3.5 text-emerald-400" /> },
  { view: 'list', label: '2. List', icon: <List className="h-3.5 w-3.5 text-cyan-400" /> },
  { view: 'board', label: '3. Board', icon: <Kanban className="h-3.5 w-3.5 text-amber-400" /> },
  { view: 'calendar', label: '4. Calendar', icon: <Calendar className="h-3.5 w-3.5 text-sky-400" /> },
  { view: 'gantt', label: '5. Gantt', icon: <GanttChart className="h-3.5 w-3.5 text-purple-400" /> },
  { view: 'docs', label: '6. Documentation', icon: <BookOpen className="h-3.5 w-3.5 text-rose-400" /> },
];

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  open,
  focusModeActive = false,
  onClose,
  onNavigateTab,
  onOpenNote,
  onOpenDailyNote,
  onExecuteUiCommands,
  onRunCommandPrompt,
}) => {
  const [query, setQuery] = useState('');
  const [notes, setNotes] = useState<VaultNoteSummary[]>([]);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [vaultSections, setVaultSections] = useState<VaultSectionHubSummary[]>([]);
  const [hasMasterBase, setHasMasterBase] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState<number>(0);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setQuery('');
    setSelectedIdx(0);
    Promise.all([
      kairosApi.searchNotes('', ''),
      kairosApi.listTasks({}),
      kairosApi.getVaultStructure().catch(() => null),
    ])
      .then(([nRes, tRes, sRes]) => {
        if (cancelled) return;
        setNotes(nRes.notes);
        setTasks(tRes.tasks);
        if (sRes) {
          setVaultSections(sRes.sections || []);
          setHasMasterBase(
            Boolean(
              sRes.bases?.some(
                (b) => b.rel_path === '_System/Dashboards/Vault_Master_Catalog.base'
              )
            )
          );
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setSelectedIdx(0);
    const timer = window.setTimeout(() => {
      kairosApi
        .searchNotes(query, '')
        .then((res) => {
          if (!cancelled) setNotes(res.notes);
        })
        .catch(() => {});
    }, 120);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, open]);

  if (!open) return null;

  const qLow = query.trim().toLowerCase();
  const filteredTasks = tasks
    .filter(
      (t) =>
        !qLow ||
        t.title.toLowerCase().includes(qLow) ||
        t.id.toLowerCase().includes(qLow) ||
        t.project.toLowerCase().includes(qLow) ||
        t.department.toLowerCase().includes(qLow)
    )
    .slice(0, 6);

  const filteredNotes = notes.slice(0, 7);
  const filteredHubs = vaultSections
    .filter(
      (s) =>
        !qLow ||
        s.title.toLowerCase().includes(qLow) ||
        s.section_rel.toLowerCase().includes(qLow) ||
        s.collections.some((c) => c.title.toLowerCase().includes(qLow))
    )
    .slice(0, 5);

  const handleOpenHubTarget = (relPath: string, folderFilter: string, summary: string) => {
    if (onExecuteUiCommands) {
      onExecuteUiCommands(
        [
          { type: 'navigate_tab', tab: 'second-brain' },
          { type: 'filter_second_brain', folder: folderFilter },
          { type: 'open_note', rel_path: relPath },
        ],
        summary
      );
    } else {
      onOpenNote(relPath);
    }
    onClose();
  };

  const handleJumpSubView = (view: ProjectsSubView, label: string) => {
    if (onExecuteUiCommands) {
      onExecuteUiCommands(
        [
          { type: 'navigate_tab', tab: 'projects' },
          { type: 'set_projects_view', view },
        ],
        `Switched Projects to ${label}`
      );
    } else {
      onNavigateTab('projects');
    }
    onClose();
  };

  const handleJumpTask = (t: TaskSummary) => {
    if (onExecuteUiCommands) {
      onExecuteUiCommands(
        [
          { type: 'navigate_tab', tab: 'projects' },
          { type: 'select_project_scope', project: t.project, department: '', list: '' },
          { type: 'open_task_drawer', task_id: t.id },
        ],
        `Opened Task ${t.id} in ${t.project}`
      );
    } else {
      onOpenNote(t.rel_path);
    }
    onClose();
  };

  const hasPromptAction = query.trim().length > 0 && Boolean(onRunCommandPrompt);
  const keyboardItems: { key: string; run: () => void }[] = [];
  if (hasPromptAction && onRunCommandPrompt) {
    const cleanQ = query.trim();
    keyboardItems.push({
      key: 'run-prompt',
      run: () => {
        onRunCommandPrompt(cleanQ);
        onClose();
      },
    });
  }
  for (const h of filteredHubs) {
    keyboardItems.push({
      key: `hub-${h.section_rel}`,
      run: () => handleOpenHubTarget(h.hub_index_rel, h.section_rel, `Opened ${h.title} Hub`),
    });
  }
  for (const t of filteredTasks) {
    keyboardItems.push({
      key: `task-${t.id}`,
      run: () => handleJumpTask(t),
    });
  }
  for (const n of filteredNotes) {
    keyboardItems.push({
      key: `note-${n.rel_path}`,
      run: () => {
        onOpenNote(n.rel_path);
        onClose();
      },
    });
  }
  const safeSelectedIdx =
    keyboardItems.length > 0 ? Math.min(selectedIdx, keyboardItems.length - 1) : 0;
  const activeKey = keyboardItems[safeSelectedIdx]?.key || '';

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 bg-black/85 flex items-start justify-center pt-16 p-4"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl rounded-2xl border border-slate-700/90 bg-[#0B101B] shadow-[0_24px_80px_rgba(0,0,0,0.95)] overflow-hidden"
      >
        <div className="flex items-center border-b border-slate-800 bg-[#0F1726] px-4 py-3 gap-2.5">
          <Search className="h-4 w-4 text-emerald-400 shrink-0" />
          <input
            autoFocus
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.preventDefault();
                onClose();
                return;
              }
              if (e.key === 'ArrowDown' && keyboardItems.length > 0) {
                e.preventDefault();
                setSelectedIdx((safeSelectedIdx + 1) % keyboardItems.length);
                return;
              }
              if (e.key === 'ArrowUp' && keyboardItems.length > 0) {
                e.preventDefault();
                setSelectedIdx(
                  (safeSelectedIdx - 1 + keyboardItems.length) % keyboardItems.length
                );
                return;
              }
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && query.trim() && onRunCommandPrompt) {
                e.preventDefault();
                onRunCommandPrompt(query.trim());
                onClose();
                return;
              }
              if (e.key === 'Enter' && keyboardItems[safeSelectedIdx]) {
                e.preventDefault();
                keyboardItems[safeSelectedIdx].run();
              }
            }}
            placeholder="Quick Jump (↑/↓ + Enter) or type a KAIROS command (Ctrl+Enter)..."
            className="w-full bg-transparent text-sm text-white placeholder-slate-400 focus:outline-none"
          />
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[480px] overflow-y-auto p-3.5 space-y-4 bg-[#0B101B]">
          {query.trim().length > 0 && onRunCommandPrompt && (
            <button
              type="button"
              onClick={() => {
                onRunCommandPrompt(query.trim());
                onClose();
              }}
              className={`w-full flex items-center justify-between gap-2 rounded-xl border px-3.5 py-2.5 text-left text-xs text-emerald-200 transition ${
                activeKey === 'run-prompt'
                  ? 'border-emerald-400 bg-emerald-500/25'
                  : 'border-emerald-500/50 bg-emerald-500/15 hover:bg-emerald-500/25'
              }`}
            >
              <span className="flex items-center gap-2 min-w-0">
                <Sparkles className="h-4 w-4 text-emerald-400 shrink-0" />
                <span className="truncate">
                  <strong className="text-white">Ask KAIROS / Execute Command:</strong> &ldquo;
                  {query.trim()}&rdquo;
                </span>
              </span>
              <span className="rounded bg-slate-900/80 border border-emerald-500/35 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300 shrink-0">
                Ctrl+Enter
              </span>
            </button>
          )}

          {/* Quick Actions */}
          <div>
            <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Quick Actions
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {onRunCommandPrompt && (
                <button
                  type="button"
                  onClick={() => {
                    onRunCommandPrompt('Give me my daily briefing');
                    onClose();
                  }}
                  className="col-span-2 flex items-center justify-between gap-2 rounded-lg border border-emerald-500/35 bg-[#102226] px-3 py-2 text-xs font-semibold text-emerald-200 hover:border-emerald-400"
                >
                  <span className="flex items-center gap-2">
                    <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
                    Executive Daily Briefing (Rollup + Today&apos;s Agenda + Hermes Continuity)
                  </span>
                  <span className="font-mono text-[10px] text-emerald-300">Spoken + Chat</span>
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  onNavigateTab('assistant');
                  onClose();
                }}
                className="flex items-center gap-2 rounded-lg border border-slate-800 bg-[#11192A] px-3 py-2 text-xs text-emerald-300 hover:border-emerald-500/50"
              >
                <BotMessageSquare className="h-3.5 w-3.5" /> Open KAIROS Spoken Assistant
              </button>
              <button
                type="button"
                onClick={() => {
                  onOpenDailyNote();
                  onClose();
                }}
                className="flex items-center gap-2 rounded-lg border border-slate-800 bg-[#11192A] px-3 py-2 text-xs text-cyan-300 hover:border-cyan-500/50"
              >
                <CalendarPlus className="h-3.5 w-3.5" /> Open Today&apos;s Daily Note
              </button>
              <button
                type="button"
                onClick={() => {
                  onNavigateTab('inbox');
                  onClose();
                }}
                className="flex items-center gap-2 rounded-lg border border-slate-800 bg-[#11192A] px-3 py-2 text-xs text-amber-300 hover:border-amber-500/50"
              >
                <Inbox className="h-3.5 w-3.5" /> Triage 00_Inbox Captures
              </button>
              <button
                type="button"
                onClick={() => {
                  onNavigateTab('browser');
                  onClose();
                }}
                className="flex items-center gap-2 rounded-lg border border-slate-800 bg-[#11192A] px-3 py-2 text-xs text-sky-300 hover:border-sky-500/50"
              >
                <Globe className="h-3.5 w-3.5" /> Open Embedded Browser &amp; Clipper
              </button>
              <button
                type="button"
                onClick={() => {
                  if (onExecuteUiCommands) {
                    onExecuteUiCommands(
                      [
                        { type: 'navigate_tab', tab: 'second-brain' },
                        { type: 'set_second_brain_graph', show: true, mode: '3d' },
                      ],
                      'Opened Second Brain 3D Galaxy Graph'
                    );
                  } else {
                    onNavigateTab('second-brain');
                  }
                  onClose();
                }}
                className="flex items-center gap-2 rounded-lg border border-slate-800 bg-[#11192A] px-3 py-2 text-xs text-purple-300 hover:border-purple-500/50"
              >
                <Sparkles className="h-3.5 w-3.5" /> Second Brain 3D Galaxy Graph
              </button>
              <button
                type="button"
                onClick={() => {
                  onNavigateTab('paperclip');
                  onClose();
                }}
                className="flex items-center gap-2 rounded-lg border border-slate-800 bg-[#11192A] px-3 py-2 text-xs text-purple-300 hover:border-purple-500/50"
              >
                <Bot className="h-3.5 w-3.5" /> Paperclip, CrewAI &amp; Hermes
              </button>
              <button
                type="button"
                onClick={() => {
                  if (onExecuteUiCommands) {
                    onExecuteUiCommands(
                      [
                        { type: 'navigate_tab', tab: 'browser' },
                        {
                          type: 'browser_navigate',
                          url: 'https://github.com/ForestCityCreatorsLLC?tab=repositories',
                          title: 'Forest City Creators LLC — Repositories',
                        },
                      ],
                      'Opened Forest City Creators LLC Repositories'
                    );
                  } else {
                    onNavigateTab('browser');
                  }
                  onClose();
                }}
                className="flex items-center gap-2 rounded-lg border border-slate-800 bg-[#11192A] px-3 py-2 text-xs text-emerald-300 hover:border-emerald-500/50"
              >
                <GitBranch className="h-3.5 w-3.5" /> ForestCityCreatorsLLC GitHub Repos
              </button>
              <button
                type="button"
                onClick={() => {
                  if (onExecuteUiCommands) {
                    onExecuteUiCommands(
                      focusModeActive
                        ? [
                            { type: 'set_left_sidebar', collapsed: false },
                            { type: 'set_chat_drawer', open: true },
                          ]
                        : [
                            { type: 'set_left_sidebar', collapsed: true },
                            { type: 'set_chat_drawer', open: false },
                          ],
                      focusModeActive
                        ? 'Restored Left Sidebar & Docked Chat Drawer'
                        : 'Entered Focus Mode (Full-Width Workspace)'
                    );
                  }
                  onClose();
                }}
                className="flex items-center gap-2 rounded-lg border border-slate-800 bg-[#11192A] px-3 py-2 text-xs text-cyan-200 hover:border-cyan-500/50"
              >
                <Maximize2 className="h-3.5 w-3.5 text-cyan-400" />{' '}
                {focusModeActive ? 'Exit Focus Mode (Restore Panels)' : 'Focus Mode (Maximize Workspace)'}
              </button>
              <button
                type="button"
                onClick={() => {
                  onNavigateTab('settings');
                  onClose();
                }}
                className="col-span-2 flex items-center gap-2 rounded-lg border border-slate-800 bg-[#11192A] px-3 py-2 text-xs text-slate-300 hover:border-cyan-500/50 hover:text-white"
              >
                <Command className="h-3.5 w-3.5 text-cyan-400" /> System Diagnostics, Voice VRAM &amp; API Settings
              </button>
            </div>
          </div>

          {/* Projects Sub-Views (1. Rollup -> 6. Documentation) */}
          <div>
            <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Projects Views (`Rollup → List → Board → Calendar → Gantt → Documentation`)
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              {PROJECTS_SUBVIEW_JUMPS.map((item) => (
                <button
                  key={item.view}
                  type="button"
                  onClick={() => handleJumpSubView(item.view, item.label)}
                  className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-[#11192A] px-2.5 py-1.5 text-xs font-medium text-slate-200 hover:border-emerald-500/50 hover:text-white"
                >
                  {item.icon}
                  <span className="truncate">{item.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Obsidian Section Hubs & Live `.base` Databases */}
          {(filteredHubs.length > 0 || hasMasterBase) && (
            <div>
              <div className="flex items-center justify-between px-2 pb-1.5">
                <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-purple-300">
                  <Layers className="h-3 w-3 text-purple-400" />
                  <span>Obsidian Section Hubs &amp; Live `.base` Databases</span>
                </span>
                {hasMasterBase && (
                  <button
                    type="button"
                    onClick={() => {
                      onOpenNote('_System/Dashboards/Vault_Master_Catalog.base');
                      onClose();
                    }}
                    className="inline-flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-200 hover:bg-emerald-500/25"
                  >
                    <Database className="h-2.5 w-2.5 text-emerald-300" />
                    <span>Master Vault `.base`</span>
                  </button>
                )}
              </div>
              <div className="space-y-1">
                {filteredHubs.map((hub) => (
                  <div
                    key={hub.section_rel}
                    className={`flex items-center justify-between gap-2 rounded-lg border px-3 py-1.5 text-xs transition ${
                      activeKey === `hub-${hub.section_rel}`
                        ? 'border-purple-400/60 bg-purple-500/15'
                        : 'border-slate-800/80 bg-[#11192A] hover:border-purple-500/40'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() =>
                        handleOpenHubTarget(
                          hub.hub_index_rel,
                          hub.section_rel,
                          `Opened ${hub.title} Section Hub`
                        )
                      }
                      className="flex-1 flex items-center gap-2 min-w-0 text-left"
                    >
                      <span>{hub.icon || '🗂️'}</span>
                      <span className="font-semibold text-white truncate">{hub.title}</span>
                      <span className="text-[10px] font-mono text-slate-400 shrink-0">
                        {hub.entry_count} items
                      </span>
                    </button>
                    <div className="flex items-center gap-1 shrink-0">
                      {hub.base_rel && (
                        <button
                          type="button"
                          onClick={() =>
                            handleOpenHubTarget(
                              hub.base_rel,
                              hub.section_rel,
                              `Opened ${hub.title} .base Catalog`
                            )
                          }
                          className="rounded border border-emerald-500/35 bg-emerald-500/15 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300 hover:bg-emerald-500/25"
                        >
                          📊 .base
                        </button>
                      )}
                      {hub.canvas_rel && (
                        <button
                          type="button"
                          onClick={() =>
                            handleOpenHubTarget(
                              hub.canvas_rel,
                              hub.section_rel,
                              `Opened ${hub.title} .canvas Map`
                            )
                          }
                          className="rounded border border-purple-500/35 bg-purple-500/15 px-1.5 py-0.5 font-mono text-[10px] text-purple-200 hover:bg-purple-500/25"
                        >
                          🎨 .canvas
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Matching Project Tasks */}
          {filteredTasks.length > 0 && (
            <div>
              <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                Project Tasks (`02_Projects/`)
              </div>
              <div className="space-y-1">
                {filteredTasks.map((t) => (
                  <div
                    key={t.id}
                    className={`w-full flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs transition ${
                      activeKey === `task-${t.id}`
                        ? 'border-emerald-500/60 bg-emerald-500/15'
                        : 'border-transparent hover:border-slate-800 hover:bg-[#131C2E]'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => handleJumpTask(t)}
                      className="flex-1 flex items-center justify-between gap-2 min-w-0 text-left"
                    >
                      <span className="flex items-center gap-2 min-w-0">
                        <ListTodo className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                        <span className="font-mono text-emerald-300">{t.id}</span>
                        <span className="text-white truncate">{t.title}</span>
                      </span>
                      <span className="text-[10px] text-slate-400 shrink-0">
                        {t.project} / {t.department.replace(/_/g, ' ')} • {t.status}
                      </span>
                    </button>
                    <button
                      type="button"
                      title="Open raw .md in Second Brain"
                      onClick={() => {
                        onOpenNote(t.rel_path);
                        onClose();
                      }}
                      className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300 hover:border-cyan-500/50 shrink-0"
                    >
                      .md
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Matching Second Brain Notes & Hermes Skills */}
          <div>
            <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Canopy Vault Notes, Project Wikis &amp; Hermes Skills
            </div>
            <div className="space-y-1">
              {filteredNotes.map((n) => (
                <button
                  key={n.rel_path}
                  type="button"
                  onClick={() => {
                    onOpenNote(n.rel_path);
                    onClose();
                  }}
                  className={`w-full flex items-center justify-between rounded-lg border px-3 py-2 text-xs transition text-left ${
                    activeKey === `note-${n.rel_path}`
                      ? 'border-emerald-500/60 bg-emerald-500/15'
                      : 'border-transparent hover:bg-[#131C2E]'
                  }`}
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <FileText className="h-3.5 w-3.5 text-cyan-400 shrink-0" />
                    <span className="text-white font-medium truncate">{n.title}</span>
                    {n.rel_path.endsWith('.base') && (
                      <span className="rounded bg-emerald-500/20 border border-emerald-500/35 px-1.5 py-0.5 font-mono text-[9px] font-semibold text-emerald-300 shrink-0">
                        📊 .base
                      </span>
                    )}
                    {n.rel_path.endsWith('.canvas') && (
                      <span className="rounded bg-purple-500/20 border border-purple-500/35 px-1.5 py-0.5 font-mono text-[9px] font-semibold text-purple-200 shrink-0">
                        🎨 .canvas
                      </span>
                    )}
                    {n.rel_path.startsWith('04_Resources/Hermes/') && (
                      <span className="rounded bg-purple-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-purple-300 shrink-0">
                        🪽 Hermes
                      </span>
                    )}
                    {n.is_private && (
                      <span className="inline-flex items-center gap-0.5 rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-amber-300 shrink-0">
                        <Lock className="h-2.5 w-2.5" /> Local
                      </span>
                    )}
                  </span>
                  <span className="font-mono text-[10px] text-slate-400 truncate max-w-[220px]">
                    {n.rel_path}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-slate-800 bg-[#0F1726] px-4 py-2 text-[10px] text-slate-400">
          <span className="flex items-center gap-1">
            <Command className="h-3 w-3" /> Press `Ctrl + K` anywhere to toggle Quick Jump
          </span>
          <span>SQLite WAL + FTS5 + Hermes Continuity Index</span>
        </div>
      </div>
    </div>
  );
};

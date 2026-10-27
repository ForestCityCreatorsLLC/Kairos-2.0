import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Archive,
  ArchiveRestore,
  BookOpen,
  Bot,
  Calendar,
  ChartBar,
  ChartGantt,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  Clock,
  CornerDownRight,
  Database,
  Edit3,
  ExternalLink,
  Eye,
  FilePlus2,
  FileText,
  Filter,
  FolderPlus,
  Kanban,
  LayoutGrid,
  List,
  Plus,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Table2,
  X,
} from 'lucide-react';
import {
  ArchivedTaskSummary,
  CalendarEventItem,
  ProjectsSubView,
  ProjectTreeItem,
  RollupMetrics,
  STANDARD_DEPARTMENTS,
  TaskStatus,
  TaskSummary,
  VaultBaseQueryResult,
  VaultNoteDetail,
  VaultNoteSummary,
  kairosApi,
} from '../../api/client.ts';
import {
  ProjectScopeSelection,
  formatProjectDisplayName,
} from '../../components/LeftSidebar.tsx';
import { ToastKind } from '../../components/ToastCenter.tsx';
import { TaskDrawer } from './TaskDrawer.tsx';

const KANBAN_COLUMNS: TaskStatus[] = [
  'Backlog',
  'To Do',
  'In Progress',
  'Review',
  'Blocked',
  'Done',
];

const PRIORITY_BADGE: Record<number, { label: string; cls: string }> = {
  1: { label: 'P1 Urgent', cls: 'bg-rose-500/20 text-rose-300 border-rose-500/30' },
  2: { label: 'P2 High', cls: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
  3: { label: 'P3 Normal', cls: 'bg-sky-500/20 text-sky-300 border-sky-500/30' },
  4: { label: 'P4 Low', cls: 'bg-slate-700/40 text-slate-300 border-slate-600' },
};

const LIST_AI_AGENTS = [
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

const DEPT_EMOJI: Record<string, string> = {
  Software_Development: '💻',
  Marketing_and_Branding: '📣',
  Documentation: '📄',
  Website: '🌐',
  Merch: '👕',
};

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

type WikiTemplateKind = 'blank' | 'meeting' | 'spec' | 'playbook';

function toLocalIsoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function parseIsoDateLocal(iso: string): Date | null {
  const clean = (iso || '').trim().slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(clean)) return null;
  const [y, m, d] = clean.split('-').map(Number);
  return new Date(y, m - 1, d, 0, 0, 0, 0);
}

function addDays(base: Date, days: number): Date {
  const d = new Date(base);
  d.setDate(d.getDate() + days);
  return d;
}

function buildWikiTemplateBody(title: string, project: string, kind: WikiTemplateKind): string {
  const today = toLocalIsoDate(new Date());
  const projHuman = project.replace(/_/g, ' ');
  if (kind === 'meeting') {
    return [
      `# 📝 ${title}`,
      '',
      `> **Project:** [[02_Projects/${project}/_Project_Index|${projHuman}]] • **Date:** \`${today}\``,
      '',
      '## 🎯 Agenda & Context',
      '- ',
      '',
      '## ✅ Key Decisions Locked',
      '- ',
      '',
      '## 🚀 Action Items',
      '- [ ] ',
      '',
    ].join('\n');
  }
  if (kind === 'spec') {
    return [
      `# 🏗️ ${title}`,
      '',
      `> **Technical Specification** for [[02_Projects/${project}/_Project_Index|${projHuman}]]`,
      '',
      '## 1. Objective & Problem Statement',
      'Describe the feature or subsystem goal.',
      '',
      '## 2. Architecture & Data Flow',
      '- **Inputs:** ',
      '- **Processing:** ',
      '- **Vault / API Outputs:** ',
      '',
      '## 3. Verification Checklist',
      '- [ ] Unit / E2E tests passing',
      '- [ ] Canopy Vault synchronized',
      '',
    ].join('\n');
  }
  if (kind === 'playbook') {
    return [
      `# 📘 ${title}`,
      '',
      `> **Standard Operating Procedure (SOP)** — [[02_Projects/${project}/_Project_Index|${projHuman}]]`,
      '',
      '## ⚡ Trigger / When to Use',
      '- ',
      '',
      '## 🪜 Step-by-Step Procedure',
      '1. ',
      '2. ',
      '3. ',
      '',
      '## 🧠 Lessons & Edge Cases',
      '- ',
      '',
    ].join('\n');
  }
  return [
    `# 📄 ${title}`,
    '',
    `> Project Wiki Note for [[02_Projects/${project}/_Project_Index|${projHuman}]] (\`${today}\`)`,
    '',
    '## Overview',
    'Write project notes, research, links, or specs here...',
    '',
  ].join('\n');
}

export interface ProjectsExternalNavSignal {
  seq: number;
  view?: ProjectsSubView;
  openTaskId?: string | null;
  filterKeyword?: string;
  filterAgent?: string;
  filterPriority?: number;
}

interface ProjectsWorkspaceProps {
  scope: ProjectScopeSelection;
  projectsTree: ProjectTreeItem[];
  archivedProjects?: string[];
  onSelectScope: (scope: ProjectScopeSelection) => void;
  refreshTick: number;
  onVaultMutated: () => void;
  onOpenNoteInSecondBrain: (relPath: string) => void;
  onResetScope?: () => void;
  externalNavSignal?: ProjectsExternalNavSignal;
  onSubViewChange?: (view: ProjectsSubView) => void;
  onSelectedTaskChange?: (taskId: string | null) => void;
  onNotify?: (kind: ToastKind, title: string, detail?: string) => void;
}

export const ProjectsWorkspace: React.FC<ProjectsWorkspaceProps> = ({
  scope,
  projectsTree,
  archivedProjects = [],
  onSelectScope,
  refreshTick,
  onVaultMutated,
  onOpenNoteInSecondBrain,
  onResetScope,
  externalNavSignal,
  onSubViewChange,
  onSelectedTaskChange,
  onNotify,
}) => {
  // Default view is strictly 'rollup' first!
  const [subView, setSubView] = useState<ProjectsSubView>('rollup');
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [rollup, setRollup] = useState<RollupMetrics | null>(null);
  const [events, setEvents] = useState<CalendarEventItem[]>([]);
  const [projectDocs, setProjectDocs] = useState<VaultNoteSummary[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [archivedTasks, setArchivedTasks] = useState<ArchivedTaskSummary[]>([]);
  const [showNewModal, setShowNewModal] = useState(false);
  const [showAddCategoryModal, setShowAddCategoryModal] = useState(false);
  const [archiveBanner, setArchiveBanner] = useState('');
  const [resyncing, setResyncing] = useState(false);

  // Inline Projects Filter Bar state
  const [filterKeyword, setFilterKeyword] = useState('');
  const [filterAgent, setFilterAgent] = useState('ALL');
  const [filterPriority, setFilterPriority] = useState<number>(0);

  // Add Category Modal state
  const [catProject, setCatProject] = useState(scope.project || 'KAIROS_2_0');
  const [catName, setCatName] = useState('');
  const [catDefaultList, setCatDefaultList] = useState('General');

  // Calendar Monthly Grid state
  const todayDate = useMemo(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate());
  }, []);
  const todayIso = useMemo(() => toLocalIsoDate(todayDate), [todayDate]);
  const [calendarCursor, setCalendarCursor] = useState<Date>(
    () => new Date(new Date().getFullYear(), new Date().getMonth(), 1)
  );
  const [selectedDateIso, setSelectedDateIso] = useState<string>(() => toLocalIsoDate(new Date()));
  const [calComposerMode, setCalComposerMode] = useState<'task-block' | 'standalone'>('task-block');
  const [blockTaskId, setBlockTaskId] = useState('');
  const [calTimeStr, setCalTimeStr] = useState('10:00');
  const [calDurationHrs, setCalDurationHrs] = useState(1);
  const [standaloneEventTitle, setStandaloneEventTitle] = useState('');
  const [standaloneEventCategory, setStandaloneEventCategory] = useState('Business');
  const [standaloneEventNotes, setStandaloneEventNotes] = useState('');

  // Gantt Timeline state
  const [ganttRangeDays, setGanttRangeDays] = useState<14 | 30 | 60>(30);
  const [ganttOffsetDays, setGanttOffsetDays] = useState<number>(-5);

  // Documentation Wiki state
  const [selectedDocPath, setSelectedDocPath] = useState<string>('');
  const [activeDocDetail, setActiveDocDetail] = useState<VaultNoteDetail | null>(null);
  const [wikiDraftBody, setWikiDraftBody] = useState<string>('');
  const [wikiEditMode, setWikiEditMode] = useState<boolean>(false);
  const [wikiSearch, setWikiSearch] = useState<string>('');
  const [wikiSavedBanner, setWikiSavedBanner] = useState<string>('');
  const [showNewWikiModal, setShowNewWikiModal] = useState<'note' | 'canvas' | null>(null);
  const [newWikiTitle, setNewWikiTitle] = useState('');
  const [newWikiTemplate, setNewWikiTemplate] = useState<WikiTemplateKind>('blank');
  const [newWikiTargetProject, setNewWikiTargetProject] = useState(scope.project || 'KAIROS_2_0');
  const [newWikiCanvasCardText, setNewWikiCanvasCardText] = useState('');
  const [quickInsertTaskId, setQuickInsertTaskId] = useState('');
  const [projectBaseResult, setProjectBaseResult] = useState<VaultBaseQueryResult | null>(null);
  const [activeProjectBaseView, setActiveProjectBaseView] = useState<string>('');
  const [projectBaseLoading, setProjectBaseLoading] = useState<boolean>(false);

  const wikiDirty = Boolean(
    wikiEditMode && activeDocDetail && wikiDraftBody !== activeDocDetail.body
  );
  const wikiDirtyRef = useRef(false);
  wikiDirtyRef.current = wikiDirty;
  const loadedWikiPathRef = useRef('');

  const notifyMutationError = (fallbackTitle: string, err: unknown) => {
    const msg = err instanceof Error ? err.message : fallbackTitle;
    const isConflict = msg.includes('409') || msg.toLowerCase().includes('paperclip');
    onNotify?.(
      isConflict ? 'warning' : 'error',
      isConflict ? 'Paperclip Lock Conflict' : fallbackTitle,
      msg
    );
  };

  useEffect(() => {
    onSubViewChange?.(subView);
  }, [subView, onSubViewChange]);

  useEffect(() => {
    onSelectedTaskChange?.(selectedTaskId);
  }, [selectedTaskId, onSelectedTaskChange]);

  useEffect(() => {
    if (!externalNavSignal || externalNavSignal.seq === 0) return;
    if (externalNavSignal.view) {
      setSubView(externalNavSignal.view);
    }
    if (externalNavSignal.openTaskId !== undefined) {
      setSelectedTaskId(externalNavSignal.openTaskId);
    }
    if (externalNavSignal.filterKeyword !== undefined) {
      setFilterKeyword(externalNavSignal.filterKeyword);
    }
    if (externalNavSignal.filterAgent !== undefined) {
      setFilterAgent(externalNavSignal.filterAgent);
    }
    if (externalNavSignal.filterPriority !== undefined) {
      setFilterPriority(externalNavSignal.filterPriority);
    }
  }, [externalNavSignal?.seq]);

  // New Task Modal state
  const [newTitle, setNewTitle] = useState('');
  const [newProject, setNewProject] = useState(scope.project || 'KAIROS_2_0');
  const [newDepartment, setNewDepartment] = useState(scope.department || 'Software_Development');
  const [useCustomTaskCategory, setUseCustomTaskCategory] = useState(false);
  const [newList, setNewList] = useState(scope.list || 'Sprint_01');
  const [newPriority, setNewPriority] = useState(2);
  const [newStart, setNewStart] = useState(todayIso);
  const [newDue, setNewDue] = useState('');
  const [newAgent, setNewAgent] = useState('None');
  const [newParentTask, setNewParentTask] = useState('');
  const [newDependsOn, setNewDependsOn] = useState('');
  const [newTimeEstimate, setNewTimeEstimate] = useState(2);

  // Quick-Add state for `2. List` and `3. Board`
  const [quickListTitle, setQuickListTitle] = useState('');
  const [quickListPriority, setQuickListPriority] = useState<number>(2);
  const [quickListAgent, setQuickListAgent] = useState<string>('None');
  const [quickBoardCol, setQuickBoardCol] = useState<TaskStatus | null>(null);
  const [quickBoardTitle, setQuickBoardTitle] = useState('');

  const reloadData = async () => {
    const [res, archTasksRes] = await Promise.all([
      kairosApi.listTasks({
        project: scope.project,
        department: scope.department,
        list_name: scope.list,
      }),
      kairosApi.getArchivedTasks(scope.project).catch(() => ({ archived_tasks: [] })),
    ]);
    setTasks(res.tasks);
    setRollup(res.rollup);
    setArchivedTasks(archTasksRes.archived_tasks);
    setBlockTaskId((prev) =>
      res.tasks.length > 0
        ? prev && res.tasks.some((t) => t.id === prev)
          ? prev
          : res.tasks[0].id
        : ''
    );

    if (subView === 'calendar') {
      const cal = await kairosApi.getCalendarEvents();
      setEvents(cal.events);
    }
    if (subView === 'docs') {
      const folderFilter = scope.project ? `02_Projects/${scope.project}` : '02_Projects';
      const docsRes = await kairosApi.searchNotes('', folderFilter);
      const nonTasks = docsRes.notes.filter(
        (n) => n.type !== 'task' && n.type !== 'subtask' && !n.rel_path.includes('/Tasks/TSK-')
      );
      setProjectDocs(nonTasks);
      if (nonTasks.length > 0) {
        const stillExists = nonTasks.some((d) => d.rel_path === selectedDocPath);
        if (!selectedDocPath || !stillExists) {
          const preferred =
            nonTasks.find((d) => d.rel_path.endsWith('_Project_Index.md')) || nonTasks[0];
          setSelectedDocPath(preferred.rel_path);
        }
      } else {
        setSelectedDocPath('');
        setActiveDocDetail(null);
      }
    }
  };

  useEffect(() => {
    const dept = scope.department || 'Software_Development';
    const std = STANDARD_DEPARTMENTS.find((d) => d.id === dept);
    const fallbackProj = scope.project || projectsTree[0]?.name || 'KAIROS_2_0';
    setNewProject(fallbackProj);
    setCatProject(fallbackProj);
    setNewWikiTargetProject(fallbackProj);
    setNewDepartment(dept);
    setNewList(scope.list || std?.defaultList || 'Sprint_01');
  }, [scope, projectsTree]);

  useEffect(() => {
    reloadData().catch(() => {});
  }, [scope, subView, refreshTick]);

  // Load selected Wiki document whenever `selectedDocPath` changes in Documentation view
  useEffect(() => {
    if (subView !== 'docs' || !selectedDocPath) return;
    let cancelled = false;
    kairosApi
      .readNote(selectedDocPath)
      .then((d) => {
        if (cancelled) return;
        const sameDoc = loadedWikiPathRef.current === d.rel_path;
        loadedWikiPathRef.current = d.rel_path;
        setActiveDocDetail(d);
        if (!sameDoc || !wikiDirtyRef.current) {
          setWikiDraftBody(d.body);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [subView, selectedDocPath, refreshTick]);

  useEffect(() => {
    setActiveProjectBaseView('');
  }, [selectedDocPath]);

  useEffect(() => {
    if (
      subView !== 'docs' ||
      !selectedDocPath ||
      !selectedDocPath.toLowerCase().endsWith('.base')
    ) {
      setProjectBaseResult(null);
      return;
    }
    let cancelled = false;
    setProjectBaseLoading(true);
    kairosApi
      .queryVaultBase(selectedDocPath, activeProjectBaseView)
      .then((res) => {
        if (!cancelled) setProjectBaseResult(res);
      })
      .catch(() => {
        if (!cancelled) setProjectBaseResult(null);
      })
      .finally(() => {
        if (!cancelled) setProjectBaseLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [subView, selectedDocPath, activeProjectBaseView, refreshTick]);

  const activeProjectNode = useMemo(
    () => projectsTree.find((p) => p.name === scope.project) || null,
    [projectsTree, scope.project]
  );

  // Merge standard departments + any custom categories found on the target project
  const availableCategoriesForModal = useMemo(() => {
    const map = new Map<string, { id: string; label: string; defaultList: string; emoji: string }>();
    for (const d of STANDARD_DEPARTMENTS) {
      map.set(d.id, { id: d.id, label: d.label, defaultList: d.defaultList, emoji: d.emoji });
    }
    const targetNode = projectsTree.find((p) => p.name === newProject);
    if (targetNode) {
      for (const custom of targetNode.departments) {
        if (!map.has(custom.name)) {
          map.set(custom.name, {
            id: custom.name,
            label: custom.name.replace(/_/g, ' '),
            defaultList: custom.lists[0]?.name || 'General',
            emoji: DEPT_EMOJI[custom.name] || '📂',
          });
        }
      }
    }
    return Array.from(map.values());
  }, [projectsTree, newProject]);

  const visibleTasks = useMemo(() => {
    const kw = filterKeyword.trim().toLowerCase();
    return tasks.filter((t) => {
      if (
        kw &&
        !t.title.toLowerCase().includes(kw) &&
        !t.id.toLowerCase().includes(kw) &&
        !t.project.toLowerCase().includes(kw) &&
        !t.department.toLowerCase().includes(kw) &&
        !t.tags.some((tg) => tg.toLowerCase().includes(kw))
      ) {
        return false;
      }
      if (filterAgent !== 'ALL' && t.ai_agent !== filterAgent) {
        return false;
      }
      if (filterPriority > 0 && t.priority !== filterPriority) {
        return false;
      }
      return true;
    });
  }, [tasks, filterKeyword, filterAgent, filterPriority]);

  const handleResyncProjects = async () => {
    setResyncing(true);
    try {
      await kairosApi.resyncProjects();
      onVaultMutated();
      await reloadData();
    } catch (err) {
      notifyMutationError('Vault Resync Failed', err);
    } finally {
      setResyncing(false);
    }
  };

  const handleRestoreArchivedProject = async (archiveName: string) => {
    if (!archiveName) return;
    try {
      const res = await kairosApi.unarchiveProject(archiveName);
      setArchiveBanner(`Restored project '${res.project}' back into 02_Projects/`);
      window.setTimeout(() => setArchiveBanner(''), 4500);
      onVaultMutated();
      onSelectScope({ project: res.project, department: '', list: '' });
    } catch (err) {
      notifyMutationError('Restore Archived Project Failed', err);
    }
  };

  const handleRestoreArchivedTask = async (taskId: string) => {
    if (!taskId) return;
    try {
      const restored = await kairosApi.restoreTask(taskId);
      setArchiveBanner(`Restored task '${taskId}' (${restored.title}) to ${restored.rel_path}`);
      window.setTimeout(() => setArchiveBanner(''), 4500);
      onNotify?.('success', `Restored ${taskId}`, restored.rel_path);
      onVaultMutated();
      await reloadData();
    } catch (err) {
      notifyMutationError('Restore Archived Task Failed', err);
    }
  };

  const handleAddCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    const targetProj = (catProject || scope.project || 'KAIROS_2_0').trim();
    const cleanCat = catName.trim().replace(/\s+/g, '_');
    const cleanList = catDefaultList.trim().replace(/\s+/g, '_') || 'General';
    if (!targetProj || !cleanCat) return;

    try {
      const created = await kairosApi.createProjectStructure(targetProj, cleanCat, cleanList, false);
      setCatName('');
      setShowAddCategoryModal(false);
      setArchiveBanner(
        `Added category '${created.department.replace(/_/g, ' ')}' (${created.list}) to ${created.project}`
      );
      window.setTimeout(() => setArchiveBanner(''), 4000);
      onVaultMutated();
      onSelectScope({
        project: created.project,
        department: created.department,
        list: '',
      });
    } catch (err) {
      notifyMutationError('Add Category Failed', err);
    }
  };

  const handleDropStatus = async (taskId: string, newStatus: TaskStatus) => {
    setTasks((prev) => prev.map((t) => (t.id === taskId ? { ...t, status: newStatus } : t)));
    try {
      await kairosApi.updateTask(taskId, { status: newStatus });
      onVaultMutated();
    } catch (err) {
      notifyMutationError('Status Update Blocked', err);
    } finally {
      reloadData().catch(() => {});
    }
  };

  const handleInlinePatchTask = async (
    taskId: string,
    patch: { priority?: number; ai_agent?: string }
  ) => {
    setTasks((prev) => prev.map((t) => (t.id === taskId ? { ...t, ...patch } : t)));
    try {
      await kairosApi.updateTask(taskId, patch);
      onVaultMutated();
    } catch (err) {
      notifyMutationError('Task Edit Blocked', err);
    } finally {
      reloadData().catch(() => {});
    }
  };

  const handleQuickCreateListTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!quickListTitle.trim()) return;
    try {
      await kairosApi.createTask({
        title: quickListTitle.trim(),
        project: newProject,
        department: newDepartment.trim().replace(/\s+/g, '_') || 'Software_Development',
        list: newList,
        status: 'To Do',
        priority: quickListPriority,
        ai_agent: quickListAgent,
        start_date: todayIso,
        time_estimate_hrs: 2,
      });
      setQuickListTitle('');
      onVaultMutated();
      reloadData().catch(() => {});
    } catch (err) {
      notifyMutationError('Quick Add Task Failed', err);
    }
  };

  const handleQuickCreateBoardTask = async (e: React.FormEvent, colStatus: TaskStatus) => {
    e.preventDefault();
    if (!quickBoardTitle.trim()) return;
    try {
      await kairosApi.createTask({
        title: quickBoardTitle.trim(),
        project: newProject,
        department: newDepartment.trim().replace(/\s+/g, '_') || 'Software_Development',
        list: newList,
        status: colStatus,
        priority: 2,
        start_date: todayIso,
        time_estimate_hrs: 2,
      });
      setQuickBoardTitle('');
      setQuickBoardCol(null);
      onVaultMutated();
      reloadData().catch(() => {});
    } catch (err) {
      notifyMutationError('Board Task Create Failed', err);
    }
  };

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    const cleanDept = newDepartment.trim().replace(/\s+/g, '_') || 'Software_Development';
    try {
      await kairosApi.createTask({
        title: newTitle.trim(),
        project: newProject,
        department: cleanDept,
        list: newList,
        priority: newPriority,
        start_date: newStart,
        due_date: newDue,
        ai_agent: newAgent,
        parent_task: newParentTask ? `[[${newParentTask}]]` : '',
        depends_on: newDependsOn ? [`[[${newDependsOn}]]`] : [],
        time_estimate_hrs: Number(newTimeEstimate) || 1,
      });
      setNewTitle('');
      setNewParentTask('');
      setNewDependsOn('');
      setUseCustomTaskCategory(false);
      setShowNewModal(false);
      onVaultMutated();
      reloadData().catch(() => {});
    } catch (err) {
      notifyMutationError('Create Task Failed', err);
    }
  };

  const handleArchiveProjectOrDept = async () => {
    if (!scope.project) return;
    const label = scope.department ? `${scope.project}/${scope.department}` : scope.project;
    const confirmed = window.confirm(
      `Move '${label}' into 05_Archives/? (You can restore archived projects anytime from the toolbar.)`
    );
    if (!confirmed) return;
    try {
      const res = await kairosApi.archiveProject(scope.project, scope.department);
      setArchiveBanner(`Archived ${label} → ${res.archived_rel}`);
      window.setTimeout(() => setArchiveBanner(''), 4000);
      onResetScope?.();
      onVaultMutated();
    } catch (err) {
      notifyMutationError('Archive Project Failed', err);
    }
  };

  const handleCalendarSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const startIso = `${selectedDateIso}T${calTimeStr || '10:00'}:00`;
    try {
      if (calComposerMode === 'task-block') {
        if (!blockTaskId) return;
        await kairosApi.timeBlockTask(
          blockTaskId,
          startIso,
          Number(calDurationHrs) || 1,
          standaloneEventCategory
        );
      } else {
        if (!standaloneEventTitle.trim()) return;
        await kairosApi.createCalendarEvent({
          title: standaloneEventTitle.trim(),
          start_time_iso: startIso,
          duration_hrs: Number(calDurationHrs) || 1,
          category: standaloneEventCategory,
          project: scope.project || '',
          notes: standaloneEventNotes.trim(),
        });
        setStandaloneEventTitle('');
        setStandaloneEventNotes('');
      }
      const cal = await kairosApi.getCalendarEvents();
      setEvents(cal.events);
      onVaultMutated();
    } catch (err) {
      notifyMutationError('Calendar Schedule Failed', err);
    }
  };

  const handleSaveWikiDoc = async () => {
    if (!activeDocDetail) return;
    try {
      const updated = await kairosApi.writeNote(
        activeDocDetail.rel_path,
        {
          ...activeDocDetail.frontmatter,
          updated_at: new Date().toISOString().slice(0, 19),
        },
        wikiDraftBody,
        'overwrite'
      );
      setActiveDocDetail(updated);
      setWikiDraftBody(updated.body);
      wikiDirtyRef.current = false;
      setWikiEditMode(false);
      setWikiSavedBanner(`Saved ${updated.rel_path}`);
      window.setTimeout(() => setWikiSavedBanner(''), 3000);
      onVaultMutated();
      reloadData().catch(() => {});
    } catch (err) {
      notifyMutationError('Save Wiki Page Failed', err);
    }
  };

  const handleRetainWikiInHermes = async () => {
    if (!activeDocDetail) return;
    try {
      const prefix = activeDocDetail.is_private ? '[#private] ' : '';
      const snippet = activeDocDetail.body
        .replace(/^#+\s+/gm, '')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 260);
      const fact = `${prefix}[Project Wiki: ${activeDocDetail.title}] ${snippet}`;
      const res = await kairosApi.retainHermesMemory({
        fact,
        target: 'memory',
        is_private: Boolean(activeDocDetail.is_private),
      });
      setWikiSavedBanner(`Retained summary in Hermes (${res.rel_path})`);
      window.setTimeout(() => setWikiSavedBanner(''), 3500);
      onVaultMutated();
    } catch (err) {
      notifyMutationError('Hermes Retain Failed', err);
    }
  };

  const handleDistillWikiAsHermesSkill = async () => {
    if (!activeDocDetail) return;
    try {
      const inferredProj =
        scope.project ||
        String(activeDocDetail.frontmatter?.project || '')
          .replace(/^\[\[/, '')
          .replace(/\]\]$/, '')
          .trim() ||
        'KAIROS_2_0';
      const created = await kairosApi.createHermesSkill({
        title: activeDocDetail.title,
        category: 'Project_Wiki',
        trigger: `When working on ${inferredProj.replace(/_/g, ' ')} or referencing ${activeDocDetail.title}`,
        steps_markdown: (wikiEditMode ? wikiDraftBody : activeDocDetail.body).slice(0, 3500),
        project: inferredProj,
        is_private: Boolean(activeDocDetail.is_private),
      });
      setWikiSavedBanner(`Distilled Hermes Skill ${created.skill_id}`);
      window.setTimeout(() => setWikiSavedBanner(''), 4000);
      onVaultMutated();
    } catch (err) {
      notifyMutationError('Skill Distillation Failed', err);
    }
  };

  const handleCreateProjectTasksBase = async () => {
    const targetProj = scope.project || projectsTree[0]?.name || 'KAIROS_2_0';
    try {
      const res = await kairosApi.createProjectTasksBase(targetProj);
      setWikiSavedBanner(`Generated Obsidian .base (${res.base_rel_path})`);
      window.setTimeout(() => setWikiSavedBanner(''), 3500);
      onVaultMutated();
      await reloadData();
      setSelectedDocPath(res.base_rel_path);
      setWikiEditMode(false);
      onNotify?.('success', 'Project Tasks .base Ready', res.base_rel_path);
    } catch (err) {
      notifyMutationError('Create Project .base Failed', err);
    }
  };

  const handleCalendarDropTask = async (taskId: string, targetDateIso: string) => {
    if (!taskId || !targetDateIso) return;
    const existing = tasks.find((t) => t.id === taskId);
    const nextStart =
      existing?.start_date && existing.start_date <= targetDateIso
        ? existing.start_date
        : targetDateIso;
    setSelectedDateIso(targetDateIso);
    try {
      await kairosApi.updateTask(taskId, {
        start_date: nextStart,
        due_date: targetDateIso,
        log_entry: `Scheduled onto Monthly Calendar date ${targetDateIso}`,
      });
      setArchiveBanner(`Scheduled ${taskId} onto ${targetDateIso}`);
      window.setTimeout(() => setArchiveBanner(''), 3500);
      onVaultMutated();
    } catch (err) {
      notifyMutationError('Calendar Reschedule Blocked', err);
    } finally {
      reloadData().catch(() => {});
    }
  };

  const handleShiftTaskDates = async (
    e: React.MouseEvent,
    task: TaskSummary,
    deltaDays: number
  ) => {
    e.stopPropagation();
    const baseStart = parseIsoDateLocal(task.start_date) || parseIsoDateLocal(task.due_date) || todayDate;
    const baseDue =
      parseIsoDateLocal(task.due_date) ||
      addDays(baseStart, Math.max(0, Math.ceil((task.time_estimate_hrs || 2) / 4) - 1));
    const shiftedStart = toLocalIsoDate(addDays(baseStart, deltaDays));
    const shiftedDue = toLocalIsoDate(addDays(baseDue, deltaDays));
    try {
      await kairosApi.updateTask(task.id, {
        start_date: shiftedStart,
        due_date: shiftedDue,
      });
      onVaultMutated();
    } catch (err) {
      notifyMutationError('Gantt Shift Blocked', err);
    } finally {
      reloadData().catch(() => {});
    }
  };

  const handleAnchorTaskToday = async (e: React.MouseEvent, task: TaskSummary) => {
    e.stopPropagation();
    const spanDays = Math.max(0, Math.ceil((task.time_estimate_hrs || 2) / 4) - 1);
    const dueIso = toLocalIsoDate(addDays(todayDate, spanDays));
    try {
      await kairosApi.updateTask(task.id, {
        start_date: todayIso,
        due_date: dueIso,
        log_entry: `Anchored onto Gantt timeline starting ${todayIso}`,
      });
      setArchiveBanner(`Scheduled ${task.id} (${todayIso} → ${dueIso})`);
      window.setTimeout(() => setArchiveBanner(''), 3200);
      onVaultMutated();
    } catch (err) {
      notifyMutationError('Gantt Schedule Blocked', err);
    } finally {
      reloadData().catch(() => {});
    }
  };

  const handleCalendarDropEvent = async (eventId: string, targetDateIso: string) => {
    if (!eventId || !targetDateIso) return;
    setSelectedDateIso(targetDateIso);
    try {
      await kairosApi.updateCalendarEvent(eventId, { new_date_iso: targetDateIso });
      setArchiveBanner(`Moved calendar event ${eventId} to ${targetDateIso}`);
      window.setTimeout(() => setArchiveBanner(''), 3200);
      onVaultMutated();
      reloadData().catch(() => {});
    } catch (err) {
      notifyMutationError('Calendar Event Move Failed', err);
    }
  };

  const handleDeleteCalendarEvent = async (e: React.MouseEvent, eventId: string) => {
    e.stopPropagation();
    try {
      await kairosApi.deleteCalendarEvent(eventId);
      setArchiveBanner(`Removed calendar event ${eventId}`);
      window.setTimeout(() => setArchiveBanner(''), 3000);
      onVaultMutated();
      reloadData().catch(() => {});
    } catch (err) {
      notifyMutationError('Calendar Event Delete Failed', err);
    }
  };

  const handleAddWikiCanvasNode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeDocDetail || !parsedCanvasPreview || !newWikiCanvasCardText.trim()) return;
    try {
      const curNodes = parsedCanvasPreview.nodes || [];
      const nextNode = {
        id: `node_${Date.now()}`,
        type: 'text',
        x: (curNodes.length % 3) * 320 + 40,
        y: Math.floor(curNodes.length / 3) * 180 + 80,
        width: 280,
        height: 140,
        text: newWikiCanvasCardText.trim(),
      };
      const updatedJson = JSON.stringify(
        {
          ...parsedCanvasPreview,
          nodes: [...curNodes, nextNode],
          edges: parsedCanvasPreview.edges || [],
        },
        null,
        2
      );
      const saved = await kairosApi.writeNote(activeDocDetail.rel_path, {}, updatedJson, 'overwrite');
      setActiveDocDetail(saved);
      setWikiDraftBody(saved.body);
      setNewWikiCanvasCardText('');
      setWikiSavedBanner('Added Canvas card');
      window.setTimeout(() => setWikiSavedBanner(''), 2500);
      onVaultMutated();
    } catch (err) {
      notifyMutationError('Canvas Card Add Failed', err);
    }
  };

  const handleRemoveWikiCanvasNode = async (nodeId: string) => {
    if (!activeDocDetail || !parsedCanvasPreview) return;
    try {
      const nextNodes = (parsedCanvasPreview.nodes || []).filter((n) => n.id !== nodeId);
      const nextEdges = (parsedCanvasPreview.edges || []).filter(
        (ed) => ed.fromNode !== nodeId && ed.toNode !== nodeId
      );
      const updatedJson = JSON.stringify(
        {
          ...parsedCanvasPreview,
          nodes: nextNodes,
          edges: nextEdges,
        },
        null,
        2
      );
      const saved = await kairosApi.writeNote(activeDocDetail.rel_path, {}, updatedJson, 'overwrite');
      setActiveDocDetail(saved);
      setWikiDraftBody(saved.body);
      onVaultMutated();
    } catch (err) {
      notifyMutationError('Canvas Card Remove Failed', err);
    }
  };

  const handleOpenWikiLinkTarget = (rawTarget: string) => {
    const clean = rawTarget.split('|')[0].trim();
    if (/^TSK-[\w-]+$/i.test(clean)) {
      setSelectedTaskId(clean.toUpperCase());
      return;
    }
    const matchingWiki = projectDocs.find(
      (d) =>
        d.rel_path === clean ||
        d.rel_path === `${clean}.md` ||
        d.rel_path.endsWith(`/${clean}.md`) ||
        d.title.toLowerCase() === clean.replace(/_/g, ' ').toLowerCase()
    );
    if (matchingWiki) {
      setSelectedDocPath(matchingWiki.rel_path);
      setWikiEditMode(false);
      return;
    }
    const withExt = clean.endsWith('.md') || clean.endsWith('.canvas') ? clean : `${clean}.md`;
    onOpenNoteInSecondBrain(withExt);
  };

  const renderInlineWikiTokens = (lineText: string) => {
    const tokenRe = /(\[\[[^\]]+\]\]|\bTSK-\d{8}-\d{3}\b)/g;
    const parts = lineText.split(tokenRe);
    return parts.map((part, idx) => {
      if (part.startsWith('[[') && part.endsWith(']]')) {
        const inner = part.slice(2, -2);
        const label = inner.includes('|') ? inner.split('|')[1] : inner.split('/').pop() || inner;
        return (
          <button
            key={idx}
            type="button"
            onClick={() => handleOpenWikiLinkTarget(inner)}
            className="mx-0.5 inline-flex items-center rounded border border-cyan-500/40 bg-cyan-500/15 px-1.5 py-0.2 font-mono text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25"
          >
            [[{label}]]
          </button>
        );
      }
      if (/^TSK-\d{8}-\d{3}$/.test(part)) {
        return (
          <button
            key={idx}
            type="button"
            onClick={() => setSelectedTaskId(part)}
            className="mx-0.5 inline-flex items-center rounded border border-emerald-500/40 bg-emerald-500/15 px-1.5 py-0.2 font-mono text-[11px] font-semibold text-emerald-300 hover:bg-emerald-500/25"
          >
            {part}
          </button>
        );
      }
      return <React.Fragment key={idx}>{part}</React.Fragment>;
    });
  };

  const renderRichWikiBody = (md: string) => {
    const blocks = (md || '').split(/\n\n+/);
    return blocks.map((blk, i) => {
      const mCallout = blk.match(
        /^>\s*\[!(IMPORTANT|NOTE|TIP|WARNING|CAUTION)\]\s*(.*)\n?([\s\S]*)/i
      );
      if (mCallout) {
        const kind = mCallout[1].toUpperCase();
        const title = mCallout[2] || kind;
        const rest = mCallout[3].replace(/^>\s?/gm, '');
        const style =
          kind === 'IMPORTANT'
            ? 'border-purple-500/50 bg-purple-500/10 text-purple-200'
            : kind === 'WARNING' || kind === 'CAUTION'
              ? 'border-amber-500/50 bg-amber-500/10 text-amber-200'
              : 'border-cyan-500/50 bg-cyan-500/10 text-cyan-200';
        return (
          <div key={i} className={`rounded-xl border-l-4 p-3 text-xs space-y-1 ${style}`}>
            <div className="font-bold">
              [{kind}] {title}
            </div>
            {rest && (
              <div className="whitespace-pre-wrap text-slate-200">
                {renderInlineWikiTokens(rest)}
              </div>
            )}
          </div>
        );
      }
      return (
        <div key={i} className="whitespace-pre-wrap text-xs leading-relaxed text-slate-200">
          {renderInlineWikiTokens(blk)}
        </div>
      );
    });
  };

  const handleCreateWikiItem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newWikiTitle.trim() || !showNewWikiModal) return;
    const targetProj = (newWikiTargetProject || scope.project || projectsTree[0]?.name || 'KAIROS_2_0').trim();
    const slug = newWikiTitle
      .trim()
      .replace(/[^A-Za-z0-9_\- ]+/g, '')
      .trim()
      .replace(/\s+/g, '_');

    const docsFolder = scope.department
      ? `02_Projects/${targetProj}/${scope.department}/Docs`
      : `02_Projects/${targetProj}/Docs`;

    try {
      if (showNewWikiModal === 'canvas') {
        const rel = `${docsFolder}/${slug || 'Project_Canvas'}.canvas`;
        const canvasJson = JSON.stringify(
          {
            nodes: [
              {
                id: 'root',
                type: 'text',
                x: 40,
                y: 80,
                width: 340,
                height: 150,
                text: `# 🎨 ${newWikiTitle.trim()}\n\nProject: **${targetProj.replace(/_/g, ' ')}**\nVisual Architecture & Brainstorm Canvas`,
              },
              {
                id: 'next-steps',
                type: 'text',
                x: 460,
                y: 80,
                width: 320,
                height: 150,
                text: '## 🚀 Key Milestones\n- Define architecture\n- Link tasks & specs\n- Distill Hermes skills',
              },
            ],
            edges: [
              {
                id: 'edge-1',
                fromNode: 'root',
                fromSide: 'right',
                toNode: 'next-steps',
                toSide: 'left',
              },
            ],
          },
          null,
          2
        );
        const saved = await kairosApi.writeNote(rel, {}, canvasJson, 'overwrite');
        setShowNewWikiModal(null);
        setNewWikiTitle('');
        onVaultMutated();
        await reloadData();
        setSelectedDocPath(saved.rel_path);
        return;
      }

      const rel = `${docsFolder}/${slug || 'Wiki_Note'}.md`;
      const body = buildWikiTemplateBody(newWikiTitle.trim(), targetProj, newWikiTemplate);
      const saved = await kairosApi.writeNote(
        rel,
        {
          title: newWikiTitle.trim(),
          type: 'project_wiki',
          project: `[[${targetProj}]]`,
          department: scope.department || 'General',
          updated_at: new Date().toISOString().slice(0, 19),
          tags: ['project-wiki', targetProj.toLowerCase()],
        },
        body,
        'overwrite'
      );
      setShowNewWikiModal(null);
      setNewWikiTitle('');
      onVaultMutated();
      await reloadData();
      setSelectedDocPath(saved.rel_path);
      setWikiEditMode(true);
    } catch (err) {
      notifyMutationError('Create Wiki Page Failed', err);
    }
  };

  // Monthly Calendar Grid computation (35 or 42 cells)
  const calendarCells = useMemo(() => {
    const year = calendarCursor.getFullYear();
    const month = calendarCursor.getMonth();
    const firstOfMonth = new Date(year, month, 1);
    const startOffset = firstOfMonth.getDay();
    const gridStart = addDays(firstOfMonth, -startOffset);
    const lastOfMonth = new Date(year, month + 1, 0);
    const totalDaysNeeded = startOffset + lastOfMonth.getDate();
    const cellCount = totalDaysNeeded <= 35 ? 35 : 42;

    return Array.from({ length: cellCount }).map((_, idx) => {
      const dateObj = addDays(gridStart, idx);
      const iso = toLocalIsoDate(dateObj);
      const inCurrentMonth = dateObj.getMonth() === month;
      const dayEvents = events.filter((ev) => {
        const evDay = (ev.start_time || '').slice(0, 10);
        if (evDay !== iso) return false;
        if (scope.project && ev.linked_project && ev.linked_project !== scope.project) {
          return false;
        }
        return true;
      });
      const dayTasks = visibleTasks.filter(
        (t) => t.due_date === iso || (!t.due_date && t.start_date === iso)
      );
      return {
        dateObj,
        iso,
        dayNum: dateObj.getDate(),
        inCurrentMonth,
        isToday: iso === todayIso,
        dayEvents,
        dayTasks,
      };
    });
  }, [calendarCursor, events, visibleTasks, scope.project, todayIso]);

  const selectedDayData = useMemo(() => {
    const cell = calendarCells.find((c) => c.iso === selectedDateIso);
    if (cell) return cell;
    return {
      iso: selectedDateIso,
      dayEvents: events.filter((ev) => (ev.start_time || '').slice(0, 10) === selectedDateIso),
      dayTasks: visibleTasks.filter(
        (t) => t.due_date === selectedDateIso || t.start_date === selectedDateIso
      ),
    };
  }, [calendarCells, selectedDateIso, events, visibleTasks]);

  // Gantt Timeline Ruler & `TODAY` Dateline computation
  const ganttTimeline = useMemo(() => {
    const windowStart = addDays(todayDate, ganttOffsetDays);
    const days = Array.from({ length: ganttRangeDays }).map((_, i) => {
      const d = addDays(windowStart, i);
      const iso = toLocalIsoDate(d);
      return {
        date: d,
        iso,
        dayNum: d.getDate(),
        dow: WEEKDAYS[d.getDay()].slice(0, 2),
        isWeekend: d.getDay() === 0 || d.getDay() === 6,
        isToday: iso === todayIso,
        monthLabel: d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' }),
      };
    });

    const monthGroups: { label: string; span: number }[] = [];
    for (const day of days) {
      const last = monthGroups[monthGroups.length - 1];
      if (last && last.label === day.monthLabel) {
        last.span += 1;
      } else {
        monthGroups.push({ label: day.monthLabel, span: 1 });
      }
    }

    const todayIdx = days.findIndex((d) => d.isToday);
    const todayPct =
      todayIdx >= 0 ? ((todayIdx + 0.5) / Math.max(1, ganttRangeDays)) * 100 : null;

    return {
      windowStart,
      windowEnd: addDays(windowStart, ganttRangeDays - 1),
      days,
      monthGroups,
      todayPct,
    };
  }, [todayDate, todayIso, ganttOffsetDays, ganttRangeDays]);

  const filteredWikiDocs = useMemo(() => {
    const q = wikiSearch.trim().toLowerCase();
    return projectDocs.filter((d) => {
      if (!q) return true;
      return (
        d.title.toLowerCase().includes(q) ||
        d.rel_path.toLowerCase().includes(q) ||
        d.excerpt.toLowerCase().includes(q)
      );
    });
  }, [projectDocs, wikiSearch]);

  const parsedCanvasPreview = useMemo(() => {
    if (!activeDocDetail || !activeDocDetail.rel_path.endsWith('.canvas')) return null;
    try {
      const parsed = JSON.parse(activeDocDetail.body) as {
        nodes?: { id: string; text?: string; file?: string; type?: string }[];
        edges?: { id?: string; fromNode: string; toNode: string }[];
      };
      return parsed;
    } catch {
      return null;
    }
  }, [activeDocDetail]);

  const formatParentBadge = (rawParent: string) => rawParent.replace(/^\[\[|\]\]$/g, '');

  const breadcrumb = [
    scope.project || 'Everything (All Projects)',
    scope.department,
    scope.list,
  ]
    .filter(Boolean)
    .join('  /  ');

  return (
    <div className="flex-1 flex flex-col min-w-0 w-full bg-kairos-bg overflow-hidden">
      {/* Projects Sub-Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-kairos-border bg-kairos-panel/70 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div>
            <div className="text-sm font-bold text-white flex items-center gap-2">
              <span>{formatProjectDisplayName(breadcrumb)}</span>
              <button
                type="button"
                onClick={handleResyncProjects}
                disabled={resyncing}
                title="Resync Projects & Tasks from Canopy Vault"
                className="inline-flex items-center gap-1 rounded border border-kairos-border bg-kairos-card px-2 py-0.5 text-[10px] font-medium text-slate-300 hover:border-emerald-500/40 hover:text-emerald-300"
              >
                <RefreshCw className={`h-2.5 w-2.5 ${resyncing ? 'animate-spin' : ''}`} />
                Resync
              </button>
            </div>
            <div className="text-[11px] text-slate-400">
              {rollup
                ? `${rollup.total_tasks} Tasks • ${rollup.progress_pct}% Complete • ${rollup.time_logged_hrs}h / ${rollup.time_estimate_hrs}h`
                : 'Obsidian YAML-Backed Projects Engine'}
            </div>
          </div>
        </div>

        {/* 6 Projects View Switcher — Strictly Ordered: Rollup -> List -> Board -> Calendar -> Gantt -> Documentation */}
        <div className="flex items-center gap-1 rounded-lg border border-kairos-border bg-kairos-bg p-1 text-xs">
          {(
            [
              { id: 'rollup', label: 'Rollup', icon: <ChartBar className="h-3.5 w-3.5" /> },
              { id: 'list', label: 'List', icon: <List className="h-3.5 w-3.5" /> },
              { id: 'board', label: 'Board', icon: <Kanban className="h-3.5 w-3.5" /> },
              { id: 'calendar', label: 'Calendar', icon: <Calendar className="h-3.5 w-3.5" /> },
              { id: 'gantt', label: 'Gantt', icon: <ChartGantt className="h-3.5 w-3.5" /> },
              { id: 'docs', label: 'Documentation', icon: <BookOpen className="h-3.5 w-3.5" /> },
            ] as { id: ProjectsSubView; label: string; icon: React.ReactNode }[]
          ).map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => setSubView(v.id)}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium transition ${
                subView === v.id
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {v.icon}
              <span>{v.label}</span>
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          {archivedProjects.length > 0 && (
            <div className="flex items-center gap-1 rounded-lg border border-cyan-500/35 bg-cyan-500/10 px-2 py-1 text-xs text-cyan-200">
              <ArchiveRestore className="h-3.5 w-3.5 text-cyan-300" />
              <select
                value=""
                onChange={(e) => {
                  if (e.target.value) handleRestoreArchivedProject(e.target.value);
                }}
                className="bg-transparent text-xs text-cyan-200 focus:outline-none cursor-pointer"
              >
                <option value="" className="bg-slate-900">
                  Restore Archived ({archivedProjects.length})
                </option>
                {archivedProjects.map((ap) => (
                  <option key={ap} value={ap} className="bg-slate-900">
                    Restore {ap}
                  </option>
                ))}
              </select>
            </div>
          )}

          {archivedTasks.length > 0 && (
            <div className="flex items-center gap-1 rounded-lg border border-purple-500/35 bg-purple-500/10 px-2 py-1 text-xs text-purple-200">
              <ArchiveRestore className="h-3.5 w-3.5 text-purple-300" />
              <select
                value=""
                onChange={(e) => {
                  if (e.target.value) handleRestoreArchivedTask(e.target.value);
                }}
                className="bg-transparent text-xs text-purple-200 focus:outline-none cursor-pointer max-w-[180px]"
              >
                <option value="" className="bg-slate-900">
                  Restore Task ({archivedTasks.length})
                </option>
                {archivedTasks.map((at) => (
                  <option key={at.id} value={at.id} className="bg-slate-900">
                    {at.id} — {at.title} ({at.project})
                  </option>
                ))}
              </select>
            </div>
          )}

          <button
            type="button"
            onClick={() => {
              setCatProject(scope.project || projectsTree[0]?.name || 'KAIROS_2_0');
              setShowAddCategoryModal(true);
            }}
            className="flex items-center gap-1.5 rounded-lg border border-cyan-500/35 bg-cyan-500/15 px-2.5 py-1.5 text-xs font-medium text-cyan-200 hover:bg-cyan-500/25 transition"
          >
            <FolderPlus className="h-3.5 w-3.5" /> + Category
          </button>

          {scope.project && (
            <button
              type="button"
              onClick={handleArchiveProjectOrDept}
              title={`Move ${scope.project}${scope.department ? '/' + scope.department : ''} into 05_Archives/`}
              className="flex items-center gap-1.5 rounded-lg border border-amber-500/35 bg-amber-500/15 px-2.5 py-1.5 text-xs font-medium text-amber-300 hover:bg-amber-500/25 transition"
            >
              <Archive className="h-3.5 w-3.5" />
              {scope.department ? 'Archive Category' : 'Archive Project'}
            </button>
          )}
          <button
            type="button"
            onClick={() => setShowNewModal(true)}
            className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-400 transition"
          >
            <Plus className="h-3.5 w-3.5" /> New Task
          </button>
        </div>
      </div>

      {/* Project Portions / Categories Quick-Switch Tabs */}
      {activeProjectNode && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-kairos-border bg-kairos-panel/50 px-4 py-1.5 text-[11px]">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mr-1">
            {formatProjectDisplayName(activeProjectNode.name)} Categories:
          </span>
          <button
            type="button"
            onClick={() =>
              onSelectScope({ project: activeProjectNode.name, department: '', list: '' })
            }
            className={`rounded-md px-2.5 py-1 font-medium transition ${
              !scope.department
                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/35'
                : 'text-slate-400 hover:text-white bg-kairos-bg border border-kairos-border'
            }`}
          >
            All Categories ({activeProjectNode.task_count})
          </button>
          {activeProjectNode.departments.map((d) => {
            const selected = scope.department === d.name;
            const em = DEPT_EMOJI[d.name] || '📂';
            return (
              <button
                key={d.name}
                type="button"
                onClick={() =>
                  onSelectScope({
                    project: activeProjectNode.name,
                    department: d.name,
                    list: '',
                  })
                }
                className={`rounded-md px-2.5 py-1 font-medium transition ${
                  selected
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/35'
                    : 'text-slate-300 hover:text-white bg-kairos-bg border border-kairos-border'
                }`}
              >
                {em} {d.name.replace(/_/g, ' ')} ({d.task_count})
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => {
              setCatProject(activeProjectNode.name);
              setShowAddCategoryModal(true);
            }}
            className="rounded-md border border-dashed border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 font-semibold text-emerald-300 hover:bg-emerald-500/20 transition"
          >
            + Add Category
          </button>
        </div>
      )}

      {/* Inline Projects Filter Bar */}
      {(subView === 'board' || subView === 'list' || subView === 'gantt') && (
        <div className="flex flex-wrap items-center gap-2 border-b border-kairos-border bg-kairos-panel/40 px-4 py-2 text-xs">
          <div className="flex items-center gap-1.5 rounded-lg border border-kairos-border bg-kairos-bg px-2.5 py-1 w-64">
            <Search className="h-3.5 w-3.5 text-slate-400 shrink-0" />
            <input
              type="text"
              value={filterKeyword}
              onChange={(e) => setFilterKeyword(e.target.value)}
              placeholder="Filter tasks, categories, IDs, or #tags..."
              className="w-full bg-transparent text-xs text-white focus:outline-none"
            />
          </div>

          <div className="flex items-center gap-1.5 text-slate-400">
            <Filter className="h-3.5 w-3.5" />
            <select
              value={filterPriority}
              onChange={(e) => setFilterPriority(Number(e.target.value))}
              className="rounded-lg border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-slate-200"
            >
              <option value={0}>All Priorities</option>
              <option value={1}>P1 Urgent</option>
              <option value={2}>P2 High</option>
              <option value={3}>P3 Normal</option>
              <option value={4}>P4 Low</option>
            </select>

            <select
              value={filterAgent}
              onChange={(e) => setFilterAgent(e.target.value)}
              className="rounded-lg border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-purple-300"
            >
              <option value="ALL">All AI Agents</option>
              <option value="None">Human Only (None)</option>
              <option value="Gemma-4">Gemma-4</option>
              <option value="Gemini-Pro">Gemini-Pro</option>
              <option value="CrewAI-Research">CrewAI-Research</option>
              <option value="CrewAI-Dev">CrewAI-Dev</option>
              <option value="CrewAI-PM">CrewAI-PM</option>
              <option value="Hermes-Agent">Hermes-Agent</option>
              <option value="Hermes-Synthesizer">Hermes-Synthesizer</option>
            </select>
          </div>

          {(filterKeyword || filterAgent !== 'ALL' || filterPriority > 0) && (
            <button
              type="button"
              onClick={() => {
                setFilterKeyword('');
                setFilterAgent('ALL');
                setFilterPriority(0);
              }}
              className="text-[11px] text-cyan-400 hover:underline"
            >
              Reset Filters ({visibleTasks.length}/{tasks.length})
            </button>
          )}
        </div>
      )}

      {archiveBanner && (
        <div className="bg-emerald-500/15 border-b border-emerald-500/30 px-4 py-1.5 text-xs text-emerald-200">
          ✓ {archiveBanner}
        </div>
      )}

      {/* Main View Canvas */}
      <div className="flex-1 overflow-auto p-4">
        {/* 1. PORTFOLIO ROLLUP DASHBOARD (DEFAULT LANDING VIEW) */}
        {subView === 'rollup' && (
          <div className="space-y-4">
            {rollup ? (
              <>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                  <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4">
                    <div className="text-[11px] text-slate-400">Overall Completion</div>
                    <div className="mt-1 text-2xl font-bold text-emerald-400">
                      {rollup.progress_pct}%
                    </div>
                    <div className="mt-2 h-2 rounded-full bg-kairos-bg overflow-hidden">
                      <div
                        style={{ width: `${rollup.progress_pct}%` }}
                        className="h-full bg-emerald-400 transition-all"
                      />
                    </div>
                  </div>
                  <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4">
                    <div className="text-[11px] text-slate-400">Total Scoped Tasks</div>
                    <div className="mt-1 text-2xl font-bold text-white">{rollup.total_tasks}</div>
                    <div className="mt-1 text-[10px] text-slate-400">
                      Across {scope.project ? scope.project.replace(/_/g, ' ') : `${projectsTree.length} Active Project(s)`}
                    </div>
                  </div>
                  <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4">
                    <div className="text-[11px] text-slate-400">Hours Logged vs Estimated</div>
                    <div className="mt-1 text-2xl font-bold text-cyan-300">
                      {rollup.time_logged_hrs}h{' '}
                      <span className="text-sm text-slate-400">/ {rollup.time_estimate_hrs}h</span>
                    </div>
                  </div>
                  <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4">
                    <div className="text-[11px] text-slate-400">Blocked / Overdue</div>
                    <div className="mt-1 text-2xl font-bold text-amber-300">
                      {rollup.blocked_task_ids.length} / {rollup.overdue_task_ids.length}
                    </div>
                  </div>
                </div>

                {/* Actionable Blocked & Overdue Task Strip */}
                {(rollup.blocked_task_ids.length > 0 || rollup.overdue_task_ids.length > 0) && (
                  <div className="rounded-xl border border-amber-500/35 bg-amber-500/10 px-4 py-2.5 flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-bold text-amber-200">⚡ Attention Needed:</span>
                    {rollup.blocked_task_ids.map((bid) => (
                      <button
                        key={`blk-${bid}`}
                        type="button"
                        onClick={() => setSelectedTaskId(bid)}
                        className="rounded-md border border-rose-500/45 bg-rose-500/20 px-2 py-0.5 font-mono text-[11px] font-semibold text-rose-200 hover:bg-rose-500/30"
                      >
                        🚫 Blocked: {bid}
                      </button>
                    ))}
                    {rollup.overdue_task_ids.map((oid) => (
                      <button
                        key={`ovd-${oid}`}
                        type="button"
                        onClick={() => setSelectedTaskId(oid)}
                        className="rounded-md border border-amber-500/45 bg-amber-500/20 px-2 py-0.5 font-mono text-[11px] font-semibold text-amber-100 hover:bg-amber-500/30"
                      >
                        ⏰ Overdue: {oid}
                      </button>
                    ))}
                  </div>
                )}

                {/* Active Projects Portfolio Cards when in Everything scope */}
                {!scope.project && projectsTree.length > 0 && (
                  <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-white flex items-center gap-1.5">
                        <LayoutGrid className="h-3.5 w-3.5 text-amber-400" /> Active Projects in
                        `02_Projects/`
                      </span>
                      <span className="text-[11px] text-slate-400">
                        Click any project card or quick-launch view pill below
                      </span>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                      {projectsTree.map((proj) => (
                        <div
                          key={proj.name}
                          onClick={() =>
                            onSelectScope({ project: proj.name, department: '', list: '' })
                          }
                          className="cursor-pointer rounded-xl border border-kairos-border bg-kairos-card p-3.5 hover:border-emerald-500/50 transition space-y-2.5"
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-bold text-white">
                              🚀 {proj.name.replace(/_/g, ' ')}
                            </span>
                            <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[11px] font-bold text-emerald-300">
                              {proj.progress_pct}%
                            </span>
                          </div>
                          <div className="h-1.5 rounded-full bg-kairos-bg overflow-hidden">
                            <div
                              style={{ width: `${proj.progress_pct}%` }}
                              className="h-full bg-emerald-400"
                            />
                          </div>
                          <div className="flex flex-wrap gap-1 pt-0.5">
                            {proj.departments.map((d) => (
                              <span
                                key={d.name}
                                className="rounded bg-kairos-bg border border-kairos-border px-1.5 py-0.5 text-[10px] text-slate-300"
                              >
                                {DEPT_EMOJI[d.name] || '📂'} {d.name.replace(/_/g, ' ')} (
                                {d.task_count})
                              </span>
                            ))}
                          </div>
                          <div
                            onClick={(e) => e.stopPropagation()}
                            className="flex flex-wrap items-center gap-1 border-t border-kairos-border/70 pt-2"
                          >
                            {(
                              [
                                { id: 'list', label: 'List' },
                                { id: 'board', label: 'Board' },
                                { id: 'calendar', label: 'Calendar' },
                                { id: 'gantt', label: 'Gantt' },
                                { id: 'docs', label: 'Wiki' },
                              ] as { id: ProjectsSubView; label: string }[]
                            ).map((vw) => (
                              <button
                                key={vw.id}
                                type="button"
                                onClick={() => {
                                  onSelectScope({ project: proj.name, department: '', list: '' });
                                  setSubView(vw.id);
                                }}
                                className="rounded border border-kairos-border bg-kairos-bg px-2 py-0.5 text-[10px] font-medium text-emerald-300 hover:border-emerald-500/50 hover:bg-emerald-500/15"
                              >
                                {vw.label}
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-semibold text-white">Status Breakdown</span>
                    <button
                      type="button"
                      onClick={() => setSubView('board')}
                      className="text-[11px] text-emerald-300 hover:underline"
                    >
                      Open Kanban Board →
                    </button>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-6 gap-2.5">
                    {KANBAN_COLUMNS.map((st) => (
                      <div
                        key={st}
                        onClick={() => setSubView('board')}
                        className="cursor-pointer rounded-lg border border-kairos-border bg-kairos-card p-3 text-center hover:border-emerald-500/40 transition"
                      >
                        <div className="text-lg font-bold text-white">
                          {rollup.by_status[st] || 0}
                        </div>
                        <div className="text-[11px] text-slate-400">{st}</div>
                      </div>
                    ))}
                  </div>
                </div>

                {rollup.by_department && Object.keys(rollup.by_department).length > 0 && (
                  <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-semibold text-white">
                        Tasks by Project Category / Portion
                      </span>
                      <button
                        type="button"
                        onClick={() => setShowAddCategoryModal(true)}
                        className="text-[11px] text-cyan-300 hover:underline"
                      >
                        + Add New Category
                      </button>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-2.5">
                      {Object.entries(rollup.by_department).map(([dept, cnt]) => (
                        <div
                          key={dept}
                          onClick={() => {
                            if (scope.project) {
                              onSelectScope({ project: scope.project, department: dept, list: '' });
                            }
                            setSubView('list');
                          }}
                          className="cursor-pointer rounded-lg border border-kairos-border bg-kairos-card p-3 text-center hover:border-cyan-500/40 transition"
                        >
                          <div className="text-lg font-bold text-cyan-300">{cnt}</div>
                          <div className="text-[11px] text-slate-300">
                            {DEPT_EMOJI[dept] || '📂'} {dept.replace(/_/g, ' ')}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="rounded-xl border border-kairos-border bg-kairos-panel p-6 text-center text-xs text-slate-400 space-y-2">
                <div>Loading Canopy Vault Projects Rollup...</div>
                <button
                  type="button"
                  onClick={handleResyncProjects}
                  className="rounded-lg bg-emerald-500/20 border border-emerald-500/40 px-3 py-1.5 text-emerald-300 font-semibold"
                >
                  ↻ Resync Canopy Vault Now
                </button>
              </div>
            )}
          </div>
        )}

        {/* 2. LIST VIEW */}
        {subView === 'list' && (
          <div className="rounded-xl border border-kairos-border bg-kairos-panel overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-kairos-border bg-kairos-card/70 text-[11px] uppercase text-slate-400">
                <tr>
                  <th className="px-3 py-2.5">ID</th>
                  <th className="px-3 py-2.5">Task Title</th>
                  <th className="px-3 py-2.5">Project & Category</th>
                  <th className="px-3 py-2.5">Status</th>
                  <th className="px-3 py-2.5">Priority</th>
                  <th className="px-3 py-2.5">Schedule</th>
                  <th className="px-3 py-2.5">Checklist</th>
                  <th className="px-3 py-2.5">AI Agent</th>
                  <th className="px-3 py-2.5">Hours</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-kairos-border">
                {visibleTasks.map((t) => {
                  const prio = PRIORITY_BADGE[t.priority] || PRIORITY_BADGE[3];
                  return (
                    <tr
                      key={t.id}
                      onClick={() => setSelectedTaskId(t.id)}
                      className="cursor-pointer hover:bg-kairos-card/60 transition"
                    >
                      <td className="px-3 py-2.5 font-mono text-[11px] text-emerald-300">{t.id}</td>
                      <td className="px-3 py-2.5 font-medium text-white">
                        {t.parent_task && (
                          <span className="mr-1.5 inline-flex items-center gap-0.5 rounded bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                            ↳ {formatParentBadge(t.parent_task)}
                          </span>
                        )}
                        {t.title}
                      </td>
                      <td className="px-3 py-2.5 text-[11px] text-slate-300">
                        {t.project.replace(/_/g, ' ')} / {t.department.replace(/_/g, ' ')} ({t.list})
                      </td>
                      <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <select
                          value={t.status}
                          onChange={(e) => handleDropStatus(t.id, e.target.value as TaskStatus)}
                          className="rounded border border-kairos-border bg-kairos-bg px-2 py-0.5 text-xs text-slate-200"
                        >
                          {KANBAN_COLUMNS.map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                      </td>
                       <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <select
                          value={t.priority}
                          onChange={(e) =>
                            handleInlinePatchTask(t.id, { priority: Number(e.target.value) })
                          }
                          className={`rounded border px-2 py-0.5 text-[10px] font-medium bg-kairos-bg ${prio.cls}`}
                        >
                          <option value={1}>P1 Urgent</option>
                          <option value={2}>P2 High</option>
                          <option value={3}>P3 Normal</option>
                          <option value={4}>P4 Low</option>
                        </select>
                      </td>
                      <td className="px-3 py-2.5 text-[11px] text-slate-400 font-mono">
                        {t.due_date || t.start_date || '—'}
                      </td>
                      <td className="px-3 py-2.5 text-slate-300">
                        {t.checklist_done}/{t.checklist_total}
                      </td>
                      <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <select
                          value={t.ai_agent}
                          onChange={(e) =>
                            handleInlinePatchTask(t.id, { ai_agent: e.target.value })
                          }
                          className="rounded border border-kairos-border bg-kairos-bg px-2 py-0.5 text-[11px] text-purple-300"
                        >
                          {Array.from(new Set([...LIST_AI_AGENTS, t.ai_agent || 'None'])).map(
                            (ag) => (
                              <option key={ag} value={ag}>
                                {ag}
                              </option>
                            )
                          )}
                        </select>
                      </td>
                      <td className="px-3 py-2.5 text-slate-300">
                        {t.time_logged_hrs}h / {t.time_estimate_hrs}h
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Inline Quick-Add Row for List View */}
            <form
              onSubmit={handleQuickCreateListTask}
              className="flex flex-wrap items-center gap-2 border-t border-kairos-border bg-kairos-card/40 px-3 py-2"
            >
              <Plus className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
              <input
                type="text"
                value={quickListTitle}
                onChange={(e) => setQuickListTitle(e.target.value)}
                placeholder={`Quick add task into ${newProject.replace(/_/g, ' ')} / ${newDepartment.replace(/_/g, ' ')}...`}
                className="flex-1 min-w-[220px] rounded border border-kairos-border bg-kairos-bg px-2.5 py-1 text-xs text-white focus:outline-none"
              />
              <select
                value={quickListPriority}
                onChange={(e) => setQuickListPriority(Number(e.target.value))}
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-slate-200"
              >
                <option value={1}>P1 Urgent</option>
                <option value={2}>P2 High</option>
                <option value={3}>P3 Normal</option>
                <option value={4}>P4 Low</option>
              </select>
              <select
                value={quickListAgent}
                onChange={(e) => setQuickListAgent(e.target.value)}
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-purple-300"
              >
                {LIST_AI_AGENTS.map((ag) => (
                  <option key={ag} value={ag}>
                    {ag}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                className="rounded-md bg-emerald-500/20 border border-emerald-500/40 px-3 py-1 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/30"
              >
                + Quick Add
              </button>
            </form>
          </div>
        )}

        {/* 3. KANBAN BOARD VIEW */}
        {subView === 'board' && (
          <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-3 min-h-full">
            {KANBAN_COLUMNS.map((colStatus) => {
              const colTasks = visibleTasks.filter((t) => t.status === colStatus);
              return (
                <div
                  key={colStatus}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    const tid = e.dataTransfer.getData('text/task-id');
                    if (tid) handleDropStatus(tid, colStatus);
                  }}
                  className="flex flex-col rounded-xl border border-kairos-border bg-kairos-panel/80 p-2.5 min-h-[420px]"
                >
                  <div className="flex items-center justify-between px-1 pb-2 mb-2 border-b border-kairos-border">
                    <span className="text-xs font-semibold text-slate-200">{colStatus}</span>
                    <div className="flex items-center gap-1">
                      <span className="rounded-full bg-kairos-card px-2 py-0.5 text-[10px] text-slate-400">
                        {colTasks.length}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          setQuickBoardCol((c) => (c === colStatus ? null : colStatus));
                          setQuickBoardTitle('');
                        }}
                        title={`Quick-add task in '${colStatus}'`}
                        className="rounded p-0.5 text-slate-400 hover:bg-emerald-500/20 hover:text-emerald-300"
                      >
                        <Plus className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>

                  {quickBoardCol === colStatus && (
                    <form
                      onSubmit={(e) => handleQuickCreateBoardTask(e, colStatus)}
                      className="mb-2 rounded-lg border border-emerald-500/40 bg-kairos-bg p-2 space-y-1.5"
                    >
                      <input
                        type="text"
                        autoFocus
                        value={quickBoardTitle}
                        onChange={(e) => setQuickBoardTitle(e.target.value)}
                        placeholder={`New '${colStatus}' task...`}
                        className="w-full rounded border border-kairos-border bg-kairos-panel px-2 py-1 text-xs text-white focus:outline-none"
                      />
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          onClick={() => setQuickBoardCol(null)}
                          className="rounded px-2 py-0.5 text-[10px] text-slate-400 hover:text-white"
                        >
                          Cancel
                        </button>
                        <button
                          type="submit"
                          className="rounded bg-emerald-500 px-2 py-0.5 text-[10px] font-semibold text-slate-950 hover:bg-emerald-400"
                        >
                          Add Card
                        </button>
                      </div>
                    </form>
                  )}

                  <div className="space-y-2 flex-1">
                    {colTasks.map((t) => {
                      const prio = PRIORITY_BADGE[t.priority] || PRIORITY_BADGE[3];
                      const deptEm = DEPT_EMOJI[t.department] || '📂';
                      return (
                        <div
                          key={t.id}
                          draggable
                          onDragStart={(e) => e.dataTransfer.setData('text/task-id', t.id)}
                          onClick={() => setSelectedTaskId(t.id)}
                          className="cursor-pointer rounded-lg border border-kairos-border bg-kairos-card p-2.5 hover:border-emerald-500/50 transition shadow-sm space-y-2"
                        >
                          <div className="flex items-center justify-between gap-1">
                            <span className="font-mono text-[10px] text-slate-400">{t.id}</span>
                            <span
                              className={`rounded border px-1.5 py-0.2 text-[10px] font-medium ${prio.cls}`}
                            >
                              {prio.label}
                            </span>
                          </div>

                          {t.parent_task && (
                            <div className="flex items-center gap-1 text-[10px] text-cyan-300 font-mono">
                              <CornerDownRight className="h-2.5 w-2.5 shrink-0" />
                              <span className="truncate">
                                Subtask of {formatParentBadge(t.parent_task)}
                              </span>
                            </div>
                          )}

                          <div className="text-xs font-semibold text-white leading-snug">
                            {t.title}
                          </div>

                          <div className="flex flex-wrap items-center justify-between gap-1 text-[10px] text-slate-400">
                            <span className="truncate">
                              🚀 {t.project.replace(/_/g, ' ')} • {deptEm}{' '}
                              {t.department.replace(/_/g, ' ')}
                            </span>
                            {t.checklist_total > 0 && (
                              <span className="flex items-center gap-0.5 text-emerald-300">
                                <CircleCheck className="h-3 w-3" />
                                {t.checklist_done}/{t.checklist_total}
                              </span>
                            )}
                          </div>

                          <div className="flex items-center justify-between pt-1 border-t border-kairos-border/60 text-[10px]">
                            <span className="text-slate-400">
                              {t.due_date ? `📅 ${t.due_date}` : t.list.replace(/_/g, ' ')}
                            </span>
                            {t.ai_agent !== 'None' && (
                              <span className="flex items-center gap-1 rounded bg-purple-500/20 px-1.5 py-0.5 text-purple-300">
                                <Bot className="h-2.5 w-2.5" /> {t.ai_agent}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* 4. REAL INTERACTIVE MONTHLY CALENDAR GRID VIEW */}
        {subView === 'calendar' && (
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
            {/* Left 8 Cols: Full 7-Column Monthly Calendar Grid */}
            <div className="xl:col-span-8 rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-emerald-400" />
                  <h2 className="text-sm font-bold text-white">
                    {calendarCursor.toLocaleDateString('en-US', {
                      month: 'long',
                      year: 'numeric',
                    })}
                  </h2>
                  <span className="rounded bg-kairos-card px-2 py-0.5 text-[10px] text-slate-400">
                    {events.length} Events • {visibleTasks.filter((t) => t.due_date || t.start_date).length} Scheduled Tasks
                  </span>
                </div>

                <div className="flex items-center gap-1.5 text-xs">
                  <button
                    type="button"
                    onClick={() =>
                      setCalendarCursor(
                        new Date(calendarCursor.getFullYear(), calendarCursor.getMonth() - 1, 1)
                      )
                    }
                    className="rounded-lg border border-kairos-border bg-kairos-card p-1.5 text-slate-300 hover:text-white"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const now = new Date();
                      setCalendarCursor(new Date(now.getFullYear(), now.getMonth(), 1));
                      setSelectedDateIso(toLocalIsoDate(now));
                    }}
                    className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-2.5 py-1 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/25"
                  >
                    Today
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setCalendarCursor(
                        new Date(calendarCursor.getFullYear(), calendarCursor.getMonth() + 1, 1)
                      )
                    }
                    className="rounded-lg border border-kairos-border bg-kairos-card p-1.5 text-slate-300 hover:text-white"
                  >
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              {/* 7-Day Weekday Header */}
              <div className="grid grid-cols-7 gap-1.5 text-center text-[10.5px] font-bold uppercase tracking-wider text-slate-400">
                {WEEKDAYS.map((wd) => (
                  <div key={wd} className="rounded bg-kairos-bg/70 py-1.5">
                    {wd}
                  </div>
                ))}
              </div>

              {/* Monthly Calendar Day Cells */}
              <div className="grid grid-cols-7 gap-1.5">
                {calendarCells.map((cell) => {
                  const isSelected = cell.iso === selectedDateIso;
                  return (
                    <div
                      key={cell.iso}
                      onClick={() => setSelectedDateIso(cell.iso)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault();
                        const droppedTaskId = e.dataTransfer.getData('text/kairos-task-id');
                        if (droppedTaskId) {
                          handleCalendarDropTask(droppedTaskId, cell.iso);
                          return;
                        }
                        const droppedEventId = e.dataTransfer.getData('text/kairos-event-id');
                        if (droppedEventId) {
                          handleCalendarDropEvent(droppedEventId, cell.iso);
                        }
                      }}
                      className={`min-h-[106px] rounded-xl border p-1.5 flex flex-col gap-1 cursor-pointer transition ${
                        cell.isToday
                          ? 'border-emerald-400 bg-emerald-500/10 ring-1 ring-emerald-400/50'
                          : isSelected
                            ? 'border-cyan-400/70 bg-cyan-500/10'
                            : cell.inCurrentMonth
                              ? 'border-kairos-border bg-kairos-card/60 hover:border-slate-600'
                              : 'border-kairos-border/40 bg-kairos-bg/40 opacity-55'
                      }`}
                    >
                      <div className="flex items-center justify-between text-[11px]">
                        <span
                          className={`font-bold ${
                            cell.isToday
                              ? 'rounded-full bg-emerald-400 px-1.5 py-0.2 text-slate-950'
                              : cell.inCurrentMonth
                                ? 'text-slate-200'
                                : 'text-slate-500'
                          }`}
                        >
                          {cell.dayNum}
                        </span>
                        {cell.isToday && (
                          <span className="text-[9px] font-bold uppercase text-emerald-300">
                            Today
                          </span>
                        )}
                      </div>

                      <div className="space-y-1 overflow-y-auto max-h-[74px] pr-0.5">
                        {cell.dayEvents.map((ev) => (
                          <div
                            key={ev.id}
                            draggable
                            onDragStart={(e) => {
                              e.dataTransfer.setData('text/kairos-event-id', ev.id);
                            }}
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpenNoteInSecondBrain(ev.rel_path);
                            }}
                            title={`${ev.title} (${ev.start_time.slice(11, 16)}) — Drag onto another day to move`}
                            className="truncate rounded bg-cyan-500/20 border border-cyan-500/35 px-1.5 py-0.5 text-[10px] font-medium text-cyan-200 hover:bg-cyan-500/30 cursor-grab active:cursor-grabbing"
                          >
                            ⏰ {ev.start_time.slice(11, 16)} {ev.title}
                          </div>
                        ))}
                        {cell.dayTasks.map((t) => (
                          <div
                            key={t.id}
                            draggable
                            onDragStart={(e) => {
                              e.dataTransfer.setData('text/kairos-task-id', t.id);
                            }}
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedTaskId(t.id);
                            }}
                            title={`${t.id}: ${t.title} (${t.status}) — Drag onto another day to reschedule`}
                            className={`truncate rounded border px-1.5 py-0.5 text-[10px] font-medium cursor-grab active:cursor-grabbing ${
                              t.status === 'Done'
                                ? 'bg-emerald-500/20 border-emerald-500/35 text-emerald-200 line-through'
                                : t.priority === 1
                                  ? 'bg-rose-500/25 border-rose-500/40 text-rose-200'
                                  : 'bg-amber-500/20 border-amber-500/35 text-amber-200'
                            }`}
                          >
                            🎯 {t.title}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Right 4 Cols: Selected Day Agenda + Event / Focus-Block Composer */}
            <div className="xl:col-span-4 space-y-4">
              <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-bold text-white">
                    📅 Agenda for <span className="text-emerald-300 font-mono">{selectedDateIso}</span>
                  </div>
                  {selectedDateIso === todayIso && (
                    <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
                      TODAY
                    </span>
                  )}
                </div>

                {selectedDayData.dayEvents.length === 0 &&
                selectedDayData.dayTasks.length === 0 ? (
                  <div className="rounded-lg border border-kairos-border bg-kairos-bg p-3 text-xs text-slate-400">
                    No events or deadlines scheduled on {selectedDateIso}. Add an event or
                    time-block a task below.
                  </div>
                ) : (
                  <div className="space-y-2 max-h-60 overflow-y-auto">
                    {selectedDayData.dayEvents.map((ev) => {
                      const cleanLinkedTask = (ev.linked_task_id || ev.linked_task || '')
                        .replace(/^\[\[|\]\]$/g, '')
                        .trim();
                      return (
                        <div
                          key={ev.id}
                          onClick={() => onOpenNoteInSecondBrain(ev.rel_path)}
                          className="cursor-pointer rounded-lg border border-cyan-500/35 bg-cyan-500/10 p-2.5 space-y-1 hover:bg-cyan-500/20"
                        >
                          <div className="flex items-center justify-between gap-2 text-xs font-semibold text-cyan-200">
                            <span className="truncate">⏰ {ev.title}</span>
                            <div className="flex items-center gap-1.5 shrink-0">
                              <span className="text-[10px] font-mono">
                                {ev.start_time.slice(11, 16)}
                              </span>
                              <button
                                type="button"
                                title="Delete Calendar Event"
                                onClick={(e) => handleDeleteCalendarEvent(e, ev.id)}
                                className="rounded p-0.5 text-slate-400 hover:bg-rose-500/25 hover:text-rose-200"
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </div>
                          </div>
                          <div className="flex flex-wrap items-center gap-1.5 text-[10.5px] text-slate-300">
                            <span>{ev.category}</span>
                            {cleanLinkedTask && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSelectedTaskId(cleanLinkedTask);
                                }}
                                className="rounded border border-emerald-500/40 bg-emerald-500/15 px-1.5 py-0.2 font-mono text-[10px] text-emerald-300 hover:bg-emerald-500/25"
                              >
                                🎯 {cleanLinkedTask}
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                    {selectedDayData.dayTasks.map((t) => (
                      <div
                        key={t.id}
                        onClick={() => setSelectedTaskId(t.id)}
                        className="cursor-pointer rounded-lg border border-kairos-border bg-kairos-card p-2.5 space-y-0.5 hover:border-emerald-500/40"
                      >
                        <div className="flex items-center justify-between text-xs font-semibold text-white">
                          <span>🎯 {t.title}</span>
                          <span className="text-[10px] font-mono text-emerald-300">{t.id}</span>
                        </div>
                        <div className="text-[10.5px] text-slate-400">
                          {t.project.replace(/_/g, ' ')} / {t.department.replace(/_/g, ' ')} •{' '}
                          {t.status}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <form
                onSubmit={handleCalendarSubmit}
                className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-3"
              >
                <div className="flex items-center gap-2 text-xs font-bold text-emerald-300">
                  <Clock className="h-4 w-4" />
                  Schedule on {selectedDateIso}
                </div>

                <div className="grid grid-cols-2 gap-1 rounded-lg bg-kairos-bg p-0.5 text-[11px]">
                  <button
                    type="button"
                    onClick={() => setCalComposerMode('task-block')}
                    className={`rounded-md py-1 font-semibold transition ${
                      calComposerMode === 'task-block'
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/35'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    🎯 Time-Block Task
                  </button>
                  <button
                    type="button"
                    onClick={() => setCalComposerMode('standalone')}
                    className={`rounded-md py-1 font-semibold transition ${
                      calComposerMode === 'standalone'
                        ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/35'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    📅 + New Event
                  </button>
                </div>

                {calComposerMode === 'task-block' ? (
                  <div>
                    <label className="block text-[10px] uppercase text-slate-400 mb-1">Task</label>
                    <select
                      value={blockTaskId}
                      onChange={(e) => setBlockTaskId(e.target.value)}
                      className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-white"
                    >
                      {tasks.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.id} — {t.title}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <>
                    <div>
                      <label className="block text-[10px] uppercase text-slate-400 mb-1">
                        Event Title
                      </label>
                      <input
                        type="text"
                        required
                        value={standaloneEventTitle}
                        onChange={(e) => setStandaloneEventTitle(e.target.value)}
                        placeholder="e.g. KAIROS 2.0 Sprint Review"
                        className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-white"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] uppercase text-slate-400 mb-1">
                        Notes (Optional)
                      </label>
                      <input
                        type="text"
                        value={standaloneEventNotes}
                        onChange={(e) => setStandaloneEventNotes(e.target.value)}
                        placeholder="Meeting link, agenda, or goals..."
                        className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-white"
                      />
                    </div>
                  </>
                )}

                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="block text-[10px] uppercase text-slate-400 mb-1">Time</label>
                    <input
                      type="time"
                      value={calTimeStr}
                      onChange={(e) => setCalTimeStr(e.target.value)}
                      className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-xs text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase text-slate-400 mb-1">Hours</label>
                    <input
                      type="number"
                      min={0.25}
                      step={0.25}
                      value={calDurationHrs}
                      onChange={(e) => setCalDurationHrs(Number(e.target.value))}
                      className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-xs text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase text-slate-400 mb-1">Type</label>
                    <select
                      value={standaloneEventCategory}
                      onChange={(e) => setStandaloneEventCategory(e.target.value)}
                      className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-xs text-white"
                    >
                      <option value="Business">Business</option>
                      <option value="Sprint">Sprint</option>
                      <option value="Launch">Launch</option>
                      <option value="Personal">Personal</option>
                    </select>
                  </div>
                </div>

                <button
                  type="submit"
                  className="w-full rounded-lg bg-emerald-500 py-2 text-xs font-semibold text-slate-950 hover:bg-emerald-400"
                >
                  {calComposerMode === 'task-block'
                    ? `Create Task Focus Block on ${selectedDateIso}`
                    : `Save Calendar Event on ${selectedDateIso}`}
                </button>
              </form>

              {/* Unscheduled Tasks Drag-and-Drop Tray */}
              {visibleTasks.some((t) => !t.due_date && t.status !== 'Done') && (
                <div className="rounded-xl border border-kairos-border bg-kairos-panel p-3.5 space-y-2">
                  <div className="text-[11px] font-bold text-amber-300">
                    📌 Unscheduled Tasks — Drag onto any Calendar Day
                  </div>
                  <div className="space-y-1.5 max-h-40 overflow-y-auto pr-0.5">
                    {visibleTasks
                      .filter((t) => !t.due_date && t.status !== 'Done')
                      .map((t) => (
                        <div
                          key={t.id}
                          draggable
                          onDragStart={(e) => {
                            e.dataTransfer.setData('text/kairos-task-id', t.id);
                          }}
                          onClick={() => setSelectedTaskId(t.id)}
                          className="flex items-center justify-between gap-2 rounded-lg border border-kairos-border bg-kairos-card px-2.5 py-1.5 text-xs text-slate-200 hover:border-amber-500/40 cursor-grab active:cursor-grabbing"
                        >
                          <span className="truncate">🎯 {t.title}</span>
                          <span className="font-mono text-[10px] text-emerald-300 shrink-0">
                            {t.id}
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 5. REAL DATE-SCALED GANTT TIMELINE WITH VERTICAL `TODAY` DATELINE */}
        {subView === 'gantt' && (
          <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-3 overflow-x-auto">
            {/* Gantt Controls Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-bold text-white flex items-center gap-2">
                  <ChartGantt className="h-4 w-4 text-emerald-400" />
                  <span>Project Gantt Timeline & Dependency Schedule</span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/20 border border-rose-500/40 px-2 py-0.5 text-[10px] font-bold text-rose-300">
                    ┃ TODAY Dateline: {todayIso}
                  </span>
                </div>
                <div className="text-[11px] text-slate-400">
                  Window: {toLocalIsoDate(ganttTimeline.windowStart)} →{' '}
                  {toLocalIsoDate(ganttTimeline.windowEnd)} • Click any task row or bar to edit
                  `start_date` / `due_date`
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 text-xs">
                <div className="flex items-center rounded-lg border border-kairos-border bg-kairos-bg p-0.5">
                  {([14, 30, 60] as const).map((dCount) => (
                    <button
                      key={dCount}
                      type="button"
                      onClick={() => setGanttRangeDays(dCount)}
                      className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                        ganttRangeDays === dCount
                          ? 'bg-emerald-500/25 text-emerald-300'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      {dCount}D
                    </button>
                  ))}
                </div>

                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setGanttOffsetDays((o) => o - 7)}
                    className="rounded-lg border border-kairos-border bg-kairos-card px-2 py-1 text-slate-300 hover:text-white"
                  >
                    ◀ -7d
                  </button>
                  <button
                    type="button"
                    onClick={() => setGanttOffsetDays(-5)}
                    className="rounded-lg border border-rose-500/40 bg-rose-500/15 px-2.5 py-1 font-semibold text-rose-200 hover:bg-rose-500/25"
                  >
                    Center Today
                  </button>
                  <button
                    type="button"
                    onClick={() => setGanttOffsetDays((o) => o + 7)}
                    className="rounded-lg border border-kairos-border bg-kairos-card px-2 py-1 text-slate-300 hover:text-white"
                  >
                    +7d ▶
                  </button>
                </div>
              </div>
            </div>

            {/* Gantt Grid Container */}
            <div className="min-w-[980px] rounded-xl border border-kairos-border bg-kairos-bg overflow-hidden">
              {/* Two-Tier Date Ruler Header */}
              <div className="grid grid-cols-12 border-b border-kairos-border bg-kairos-card/80">
                <div className="col-span-4 border-r border-kairos-border px-3 py-2 flex flex-col justify-center">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-slate-300">
                    Task / Category / Dependencies
                  </span>
                  <span className="text-[10px] text-slate-500">
                    {visibleTasks.length} task(s) plotted on timeline
                  </span>
                </div>

                <div className="col-span-8 relative">
                  {/* Tier 1: Month Spans */}
                  <div
                    className="grid border-b border-kairos-border/70 text-[10px] font-bold uppercase tracking-wider text-cyan-300"
                    style={{
                      gridTemplateColumns: `repeat(${ganttRangeDays}, minmax(0, 1fr))`,
                    }}
                  >
                    {ganttTimeline.monthGroups.map((mg, mIdx) => (
                      <div
                        key={`${mg.label}-${mIdx}`}
                        style={{ gridColumn: `span ${mg.span} / span ${mg.span}` }}
                        className="border-r border-kairos-border/60 px-2 py-1 truncate"
                      >
                        {mg.label}
                      </div>
                    ))}
                  </div>

                  {/* Tier 2: Day-by-Day Date Ticks */}
                  <div
                    className="grid text-center text-[9.5px]"
                    style={{
                      gridTemplateColumns: `repeat(${ganttRangeDays}, minmax(0, 1fr))`,
                    }}
                  >
                    {ganttTimeline.days.map((day) => (
                      <div
                        key={day.iso}
                        title={day.iso}
                        className={`border-r border-kairos-border/40 py-1 leading-tight ${
                          day.isToday
                            ? 'bg-rose-500/25 text-rose-200 font-bold'
                            : day.isWeekend
                              ? 'bg-slate-900/70 text-slate-500'
                              : 'text-slate-400'
                        }`}
                      >
                        {ganttRangeDays <= 30 && (
                          <div className="text-[8.5px] opacity-75">{day.dow}</div>
                        )}
                        <div>{day.dayNum}</div>
                      </div>
                    ))}
                  </div>

                  {/* TODAY Flag Pill on Ruler */}
                  {ganttTimeline.todayPct !== null && (
                    <div
                      style={{ left: `${ganttTimeline.todayPct}%` }}
                      className="pointer-events-none absolute top-0.5 -translate-x-1/2 z-20 rounded bg-rose-500 px-1.5 py-0.2 text-[9px] font-extrabold text-white shadow"
                    >
                      TODAY
                    </div>
                  )}
                </div>
              </div>

              {/* Task Rows with Continuous Vertical `TODAY` Dateline */}
              <div className="divide-y divide-kairos-border/60">
                {visibleTasks.map((t, idx) => {
                  const estDays = Math.max(1, Math.ceil((t.time_estimate_hrs || 2) / 4));
                  const parsedStart = parseIsoDateLocal(t.start_date);
                  const parsedDue = parseIsoDateLocal(t.due_date);

                  let barStart: Date;
                  let barEnd: Date;
                  let unscheduled = false;

                  if (parsedStart && parsedDue) {
                    barStart = parsedStart <= parsedDue ? parsedStart : parsedDue;
                    barEnd = parsedDue >= parsedStart ? parsedDue : parsedStart;
                  } else if (parsedDue) {
                    barEnd = parsedDue;
                    barStart = addDays(parsedDue, -(estDays - 1));
                  } else if (parsedStart) {
                    barStart = parsedStart;
                    barEnd = addDays(parsedStart, estDays - 1);
                  } else {
                    unscheduled = true;
                    barStart = addDays(todayDate, idx % 4);
                    barEnd = addDays(barStart, estDays);
                  }

                  const msPerDay = 86400000;
                  const startDiffDays = Math.round(
                    (barStart.getTime() - ganttTimeline.windowStart.getTime()) / msPerDay
                  );
                  const endDiffDays = Math.round(
                    (barEnd.getTime() - ganttTimeline.windowStart.getTime()) / msPerDay
                  );

                  const clampedStart = Math.max(0, Math.min(ganttRangeDays - 1, startDiffDays));
                  const clampedEnd = Math.max(
                    clampedStart,
                    Math.min(ganttRangeDays - 1, endDiffDays)
                  );
                  const outOfWindow = endDiffDays < 0 || startDiffDays >= ganttRangeDays;

                  const leftPct = (clampedStart / ganttRangeDays) * 100;
                  const widthPct = Math.max(
                    100 / ganttRangeDays,
                    ((clampedEnd - clampedStart + 1) / ganttRangeDays) * 100
                  );
                  const checkPct =
                    t.checklist_total > 0
                      ? Math.round((t.checklist_done / t.checklist_total) * 100)
                      : t.status === 'Done'
                        ? 100
                        : 0;

                  return (
                    <div
                      key={t.id}
                      onClick={() => setSelectedTaskId(t.id)}
                      className="grid grid-cols-12 items-stretch hover:bg-kairos-card/45 cursor-pointer transition"
                    >
                      {/* Left Label Cell */}
                      <div className="col-span-4 border-r border-kairos-border px-3 py-2.5 flex flex-col justify-center min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-semibold text-white truncate">
                            {t.parent_task ? `↳ ${t.title}` : t.title}
                          </span>
                          <span className="font-mono text-[10px] text-emerald-300 shrink-0">
                            {t.id}
                          </span>
                        </div>
                        <div className="flex items-center justify-between gap-1 text-[10px] text-slate-400 mt-0.5">
                          <span className="truncate flex items-center gap-1 flex-wrap">
                            <span>
                              {DEPT_EMOJI[t.department] || '📂'} {t.department.replace(/_/g, ' ')} •{' '}
                              {unscheduled
                                ? 'Unscheduled'
                                : `${toLocalIsoDate(barStart)} → ${toLocalIsoDate(barEnd)}`}
                            </span>
                            {t.depends_on.map((depRaw) => {
                              const depClean = formatParentBadge(depRaw);
                              const upstream = tasks.find((cand) => cand.id === depClean);
                              const depDone = upstream?.status === 'Done';
                              return (
                                <button
                                  key={depRaw}
                                  type="button"
                                  title={
                                    upstream
                                      ? `Depends on ${depClean}: ${upstream.title} (${upstream.status})`
                                      : `Inspect dependency ${depClean}`
                                  }
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSelectedTaskId(depClean);
                                  }}
                                  className={`rounded border px-1 py-0.2 font-mono text-[9px] transition ${
                                    depDone
                                      ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25'
                                      : 'border-amber-500/45 bg-amber-500/15 text-amber-200 hover:bg-amber-500/25'
                                  }`}
                                >
                                  ⛓ {depClean}
                                </button>
                              );
                            })}
                          </span>
                          <span className="flex items-center gap-0.5 shrink-0">
                            {unscheduled && (
                              <button
                                type="button"
                                title="Anchor unscheduled task onto today's Gantt timeline"
                                onClick={(e) => handleAnchorTaskToday(e, t)}
                                className="rounded border border-emerald-500/45 bg-emerald-500/15 px-1.5 py-0.2 text-[9px] font-semibold text-emerald-300 hover:bg-emerald-500/25"
                              >
                                Today
                              </button>
                            )}
                            <button
                              type="button"
                              title="Shift schedule -1 day"
                              onClick={(e) => handleShiftTaskDates(e, t, -1)}
                              className="rounded border border-kairos-border bg-kairos-bg px-1 py-0.2 text-[9px] text-slate-400 hover:text-white hover:border-slate-500"
                            >
                              -1d
                            </button>
                            <button
                              type="button"
                              title="Shift schedule +1 day"
                              onClick={(e) => handleShiftTaskDates(e, t, 1)}
                              className="rounded border border-kairos-border bg-kairos-bg px-1 py-0.2 text-[9px] text-slate-400 hover:text-white hover:border-slate-500"
                            >
                              +1d
                            </button>
                          </span>
                        </div>
                      </div>

                      {/* Right Timeline Track */}
                      <div className="col-span-8 relative h-12 flex items-center">
                        {/* Vertical Day Gridlines */}
                        <div
                          className="pointer-events-none absolute inset-0 grid"
                          style={{
                            gridTemplateColumns: `repeat(${ganttRangeDays}, minmax(0, 1fr))`,
                          }}
                        >
                          {ganttTimeline.days.map((d) => (
                            <div
                              key={d.iso}
                              className={`border-r border-kairos-border/25 ${
                                d.isWeekend ? 'bg-slate-900/40' : ''
                              }`}
                            />
                          ))}
                        </div>

                        {/* Glowing Vertical `TODAY` Dateline */}
                        {ganttTimeline.todayPct !== null && (
                          <div
                            style={{ left: `${ganttTimeline.todayPct}%` }}
                            className="pointer-events-none absolute inset-y-0 z-10 w-[2px] -translate-x-1/2 bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.95)]"
                          />
                        )}

                        {/* Task Gantt Bar */}
                        {!outOfWindow ? (
                          <div
                            style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                            className={`relative z-20 h-7 rounded-md px-2 flex items-center justify-between text-[10px] font-semibold overflow-hidden shadow ${
                              t.status === 'Done'
                                ? 'bg-emerald-500/35 text-emerald-100 border border-emerald-400/60'
                                : t.priority === 1
                                  ? 'bg-rose-500/35 text-rose-100 border border-rose-400/60'
                                  : unscheduled
                                    ? 'bg-slate-700/50 text-slate-200 border border-dashed border-slate-400'
                                    : 'bg-cyan-500/30 text-cyan-100 border border-cyan-400/60'
                            }`}
                          >
                            {checkPct > 0 && (
                              <div
                                style={{ width: `${checkPct}%` }}
                                className="pointer-events-none absolute inset-y-0 left-0 bg-white/10"
                              />
                            )}
                            <span className="relative truncate">
                              {t.status} {unscheduled ? '(est)' : ''}
                            </span>
                            <span className="relative ml-1 shrink-0 font-mono">
                              {t.time_estimate_hrs}h
                            </span>
                          </div>
                        ) : (
                          <div className="px-3 text-[10px] italic text-slate-500">
                            {endDiffDays < 0 ? '◀ Earlier than window' : 'Later than window ▶'} (
                            {toLocalIsoDate(barStart)})
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* 6. PROJECT DOCUMENTATION WIKI & CANVAS HUB (`subView === 'docs'`) */}
        {subView === 'docs' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 min-h-[540px]">
            {/* Left 4 Cols: Project Wiki Tree + New Note / New Canvas Creators */}
            <div className="lg:col-span-4 rounded-xl border border-kairos-border bg-kairos-panel p-3.5 flex flex-col gap-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-xs font-bold text-white flex items-center gap-1.5">
                  <BookOpen className="h-4 w-4 text-emerald-400" />
                  <span>Project Documentation Wiki</span>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => {
                      setNewWikiTargetProject(
                        scope.project || projectsTree[0]?.name || 'KAIROS_2_0'
                      );
                      setShowNewWikiModal('note');
                    }}
                    className="flex items-center gap-1 rounded-md bg-emerald-500 px-2 py-1 text-[11px] font-semibold text-slate-950 hover:bg-emerald-400"
                  >
                    <FilePlus2 className="h-3 w-3" /> + Wiki Note
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setNewWikiTargetProject(
                        scope.project || projectsTree[0]?.name || 'KAIROS_2_0'
                      );
                      setShowNewWikiModal('canvas');
                    }}
                    className="rounded-md border border-cyan-500/40 bg-cyan-500/15 px-2 py-1 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25"
                  >
                    + Canvas
                  </button>
                  <button
                    type="button"
                    onClick={handleCreateProjectTasksBase}
                    title="Generate or refresh native Obsidian Project_Tasks.base database for this project"
                    className="flex items-center gap-1 rounded-md border border-purple-500/40 bg-purple-500/15 px-2 py-1 text-[11px] font-semibold text-purple-200 hover:bg-purple-500/25"
                  >
                    <Database className="h-3 w-3 text-purple-300" /> + Tasks .base
                  </button>
                </div>
              </div>

              <div className="flex items-center gap-1.5 rounded-lg border border-kairos-border bg-kairos-bg px-2.5 py-1.5">
                <Search className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                <input
                  type="text"
                  value={wikiSearch}
                  onChange={(e) => setWikiSearch(e.target.value)}
                  placeholder="Search project wiki pages, .base & canvases..."
                  className="w-full bg-transparent text-xs text-white focus:outline-none"
                />
              </div>

              <div className="flex-1 overflow-y-auto space-y-1.5 pr-0.5">
                {filteredWikiDocs.length === 0 ? (
                  <div className="rounded-lg border border-kairos-border bg-kairos-bg p-3 text-xs text-slate-400">
                    No wiki pages in this scope yet. Click <strong>+ Wiki Note</strong> above to
                    create a project note, meeting log, technical spec, or SOP!
                  </div>
                ) : (
                  filteredWikiDocs.map((doc) => {
                    const active = doc.rel_path === selectedDocPath;
                    const isCanvas = doc.rel_path.endsWith('.canvas');
                    const isBase = doc.rel_path.endsWith('.base');
                    const isIndex = doc.rel_path.endsWith('_Project_Index.md');
                    return (
                      <button
                        key={doc.rel_path}
                        type="button"
                        onClick={() => {
                          if (doc.rel_path !== selectedDocPath && wikiDirtyRef.current) {
                            const ok = window.confirm(
                              `You have unsaved edits in '${activeDocDetail?.title || selectedDocPath}'. Discard unsaved Wiki edits and switch pages?`
                            );
                            if (!ok) return;
                            wikiDirtyRef.current = false;
                          }
                          setSelectedDocPath(doc.rel_path);
                          setWikiEditMode(false);
                        }}
                        className={`w-full text-left rounded-xl border p-2.5 transition space-y-1 ${
                          active
                            ? 'border-emerald-500/50 bg-emerald-500/15'
                            : 'border-kairos-border bg-kairos-card/60 hover:border-slate-600'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-1.5">
                          <span className="text-xs font-bold text-white truncate">
                            {isCanvas ? '🎨 ' : isBase ? '📊 ' : isIndex ? '📌 ' : '📘 '}
                            {doc.title}
                          </span>
                          <span className="rounded bg-kairos-bg px-1.5 py-0.2 text-[9.5px] font-mono text-cyan-300 shrink-0">
                            {isCanvas ? 'canvas' : isBase ? 'base' : doc.type}
                          </span>
                        </div>
                        <div className="font-mono text-[10px] text-slate-500 truncate">
                          {doc.rel_path}
                        </div>
                        {doc.excerpt && (
                          <div className="text-[10.5px] text-slate-400 line-clamp-2">
                            {doc.excerpt}
                          </div>
                        )}
                      </button>
                    );
                  })
                )}
              </div>
            </div>

            {/* Right 8 Cols: Live Project Wiki Reader & Markdown Editor */}
            <div className="lg:col-span-8 rounded-xl border border-kairos-border bg-kairos-panel p-4 flex flex-col min-h-[540px]">
              {!activeDocDetail ? (
                <div className="flex-1 flex flex-col items-center justify-center text-center text-xs text-slate-400 gap-2">
                  <FileText className="h-8 w-8 text-slate-600" />
                  <div>Select a Wiki page on the left or create a new Project Note.</div>
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-kairos-border pb-3 mb-3">
                    <div className="min-w-0">
                      <div className="text-sm font-bold text-white truncate">
                        {activeDocDetail.title}
                      </div>
                      <div className="font-mono text-[10.5px] text-slate-400 truncate">
                        {activeDocDetail.rel_path}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      {wikiDirty && (
                        <span className="rounded border border-amber-500/45 bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold text-amber-200">
                          ● Unsaved (Ctrl+S)
                        </span>
                      )}
                      {wikiSavedBanner && (
                        <span className="text-[11px] font-semibold text-emerald-300">
                          ✓ {wikiSavedBanner}
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => setWikiEditMode((v) => !v)}
                        className="flex items-center gap-1 rounded-lg border border-kairos-border bg-kairos-card px-2.5 py-1 text-xs font-medium text-slate-200 hover:border-emerald-500/40"
                      >
                        {wikiEditMode ? (
                          <>
                            <Eye className="h-3.5 w-3.5 text-cyan-300" /> Preview Wiki
                          </>
                        ) : (
                          <>
                            <Edit3 className="h-3.5 w-3.5 text-emerald-300" /> Edit Page
                          </>
                        )}
                      </button>

                      {wikiEditMode && (
                        <button
                          type="button"
                          onClick={handleSaveWikiDoc}
                          className="flex items-center gap-1 rounded-lg bg-emerald-500 px-3 py-1 text-xs font-bold text-slate-950 hover:bg-emerald-400"
                        >
                          <Save className="h-3.5 w-3.5" /> Save to Vault
                        </button>
                      )}

                      {!activeDocDetail.rel_path.endsWith('.canvas') &&
                        !activeDocDetail.rel_path.endsWith('.base') && (
                          <>
                            <button
                              type="button"
                              onClick={handleRetainWikiInHermes}
                              title="Retain this Project Wiki page summary into Hermes MEMORY.md"
                              className="rounded-lg border border-purple-500/40 bg-purple-500/15 px-2.5 py-1 text-xs font-semibold text-purple-200 hover:bg-purple-500/25"
                            >
                              🪽 Retain
                            </button>
                            <button
                              type="button"
                              onClick={handleDistillWikiAsHermesSkill}
                              title="Distill this Project Wiki note/SOP into a reusable Hermes SKL-*.md Skill"
                              className="rounded-lg border border-amber-500/40 bg-amber-500/15 px-2.5 py-1 text-xs font-semibold text-amber-200 hover:bg-amber-500/25"
                            >
                              🪽 Distill Skill
                            </button>
                          </>
                        )}

                      <button
                        type="button"
                        onClick={() => onOpenNoteInSecondBrain(activeDocDetail.rel_path)}
                        className="flex items-center gap-1 rounded-lg border border-cyan-500/35 bg-cyan-500/10 px-2.5 py-1 text-xs text-cyan-300 hover:bg-cyan-500/20"
                      >
                        <ExternalLink className="h-3.5 w-3.5" /> Second Brain
                      </button>
                    </div>
                  </div>

                  {wikiEditMode ? (
                    <div className="flex-1 flex flex-col gap-2 min-h-0">
                      {!activeDocDetail.rel_path.endsWith('.canvas') &&
                        !activeDocDetail.rel_path.endsWith('.base') &&
                        visibleTasks.length > 0 && (
                          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-[11px]">
                            <span className="font-semibold text-slate-400">
                              Link Project Task:
                            </span>
                            <select
                              value={quickInsertTaskId}
                              onChange={(e) => setQuickInsertTaskId(e.target.value)}
                              className="flex-1 min-w-[200px] rounded border border-kairos-border bg-kairos-panel px-2 py-1 text-xs text-white"
                            >
                              <option value="">Select task to embed [[TSK-...]] WikiLink...</option>
                              {visibleTasks.map((vt) => (
                                <option key={vt.id} value={vt.id}>
                                  {vt.id} — {vt.title} ({vt.status})
                                </option>
                              ))}
                            </select>
                            <button
                              type="button"
                              disabled={!quickInsertTaskId}
                              onClick={() => {
                                if (!quickInsertTaskId) return;
                                const chosen = visibleTasks.find((vt) => vt.id === quickInsertTaskId);
                                const snippet = chosen
                                  ? `\n- [[${chosen.id}]] — ${chosen.title} (${chosen.status})`
                                  : `\n- [[${quickInsertTaskId}]]`;
                                setWikiDraftBody((prev) => `${prev.trimEnd()}${snippet}\n`);
                                setQuickInsertTaskId('');
                              }}
                              className="rounded-md bg-emerald-500/20 border border-emerald-500/40 px-2.5 py-1 text-[11px] font-semibold text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-40"
                            >
                              + Insert [[Task]]
                            </button>
                          </div>
                        )}
                      <textarea
                        value={wikiDraftBody}
                        onChange={(e) => setWikiDraftBody(e.target.value)}
                        onKeyDown={(e) => {
                          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
                            e.preventDefault();
                            handleSaveWikiDoc();
                          }
                        }}
                        className="flex-1 w-full rounded-xl border border-kairos-border bg-kairos-bg p-3.5 font-mono text-xs leading-relaxed text-slate-100 focus:border-emerald-500/60 focus:outline-none resize-none"
                      />
                    </div>
                  ) : activeDocDetail.rel_path.toLowerCase().endsWith('.base') ? (
                    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-y-auto">
                      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2">
                        <div className="flex items-center gap-2 text-xs font-bold text-emerald-200">
                          <Table2 className="h-4 w-4 text-emerald-300" />
                          <span>
                            Live Obsidian `.base` Database (
                            {projectBaseResult?.total_rows ?? projectBaseResult?.rows.length ?? 0}{' '}
                            rows)
                          </span>
                        </div>
                        {projectBaseResult && projectBaseResult.views.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1">
                            {projectBaseResult.views.map((vw) => {
                              const activeVw = projectBaseResult.active_view?.name === vw.name;
                              return (
                                <button
                                  key={vw.name}
                                  type="button"
                                  onClick={() => setActiveProjectBaseView(vw.name)}
                                  className={`rounded-md px-2 py-0.5 text-[11px] font-semibold transition ${
                                    activeVw
                                      ? 'bg-emerald-500 text-slate-950'
                                      : 'bg-kairos-bg text-slate-300 border border-kairos-border hover:border-emerald-500/40'
                                  }`}
                                >
                                  {vw.name}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>

                      {projectBaseLoading ? (
                        <div className="rounded-xl border border-kairos-border bg-kairos-bg p-4 text-xs text-slate-400">
                          Evaluating Obsidian `.base` filters, formulas, and summaries...
                        </div>
                      ) : projectBaseResult ? (
                        <>
                          <div className="overflow-x-auto rounded-xl border border-kairos-border bg-kairos-bg">
                            <table className="w-full text-left border-collapse text-xs">
                              <thead>
                                <tr className="border-b border-kairos-border bg-kairos-card/70 text-[10.5px] uppercase tracking-wider text-slate-400">
                                  {projectBaseResult.columns.map((col) => (
                                    <th key={col.key} className="px-3 py-2 font-semibold whitespace-nowrap">
                                      {col.label}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-kairos-border/60">
                                {projectBaseResult.rows.length === 0 ? (
                                  <tr>
                                    <td
                                      colSpan={Math.max(projectBaseResult.columns.length, 1)}
                                      className="px-3 py-4 text-center text-slate-500"
                                    >
                                      No vault entries match this `.base` view yet.
                                    </td>
                                  </tr>
                                ) : (
                                  projectBaseResult.rows.map((row) => {
                                    const rowTaskId = String(row.task_id || '');
                                    const isTaskRow = rowTaskId.startsWith('TSK-');
                                    return (
                                      <tr
                                        key={row.rel_path}
                                        onClick={() => {
                                          if (isTaskRow) {
                                            setSelectedTaskId(rowTaskId);
                                          } else if (row.rel_path) {
                                            setSelectedDocPath(row.rel_path);
                                          }
                                        }}
                                        className="cursor-pointer hover:bg-emerald-500/10 transition"
                                        title={
                                          isTaskRow
                                            ? `Click to inspect Task ${rowTaskId}`
                                            : `Click to open ${row.rel_path}`
                                        }
                                      >
                                        {projectBaseResult.columns.map((col) => {
                                          const rawVal = row.cells[col.key];
                                          const display =
                                            rawVal === null || rawVal === undefined || rawVal === ''
                                              ? '—'
                                              : Array.isArray(rawVal)
                                                ? rawVal.join(', ')
                                                : String(rawVal);
                                          return (
                                            <td
                                              key={col.key}
                                              className={`px-3 py-2 whitespace-nowrap ${
                                                col.key === 'file.name'
                                                  ? 'font-semibold text-emerald-300'
                                                  : col.key.startsWith('formula.')
                                                    ? 'font-mono text-cyan-200'
                                                    : 'text-slate-200'
                                              }`}
                                            >
                                              {display}
                                            </td>
                                          );
                                        })}
                                      </tr>
                                    );
                                  })
                                )}
                              </tbody>
                            </table>
                          </div>

                          {Object.keys(projectBaseResult.summaries || {}).length > 0 && (
                            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-kairos-border bg-kairos-card/60 px-3 py-1.5 text-[11px] text-slate-300">
                              <span className="font-semibold text-emerald-300">Summaries:</span>
                              {Object.entries(projectBaseResult.summaries).map(
                                ([colKey, summaryEntry]) => (
                                  <span
                                    key={colKey}
                                    className="rounded border border-kairos-border bg-kairos-bg px-2 py-0.5 font-mono text-[10.5px]"
                                  >
                                    {colKey} ({summaryEntry.formula}):{' '}
                                    <strong className="text-white">
                                      {String(summaryEntry.value ?? '—')}
                                    </strong>
                                  </span>
                                )
                              )}
                            </div>
                          )}
                        </>
                      ) : (
                        <div className="rounded-xl border border-kairos-border bg-kairos-bg p-4 text-xs text-slate-400">
                          Unable to evaluate `.base` file. Click <strong>Edit Page</strong> to inspect raw YAML or open in Second Brain for full inline cell editing.
                        </div>
                      )}
                    </div>
                  ) : parsedCanvasPreview ? (
                    <div className="flex-1 space-y-3 overflow-y-auto">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="text-xs font-semibold text-cyan-300">
                          🎨 JSON Canvas Whiteboard Nodes ({parsedCanvasPreview.nodes?.length || 0}{' '}
                          nodes, {parsedCanvasPreview.edges?.length || 0} connections)
                        </div>
                      </div>

                      <form onSubmit={handleAddWikiCanvasNode} className="flex items-center gap-2">
                        <input
                          type="text"
                          value={newWikiCanvasCardText}
                          onChange={(e) => setNewWikiCanvasCardText(e.target.value)}
                          placeholder="Add interactive card to this .canvas whiteboard (supports [[TSK-...]] & [[WikiLinks]])..."
                          className="flex-1 rounded-lg border border-kairos-border bg-kairos-bg px-3 py-1.5 text-xs text-white focus:border-cyan-500/60 focus:outline-none"
                        />
                        <button
                          type="submit"
                          className="flex items-center gap-1 rounded-lg bg-cyan-500 px-3 py-1.5 text-xs font-bold text-slate-950 hover:bg-cyan-400"
                        >
                          <Plus className="h-3.5 w-3.5" /> Add Card
                        </button>
                      </form>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {(parsedCanvasPreview.nodes || []).map((nd) => (
                          <div
                            key={nd.id}
                            className="rounded-xl border border-cyan-500/30 bg-kairos-bg p-3.5 whitespace-pre-wrap text-xs text-slate-200 space-y-1.5"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-mono text-[10px] text-cyan-400">
                                Node: {nd.id}
                              </span>
                              <button
                                type="button"
                                title="Remove canvas card"
                                onClick={() => handleRemoveWikiCanvasNode(nd.id)}
                                className="rounded p-0.5 text-slate-500 hover:bg-rose-500/20 hover:text-rose-300 transition"
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </div>
                            <div className="leading-relaxed">
                              {renderInlineWikiTokens(nd.text || nd.file || '(Canvas node)')}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="flex-1 overflow-y-auto rounded-xl border border-kairos-border/60 bg-kairos-bg/70 p-4 space-y-3">
                      {renderRichWikiBody(activeDocDetail.body)}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Add New Custom Category Modal */}
      {showAddCategoryModal && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4">
          <form
            onSubmit={handleAddCategory}
            className="w-full max-w-md rounded-2xl border border-cyan-500/45 bg-[#0B101B] p-5 space-y-3 shadow-[0_20px_60px_rgba(0,0,0,0.95)]"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-bold text-white">
                <FolderPlus className="h-4 w-4 text-cyan-400" />
                Add New Project Category
              </div>
              <button
                type="button"
                onClick={() => setShowAddCategoryModal(false)}
                className="text-xs text-slate-400 hover:text-white"
              >
                Cancel
              </button>
            </div>

            <p className="text-xs text-slate-400">
              Creates `02_Projects/[Project]/[Category]/[List]/Tasks/` and registers the new
              category inside `_Project_Index.md`.
            </p>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">Project</label>
              <select
                value={catProject}
                onChange={(e) => setCatProject(e.target.value)}
                className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-2 text-xs text-white"
              >
                {projectsTree.map((p) => (
                  <option key={p.name} value={p.name}>
                    🚀 {p.name.replace(/_/g, ' ')}
                  </option>
                ))}
                {projectsTree.length === 0 && <option value="KAIROS_2_0">KAIROS 2.0</option>}
              </select>
            </div>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">
                Category Name
              </label>
              <input
                type="text"
                required
                value={catName}
                onChange={(e) => setCatName(e.target.value)}
                placeholder="e.g. Hardware R and D, Podcast, Operations, Legal..."
                className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-2 text-xs text-white"
              />
            </div>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">
                Initial List / Sprint Name
              </label>
              <input
                type="text"
                value={catDefaultList}
                onChange={(e) => setCatDefaultList(e.target.value)}
                placeholder="General or Sprint_01"
                className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-2 text-xs text-white"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowAddCategoryModal(false)}
                className="rounded-lg border border-kairos-border px-3 py-1.5 text-xs text-slate-300"
              >
                Close
              </button>
              <button
                type="submit"
                className="rounded-lg bg-cyan-500 px-4 py-1.5 text-xs font-bold text-slate-950 hover:bg-cyan-400"
              >
                Create Category
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Create New Project Wiki Note / Canvas Modal */}
      {showNewWikiModal && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4">
          <form
            onSubmit={handleCreateWikiItem}
            className="w-full max-w-md rounded-2xl border border-emerald-500/45 bg-[#0B101B] p-5 space-y-3 shadow-[0_20px_60px_rgba(0,0,0,0.95)]"
          >
            <div className="flex items-center justify-between">
              <div className="text-sm font-bold text-white">
                {showNewWikiModal === 'canvas'
                  ? '🎨 New Project Canvas (.canvas)'
                  : '📘 New Project Wiki Note (.md)'}
              </div>
              <button
                type="button"
                onClick={() => setShowNewWikiModal(null)}
                className="text-xs text-slate-400 hover:text-white"
              >
                Cancel
              </button>
            </div>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">Project</label>
              <select
                value={newWikiTargetProject}
                onChange={(e) => setNewWikiTargetProject(e.target.value)}
                className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-2 text-xs text-white"
              >
                {projectsTree.map((p) => (
                  <option key={p.name} value={p.name}>
                    🚀 {p.name.replace(/_/g, ' ')}
                  </option>
                ))}
                {projectsTree.length === 0 && <option value="KAIROS_2_0">KAIROS 2.0</option>}
              </select>
            </div>

            <div>
              <label className="block text-[10px] uppercase text-slate-400 mb-1">Page Title</label>
              <input
                type="text"
                required
                value={newWikiTitle}
                onChange={(e) => setNewWikiTitle(e.target.value)}
                placeholder={
                  showNewWikiModal === 'canvas'
                    ? 'e.g. System Dataflow Canvas'
                    : 'e.g. Q4 Launch Strategy & Decisions'
                }
                className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-2 text-xs text-white"
              />
            </div>

            {showNewWikiModal === 'note' && (
              <div>
                <label className="block text-[10px] uppercase text-slate-400 mb-1">
                  Wiki Template
                </label>
                <select
                  value={newWikiTemplate}
                  onChange={(e) => setNewWikiTemplate(e.target.value as WikiTemplateKind)}
                  className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-2 text-xs text-white"
                >
                  <option value="blank">📄 Blank Project Wiki Note</option>
                  <option value="meeting">📝 Meeting & Decisions Log</option>
                  <option value="spec">🏗️ Technical Architecture Spec</option>
                  <option value="playbook">📘 SOP / Team Playbook</option>
                </select>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowNewWikiModal(null)}
                className="rounded-lg border border-kairos-border px-3 py-1.5 text-xs text-slate-300"
              >
                Close
              </button>
              <button
                type="submit"
                className="rounded-lg bg-emerald-500 px-4 py-1.5 text-xs font-bold text-slate-950 hover:bg-emerald-400"
              >
                Create in Project Wiki
              </button>
            </div>
          </form>
        </div>
      )}

      {/* New Project Task Modal */}
      {showNewModal && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4">
          <form
            onSubmit={handleCreateTask}
            className="w-full max-w-lg rounded-2xl border border-slate-700/90 bg-[#0B101B] p-5 space-y-3 shadow-[0_20px_60px_rgba(0,0,0,0.95)]"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-bold text-white">
                <Sparkles className="h-4 w-4 text-emerald-400" />
                Create Obsidian-Backed Project Task (`TSK-*.md`)
              </div>
              <button
                type="button"
                onClick={() => setShowNewModal(false)}
                className="text-xs text-slate-400 hover:text-white"
              >
                Cancel
              </button>
            </div>

            <input
              type="text"
              required
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="Task title..."
              className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-2 text-sm text-white"
            />

            <div className="grid grid-cols-3 gap-2">
              <input
                type="text"
                value={newProject}
                onChange={(e) => setNewProject(e.target.value)}
                placeholder="Project (e.g. KAIROS_2_0)"
                className="rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-white"
              />
              {!useCustomTaskCategory &&
              availableCategoriesForModal.some((d) => d.id === newDepartment) ? (
                <select
                  value={newDepartment}
                  onChange={(e) => {
                    const deptId = e.target.value;
                    if (deptId === '__custom__') {
                      setUseCustomTaskCategory(true);
                      setNewDepartment('');
                      setNewList('General');
                      return;
                    }
                    setNewDepartment(deptId);
                    const found = availableCategoriesForModal.find((d) => d.id === deptId);
                    if (found) setNewList(found.defaultList);
                  }}
                  className="rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-xs text-white"
                >
                  {availableCategoriesForModal.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.emoji} {d.label}
                    </option>
                  ))}
                  <option value="__custom__">✨ Custom Category...</option>
                </select>
              ) : (
                <div className="flex items-center gap-1">
                  <input
                    type="text"
                    value={newDepartment}
                    onChange={(e) => setNewDepartment(e.target.value)}
                    placeholder="Custom Category (e.g. R_and_D)"
                    className="min-w-0 flex-1 rounded border border-emerald-500/50 bg-kairos-bg px-2 py-1.5 text-xs text-white"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      setUseCustomTaskCategory(false);
                      setNewDepartment(availableCategoriesForModal[0]?.id || 'Software_Development');
                    }}
                    className="rounded border border-kairos-border px-1.5 py-1.5 text-[10px] text-slate-400 hover:text-white shrink-0"
                    title="Switch back to preset categories"
                  >
                    Presets
                  </button>
                </div>
              )}
              <input
                type="text"
                value={newList}
                onChange={(e) => setNewList(e.target.value)}
                placeholder="List / Sprint"
                className="rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-white"
              />
            </div>

            <div className="grid grid-cols-4 gap-2">
              <select
                value={newPriority}
                onChange={(e) => setNewPriority(Number(e.target.value))}
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-xs text-white"
              >
                <option value={1}>P1 Urgent</option>
                <option value={2}>P2 High</option>
                <option value={3}>P3 Normal</option>
                <option value={4}>P4 Low</option>
              </select>
              <input
                type="date"
                value={newStart}
                onChange={(e) => setNewStart(e.target.value)}
                title="Start Date"
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-xs text-white"
              />
              <input
                type="date"
                value={newDue}
                onChange={(e) => setNewDue(e.target.value)}
                title="Due Date"
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-xs text-white"
              />
              <select
                value={newAgent}
                onChange={(e) => setNewAgent(e.target.value)}
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-xs text-purple-300"
              >
                <option value="None">AI: None</option>
                <option value="Gemma-4">Gemma-4</option>
                <option value="Gemini-Pro">Gemini-Pro</option>
                <option value="CrewAI-Research">CrewAI-Research</option>
                <option value="CrewAI-Dev">CrewAI-Dev</option>
                <option value="CrewAI-PM">CrewAI-PM</option>
                <option value="Hermes-Agent">Hermes-Agent</option>
                <option value="Hermes-Synthesizer">Hermes-Synthesizer</option>
              </select>
            </div>

            <div className="grid grid-cols-3 gap-2">
              <select
                value={newParentTask}
                onChange={(e) => setNewParentTask(e.target.value)}
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-xs text-cyan-300"
              >
                <option value="">Parent Task: None</option>
                {tasks.map((t) => (
                  <option key={t.id} value={t.id}>
                    ↳ {t.id} ({t.title.slice(0, 18)})
                  </option>
                ))}
              </select>

              <select
                value={newDependsOn}
                onChange={(e) => setNewDependsOn(e.target.value)}
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-xs text-amber-300"
              >
                <option value="">Depends On: None</option>
                {tasks.map((t) => (
                  <option key={t.id} value={t.id}>
                    ⛓ {t.id} ({t.title.slice(0, 18)})
                  </option>
                ))}
              </select>

              <input
                type="number"
                min={0.5}
                step={0.5}
                value={newTimeEstimate}
                onChange={(e) => setNewTimeEstimate(Number(e.target.value))}
                placeholder="Est Hours"
                className="rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-white"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowNewModal(false)}
                className="rounded-lg border border-kairos-border px-3 py-1.5 text-xs text-slate-300"
              >
                Close
              </button>
              <button
                type="submit"
                className="rounded-lg bg-emerald-500 px-4 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-400"
              >
                Write `TSK-*.md` to Canopy Vault
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Slide-Over Task Drawer */}
      <TaskDrawer
        taskId={selectedTaskId}
        projectsTree={projectsTree}
        allTasks={tasks}
        onClose={() => setSelectedTaskId(null)}
        onSelectTaskId={(tid) => setSelectedTaskId(tid)}
        onUpdated={() => {
          onVaultMutated();
          reloadData();
        }}
        onOpenInSecondBrain={(rel) => {
          setSelectedTaskId(null);
          onOpenNoteInSecondBrain(rel);
        }}
        onNotify={onNotify}
      />
    </div>
  );
};

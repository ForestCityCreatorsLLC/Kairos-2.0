import React, { useMemo, useState } from 'react';
import {
  Bot,
  BotMessageSquare,
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  Database,
  FolderKanban,
  FolderPlus,
  Globe,
  Inbox,
  Layers,
  ListTodo,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRight,
  Search,
  Settings,
} from 'lucide-react';
import {
  ProjectTreeItem,
  STANDARD_DEPARTMENTS,
  VaultSectionHubSummary,
  kairosApi,
} from '../api/client.ts';
import { ToastKind } from './ToastCenter.tsx';

export type WorkspaceTab =
  | 'assistant'
  | 'inbox'
  | 'second-brain'
  | 'projects'
  | 'browser'
  | 'paperclip'
  | 'settings';

export interface ProjectScopeSelection {
  project: string;
  department: string;
  list: string;
}

const DEPT_EMOJI_MAP: Record<string, string> = {
  Software_Development: '💻',
  Marketing_and_Branding: '📣',
  Documentation: '📄',
  Website: '🌐',
  Merch: '👕',
};

export function formatProjectDisplayName(name: string): string {
  return name.replace(/_(\d+)_(\d+)(?=_|$)/g, ' $1.$2').replace(/_/g, ' ');
}

interface LeftSidebarProps {
  activeTab: WorkspaceTab;
  onSelectTab: (tab: WorkspaceTab) => void;
  projects: ProjectTreeItem[];
  vaultSections?: VaultSectionHubSummary[];
  selectedNotePath?: string;
  onOpenSectionNote?: (relPath: string) => void;
  projectScope: ProjectScopeSelection;
  onSelectProjectScope: (scope: ProjectScopeSelection) => void;
  totalTasks: number;
  inboxCount: number;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  chatDrawerOpen?: boolean;
  onToggleChatDrawer?: () => void;
  onOpenCommandPalette: () => void;
  onStructureCreated: () => void;
  onNotify?: (kind: ToastKind, title: string, detail?: string) => void;
}

export const LeftSidebar: React.FC<LeftSidebarProps> = ({
  activeTab,
  onSelectTab,
  projects,
  vaultSections = [],
  selectedNotePath = '',
  onOpenSectionNote,
  projectScope,
  onSelectProjectScope,
  totalTasks,
  inboxCount,
  collapsed = false,
  onToggleCollapsed,
  chatDrawerOpen = true,
  onToggleChatDrawer,
  onOpenCommandPalette,
  onStructureCreated,
  onNotify,
}) => {
  const [projectsExpanded, setProjectsExpanded] = useState(true);
  const [sectionsExpanded, setSectionsExpanded] = useState(true);
  const [collapsedProjects, setCollapsedProjects] = useState<Record<string, boolean>>({});
  const [collapsedDepts, setCollapsedDepts] = useState<Record<string, boolean>>({});

  const [showNewStructure, setShowNewStructure] = useState(false);
  const [createMode, setCreateMode] = useState<'new-project' | 'add-category' | 'add-list'>(
    'new-project'
  );
  const [projectName, setProjectName] = useState('Canopy_Brand_OS');
  const [departmentName, setDepartmentName] = useState('Software_Development');
  const [listName, setListName] = useState('Sprint_01');
  const [resyncing, setResyncing] = useState(false);
  const [creatingStructure, setCreatingStructure] = useState(false);

  const availableCategoriesForProject = useMemo(() => {
    const map = new Map<string, { id: string; label: string; defaultList: string; emoji: string }>();
    for (const d of STANDARD_DEPARTMENTS) {
      map.set(d.id, { id: d.id, label: d.label, defaultList: d.defaultList, emoji: d.emoji });
    }
    const targetProj = projects.find((p) => p.name === projectName.trim());
    if (targetProj) {
      for (const custom of targetProj.departments) {
        if (!map.has(custom.name)) {
          map.set(custom.name, {
            id: custom.name,
            label: custom.name.replace(/_/g, ' '),
            defaultList: custom.lists[0]?.name || 'General',
            emoji: DEPT_EMOJI_MAP[custom.name] || '📂',
          });
        }
      }
    }
    return Array.from(map.values());
  }, [projects, projectName]);

  const handleDepartmentPresetChange = (deptVal: string) => {
    setDepartmentName(deptVal);
    const found = availableCategoriesForProject.find((d) => d.id === deptVal);
    if (found) {
      setListName(found.defaultList);
    }
  };

  const handleResyncVault = async () => {
    setResyncing(true);
    try {
      await kairosApi.resyncProjects();
      onStructureCreated();
    } catch {
      // ignore if still starting
    } finally {
      setResyncing(false);
    }
  };

  const handleCreateStructure = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!projectName.trim() || creatingStructure) return;
    const isFullTemplate = createMode === 'new-project';
    const targetDept = isFullTemplate
      ? 'Software_Development'
      : departmentName.trim().replace(/\s+/g, '_') || 'Custom_Category';
    const targetList = isFullTemplate
      ? 'Sprint_01'
      : listName.trim().replace(/\s+/g, '_') || 'General';

    setCreatingStructure(true);
    try {
      const created = await kairosApi.createProjectStructure(
        projectName.trim(),
        targetDept,
        targetList,
        isFullTemplate
      );
      setShowNewStructure(false);
      onStructureCreated();
      onSelectTab('projects');
      if (isFullTemplate) {
        onSelectProjectScope({
          project: created.project,
          department: '',
          list: '',
        });
      } else if (createMode === 'add-category') {
        onSelectProjectScope({
          project: created.project,
          department: created.department,
          list: '',
        });
      } else {
        onSelectProjectScope({
          project: created.project,
          department: created.department,
          list: created.list,
        });
      }
      onNotify?.(
        'success',
        isFullTemplate ? 'Scaffolded Project' : 'Created Project Folder',
        `${created.project}/${created.department}`
      );
    } catch (err) {
      onNotify?.(
        'error',
        'Failed to Create Project Structure',
        err instanceof Error ? err.message : 'Unable to create Canopy Vault project structure'
      );
    } finally {
      setCreatingStructure(false);
    }
  };

  const navBtn = (tab: WorkspaceTab, label: string, icon: React.ReactNode, badge?: number) => {
    const active = activeTab === tab;
    return (
      <button
        type="button"
        onClick={() => onSelectTab(tab)}
        className={`w-full flex items-center justify-between rounded-lg px-3 py-2 text-xs font-medium transition ${
          active
            ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
            : 'text-slate-300 hover:bg-kairos-card border border-transparent'
        }`}
      >
        <span className="flex items-center gap-2.5">
          {icon}
          <span>{label}</span>
        </span>
        {badge !== undefined && (
          <span className="rounded-full bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300">
            {badge}
          </span>
        )}
      </button>
    );
  };

  const iconRailBtn = (
    tab: WorkspaceTab,
    tooltip: string,
    icon: React.ReactNode,
    badge?: number,
    onCustomClick?: () => void
  ) => {
    const active = activeTab === tab;
    return (
      <button
        type="button"
        title={tooltip}
        aria-label={tooltip}
        onClick={onCustomClick || (() => onSelectTab(tab))}
        className={`relative flex h-9 w-9 items-center justify-center rounded-lg transition ${
          active
            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm'
            : 'text-slate-300 hover:bg-kairos-card hover:text-white border border-transparent'
        }`}
      >
        {icon}
        {badge !== undefined && badge > 0 && (
          <span className="absolute -right-1 -top-1 min-w-[15px] rounded-full bg-emerald-500 px-1 text-center text-[9px] font-bold leading-[14px] text-slate-950">
            {badge > 99 ? '99+' : badge}
          </span>
        )}
      </button>
    );
  };

  if (collapsed) {
    const projectNamesSummary =
      projects.map((p) => formatProjectDisplayName(p.name)).join(', ') || 'Canopy Vault';
    return (
      <aside className="w-14 shrink-0 border-r border-kairos-border bg-kairos-panel flex flex-col items-center justify-between py-2.5 px-1.5 overflow-y-auto overflow-x-hidden select-none transition-all duration-150">
        <div className="flex flex-col items-center gap-1.5 w-full">
          {onToggleCollapsed && (
            <button
              type="button"
              onClick={onToggleCollapsed}
              title="Expand Workspace Menu"
              aria-label="Expand Workspace Menu"
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-kairos-border bg-kairos-bg text-slate-300 hover:border-emerald-500/40 hover:text-emerald-300 transition"
            >
              <PanelLeftOpen className="h-4 w-4" />
            </button>
          )}

          <button
            type="button"
            onClick={onOpenCommandPalette}
            title="Quick Jump Omni-Search (Ctrl+K)"
            aria-label="Quick Jump Omni-Search (Ctrl+K)"
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-kairos-border bg-kairos-bg text-slate-400 hover:border-emerald-500/40 hover:text-slate-200 transition"
          >
            <Search className="h-4 w-4 text-emerald-400" />
          </button>

          <div className="w-7 border-t border-kairos-border my-0.5" />

          {iconRailBtn(
            'assistant',
            'KAIROS Assistant',
            <BotMessageSquare className="h-4 w-4 text-emerald-400" />
          )}
          {iconRailBtn(
            'inbox',
            `Inbox (00_Inbox) — ${inboxCount}`,
            <Inbox className="h-4 w-4 text-cyan-400" />,
            inboxCount
          )}
          {iconRailBtn(
            'second-brain',
            vaultSections.length > 0
              ? `Second Brain (Vault) — ${vaultSections.length} Section Hub(s)`
              : 'Second Brain (Vault)',
            <BrainCircuit className="h-4 w-4 text-emerald-400" />,
            vaultSections.length > 0 ? vaultSections.length : undefined
          )}
          {iconRailBtn(
            'projects',
            `Projects (${projectNamesSummary}) — ${totalTasks} tasks`,
            <FolderKanban className="h-4 w-4 text-amber-400" />,
            undefined,
            () => {
              onSelectTab('projects');
            }
          )}
          {iconRailBtn(
            'browser',
            'Browser & Clipper',
            <Globe className="h-4 w-4 text-sky-400" />
          )}
          {iconRailBtn(
            'paperclip',
            'Paperclip, CrewAI & Hermes',
            <Bot className="h-4 w-4 text-purple-400" />
          )}
        </div>

        <div className="pt-2 border-t border-kairos-border w-full flex flex-col items-center gap-1.5">
          {onToggleChatDrawer && activeTab !== 'assistant' && (
            <button
              type="button"
              onClick={onToggleChatDrawer}
              title={
                chatDrawerOpen
                  ? 'Collapse KAIROS Chat Panel (Ctrl+\\)'
                  : 'Open KAIROS Chat Panel (Ctrl+\\)'
              }
              aria-label={
                chatDrawerOpen
                  ? 'Collapse KAIROS Chat Panel'
                  : 'Open KAIROS Chat Panel'
              }
              className={`flex h-9 w-9 items-center justify-center rounded-lg border transition ${
                chatDrawerOpen
                  ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                  : 'border-kairos-border bg-kairos-bg text-slate-400 hover:border-emerald-500/40 hover:text-emerald-300'
              }`}
            >
              <PanelRight className="h-4 w-4" />
            </button>
          )}
          {iconRailBtn(
            'settings',
            'System & API Config',
            <Settings className="h-4 w-4 text-slate-400" />
          )}
        </div>
      </aside>
    );
  }

  return (
    <aside className="w-64 shrink-0 border-r border-kairos-border bg-kairos-panel flex flex-col justify-between p-2.5 overflow-y-auto select-none transition-all duration-150">
      <div className="space-y-1.5">
        {/* Quick Jump Omni-Search (Ctrl+K) + Retract Sidebar Toggle */}
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={onOpenCommandPalette}
            className="flex-1 min-w-0 flex items-center justify-between rounded-lg border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-slate-400 hover:border-emerald-500/40 hover:text-slate-200 transition"
          >
            <span className="flex items-center gap-2 truncate">
              <Search className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
              <span className="truncate">Quick Jump...</span>
            </span>
            <span className="rounded border border-kairos-border bg-kairos-panel px-1.5 py-0.5 font-mono text-[9px] text-slate-400 shrink-0">
              Ctrl+K
            </span>
          </button>
          {onToggleCollapsed && (
            <button
              type="button"
              onClick={onToggleCollapsed}
              title="Retract Sidebar to Icon Menu"
              aria-label="Retract Sidebar to Icon Menu"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-kairos-border bg-kairos-bg text-slate-400 hover:border-emerald-500/40 hover:text-emerald-300 transition"
            >
              <PanelLeftClose className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        <div className="px-2 pt-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Workspace Menu
        </div>

        {navBtn(
          'assistant',
          'KAIROS Assistant',
          <BotMessageSquare className="h-4 w-4 text-emerald-400" />
        )}
        {navBtn('inbox', 'Inbox (00_Inbox)', <Inbox className="h-4 w-4 text-cyan-400" />, inboxCount)}
        {navBtn(
          'second-brain',
          'Second Brain (Vault)',
          <BrainCircuit className="h-4 w-4 text-emerald-400" />,
          vaultSections.length > 0 ? vaultSections.length : undefined
        )}
        {vaultSections.length > 0 && onOpenSectionNote && (
          <div className="ml-2.5 pl-2 border-l border-kairos-border space-y-0.5">
            <button
              type="button"
              onClick={() => setSectionsExpanded((p) => !p)}
              className="w-full flex items-center justify-between rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-purple-300/90 hover:text-purple-200"
            >
              <span className="flex items-center gap-1">
                {sectionsExpanded ? (
                  <ChevronDown className="h-2.5 w-2.5" />
                ) : (
                  <ChevronRight className="h-2.5 w-2.5" />
                )}
                <span>Section Hubs ({vaultSections.length})</span>
              </span>
            </button>
            {sectionsExpanded &&
              vaultSections.map((sec) => {
                const hubSelected =
                  activeTab === 'second-brain' &&
                  Boolean(selectedNotePath) &&
                  selectedNotePath.startsWith(`${sec.section_rel}/`);
                return (
                  <div
                    key={sec.section_rel}
                    className={`flex items-center justify-between gap-1 rounded px-1.5 py-0.5 text-[11px] transition ${
                      hubSelected
                        ? 'bg-purple-500/20 text-purple-200 font-medium'
                        : 'text-slate-300 hover:bg-kairos-card/60 hover:text-white'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onOpenSectionNote(sec.hub_index_rel)}
                      title={`Open ${sec.title} Hub MOC (${sec.hub_index_rel})`}
                      className="flex-1 min-w-0 flex items-center gap-1.5 text-left truncate"
                    >
                      <span className="shrink-0">{sec.icon || '🗂️'}</span>
                      <span className="truncate">{sec.title}</span>
                    </button>
                    <div className="flex items-center gap-1 shrink-0">
                      {sec.base_rel && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onOpenSectionNote(sec.base_rel);
                          }}
                          title={`Open Live .base Catalog (${sec.base_rel})`}
                          className="rounded p-0.5 text-emerald-400 hover:bg-emerald-500/20 hover:text-emerald-200"
                        >
                          <Database className="h-2.5 w-2.5" />
                        </button>
                      )}
                      <span className="text-[9.5px] text-slate-500">
                        {sec.entry_count ?? 0}
                      </span>
                    </div>
                  </div>
                );
              })}
          </div>
        )}

        {/* Projects Hierarchy (`02_Projects/[Project]/[Department]/[List]`) */}
        <div className="pt-1">
          <div
            className={`w-full flex items-center justify-between rounded-lg px-3 py-2 text-xs font-medium cursor-pointer transition ${
              activeTab === 'projects'
                ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                : 'text-slate-200 hover:bg-kairos-card border border-transparent'
            }`}
            onClick={() => {
              onSelectTab('projects');
              onSelectProjectScope({ project: '', department: '', list: '' });
            }}
          >
            <span className="flex items-center gap-2.5">
              <FolderKanban className="h-4 w-4 text-amber-400" />
              <span>Projects</span>
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                title="Create New Project or Add Department / Sprint"
                onClick={(e) => {
                  e.stopPropagation();
                  setShowNewStructure((v) => !v);
                }}
                className="p-0.5 text-slate-400 hover:text-emerald-300"
              >
                <FolderPlus className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setProjectsExpanded((p) => !p);
                }}
                className="p-0.5 text-slate-400 hover:text-white"
              >
                {projectsExpanded ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
          </div>

          {showNewStructure && (
            <form
              onSubmit={handleCreateStructure}
              className="mt-1.5 rounded-lg border border-kairos-border bg-kairos-bg p-2.5 space-y-2 text-[11px]"
            >
              <div className="grid grid-cols-3 gap-1 rounded bg-kairos-panel p-0.5 text-[10px]">
                <button
                  type="button"
                  onClick={() => setCreateMode('new-project')}
                  className={`rounded py-1 font-semibold transition ${
                    createMode === 'new-project'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  🚀 Project
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCreateMode('add-category');
                    if (projectScope.project) {
                      setProjectName(projectScope.project);
                    } else if (projects.length > 0) {
                      setProjectName(projects[0].name);
                    }
                    setDepartmentName('Research_and_Design');
                    setListName('General');
                  }}
                  className={`rounded py-1 font-semibold transition ${
                    createMode === 'add-category'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  📂 + Category
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCreateMode('add-list');
                    if (projectScope.project) {
                      setProjectName(projectScope.project);
                    } else if (projects.length > 0) {
                      setProjectName(projects[0].name);
                    }
                  }}
                  className={`rounded py-1 font-semibold transition ${
                    createMode === 'add-list'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  ➕ + List
                </button>
              </div>

              {createMode === 'new-project' ? (
                <>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">
                      New Project Name
                    </label>
                    <input
                      type="text"
                      value={projectName}
                      onChange={(e) => setProjectName(e.target.value)}
                      placeholder="e.g. Canopy_Brand_OS"
                      className="w-full rounded border border-kairos-border bg-kairos-panel px-2 py-1 text-white"
                    />
                  </div>
                  <div className="rounded border border-emerald-500/20 bg-emerald-500/5 px-2 py-1.5 text-[10px] text-slate-300 leading-relaxed">
                    <span className="font-semibold text-emerald-300">KAIROS 2.0 Template:</span>{' '}
                    Scaffolds <code className="text-emerald-200">_Project_Index.md</code>,{' '}
                    <code className="text-emerald-200">Docs/Architecture_Diagram.canvas</code>, plus{' '}
                    <span className="text-slate-200">
                      💻 Software Dev, 📣 Marketing, 📄 Docs, 🌐 Website & 👕 Merch
                    </span>
                    .
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">
                      Target Project
                    </label>
                    {projects.length > 0 && (
                      <select
                        value={
                          projects.some((p) => p.name === projectName) ? projectName : '__custom__'
                        }
                        onChange={(e) => {
                          if (e.target.value !== '__custom__') {
                            setProjectName(e.target.value);
                          }
                        }}
                        className="w-full rounded border border-kairos-border bg-kairos-panel px-2 py-1 text-white mb-1"
                      >
                        {projects.map((p) => (
                          <option key={p.name} value={p.name}>
                            📁 {formatProjectDisplayName(p.name)}
                          </option>
                        ))}
                        <option value="__custom__">✨ Custom Project...</option>
                      </select>
                    )}
                    <input
                      type="text"
                      value={projectName}
                      onChange={(e) => setProjectName(e.target.value)}
                      placeholder="e.g. KAIROS_2_0"
                      className="w-full rounded border border-kairos-border bg-kairos-panel px-2 py-1 text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">
                      {createMode === 'add-category' ? 'New Category Name' : 'Category / Department'}
                    </label>
                    {createMode === 'add-list' && (
                      <select
                        value={
                          availableCategoriesForProject.some((d) => d.id === departmentName)
                            ? departmentName
                            : '__custom__'
                        }
                        onChange={(e) => {
                          if (e.target.value !== '__custom__') {
                            handleDepartmentPresetChange(e.target.value);
                          }
                        }}
                        className="w-full rounded border border-kairos-border bg-kairos-panel px-2 py-1 text-white mb-1"
                      >
                        {availableCategoriesForProject.map((d) => (
                          <option key={d.id} value={d.id}>
                            {d.emoji} {d.label}
                          </option>
                        ))}
                        <option value="__custom__">✨ Custom Category...</option>
                      </select>
                    )}
                    <input
                      type="text"
                      value={departmentName}
                      onChange={(e) => setDepartmentName(e.target.value)}
                      placeholder="e.g. Hardware_R_and_D or Podcast"
                      className="w-full rounded border border-kairos-border bg-kairos-panel px-2 py-1 text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">
                      {createMode === 'add-category'
                        ? 'Default List inside Category'
                        : 'New List / Sprint'}
                    </label>
                    <input
                      type="text"
                      value={listName}
                      onChange={(e) => setListName(e.target.value)}
                      placeholder="e.g. Sprint_02 or Launch_Week"
                      className="w-full rounded border border-kairos-border bg-kairos-panel px-2 py-1 text-white"
                    />
                  </div>
                </>
              )}

              <div className="flex justify-end gap-1 pt-0.5">
                <button
                  type="button"
                  onClick={() => setShowNewStructure(false)}
                  className="rounded px-2 py-0.5 text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingStructure}
                  className="rounded bg-emerald-500 px-2.5 py-0.5 font-semibold text-slate-950 disabled:opacity-50"
                >
                  {creatingStructure
                    ? 'Saving...'
                    : createMode === 'new-project'
                      ? 'Scaffold Project'
                      : createMode === 'add-category'
                        ? 'Add Category'
                        : 'Add List'}
                </button>
              </div>
            </form>
          )}

          {projectsExpanded && (
            <div className="mt-1 ml-2.5 pl-2 border-l border-kairos-border space-y-1">
              {/* Top Row under Projects: Everything */}
              <button
                type="button"
                onClick={() => {
                  onSelectTab('projects');
                  onSelectProjectScope({ project: '', department: '', list: '' });
                }}
                className={`w-full flex items-center justify-between rounded px-2 py-1 text-[11px] transition ${
                  activeTab === 'projects' && !projectScope.project
                    ? 'bg-kairos-card text-emerald-300 font-semibold'
                    : 'text-slate-300 hover:text-white'
                }`}
              >
                <span className="flex items-center gap-1.5">
                  <Layers className="h-3 w-3 text-emerald-400" /> Everything
                </span>
                <span className="text-[10px] text-slate-400">{totalTasks}</span>
              </button>

              {projects.length === 0 && (
                <div className="rounded border border-kairos-border bg-kairos-bg/80 p-2 text-[10.5px] text-slate-400 space-y-1.5">
                  <div>Syncing `02_Projects/` from Canopy Vault...</div>
                  <button
                    type="button"
                    onClick={handleResyncVault}
                    disabled={resyncing}
                    className="w-full rounded bg-emerald-500/20 border border-emerald-500/40 py-1 text-[10px] font-semibold text-emerald-300 hover:bg-emerald-500/30"
                  >
                    {resyncing ? 'Resyncing...' : '↻ Resync Projects'}
                  </button>
                </div>
              )}

              {/* Each Project in Its Own Top-Level Folder */}
              {projects.map((proj) => {
                const projCollapsed = Boolean(collapsedProjects[proj.name]);
                const projSelected =
                  activeTab === 'projects' &&
                  projectScope.project === proj.name &&
                  !projectScope.department;

                return (
                  <div key={proj.name} className="space-y-0.5 pt-0.5">
                    <div
                      className={`w-full flex items-center justify-between rounded px-1.5 py-1 text-[11px] font-semibold cursor-pointer transition ${
                        projSelected
                          ? 'bg-kairos-card text-amber-300'
                          : 'text-slate-200 hover:text-white hover:bg-kairos-card/40'
                      }`}
                      onClick={() => {
                        onSelectTab('projects');
                        onSelectProjectScope({ project: proj.name, department: '', list: '' });
                      }}
                    >
                      <span className="flex items-center gap-1 min-w-0">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setCollapsedProjects((prev) => ({
                              ...prev,
                              [proj.name]: !prev[proj.name],
                            }));
                          }}
                          className="text-slate-400 hover:text-white"
                        >
                          {projCollapsed ? (
                            <ChevronRight className="h-3 w-3" />
                          ) : (
                            <ChevronDown className="h-3 w-3" />
                          )}
                        </button>
                        <span className="truncate">
                          🚀 {formatProjectDisplayName(proj.name)}
                        </span>
                      </span>
                      <span className="text-[10px] text-slate-400 shrink-0">{proj.task_count}</span>
                    </div>

                    {/* Inside Each Project: Software Dev, Marketing & Branding, Documentation, Website, Merch */}
                    {!projCollapsed &&
                      proj.departments.map((dept) => {
                        const deptKey = `${proj.name}/${dept.name}`;
                        const isDeptCollapsed = Boolean(collapsedDepts[deptKey]);
                        const deptSelected =
                          activeTab === 'projects' &&
                          projectScope.project === proj.name &&
                          projectScope.department === dept.name &&
                          !projectScope.list;
                        const emoji = DEPT_EMOJI_MAP[dept.name] || '📂';

                        return (
                          <div key={dept.name} className="ml-3 space-y-0.5">
                            <div
                              onClick={() => {
                                onSelectTab('projects');
                                onSelectProjectScope({
                                  project: proj.name,
                                  department: dept.name,
                                  list: '',
                                });
                              }}
                              className={`w-full flex items-center justify-between rounded px-1.5 py-1 text-[11px] cursor-pointer transition ${
                                deptSelected
                                  ? 'bg-kairos-card text-cyan-300 font-medium'
                                  : 'text-slate-400 hover:text-slate-200'
                              }`}
                            >
                              <span className="flex items-center gap-1 min-w-0">
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setCollapsedDepts((prev) => ({
                                      ...prev,
                                      [deptKey]: !prev[deptKey],
                                    }));
                                  }}
                                  className="text-slate-500 hover:text-slate-200"
                                >
                                  {isDeptCollapsed ? (
                                    <ChevronRight className="h-2.5 w-2.5" />
                                  ) : (
                                    <ChevronDown className="h-2.5 w-2.5" />
                                  )}
                                </button>
                                <span className="truncate">
                                  {emoji} {dept.name.replace(/_/g, ' ')}
                                </span>
                              </span>
                              <span className="text-[10px] text-slate-500 shrink-0">
                                {dept.task_count}
                              </span>
                            </div>

                            {!isDeptCollapsed &&
                              dept.lists.map((ls) => {
                                const listSelected =
                                  activeTab === 'projects' &&
                                  projectScope.project === proj.name &&
                                  projectScope.department === dept.name &&
                                  projectScope.list === ls.name;
                                return (
                                  <button
                                    key={ls.name}
                                    type="button"
                                    onClick={() => {
                                      onSelectTab('projects');
                                      onSelectProjectScope({
                                        project: proj.name,
                                        department: dept.name,
                                        list: ls.name,
                                      });
                                    }}
                                    className={`ml-3.5 w-[calc(100%-0.875rem)] flex items-center justify-between rounded px-2 py-0.5 text-[10.5px] transition ${
                                      listSelected
                                        ? 'bg-emerald-500/20 text-emerald-300 font-medium'
                                        : 'text-slate-500 hover:text-slate-200'
                                    }`}
                                  >
                                    <span className="flex items-center gap-1 truncate">
                                      <ListTodo className="h-2.5 w-2.5 shrink-0" />
                                      <span className="truncate">
                                        {ls.name.replace(/_/g, ' ')}
                                      </span>
                                    </span>
                                    <span className="text-[10px] text-slate-500">
                                      {ls.task_count}
                                    </span>
                                  </button>
                                );
                              })}
                          </div>
                        );
                      })}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="pt-1 space-y-1">
          {navBtn('browser', 'Browser & Clipper', <Globe className="h-4 w-4 text-sky-400" />)}
          {navBtn(
            'paperclip',
            'Paperclip, CrewAI & Hermes',
            <Bot className="h-4 w-4 text-purple-400" />
          )}
        </div>
      </div>

      <div className="pt-2 border-t border-kairos-border">
        {navBtn('settings', 'System & API Config', <Settings className="h-4 w-4 text-slate-400" />)}
      </div>
    </aside>
  );
};

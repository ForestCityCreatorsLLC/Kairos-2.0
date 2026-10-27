import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  BrainMode,
  CORE_WS,
  PaperclipSnapshot,
  PersonaRole,
  ProjectsSubView,
  ProjectTreeItem,
  ToneMode,
  UIActionCommand,
  VaultSectionHubSummary,
  kairosApi,
} from './api/client.ts';
import { CommandPalette } from './components/CommandPalette.tsx';
import { KairosChatDrawer } from './components/KairosChatDrawer.tsx';
import {
  LeftSidebar,
  ProjectScopeSelection,
  WorkspaceTab,
} from './components/LeftSidebar.tsx';
import { AppToastItem, ToastCenter, ToastKind } from './components/ToastCenter.tsx';
import { TopBar } from './components/TopBar.tsx';
import {
  VoiceNavToastBanner,
  VoiceNavToastData,
} from './components/VoiceNavigatorHUD.tsx';
import { WorkspaceErrorBoundary } from './components/WorkspaceErrorBoundary.tsx';
import { AssistantWorkspace } from './features/assistant/AssistantWorkspace.tsx';
import {
  BROWSER_HOME_TITLE,
  BROWSER_HOME_URL,
  BrowserExternalSignal,
  BrowserTab,
  BrowserWorkspace,
  DEFAULT_BROWSER_TABS,
  normalizeBrowserInput,
} from './features/browser/BrowserWorkspace.tsx';
import { InboxWorkspace } from './features/inbox/InboxWorkspace.tsx';
import { PaperclipWorkspace } from './features/paperclip/PaperclipWorkspace.tsx';
import {
  ProjectsExternalNavSignal,
  ProjectsWorkspace,
} from './features/projects/ProjectsWorkspace.tsx';
import {
  SecondBrainExternalSignal,
  SecondBrainWorkspace,
} from './features/second-brain/SecondBrainWorkspace.tsx';
import { SettingsWorkspace } from './features/settings/SettingsWorkspace.tsx';
import { speakKairosReply, warmupSpeechVoices } from './utils/speech.ts';

const OPERATOR_PREFS_STORAGE_KEY = 'kairos.operator.prefs.v2';

interface PersistedOperatorPrefs {
  activeTab?: WorkspaceTab;
  projectsSubView?: ProjectsSubView;
  brainMode?: BrainMode;
  persona?: PersonaRole;
  toneMode?: ToneMode;
  sidebarCollapsed?: boolean;
  chatDrawerOpen?: boolean;
  chatDrawerWidth?: number;
  ttsEnabled?: boolean;
  neuralTts?: boolean;
  ttsVoice?: string;
  projectScope?: ProjectScopeSelection;
  selectedNotePath?: string;
}

function loadOperatorPrefs(): PersistedOperatorPrefs {
  try {
    const raw = window.localStorage.getItem(OPERATOR_PREFS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as PersistedOperatorPrefs;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

export const App: React.FC = () => {
  const [initialPrefs] = useState<PersistedOperatorPrefs>(() => loadOperatorPrefs());

  const [activeTab, setActiveTab] = useState<WorkspaceTab>(initialPrefs.activeTab || 'projects');
  const [projectsSubView, setProjectsSubView] = useState<ProjectsSubView>(
    initialPrefs.projectsSubView || 'rollup'
  );
  const [brainMode, setBrainMode] = useState<BrainMode>(initialPrefs.brainMode || 'auto');
  const [persona, setPersona] = useState<PersonaRole>(initialPrefs.persona || 'companion');
  const [toneMode, setToneMode] = useState<ToneMode>(initialPrefs.toneMode || 'DEFAULT');
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(
    initialPrefs.sidebarCollapsed ?? false
  );
  const [chatDrawerOpen, setChatDrawerOpen] = useState<boolean>(
    initialPrefs.chatDrawerOpen ?? true
  );
  const [chatDrawerWidth, setChatDrawerWidth] = useState<number>(() =>
    Math.max(300, Math.min(640, initialPrefs.chatDrawerWidth ?? 390))
  );
  const [isResizingDrawer, setIsResizingDrawer] = useState<boolean>(false);

  const handleStartResizeDrawer = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsResizingDrawer(true);
  }, []);

  useEffect(() => {
    if (!isResizingDrawer) return;
    const onMouseMove = (ev: MouseEvent) => {
      const nextWidth = Math.max(300, Math.min(640, window.innerWidth - ev.clientX));
      setChatDrawerWidth(nextWidth);
    };
    const onMouseUp = () => {
      setIsResizingDrawer(false);
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [isResizingDrawer]);

  // Shared Voice Output state across TopBar, Docked Chat Drawer, and Assistant Workspace
  const [ttsEnabled, setTtsEnabled] = useState<boolean>(initialPrefs.ttsEnabled ?? true);
  const [neuralTts, setNeuralTts] = useState<boolean>(initialPrefs.neuralTts ?? true);
  const [ttsVoice, setTtsVoice] = useState<string>(initialPrefs.ttsVoice || 'Kore');

  const [projects, setProjects] = useState<ProjectTreeItem[]>([]);
  const [vaultSections, setVaultSections] = useState<VaultSectionHubSummary[]>([]);
  const [archivedProjects, setArchivedProjects] = useState<string[]>([]);
  const [totalTasks, setTotalTasks] = useState(0);
  const [inboxCount, setInboxCount] = useState(0);
  const [paperclipSnapshot, setPaperclipSnapshot] = useState<PaperclipSnapshot | null>(null);
  const [hermesSkillCount, setHermesSkillCount] = useState(0);
  const [backendConnected, setBackendConnected] = useState(false);
  const [projectScope, setProjectScope] = useState<ProjectScopeSelection>(
    initialPrefs.projectScope || {
      project: '',
      department: '',
      list: '',
    }
  );
  const [selectedNotePath, setSelectedNotePath] = useState(
    initialPrefs.selectedNotePath || 'AGENTS.md'
  );
  const [openTaskId, setOpenTaskId] = useState<string | null>(null);
  const [isOpenTaskPrivate, setIsOpenTaskPrivate] = useState(false);
  const [isPrivateContext, setIsPrivateContext] = useState(() =>
    (initialPrefs.selectedNotePath || 'AGENTS.md').toLowerCase().startsWith('03_personal/finance')
  );
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [toasts, setToasts] = useState<AppToastItem[]>([]);

  const [browserTabs, setBrowserTabs] = useState<BrowserTab[]>(DEFAULT_BROWSER_TABS);
  const [activeBrowserTabId, setActiveBrowserTabId] = useState<string>(
    DEFAULT_BROWSER_TABS[0].id
  );
  const [hasOpenedBrowser, setHasOpenedBrowser] = useState<boolean>(
    (initialPrefs.activeTab || 'projects') === 'browser'
  );
  const browserTabsRef = useRef<BrowserTab[]>(browserTabs);
  const activeBrowserTabIdRef = useRef<string>(activeBrowserTabId);
  const lastUiCommandExecRef = useRef<{ sig: string; ts: number }>({ sig: '', ts: 0 });

  useEffect(() => {
    browserTabsRef.current = browserTabs;
  }, [browserTabs]);

  useEffect(() => {
    activeBrowserTabIdRef.current = activeBrowserTabId;
  }, [activeBrowserTabId]);

  useEffect(() => {
    if (activeTab === 'browser' && !hasOpenedBrowser) {
      setHasOpenedBrowser(true);
    }
  }, [activeTab, hasOpenedBrowser]);

  // Voice & Conversational Platform Navigation Signals
  const [projectsNavSignal, setProjectsNavSignal] = useState<ProjectsExternalNavSignal>({
    seq: 0,
  });
  const [secondBrainSignal, setSecondBrainSignal] = useState<SecondBrainExternalSignal>({
    seq: 0,
  });
  const [browserSignal, setBrowserSignal] = useState<BrowserExternalSignal>({ seq: 0 });
  const [settingsVerifySignal, setSettingsVerifySignal] = useState<{
    seq: number;
    live: boolean;
  }>({ seq: 0, live: false });
  const [navToast, setNavToast] = useState<VoiceNavToastData | null>(null);

  const pushToast = useCallback((kind: ToastKind, title: string, detail?: string) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((prev) => [...prev.slice(-3), { id, kind, title, detail }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, 5200);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((item) => item.id !== id));
  }, []);

  useEffect(() => {
    warmupSpeechVoices();
  }, []);

  // Persist operator layout, persona, tone, voice & scope preferences across restarts
  useEffect(() => {
    try {
      const snapshot: PersistedOperatorPrefs = {
        activeTab,
        projectsSubView,
        brainMode,
        persona,
        toneMode,
        sidebarCollapsed,
        chatDrawerOpen,
        chatDrawerWidth,
        ttsEnabled,
        neuralTts,
        ttsVoice,
        projectScope,
        selectedNotePath,
      };
      window.localStorage.setItem(OPERATOR_PREFS_STORAGE_KEY, JSON.stringify(snapshot));
    } catch {
      // ignore storage quota errors
    }
  }, [
    activeTab,
    brainMode,
    chatDrawerOpen,
    chatDrawerWidth,
    neuralTts,
    persona,
    projectScope,
    projectsSubView,
    selectedNotePath,
    sidebarCollapsed,
    toneMode,
    ttsEnabled,
    ttsVoice,
  ]);

  // Eagerly evaluate `is_private` whenever `selectedNotePath` changes (even before opening Second Brain)
  useEffect(() => {
    if (!selectedNotePath) {
      setIsPrivateContext(false);
      return;
    }
    if (selectedNotePath.toLowerCase().startsWith('03_personal/finance')) {
      setIsPrivateContext(true);
    }
    let cancelled = false;
    kairosApi
      .readNote(selectedNotePath)
      .then((n) => {
        if (!cancelled) {
          setIsPrivateContext(Boolean(n.is_private));
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedNotePath, refreshTick]);

  useEffect(() => {
    if (!openTaskId) {
      setIsOpenTaskPrivate(false);
      return;
    }
    let cancelled = false;
    kairosApi
      .getTaskDetail(openTaskId)
      .then((t) => {
        if (!cancelled) {
          setIsOpenTaskPrivate(Boolean(t.is_private));
        }
      })
      .catch(() => {
        if (!cancelled) setIsOpenTaskPrivate(false);
      });
    return () => {
      cancelled = true;
    };
  }, [openTaskId, refreshTick]);

  const bumpRefresh = useCallback(() => {
    setRefreshTick((t) => t + 1);
  }, []);

  const effectivePrivateContext = Boolean(
    (isPrivateContext && (activeTab === 'second-brain' || activeTab === 'assistant')) ||
      (isOpenTaskPrivate && (activeTab === 'projects' || activeTab === 'assistant'))
  );
  const effectiveActiveNotePath =
    activeTab === 'second-brain' || activeTab === 'assistant' ? selectedNotePath : '';
  const activeBrowserTab =
    browserTabs.find((t) => t.id === activeBrowserTabId) || browserTabs[0] || null;
  const effectiveActiveTaskId =
    (activeTab === 'projects' || activeTab === 'assistant') && openTaskId ? openTaskId : '';
  const activeBrowserUrl = activeBrowserTab?.liveUrl || activeBrowserTab?.url || '';
  const activeBrowserTitle = activeBrowserTab?.title || '';

  const handleSpeakReply = useCallback(
    (text: string, forcePrivate?: boolean) => {
      const priv = Boolean(forcePrivate || effectivePrivateContext);
      speakKairosReply({
        text,
        ttsEnabled,
        neuralTts,
        ttsVoice,
        isPrivate: priv,
        activeNotePath: effectiveActiveNotePath,
      }).catch(() => {});
    },
    [effectiveActiveNotePath, effectivePrivateContext, neuralTts, ttsEnabled, ttsVoice]
  );

  const executeUiCommands = useCallback(
    (cmds: UIActionCommand[], summary?: string, agent = 'KAIROS-Navigator') => {
      if (!cmds || cmds.length === 0) return;

      // Deduplicate simultaneous WebSocket `ui_navigate` + HTTP response execution within 900ms
      const cmdSig = JSON.stringify(cmds);
      const nowMs = Date.now();
      if (
        lastUiCommandExecRef.current.sig === cmdSig &&
        nowMs - lastUiCommandExecRef.current.ts < 900
      ) {
        return;
      }
      lastUiCommandExecRef.current = { sig: cmdSig, ts: nowMs };

      let resolvedTargetTab: WorkspaceTab | null = null;
      let nextProjectsPatch: Omit<ProjectsExternalNavSignal, 'seq'> | null = null;
      let nextBrainPatch: Omit<SecondBrainExternalSignal, 'seq'> | null = null;
      let nextBrowserPatch: Omit<BrowserExternalSignal, 'seq'> | null = null;

      for (const cmd of cmds) {
        switch (cmd.type) {
          case 'navigate_tab':
            resolvedTargetTab = cmd.tab;
            break;
          case 'select_project_scope':
            if (!resolvedTargetTab) resolvedTargetTab = 'projects';
            setProjectScope({
              project: cmd.project || '',
              department: cmd.department || '',
              list: cmd.list || '',
            });
            break;
          case 'set_projects_view':
            if (!resolvedTargetTab) resolvedTargetTab = 'projects';
            nextProjectsPatch = { ...(nextProjectsPatch || {}), view: cmd.view };
            setProjectsSubView(cmd.view);
            break;
          case 'open_task_drawer':
            if (!resolvedTargetTab) resolvedTargetTab = 'projects';
            nextProjectsPatch = { ...(nextProjectsPatch || {}), openTaskId: cmd.task_id };
            break;
          case 'close_task_drawer':
            nextProjectsPatch = { ...(nextProjectsPatch || {}), openTaskId: null };
            break;
          case 'filter_projects_tasks':
            if (!resolvedTargetTab) resolvedTargetTab = 'projects';
            nextProjectsPatch = {
              ...(nextProjectsPatch || {}),
              ...(cmd.keyword !== undefined ? { filterKeyword: cmd.keyword } : {}),
              ...(cmd.ai_agent !== undefined ? { filterAgent: cmd.ai_agent } : {}),
              ...(cmd.priority !== undefined ? { filterPriority: cmd.priority } : {}),
            };
            break;
          case 'open_note':
            if (!resolvedTargetTab) resolvedTargetTab = 'second-brain';
            setSelectedNotePath(cmd.rel_path);
            setIsPrivateContext(
              cmd.rel_path.toLowerCase().startsWith('03_personal/finance')
            );
            break;
          case 'set_second_brain_graph':
            if (cmd.show && !resolvedTargetTab) resolvedTargetTab = 'second-brain';
            nextBrainPatch = {
              ...(nextBrainPatch || {}),
              showGraph: cmd.show,
              graphMode: cmd.mode,
            };
            break;
          case 'filter_second_brain':
            if (!resolvedTargetTab) resolvedTargetTab = 'second-brain';
            nextBrainPatch = {
              ...(nextBrainPatch || {}),
              ...(cmd.query !== undefined ? { searchQuery: cmd.query } : {}),
              ...(cmd.folder !== undefined ? { folderFilter: cmd.folder } : {}),
            };
            if (cmd.folder?.toLowerCase().startsWith('03_personal/finance')) {
              setIsPrivateContext(true);
            }
            break;
          case 'browser_navigate': {
            resolvedTargetTab = 'browser';
            setHasOpenedBrowser(true);
            const resolved = normalizeBrowserInput(cmd.url);
            if (resolved) {
              const nextTitle = cmd.title || resolved.title;
              let targetHost = '';
              try {
                targetHost = new URL(resolved.url).hostname.replace(/^www\./, '').toLowerCase();
              } catch {
                targetHost = '';
              }

              const curTabs = browserTabsRef.current;
              const curActiveId = activeBrowserTabIdRef.current;
              let nextTabs = curTabs;
              let nextActiveId = curActiveId;

              const exactMatch = curTabs.find(
                (t) => (t.liveUrl || t.url) === resolved.url || t.url === resolved.url
              );
              const sameHostMatch = targetHost
                ? curTabs.find((t) => {
                    try {
                      return (
                        new URL(t.liveUrl || t.url).hostname
                          .replace(/^www\./, '')
                          .toLowerCase() === targetHost
                      );
                    } catch {
                      return false;
                    }
                  })
                : undefined;

              if (exactMatch) {
                nextActiveId = exactMatch.id;
                nextTabs = curTabs.map((t) =>
                  t.id === exactMatch.id
                    ? { ...t, url: resolved.url, liveUrl: resolved.url, title: nextTitle }
                    : t
                );
              } else if (sameHostMatch) {
                nextActiveId = sameHostMatch.id;
                nextTabs = curTabs.map((t) =>
                  t.id === sameHostMatch.id
                    ? { ...t, url: resolved.url, liveUrl: resolved.url, title: nextTitle }
                    : t
                );
              } else if (cmd.new_tab && curTabs.length < 8) {
                const newId = `tab-${Date.now()}`;
                nextActiveId = newId;
                nextTabs = [
                  ...curTabs,
                  { id: newId, title: nextTitle, url: resolved.url, liveUrl: resolved.url },
                ];
              } else {
                const targetId =
                  curTabs.find((t) => t.id === curActiveId)?.id || curTabs[0]?.id || 'tab-1';
                nextActiveId = targetId;
                nextTabs = curTabs.map((t) =>
                  t.id === targetId
                    ? { ...t, url: resolved.url, liveUrl: resolved.url, title: nextTitle }
                    : t
                );
              }

              browserTabsRef.current = nextTabs;
              activeBrowserTabIdRef.current = nextActiveId;
              setBrowserTabs(nextTabs);
              setActiveBrowserTabId(nextActiveId);

              nextBrowserPatch = {
                ...(nextBrowserPatch || {}),
                navigateUrl: resolved.url,
                navigateTitle: nextTitle,
                newTab: Boolean(cmd.new_tab),
              };
            }
            break;
          }
          case 'browser_control': {
            if (!resolvedTargetTab) resolvedTargetTab = 'browser';
            setHasOpenedBrowser(true);
            const curTabs = browserTabsRef.current;
            const curActiveId = activeBrowserTabIdRef.current;

            if (cmd.action === 'new_tab') {
              if (curTabs.length < 8) {
                const newId = `tab-${Date.now()}`;
                const nextTabs: BrowserTab[] = [
                  ...curTabs,
                  {
                    id: newId,
                    title: BROWSER_HOME_TITLE,
                    url: BROWSER_HOME_URL,
                    liveUrl: BROWSER_HOME_URL,
                  },
                ];
                browserTabsRef.current = nextTabs;
                activeBrowserTabIdRef.current = newId;
                setBrowserTabs(nextTabs);
                setActiveBrowserTabId(newId);
              }
            } else if (cmd.action === 'close_tab') {
              if (curTabs.length > 1) {
                const filtered = curTabs.filter((t) => t.id !== curActiveId);
                const nextActiveId =
                  curActiveId === activeBrowserTabIdRef.current
                    ? filtered[filtered.length - 1].id
                    : curActiveId;
                browserTabsRef.current = filtered;
                activeBrowserTabIdRef.current = nextActiveId;
                setBrowserTabs(filtered);
                setActiveBrowserTabId(nextActiveId);
              }
            } else if (cmd.action === 'home') {
              const targetId =
                curTabs.find((t) => t.id === curActiveId)?.id || curTabs[0]?.id || 'tab-1';
              const nextTabs = curTabs.map((t) =>
                t.id === targetId
                  ? {
                      ...t,
                      url: BROWSER_HOME_URL,
                      liveUrl: BROWSER_HOME_URL,
                      title: BROWSER_HOME_TITLE,
                    }
                  : t
              );
              browserTabsRef.current = nextTabs;
              activeBrowserTabIdRef.current = targetId;
              setBrowserTabs(nextTabs);
              setActiveBrowserTabId(targetId);
              nextBrowserPatch = {
                ...(nextBrowserPatch || {}),
                controlAction: 'home',
              };
            } else {
              nextBrowserPatch = {
                ...(nextBrowserPatch || {}),
                controlAction: cmd.action,
              };
            }
            break;
          }
          case 'browser_clip':
            if (!resolvedTargetTab) resolvedTargetTab = 'browser';
            setHasOpenedBrowser(true);
            nextBrowserPatch = {
              ...(nextBrowserPatch || {}),
              clipDestFolder: cmd.dest_folder || '00_Inbox',
            };
            break;
          case 'set_persona':
            setPersona(cmd.persona);
            break;
          case 'set_tone_mode':
            setToneMode(cmd.tone_mode);
            break;
          case 'set_brain_mode':
            setBrainMode(cmd.brain_mode);
            break;
          case 'set_left_sidebar':
            setSidebarCollapsed(cmd.collapsed);
            break;
          case 'set_chat_drawer':
            setChatDrawerOpen(cmd.open);
            break;
          case 'set_command_palette':
            setCommandPaletteOpen(cmd.open);
            break;
          case 'trigger_api_verify':
            if (!resolvedTargetTab) resolvedTargetTab = 'settings';
            setSettingsVerifySignal((prev) => ({
              seq: prev.seq + 1,
              live: Boolean(cmd.live),
            }));
            break;
        }
      }

      if (resolvedTargetTab) {
        if (resolvedTargetTab === 'browser') setHasOpenedBrowser(true);
        setActiveTab(resolvedTargetTab);
      }

      if (nextProjectsPatch) {
        const patch = nextProjectsPatch;
        setProjectsNavSignal((prev) => ({ seq: prev.seq + 1, ...patch }));
      }
      if (nextBrainPatch) {
        const patch = nextBrainPatch;
        setSecondBrainSignal((prev) => ({ seq: prev.seq + 1, ...patch }));
      }
      if (nextBrowserPatch) {
        const patch = nextBrowserPatch;
        setBrowserSignal((prev) => ({ seq: prev.seq + 1, ...patch }));
      }

      setNavToast({
        id: Date.now(),
        summary: summary || `Executed ${cmds.length} voice navigation command(s)`,
        agent,
      });
    },
    []
  );

  useEffect(() => {
    if (!navToast) return;
    const t = window.setTimeout(() => setNavToast(null), 5000);
    return () => window.clearTimeout(t);
  }, [navToast?.id]);

  const loadSidebarSummary = useCallback(async (): Promise<boolean> => {
    try {
      const [tree, health, inboxRes, vaultStruct] = await Promise.all([
        kairosApi.getProjectsTree(),
        kairosApi.getHealth(),
        kairosApi.searchNotes('', '00_Inbox'),
        kairosApi.getVaultStructure().catch(() => null),
      ]);
      setProjects(tree.projects);
      if (vaultStruct) {
        setVaultSections(vaultStruct.sections || []);
      }
      setProjectScope((prev) => {
        if (
          prev.project &&
          tree.projects.length > 0 &&
          !tree.projects.some((p) => p.name === prev.project)
        ) {
          return { project: '', department: '', list: '' };
        }
        return prev;
      });
      setArchivedProjects(tree.archived_projects || []);
      setTotalTasks(tree.rollup.total_tasks);
      setPaperclipSnapshot(health.paperclip);
      setHermesSkillCount(health.hermes_skill_count || 0);
      setInboxCount(inboxRes.notes.length);
      setBackendConnected(true);
      return true;
    } catch {
      setBackendConnected(false);
      return false;
    }
  }, []);

  useEffect(() => {
    loadSidebarSummary();
  }, [loadSidebarSummary, refreshTick]);

  // Automatic startup retry loop until Core `:8420` finishes indexing Canopy Vault
  useEffect(() => {
    if (backendConnected) return;
    const timer = window.setInterval(async () => {
      const ok = await loadSidebarSummary();
      if (ok) {
        bumpRefresh();
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [backendConnected, loadSidebarSummary, bumpRefresh]);

  // Global `Ctrl+K` Quick Jump, `Ctrl+B` Left Sidebar Toggle, and `Ctrl+\` Chat Drawer Toggle
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setCommandPaletteOpen((v) => !v);
      } else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        setSidebarCollapsed((v) => !v);
      } else if ((e.ctrlKey || e.metaKey) && e.key === '\\') {
        e.preventDefault();
        setChatDrawerOpen((v) => !v);
      } else if (e.key === 'Escape') {
        setCommandPaletteOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  // Auto-reconnecting Real-Time WebSocket push from `watchdog` + Paperclip/CrewAI/Hermes + Voice Navigator
  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let wsRefreshTimer: number | null = null;
    let alive = true;

    const scheduleWsRefresh = () => {
      if (wsRefreshTimer !== null) {
        window.clearTimeout(wsRefreshTimer);
      }
      wsRefreshTimer = window.setTimeout(() => {
        wsRefreshTimer = null;
        if (alive) bumpRefresh();
      }, 180);
    };

    const connectWs = () => {
      if (!alive) return;
      try {
        ws = new WebSocket(CORE_WS);
        ws.onopen = () => {
          if (alive) bumpRefresh();
        };
        ws.onmessage = (ev) => {
          try {
            const payload = JSON.parse(ev.data) as {
              event?: string;
              task_id?: string;
              crew?: string;
              error?: string;
              ui_commands?: UIActionCommand[];
              actions?: string[];
            };
            if (payload.event === 'ui_navigate' && payload.ui_commands?.length) {
              executeUiCommands(
                payload.ui_commands,
                payload.actions?.join(' • '),
                'KAIROS-Navigator'
              );
            } else if (payload.event === 'crew_completed') {
              pushToast(
                'success',
                `Agent Run Completed (${payload.task_id || 'Task'})`,
                payload.crew ? `Executed by ${payload.crew}` : 'Deliverable saved to Canopy Vault'
              );
            } else if (payload.event === 'crew_error') {
              pushToast(
                'error',
                `Agent Run Failed (${payload.task_id || 'Task'})`,
                payload.error || 'Check Paperclip Control Plane for details.'
              );
            }
          } catch {
            // ignore non-json frames
          }
          scheduleWsRefresh();
        };
        ws.onclose = () => {
          if (alive) {
            reconnectTimer = window.setTimeout(connectWs, 2500);
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
          reconnectTimer = window.setTimeout(connectWs, 2500);
        }
      }
    };

    connectWs();
    return () => {
      alive = false;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (wsRefreshTimer !== null) window.clearTimeout(wsRefreshTimer);
      ws?.close();
    };
  }, [bumpRefresh, executeUiCommands, pushToast]);

  const handleOpenNoteInSecondBrain = (relPath: string) => {
    setSelectedNotePath(relPath);
    setActiveTab('second-brain');
  };

  const handleOpenDailyNote = async () => {
    try {
      const daily = await kairosApi.openDailyNote();
      setSelectedNotePath(daily.rel_path);
      setIsPrivateContext(daily.is_private);
      setActiveTab('second-brain');
      bumpRefresh();
    } catch (err) {
      pushToast(
        'error',
        'Daily Note Error',
        err instanceof Error ? err.message : 'Unable to open today’s daily note'
      );
    }
  };

  const handleRunPaletteCommand = useCallback(
    async (promptText: string) => {
      const clean = promptText.trim();
      if (!clean) return;
      if (activeTab !== 'assistant') {
        setChatDrawerOpen(true);
      }
      try {
        const res = await kairosApi.sendAssistantChat({
          prompt: clean,
          session_id: activeSessionId,
          mode: effectivePrivateContext ? 'gemma-4' : brainMode,
          persona,
          tone_mode: toneMode,
          active_note_path: effectiveActiveNotePath,
          active_task_id: effectiveActiveTaskId,
          active_browser_url: activeBrowserUrl,
          active_browser_title: activeBrowserTitle,
          project_scope: projectScope.project || 'KAIROS_2_0',
          department_scope: projectScope.department || 'Software_Development',
          current_tab: activeTab,
          current_view: activeTab === 'projects' ? projectsSubView : '',
        });
        if (res.session?.session_id) {
          setActiveSessionId(res.session.session_id);
        }
        if (res.session?.persona && res.session.persona !== persona) {
          setPersona(res.session.persona);
        }
        if (res.session?.tone_mode && res.session.tone_mode !== toneMode) {
          setToneMode(res.session.tone_mode);
        }
        if (res.ui_commands && res.ui_commands.length > 0) {
          executeUiCommands(res.ui_commands, res.actions?.join(' • ') || clean, res.agent);
        }
        handleSpeakReply(res.spoken_reply || res.reply, res.privacy_locked);
        bumpRefresh();
      } catch (err) {
        pushToast(
          'error',
          'Command Failed',
          err instanceof Error ? err.message : 'Unable to reach KAIROS Core (:8420)'
        );
      }
    },
    [
      activeBrowserTitle,
      activeBrowserUrl,
      activeSessionId,
      activeTab,
      brainMode,
      bumpRefresh,
      effectiveActiveNotePath,
      effectiveActiveTaskId,
      effectivePrivateContext,
      executeUiCommands,
      handleSpeakReply,
      persona,
      projectScope.department,
      projectScope.project,
      projectsSubView,
      pushToast,
      toneMode,
    ]
  );

  return (
    <div className="h-screen w-screen flex flex-col bg-kairos-bg text-slate-100 overflow-hidden">
      {/* Zone 1: Permanent Embedded KAIROS Top Bar (56px, always present, never pops out) */}
      <TopBar
        brainMode={brainMode}
        onChangeBrainMode={setBrainMode}
        activeNotePath={effectiveActiveNotePath}
        activeTaskId={effectiveActiveTaskId}
        activeBrowserUrl={activeBrowserUrl}
        activeBrowserTitle={activeBrowserTitle}
        isPrivateContext={effectivePrivateContext}
        paperclipSnapshot={paperclipSnapshot}
        hermesSkillCount={hermesSkillCount}
        onOpenPaperclip={() => setActiveTab('paperclip')}
        onExecuteUiCommands={executeUiCommands}
        chatDrawerOpen={chatDrawerOpen}
        onToggleChatDrawer={() => {
          if (activeTab === 'assistant') {
            setActiveTab('projects');
            setChatDrawerOpen(true);
          } else {
            setChatDrawerOpen((v) => !v);
          }
        }}
        activeSessionId={activeSessionId}
        persona={persona}
        onChangePersona={setPersona}
        toneMode={toneMode}
        onChangeToneMode={setToneMode}
        projectScope={projectScope.project}
        departmentScope={projectScope.department}
        currentTab={activeTab}
        currentView={activeTab === 'projects' ? projectsSubView : ''}
        ttsEnabled={ttsEnabled}
        onToggleTtsEnabled={() => setTtsEnabled((v) => !v)}
        neuralTts={neuralTts}
        onChangeNeuralTts={setNeuralTts}
        ttsVoice={ttsVoice}
        onChangeTtsVoice={setTtsVoice}
        onCommandCompleted={(sid) => {
          if (sid) setActiveSessionId(sid);
          bumpRefresh();
        }}
      />

      {/* Zone 2 + Zone 3 (+ Collapsible KAIROS Docked Chat Drawer): Left Menu + Main Workspace + KAIROS Co-Pilot */}
      <div className="flex-1 flex min-w-0 min-h-0 w-full overflow-hidden">
        <LeftSidebar
          activeTab={activeTab}
          onSelectTab={setActiveTab}
          projects={projects}
          vaultSections={vaultSections}
          selectedNotePath={selectedNotePath}
          onOpenSectionNote={handleOpenNoteInSecondBrain}
          projectScope={projectScope}
          onSelectProjectScope={setProjectScope}
          totalTasks={totalTasks}
          inboxCount={inboxCount}
          collapsed={sidebarCollapsed}
          onToggleCollapsed={() => setSidebarCollapsed((v) => !v)}
          chatDrawerOpen={chatDrawerOpen && activeTab !== 'assistant'}
          onToggleChatDrawer={() => setChatDrawerOpen((v) => !v)}
          onOpenCommandPalette={() => setCommandPaletteOpen(true)}
          onStructureCreated={bumpRefresh}
          onNotify={pushToast}
        />

        <main className="flex-1 flex min-w-0 min-h-0 w-full overflow-hidden">
          {activeTab === 'assistant' && (
            <WorkspaceErrorBoundary workspaceName="KAIROS Assistant">
              <AssistantWorkspace
                brainMode={brainMode}
                persona={persona}
                onChangePersona={setPersona}
                toneMode={toneMode}
                onChangeToneMode={setToneMode}
                activeSessionId={activeSessionId}
                onSelectSessionId={setActiveSessionId}
                activeNotePath={selectedNotePath}
                activeTaskId={effectiveActiveTaskId}
                activeBrowserUrl={activeBrowserUrl}
                activeBrowserTitle={activeBrowserTitle}
                isPrivateContext={effectivePrivateContext}
                projectScope={projectScope.project}
                departmentScope={projectScope.department}
                projects={projects}
                hermesSkillCount={hermesSkillCount}
                currentTab={activeTab}
                currentView=""
                refreshTick={refreshTick}
                onVaultMutated={bumpRefresh}
                onOpenNoteInSecondBrain={handleOpenNoteInSecondBrain}
                onExecuteUiCommands={executeUiCommands}
                ttsEnabled={ttsEnabled}
                onToggleTtsEnabled={() => setTtsEnabled((v) => !v)}
                onSpeakReply={handleSpeakReply}
                onNotify={pushToast}
              />
            </WorkspaceErrorBoundary>
          )}

          {activeTab === 'inbox' && (
            <WorkspaceErrorBoundary workspaceName="Inbox Triage Hub">
              <InboxWorkspace
                projects={projects}
                refreshTick={refreshTick}
                onVaultMutated={bumpRefresh}
                onOpenNoteInSecondBrain={handleOpenNoteInSecondBrain}
                onNavigateToProjects={() => setActiveTab('projects')}
                onNotify={pushToast}
              />
            </WorkspaceErrorBoundary>
          )}

          {activeTab === 'projects' && (
            <WorkspaceErrorBoundary
              workspaceName="Projects Workspace"
              resetKey={projectScope.project || 'all'}
            >
              <ProjectsWorkspace
                scope={projectScope}
                projectsTree={projects}
                archivedProjects={archivedProjects}
                onSelectScope={setProjectScope}
                refreshTick={refreshTick}
                onVaultMutated={bumpRefresh}
                onOpenNoteInSecondBrain={handleOpenNoteInSecondBrain}
                onResetScope={() => setProjectScope({ project: '', department: '', list: '' })}
                externalNavSignal={projectsNavSignal}
                onSubViewChange={setProjectsSubView}
                onSelectedTaskChange={setOpenTaskId}
                onNotify={pushToast}
              />
            </WorkspaceErrorBoundary>
          )}

          {activeTab === 'second-brain' && (
            <WorkspaceErrorBoundary
              workspaceName="Second Brain Explorer"
              resetKey={selectedNotePath || 'root'}
            >
              <SecondBrainWorkspace
                selectedNotePath={selectedNotePath}
                onSelectNote={(rel, priv) => {
                  setSelectedNotePath(rel);
                  setIsPrivateContext(priv);
                }}
                refreshTick={refreshTick}
                onVaultMutated={bumpRefresh}
                externalBrainSignal={secondBrainSignal}
                onExecuteUiCommands={executeUiCommands}
                onNotify={pushToast}
              />
            </WorkspaceErrorBoundary>
          )}

          {(hasOpenedBrowser || activeTab === 'browser') && (
            <div
              className={
                activeTab === 'browser'
                  ? 'flex-1 flex min-w-0 min-h-0 w-full overflow-hidden'
                  : 'hidden'
              }
            >
              <WorkspaceErrorBoundary
                workspaceName="Embedded Research Browser"
                resetKey={`${activeBrowserTabId}-${browserSignal.seq}`}
              >
                <BrowserWorkspace
                  projects={projects}
                  tabs={browserTabs}
                  onChangeTabs={setBrowserTabs}
                  activeTabId={activeBrowserTabId}
                  onChangeActiveTabId={setActiveBrowserTabId}
                  refreshTick={refreshTick}
                  externalBrowserSignal={browserSignal}
                  onVaultMutated={bumpRefresh}
                  onExecuteUiCommands={executeUiCommands}
                  onNotify={pushToast}
                  onClippedToVault={(relPath) => {
                    bumpRefresh();
                    handleOpenNoteInSecondBrain(relPath);
                  }}
                />
              </WorkspaceErrorBoundary>
            </div>
          )}

          {activeTab === 'paperclip' && (
            <WorkspaceErrorBoundary workspaceName="Paperclip & CrewAI Control Plane">
              <PaperclipWorkspace
                projects={projects}
                refreshTick={refreshTick}
                activeSessionId={activeSessionId}
                persona={persona}
                toneMode={toneMode}
                brainMode={effectivePrivateContext ? 'gemma-4' : brainMode}
                onSelectSessionId={setActiveSessionId}
                onSpeakReply={handleSpeakReply}
                onVaultMutated={bumpRefresh}
                onOpenNoteInSecondBrain={handleOpenNoteInSecondBrain}
                onExecuteUiCommands={executeUiCommands}
                onNotify={pushToast}
              />
            </WorkspaceErrorBoundary>
          )}

          {activeTab === 'settings' && (
            <WorkspaceErrorBoundary workspaceName="Settings & Diagnostics">
              <SettingsWorkspace
                refreshTick={refreshTick}
                externalVerifySignal={settingsVerifySignal}
                ttsEnabled={ttsEnabled}
                onToggleTtsEnabled={() => setTtsEnabled((v) => !v)}
                neuralTts={neuralTts}
                onChangeNeuralTts={setNeuralTts}
                ttsVoice={ttsVoice}
                onChangeTtsVoice={setTtsVoice}
                onVaultMutated={bumpRefresh}
                onNotify={pushToast}
              />
            </WorkspaceErrorBoundary>
          )}
        </main>

        {/* Docked KAIROS Virtual Assistant Chat Drawer (unmounted cleanly when collapsed so main workspace expands to 100%) */}
        {chatDrawerOpen && activeTab !== 'assistant' && (
          <WorkspaceErrorBoundary
            workspaceName="KAIROS Chat Drawer"
            resetKey={`${activeTab}-${String(chatDrawerOpen)}`}
            containerClassName="shrink-0 border-l border-kairos-border flex items-center justify-center p-4 bg-[#0B1220]"
          >
            <KairosChatDrawer
              open={true}
              widthPx={chatDrawerWidth}
              onResizeMouseDown={handleStartResizeDrawer}
              onClose={() => setChatDrawerOpen(false)}
              onExpandFullWorkspace={() => setActiveTab('assistant')}
              brainMode={brainMode}
              persona={persona}
              onChangePersona={setPersona}
              toneMode={toneMode}
              onChangeToneMode={setToneMode}
              activeSessionId={activeSessionId}
              onSelectSessionId={setActiveSessionId}
              activeNotePath={effectiveActiveNotePath}
              activeTaskId={effectiveActiveTaskId}
              activeBrowserUrl={activeBrowserUrl}
              activeBrowserTitle={activeBrowserTitle}
              isPrivateContext={effectivePrivateContext}
              projectScope={projectScope.project}
              departmentScope={projectScope.department}
              currentTab={activeTab}
              currentView={activeTab === 'projects' ? projectsSubView : ''}
              refreshTick={refreshTick}
              onVaultMutated={bumpRefresh}
              onOpenNoteInSecondBrain={handleOpenNoteInSecondBrain}
              onExecuteUiCommands={executeUiCommands}
              ttsEnabled={ttsEnabled}
              onToggleTtsEnabled={() => setTtsEnabled((v) => !v)}
              onSpeakReply={handleSpeakReply}
              onNotify={pushToast}
            />
          </WorkspaceErrorBoundary>
        )}
      </div>

      {/* Transparent drag-shield so resizing next to <webview> or <iframe> never drops pointer events */}
      {isResizingDrawer && <div className="fixed inset-0 z-40 cursor-col-resize" />}

      {/* Global Notification Toast Stack (Paperclip 409 Locks, Save Confirmations, Agent Runs) */}
      <ToastCenter toasts={toasts} onDismiss={dismissToast} />

      {/* Live Voice Navigation Toast Banner */}
      <VoiceNavToastBanner toast={navToast} onDismiss={() => setNavToast(null)} />

      {/* Global Quick Jump Omni-Search Palette (Ctrl+K) */}
      <CommandPalette
        open={commandPaletteOpen}
        focusModeActive={sidebarCollapsed && !chatDrawerOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigateTab={setActiveTab}
        onOpenNote={handleOpenNoteInSecondBrain}
        onOpenDailyNote={handleOpenDailyNote}
        onExecuteUiCommands={executeUiCommands}
        onRunCommandPrompt={handleRunPaletteCommand}
      />
    </div>
  );
};

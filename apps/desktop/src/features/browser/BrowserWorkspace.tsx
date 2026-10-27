import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CircleCheck,
  ExternalLink,
  FolderPlus,
  GitBranch,
  Globe,
  Home,
  KeyRound,
  Lock,
  Paperclip,
  Play,
  Plus,
  RotateCw,
  Scissors,
  Search,
  X,
} from 'lucide-react';
import {
  PaperclipSnapshot,
  ProjectTreeItem,
  UIActionCommand,
  VaultSectionHubSummary,
  kairosApi,
} from '../../api/client.ts';
import { ToastKind } from '../../components/ToastCenter.tsx';

export interface BrowserTab {
  id: string;
  title: string;
  url: string;
  liveUrl?: string;
}

export const BROWSER_HOME_URL = 'https://github.com/ForestCityCreatorsLLC?tab=repositories';
export const BROWSER_HOME_TITLE = 'Forest City Creators LLC — Repositories';

export const DEFAULT_BROWSER_TABS: BrowserTab[] = [
  {
    id: 'tab-1',
    title: BROWSER_HOME_TITLE,
    url: BROWSER_HOME_URL,
  },
  {
    id: 'tab-2',
    title: 'YouTube',
    url: 'https://www.youtube.com',
  },
];

const QUICK_BOOKMARKS: { label: string; url: string; title: string }[] = [
  { label: '🏢 FCC Repositories', url: BROWSER_HOME_URL, title: BROWSER_HOME_TITLE },
  { label: '▶ YouTube', url: 'https://www.youtube.com', title: 'YouTube' },
  { label: '🏈 ESPN', url: 'https://www.espn.com', title: 'ESPN' },
  { label: '🔎 Google', url: 'https://www.google.com', title: 'Google' },
];

const FRAME_RESTRICTED_HOSTS = [
  'youtube.com',
  'youtu.be',
  'spotify.com',
  'soundcloud.com',
  'espn.com',
  'nba.com',
  'nfl.com',
  'mlb.com',
  'nhl.com',
  'github.com',
  'google.com',
  'reddit.com',
  'instagram.com',
  'linkedin.com',
  'x.com',
  'twitter.com',
];

interface ElectronWebviewElement extends HTMLElement {
  src: string;
  canGoBack?: () => boolean;
  canGoForward?: () => boolean;
  goBack?: () => void;
  goForward?: () => void;
  reload?: () => void;
  loadURL?: (url: string) => Promise<void>;
  getURL?: () => string;
  executeJavaScript?: (code: string, userGesture?: boolean) => Promise<unknown>;
}

export function normalizeBrowserInput(raw: string): { url: string; title: string } | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const low = trimmed.toLowerCase();
  if (
    low.startsWith('javascript:') ||
    low.startsWith('data:') ||
    low.startsWith('file:') ||
    low.startsWith('vbscript:')
  ) {
    return null;
  }
  const hasExplicitHttp = low.startsWith('http://') || low.startsWith('https://');
  const looksLikeSearch = /\s/.test(trimmed) || (!hasExplicitHttp && !trimmed.includes('.'));
  if (looksLikeSearch) {
    return {
      url: `https://duckduckgo.com/?q=${encodeURIComponent(trimmed)}`,
      title: `Search: ${trimmed.slice(0, 28)}`,
    };
  }
  const candidate = hasExplicitHttp ? trimmed : `https://${trimmed}`;
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return null;
    }
    const hostTitle = (parsed.hostname || trimmed).replace(/^www\./, '');
    return { url: parsed.toString(), title: hostTitle || 'Web Tab' };
  } catch {
    return {
      url: `https://duckduckgo.com/?q=${encodeURIComponent(trimmed)}`,
      title: `Search: ${trimmed.slice(0, 28)}`,
    };
  }
}

function isFrameRestrictedInWebPreview(rawUrl: string): boolean {
  try {
    const host = new URL(rawUrl).hostname.toLowerCase();
    return FRAME_RESTRICTED_HOSTS.some((h) => host === h || host.endsWith(`.${h}`));
  } catch {
    return false;
  }
}

export interface BrowserExternalSignal {
  seq: number;
  navigateUrl?: string;
  navigateTitle?: string;
  newTab?: boolean;
  clipDestFolder?: string;
  controlAction?: 'back' | 'forward' | 'reload' | 'home' | 'new_tab' | 'close_tab';
}

interface BrowserWorkspaceProps {
  projects?: ProjectTreeItem[];
  tabs?: BrowserTab[];
  onChangeTabs?: React.Dispatch<React.SetStateAction<BrowserTab[]>>;
  activeTabId?: string;
  onChangeActiveTabId?: (id: string) => void;
  onClippedToVault: (relPath: string) => void;
  onVaultMutated?: () => void;
  onExecuteUiCommands?: (cmds: UIActionCommand[], summary?: string, agent?: string) => void;
  refreshTick: number;
  externalBrowserSignal?: BrowserExternalSignal;
  onNotify?: (kind: ToastKind, title: string, detail?: string) => void;
}

export const BrowserWorkspace: React.FC<BrowserWorkspaceProps> = ({
  projects = [],
  tabs: controlledTabs,
  onChangeTabs,
  activeTabId: controlledActiveTabId,
  onChangeActiveTabId,
  onClippedToVault,
  onVaultMutated,
  onExecuteUiCommands,
  refreshTick,
  externalBrowserSignal,
  onNotify,
}) => {
  const desktopBridge = (
    window as unknown as {
      kairosDesktop?: {
        isElectron?: boolean;
        getGithubAuthInfo?: () => Promise<{
          configured: boolean;
          username: string;
          loggedIn?: boolean;
        }>;
        triggerGithubSignIn?: (returnUrl?: string) => Promise<{ ok: boolean; loginUrl: string }>;
      };
    }
  ).kairosDesktop;
  const isElectron = Boolean(desktopBridge?.isElectron);

  const [internalTabs, setInternalTabs] = useState<BrowserTab[]>(DEFAULT_BROWSER_TABS);
  const [internalActiveId, setInternalActiveId] = useState<string>(DEFAULT_BROWSER_TABS[0].id);

  const tabs = controlledTabs ?? internalTabs;
  const setTabs = onChangeTabs ?? setInternalTabs;
  const activeTabId = controlledActiveTabId ?? internalActiveId;
  const setActiveTabId = onChangeActiveTabId ?? setInternalActiveId;

  const activeTab = tabs.find((t) => t.id === activeTabId) || tabs[0] || DEFAULT_BROWSER_TABS[0];
  const effectiveCurrentUrl = activeTab.liveUrl || activeTab.url;

  const [addressInput, setAddressInput] = useState(effectiveCurrentUrl);
  const [destFolder, setDestFolder] = useState('00_Inbox');
  const [clipStatus, setClipStatus] = useState('');
  const [clipStatusKind, setClipStatusKind] = useState<'success' | 'error'>('success');
  const [clipping, setClipping] = useState(false);
  const [syncingOrg, setSyncingOrg] = useState(false);
  const [paperclip, setPaperclip] = useState<PaperclipSnapshot | null>(null);
  const [vaultSections, setVaultSections] = useState<VaultSectionHubSummary[]>([]);
  const [showAgentFeed, setShowAgentFeed] = useState(false);
  const [showFccReposDrawer, setShowFccReposDrawer] = useState(false);
  const [loadingFccRepos, setLoadingFccRepos] = useState(false);
  const [fccReposFilter, setFccReposFilter] = useState('');
  const [fccRepos, setFccRepos] = useState<
    Awaited<ReturnType<typeof kairosApi.listGitHubOrgRepos>>['repos']
  >([]);
  const [showHubEntryComposer, setShowHubEntryComposer] = useState(false);
  const [hubEntryTitle, setHubEntryTitle] = useState('');
  const [hubEntryVendor, setHubEntryVendor] = useState('');
  const [hubEntrySection, setHubEntrySection] = useState('__auto_music__');
  const [hubEntryCollection, setHubEntryCollection] = useState('Plugins');
  const [savingHubEntry, setSavingHubEntry] = useState(false);
  const [githubAuthInfo, setGithubAuthInfo] = useState<{
    configured: boolean;
    username: string;
    loggedIn: boolean;
  }>({ configured: false, username: '', loggedIn: false });
  const [webviewLoadError, setWebviewLoadError] = useState<{
    tabId: string;
    errorCode: number;
    errorDescription: string;
    validatedURL: string;
  } | null>(null);

  const webviewRef = useRef<ElectronWebviewElement | null>(null);
  const webviewDomReadyTabRef = useRef<string | null>(null);
  const pendingWebviewNavRef = useRef<{ tabId: string; url: string } | null>(null);
  const mountedTabSrcRef = useRef<{ tabId: string; src: string }>({ tabId: '', src: '' });
  const activeTabUrlRef = useRef<string>(effectiveCurrentUrl);
  activeTabUrlRef.current = effectiveCurrentUrl;

  if (mountedTabSrcRef.current.tabId !== activeTab.id) {
    mountedTabSrcRef.current = {
      tabId: activeTab.id,
      src: effectiveCurrentUrl,
    };
  }
  const mountedWebviewSrc = mountedTabSrcRef.current.src;

  const safeLoadWebviewUrl = (targetUrl: string, forTabId = activeTab.id) => {
    if (!isElectron || !targetUrl) return;
    const wv = webviewRef.current;
    if (!wv || webviewDomReadyTabRef.current !== forTabId) {
      pendingWebviewNavRef.current = { tabId: forTabId, url: targetUrl };
      return;
    }
    try {
      const currentGuestUrl = typeof wv.getURL === 'function' ? wv.getURL() : '';
      if (currentGuestUrl !== targetUrl && typeof wv.loadURL === 'function') {
        Promise.resolve(wv.loadURL(targetUrl)).catch(() => {});
      }
    } catch {
      pendingWebviewNavRef.current = { tabId: forTabId, url: targetUrl };
    }
  };

  const setClipFeedback = (kind: 'success' | 'error', msg: string) => {
    setClipStatusKind(kind);
    setClipStatus(msg);
    if (kind === 'success') {
      window.setTimeout(() => {
        setClipStatus((cur) => (cur === msg ? '' : cur));
      }, 4500);
    }
  };

  const clipDestinations = useMemo(() => {
    const base = [
      { value: '00_Inbox', label: 'Clip → 00_Inbox' },
      {
        value: '04_Resources/Code_and_Research',
        label: 'Clip → 04_Resources (Code & Research)',
      },
      { value: '04_Resources/Hermes', label: 'Clip → 04_Resources/Hermes' },
      { value: '03_Personal/Finance', label: 'Clip → 🔒 03_Personal/Finance (Local)' },
    ];
    const seen = new Set(base.map((item) => item.value));

    for (const sec of vaultSections) {
      const icon = sec.icon || '🗂️';
      if (sec.section_rel && !seen.has(sec.section_rel)) {
        seen.add(sec.section_rel);
        base.push({
          value: sec.section_rel,
          label: `Clip → ${icon} ${sec.title} (Hub Root)`,
        });
      }
      for (const col of sec.collections || []) {
        const colPath = col.rel_path || `${sec.section_rel}/${col.folder}`;
        if (colPath && !seen.has(colPath)) {
          seen.add(colPath);
          base.push({
            value: colPath,
            label: `Clip → ${icon} ${sec.title} / ${col.title}`,
          });
        }
      }
    }

    const projectNames =
      projects.length > 0 ? projects.map((p) => p.name) : ['KAIROS_2_0'];
    for (const pName of projectNames) {
      const docsPath = `02_Projects/${pName}/Docs`;
      const prettyProj = pName
        .replace(/_(\d+)_(\d+)(?=_|$)/g, ' $1.$2')
        .replace(/_/g, ' ');
      if (!seen.has(docsPath)) {
        seen.add(docsPath);
        base.push({
          value: docsPath,
          label: `Clip → 📖 ${prettyProj} Wiki (Docs/)`,
        });
      }
    }
    return base;
  }, [projects, vaultSections]);

  useEffect(() => {
    setAddressInput(activeTab.liveUrl || activeTab.url);
  }, [activeTab.id, activeTab.url, activeTab.liveUrl]);

  useEffect(() => {
    kairosApi
      .getPaperclipStatus()
      .then((res) => setPaperclip(res.paperclip))
      .catch(() => {});
    kairosApi
      .getVaultStructure()
      .then((res) => setVaultSections(res.sections || []))
      .catch(() => {});
    if (desktopBridge?.getGithubAuthInfo) {
      desktopBridge
        .getGithubAuthInfo()
        .then((info) => {
          if (info) {
            setGithubAuthInfo({
              configured: Boolean(info.configured),
              username: info.username || '',
              loggedIn: Boolean(info.loggedIn),
            });
          }
        })
        .catch(() => {});
    }
  }, [refreshTick]);

  // Sync live URL & page title as the operator clicks links or YouTube SPA videos inside Electron <webview>
  useEffect(() => {
    if (!isElectron) return;
    const wv = webviewRef.current;
    if (!wv) return;
    const tabId = activeTab.id;
    webviewDomReadyTabRef.current = null;

    const onDomReady = () => {
      webviewDomReadyTabRef.current = tabId;
      const pending =
        pendingWebviewNavRef.current?.tabId === tabId
          ? pendingWebviewNavRef.current.url
          : '';
      if (pendingWebviewNavRef.current?.tabId === tabId) {
        pendingWebviewNavRef.current = null;
      }
      const desiredUrl = pending || activeTabUrlRef.current;
      if (!desiredUrl) return;
      try {
        const currentGuestUrl = typeof wv.getURL === 'function' ? wv.getURL() : '';
        if (currentGuestUrl && currentGuestUrl !== desiredUrl && typeof wv.loadURL === 'function') {
          Promise.resolve(wv.loadURL(desiredUrl)).catch(() => {});
        }
      } catch {
        // ignore transient guest initialization race
      }
    };

    const onNav = (ev: Event) => {
      const navUrl = (ev as unknown as { url?: string }).url;
      if (navUrl && (navUrl.startsWith('https://') || navUrl.startsWith('http://'))) {
        setWebviewLoadError((prev) => (prev?.tabId === tabId ? null : prev));
        setAddressInput(navUrl);
        setTabs((prev) =>
          prev.map((t) => (t.id === tabId ? { ...t, liveUrl: navUrl } : t))
        );
        if (navUrl.includes('github.com') && desktopBridge?.getGithubAuthInfo) {
          desktopBridge
            .getGithubAuthInfo()
            .then((info) => {
              if (info) {
                setGithubAuthInfo({
                  configured: Boolean(info.configured),
                  username: info.username || '',
                  loggedIn: Boolean(info.loggedIn),
                });
              }
            })
            .catch(() => {});
        }
      }
    };

    const onTitle = (ev: Event) => {
      const pageTitle = (ev as unknown as { title?: string }).title?.trim();
      if (pageTitle) {
        setTabs((prev) =>
          prev.map((t) => (t.id === tabId ? { ...t, title: pageTitle.slice(0, 48) } : t))
        );
      }
    };

    const onDidFailLoad = (ev: Event) => {
      const failEv = ev as unknown as {
        errorCode?: number;
        errorDescription?: string;
        validatedURL?: string;
        isMainFrame?: boolean;
      };
      if (failEv.isMainFrame === false) return;
      const code = typeof failEv.errorCode === 'number' ? failEv.errorCode : 0;
      // Ignore ERR_ABORTED (-3) caused by YouTube SPA/redirect navigation and benign code 0
      if (code === -3 || code === 0) return;
      setWebviewLoadError({
        tabId,
        errorCode: code,
        errorDescription: failEv.errorDescription || 'Page failed to load',
        validatedURL: failEv.validatedURL || activeTabUrlRef.current,
      });
    };

    wv.addEventListener('dom-ready', onDomReady);
    wv.addEventListener('did-navigate', onNav);
    wv.addEventListener('did-navigate-in-page', onNav);
    wv.addEventListener('page-title-updated', onTitle);
    wv.addEventListener('did-fail-load', onDidFailLoad);
    return () => {
      if (webviewDomReadyTabRef.current === tabId) {
        webviewDomReadyTabRef.current = null;
      }
      wv.removeEventListener('dom-ready', onDomReady);
      wv.removeEventListener('did-navigate', onNav);
      wv.removeEventListener('did-navigate-in-page', onNav);
      wv.removeEventListener('page-title-updated', onTitle);
      wv.removeEventListener('did-fail-load', onDidFailLoad);
    };
  }, [isElectron, activeTab.id, setTabs]);

  const navigateActiveTabTo = (targetUrl: string, targetTitle?: string) => {
    const resolved = normalizeBrowserInput(targetUrl);
    if (!resolved) {
      if (targetUrl.trim()) {
        onNotify?.(
          'warning',
          'Blocked URL Scheme',
          'Only http:// and https:// URLs or plain search queries are permitted.'
        );
      }
      return;
    }
    const finalTitle = targetTitle || resolved.title;
    setWebviewLoadError((prev) => (prev?.tabId === activeTab.id ? null : prev));
    setAddressInput(resolved.url);
    safeLoadWebviewUrl(resolved.url, activeTab.id);
    setTabs((prev) =>
      prev.map((t) =>
        t.id === activeTab.id
          ? { ...t, url: resolved.url, liveUrl: resolved.url, title: finalTitle }
          : t
      )
    );
  };

  const handleNavigate = (e: React.FormEvent) => {
    e.preventDefault();
    navigateActiveTabTo(addressInput);
  };

  const handleGoBack = () => {
    if (webviewDomReadyTabRef.current !== activeTab.id) return;
    try {
      if (webviewRef.current?.canGoBack?.()) {
        webviewRef.current.goBack?.();
      }
    } catch {
      // ignore if webview not ready
    }
  };

  const handleGoForward = () => {
    if (webviewDomReadyTabRef.current !== activeTab.id) return;
    try {
      if (webviewRef.current?.canGoForward?.()) {
        webviewRef.current.goForward?.();
      }
    } catch {
      // ignore if webview not ready
    }
  };

  const handleReload = () => {
    setWebviewLoadError((prev) => (prev?.tabId === activeTab.id ? null : prev));
    if (isElectron && webviewDomReadyTabRef.current === activeTab.id) {
      try {
        if (webviewRef.current?.reload) {
          webviewRef.current.reload();
          return;
        }
      } catch {
        // ignore
      }
    }
    navigateActiveTabTo(effectiveCurrentUrl, activeTab.title);
  };

  const handleGoHome = () => {
    navigateActiveTabTo(BROWSER_HOME_URL, BROWSER_HOME_TITLE);
  };

  const handleGithubEnvSignIn = async () => {
    const returnTarget = effectiveCurrentUrl.startsWith('https://github.com')
      ? effectiveCurrentUrl
      : BROWSER_HOME_URL;
    if (desktopBridge?.triggerGithubSignIn) {
      const res = await desktopBridge.triggerGithubSignIn(returnTarget).catch(() => null);
      if (res?.loginUrl) {
        navigateActiveTabTo(res.loginUrl, 'GitHub Sign In');
        return;
      }
    }
    navigateActiveTabTo(
      `https://github.com/login?return_to=${encodeURIComponent(returnTarget)}`,
      'GitHub Sign In'
    );
  };

  const handleSyncFccOrgRepos = async () => {
    if (syncingOrg) return;
    setSyncingOrg(true);
    try {
      const res = await kairosApi.syncGitHubOrgToVault('ForestCityCreatorsLLC');
      setFccRepos(res.repos || []);
      setClipFeedback(
        'success',
        `Synced ${res.repo_count} ForestCityCreatorsLLC repo(s) → ${res.catalog_rel_path}`
      );
      onVaultMutated?.();
      onNotify?.(
        'success',
        'Synced ForestCityCreatorsLLC GitHub Catalog',
        `${res.repo_count} repo(s) saved to ${res.catalog_rel_path}`
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'GitHub org sync failed';
      setClipFeedback('error', msg);
      onNotify?.('error', 'GitHub Org Sync Failed', msg);
    } finally {
      setSyncingOrg(false);
    }
  };

  const handleToggleFccReposDrawer = async () => {
    const nextOpen = !showFccReposDrawer;
    setShowFccReposDrawer(nextOpen);
    if (nextOpen) {
      setShowHubEntryComposer(false);
      setLoadingFccRepos(true);
      try {
        const res = await kairosApi.listGitHubOrgRepos('ForestCityCreatorsLLC');
        setFccRepos(res.repos || []);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unable to load ForestCityCreatorsLLC repositories';
        setClipFeedback('error', msg);
      } finally {
        setLoadingFccRepos(false);
      }
    }
  };

  const handleCreateRepoTask = async (repo: {
    name: string;
    full_name: string;
    html_url: string;
    description: string;
  }) => {
    const targetProj = projects[0]?.name || 'KAIROS_2_0';
    try {
      const created = await kairosApi.createTask({
        title: `[${repo.name}] Engineering Sprint Task`,
        project: targetProj,
        department: 'Software_Development',
        list: 'Sprint_01',
        priority: 2,
        description: `Repository: [${repo.full_name}](${repo.html_url})\n\n${repo.description || 'Tracked from Embedded Browser ForestCityCreatorsLLC drawer.'}`,
        tags: ['github', repo.name.toLowerCase()],
      });
      const tid = String(created.frontmatter.id || '');
      onVaultMutated?.();
      setShowFccReposDrawer(false);
      if (onExecuteUiCommands && tid) {
        onExecuteUiCommands(
          [
            { type: 'navigate_tab', tab: 'projects' },
            {
              type: 'select_project_scope',
              project: targetProj,
              department: 'Software_Development',
              list: 'Sprint_01',
            },
            { type: 'open_task_drawer', task_id: tid },
          ],
          `Created ${tid} for ${repo.full_name}`,
          'Browser-GitHub'
        );
      } else {
        setClipFeedback('success', `Created task ${tid} for ${repo.full_name}`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to create repository task';
      setClipFeedback('error', msg);
    }
  };

  const handleOpenHubEntryComposer = () => {
    const next = !showHubEntryComposer;
    setShowHubEntryComposer(next);
    if (!next) return;
    setShowFccReposDrawer(false);
    let cleanTitle = (activeTab.title || '').trim();
    let vendorGuess = '';
    for (const sep of [' — ', ' - ', ' | ']) {
      if (cleanTitle.includes(sep)) {
        const [lhs, rhs] = cleanTitle.split(sep);
        if (lhs?.trim() && rhs?.trim()) {
          cleanTitle = lhs.trim();
          vendorGuess = rhs.trim();
          break;
        }
      }
    }
    setHubEntryTitle(cleanTitle || effectiveCurrentUrl);
    setHubEntryVendor(vendorGuess);
    if (vaultSections.length > 0) {
      const firstSec = vaultSections[0];
      setHubEntrySection(firstSec.section_rel);
      setHubEntryCollection(firstSec.collections?.[0]?.folder || '');
    } else {
      setHubEntrySection('__auto_music__');
      setHubEntryCollection('Plugins');
    }
  };

  const handleSaveHubEntry = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hubEntryTitle.trim() || savingHubEntry) return;
    setSavingHubEntry(true);
    try {
      let targetSectionRel = hubEntrySection;
      if (targetSectionRel === '__auto_music__') {
        const scaf = await kairosApi.scaffoldVaultSection({
          blueprint_key: 'music_production',
          seed_starters: true,
        });
        targetSectionRel = scaf.section_rel;
      }
      const isPrivateDest =
        destFolder === '03_Personal/Finance' ||
        /#private\b/i.test(hubEntryTitle) ||
        effectiveCurrentUrl.toLowerCase().includes('#private');
      const urlKey = hubEntryCollection === 'Distribution' ? 'dashboard_url' : 'support_url';
      const props: Record<string, unknown> = {
        status: 'Active',
        [urlKey]: effectiveCurrentUrl,
      };
      if (hubEntryVendor.trim()) {
        props.vendor = hubEntryVendor.trim();
      }
      const saved = await kairosApi.createVaultSectionEntry({
        section_or_folder: targetSectionRel,
        collection: hubEntryCollection,
        title: hubEntryTitle.trim(),
        properties: props,
        is_private: isPrivateDest,
      });
      setShowHubEntryComposer(false);
      setClipFeedback('success', `Saved structured Hub entry → ${saved.rel_path}`);
      onVaultMutated?.();
      onNotify?.('success', 'Saved Section Hub Entry', saved.rel_path);
      onClippedToVault(saved.rel_path);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to save Section Hub entry';
      setClipFeedback('error', msg);
      onNotify?.('error', 'Hub Entry Save Failed', msg);
    } finally {
      setSavingHubEntry(false);
    }
  };

  const handleOpenExternal = () => {
    window.open(effectiveCurrentUrl, '_blank', 'noopener,noreferrer');
  };

  const handleAddTab = (
    initialUrl = BROWSER_HOME_URL,
    initialTitle = BROWSER_HOME_TITLE
  ) => {
    const id = `tab-${Date.now()}`;
    const newTab: BrowserTab = {
      id,
      title: initialTitle,
      url: initialUrl,
      liveUrl: initialUrl,
    };
    setTabs((prev) => [...prev, newTab]);
    setActiveTabId(id);
  };

  const handleCloseTab = (id: string) => {
    if (tabs.length <= 1) return;
    const filtered = tabs.filter((t) => t.id !== id);
    setTabs(filtered);
    if (activeTabId === id) {
      setActiveTabId(filtered[filtered.length - 1].id);
    }
  };

  const extractLiveWebviewHtml = async (): Promise<string> => {
    if (!isElectron || webviewDomReadyTabRef.current !== activeTab.id) return '';
    const wv = webviewRef.current;
    if (!wv || typeof wv.executeJavaScript !== 'function') return '';
    try {
      const result = await Promise.race([
        wv.executeJavaScript(
          'document.documentElement ? document.documentElement.outerHTML.slice(0, 1500000) : ""',
          false
        ),
        new Promise<string>((resolve) => window.setTimeout(() => resolve(''), 1500)),
      ]);
      return typeof result === 'string' ? result : '';
    } catch {
      return '';
    }
  };

  const handleClipPage = async (overrideFolder?: string, retainInHermes = false) => {
    if (clipping) return;
    const targetFolder = overrideFolder || destFolder;
    const clipUrl = effectiveCurrentUrl;
    setClipping(true);
    setClipStatus('');
    try {
      const liveHtml = await extractLiveWebviewHtml();
      const saved = await kairosApi.clipWebpage(clipUrl, activeTab.title, targetFolder, liveHtml);
      if (retainInHermes) {
        const prefix = saved.is_private ? '[#private] ' : '';
        await kairosApi.retainHermesMemory({
          fact: `${prefix}Clipped [[${saved.title}]] (${saved.rel_path}) from ${clipUrl}`,
          target: 'memory',
          section: 'Web Research & Browser Clips',
          is_private: Boolean(saved.is_private),
        });
        setClipFeedback('success', `Clipped to ${saved.rel_path} + retained in Hermes MEMORY.md`);
      } else {
        setClipFeedback('success', `Saved clean Markdown to ${saved.rel_path}`);
      }
      onClippedToVault(saved.rel_path);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Clip failed';
      setClipFeedback('error', msg);
      onNotify?.('error', 'Web Clip Failed', msg);
    } finally {
      setClipping(false);
    }
  };

  const handleClipToTask = async () => {
    if (clipping) return;
    const clipUrl = effectiveCurrentUrl;
    const clipFolder =
      destFolder === '03_Personal/Finance' ? '03_Personal/Finance' : '04_Resources/Code_and_Research';
    setClipping(true);
    setClipStatus('');
    try {
      const liveHtml = await extractLiveWebviewHtml();
      const saved = await kairosApi.clipWebpage(clipUrl, activeTab.title, clipFolder, liveHtml);
      const targetProj = destFolder.startsWith('02_Projects/')
        ? destFolder.split('/')[1] || 'KAIROS_2_0'
        : projects[0]?.name || 'KAIROS_2_0';
      const created = await kairosApi.createTask({
        title: `Research: ${saved.title}`,
        project: targetProj,
        department: 'Software_Development',
        list: 'Sprint_01',
        status: 'To Do',
        priority: 2,
        description: `Clipped from ${clipUrl}\n\nLinked Research Clip: [[${saved.rel_path}|${saved.title}]]`,
        tags: saved.is_private ? ['private'] : undefined,
      });
      const tid = String(created.frontmatter?.id || '');
      setClipFeedback('success', `Clipped ${saved.rel_path} → Created Task ${tid}`);
      onVaultMutated?.();
      if (tid && onExecuteUiCommands) {
        onExecuteUiCommands(
          [
            { type: 'navigate_tab', tab: 'projects' },
            { type: 'open_task_drawer', task_id: tid },
          ],
          `Created ${tid} from browser clip`,
          'Browser-Clipper'
        );
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Clip → Task failed';
      setClipFeedback('error', msg);
      onNotify?.('error', 'Clip → Task Failed', msg);
    } finally {
      setClipping(false);
    }
  };

  const handleClipToSkill = async () => {
    if (clipping) return;
    const clipUrl = effectiveCurrentUrl;
    const clipFolder =
      destFolder === '03_Personal/Finance' ? '03_Personal/Finance' : '04_Resources/Code_and_Research';
    setClipping(true);
    setClipStatus('');
    try {
      const liveHtml = await extractLiveWebviewHtml();
      const saved = await kairosApi.clipWebpage(clipUrl, activeTab.title, clipFolder, liveHtml);
      const skill = await kairosApi.createHermesSkill({
        title: saved.title,
        category: 'Web_Research',
        trigger: `When applying insights from ${clipUrl}`,
        steps_markdown: (saved.body || '').slice(0, 3200),
        is_private: Boolean(saved.is_private),
      });
      setClipFeedback('success', `Distilled Hermes Skill ${skill.skill_id} (${skill.rel_path})`);
      onClippedToVault(skill.rel_path);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Clip → Skill failed';
      setClipFeedback('error', msg);
      onNotify?.('error', 'Clip → Skill Failed', msg);
    } finally {
      setClipping(false);
    }
  };

  useEffect(() => {
    if (!externalBrowserSignal || externalBrowserSignal.seq === 0) return;
    // Standalone fallback if uncontrolled; when controlled from App.tsx, App.tsx updates tabs directly
    if (!controlledTabs && externalBrowserSignal.navigateUrl) {
      navigateActiveTabTo(externalBrowserSignal.navigateUrl, externalBrowserSignal.navigateTitle);
    } else if (isElectron && externalBrowserSignal.navigateUrl) {
      safeLoadWebviewUrl(externalBrowserSignal.navigateUrl, activeTab.id);
    }
    if (externalBrowserSignal.controlAction) {
      switch (externalBrowserSignal.controlAction) {
        case 'back':
          handleGoBack();
          break;
        case 'forward':
          handleGoForward();
          break;
        case 'reload':
          handleReload();
          break;
        case 'home':
          if (!controlledTabs) {
            handleGoHome();
          } else if (isElectron) {
            safeLoadWebviewUrl(BROWSER_HOME_URL, activeTab.id);
          }
          break;
        case 'new_tab':
          if (!controlledTabs) {
            handleAddTab();
          }
          break;
        case 'close_tab':
          if (!controlledTabs) {
            handleCloseTab(activeTab.id);
          }
          break;
      }
    }
    if (externalBrowserSignal.clipDestFolder) {
      setDestFolder(externalBrowserSignal.clipDestFolder);
      handleClipPage(externalBrowserSignal.clipDestFolder).catch(() => {});
    }
  }, [externalBrowserSignal?.seq]);

  const showWebPreviewRestrictionBanner =
    !isElectron && isFrameRestrictedInWebPreview(effectiveCurrentUrl);

  return (
    <div className="flex-1 flex flex-col min-w-0 w-full bg-kairos-bg overflow-hidden">
      {/* Multi-Tab Bar + Quick Launch Bookmarks */}
      <div className="flex items-center justify-between gap-2 border-b border-kairos-border bg-kairos-panel px-3 pt-2">
        <div className="flex items-center gap-1 overflow-x-auto min-w-0">
          {tabs.map((t) => {
            const active = t.id === activeTab.id;
            const isYt = (t.liveUrl || t.url).includes('youtube.com');
            return (
              <div
                key={t.id}
                onClick={() => setActiveTabId(t.id)}
                className={`flex items-center gap-2 rounded-t-lg border border-b-0 px-3 py-1.5 text-xs cursor-pointer transition shrink-0 ${
                  active
                    ? 'border-kairos-border bg-kairos-bg text-emerald-300 font-semibold'
                    : 'border-transparent bg-kairos-card/40 text-slate-400 hover:text-white'
                }`}
              >
                {isYt ? (
                  <Play className="h-3 w-3 shrink-0 text-rose-400" />
                ) : (
                  <Globe className="h-3 w-3 shrink-0" />
                )}
                <span className="max-w-[175px] truncate">{t.title}</span>
                {tabs.length > 1 && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCloseTab(t.id);
                    }}
                    className="text-slate-500 hover:text-white"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
            );
          })}
          <button
            type="button"
            onClick={() => handleAddTab()}
            title="Open New Browser Tab"
            className="ml-1 rounded p-1 text-slate-400 hover:bg-kairos-card hover:text-white shrink-0"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="hidden xl:flex items-center gap-1 pb-1.5 shrink-0">
          {QUICK_BOOKMARKS.map((bm) => (
            <button
              key={bm.url}
              type="button"
              onClick={() => navigateActiveTabTo(bm.url, bm.title)}
              className="rounded-md border border-kairos-border bg-kairos-card/60 px-2 py-0.5 text-[10.5px] font-medium text-slate-300 hover:border-emerald-500/50 hover:text-white transition"
            >
              {bm.label}
            </button>
          ))}
          <button
            type="button"
            onClick={handleToggleFccReposDrawer}
            title="Browse ForestCityCreatorsLLC repositories (Private & Public) and open in Browser or create Sprint Tasks"
            className={`flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10.5px] font-semibold transition ${
              showFccReposDrawer
                ? 'border-emerald-500/50 bg-emerald-500/20 text-emerald-200'
                : 'border-emerald-500/35 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'
            }`}
          >
            <GitBranch className="h-3 w-3" />
            <span>FCC Repos</span>
          </button>
          <button
            type="button"
            disabled={syncingOrg}
            onClick={handleSyncFccOrgRepos}
            title="Sync ForestCityCreatorsLLC GitHub repository catalog into Canopy Vault (04_Resources/Code_and_Research/ForestCityCreatorsLLC_Repositories.md)"
            className="flex items-center gap-1 rounded-md border border-cyan-500/35 bg-cyan-500/10 px-2 py-0.5 text-[10.5px] font-semibold text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50 transition"
          >
            <GitBranch className="h-3 w-3" />
            <span>{syncingOrg ? 'Syncing...' : 'Sync FCC Repos'}</span>
          </button>
        </div>
      </div>

      {/* Browser Navigation Controls + Address/Search Bar + Defuddle Clipper Controls */}
      <div className="flex flex-wrap items-center gap-2 border-b border-kairos-border bg-kairos-bg px-3 py-2">
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={handleGoBack}
            title="Back"
            className="rounded-lg border border-kairos-border bg-kairos-panel p-1.5 text-slate-300 hover:bg-kairos-card hover:text-white"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={handleGoForward}
            title="Forward"
            className="rounded-lg border border-kairos-border bg-kairos-panel p-1.5 text-slate-300 hover:bg-kairos-card hover:text-white"
          >
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={handleReload}
            title="Reload Current Tab"
            className="rounded-lg border border-kairos-border bg-kairos-panel p-1.5 text-slate-300 hover:bg-kairos-card hover:text-white"
          >
            <RotateCw className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={handleGoHome}
            title="Home — Forest City Creators LLC Repositories"
            aria-label="Home — Forest City Creators LLC Repositories"
            className="rounded-lg border border-kairos-border bg-kairos-panel p-1.5 text-emerald-300 hover:bg-kairos-card hover:text-emerald-200"
          >
            <Home className="h-3.5 w-3.5" />
          </button>
          {isElectron && (githubAuthInfo.configured || githubAuthInfo.loggedIn) && (
            <button
              type="button"
              onClick={
                githubAuthInfo.loggedIn ? handleGoHome : handleGithubEnvSignIn
              }
              title={
                githubAuthInfo.loggedIn
                  ? `Signed in to GitHub${
                      githubAuthInfo.username ? ` (${githubAuthInfo.username})` : ''
                    } — click to open Forest City Creators LLC Repositories`
                  : `Sign in to GitHub as ${githubAuthInfo.username} using .env credentials`
              }
              aria-label={
                githubAuthInfo.loggedIn
                  ? 'GitHub Session Authenticated'
                  : 'Sign in to GitHub using .env credentials'
              }
              className={`flex items-center gap-1 rounded-lg border px-2 py-1.5 text-[11px] font-medium transition ${
                githubAuthInfo.loggedIn
                  ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-200 hover:bg-emerald-500/25'
                  : 'border-amber-500/40 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20'
              }`}
            >
              {githubAuthInfo.loggedIn ? (
                <CircleCheck className="h-3 w-3 text-emerald-300" />
              ) : (
                <KeyRound className="h-3 w-3 text-amber-300" />
              )}
              <span>{githubAuthInfo.loggedIn ? 'GitHub' : 'Sign In'}</span>
            </button>
          )}
        </div>

        <form onSubmit={handleNavigate} className="flex-1 flex items-center gap-2 min-w-[260px]">
          <div className="relative flex-1 flex items-center">
            <Search className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-slate-500" />
            <input
              type="text"
              value={addressInput}
              onChange={(e) => setAddressInput(e.target.value)}
              placeholder="Enter URL or search query (or say: 'Can you pull up highlights of the game?')..."
              className="w-full rounded-lg border border-kairos-border bg-kairos-panel pl-8 pr-3 py-1.5 text-xs font-mono text-slate-200 focus:border-emerald-500/50 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            className="flex items-center gap-1 rounded-lg border border-kairos-border bg-kairos-card px-2.5 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-800"
          >
            Go
          </button>
          <button
            type="button"
            onClick={handleOpenExternal}
            title="Open Current Page in System Browser"
            className="flex items-center gap-1 rounded-lg border border-kairos-border bg-kairos-panel px-2 py-1.5 text-xs text-cyan-300 hover:bg-kairos-card hover:text-cyan-200"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
        </form>

        <div className="flex flex-wrap items-center gap-1.5">
          <select
            value={destFolder}
            onChange={(e) => setDestFolder(e.target.value)}
            className="rounded-lg border border-kairos-border bg-kairos-panel px-2 py-1.5 text-xs text-slate-300"
          >
            {clipDestinations.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>

          <button
            type="button"
            disabled={clipping}
            onClick={() => handleClipPage()}
            className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
          >
            <Scissors className="h-3.5 w-3.5" />
            {clipping ? 'Clipping...' : 'Clip to Canopy Vault'}
          </button>

          <button
            type="button"
            disabled={clipping}
            onClick={() => handleClipPage(undefined, true)}
            title="Clip clean Markdown AND retain reference in 04_Resources/Hermes/MEMORY.md"
            className="rounded-lg border border-purple-500/40 bg-purple-500/15 px-2.5 py-1.5 text-xs font-semibold text-purple-200 hover:bg-purple-500/25 disabled:opacity-50"
          >
            🪽 Clip + Hermes
          </button>

          <button
            type="button"
            disabled={clipping}
            onClick={handleClipToTask}
            title="Clip clean Markdown to 04_Resources and open a linked TSK-*.md task in Projects"
            className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-2.5 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-50"
          >
            🎯 Clip → Task
          </button>

          <button
            type="button"
            disabled={clipping}
            onClick={handleClipToSkill}
            title="Clip webpage and distill into a reusable Hermes SKL-*.md Skill"
            className="rounded-lg border border-amber-500/40 bg-amber-500/15 px-2.5 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
          >
            ⚡ Clip → Skill
          </button>

          <button
            type="button"
            onClick={handleOpenHubEntryComposer}
            title="Save active webpage as a structured Obsidian Section Hub entry (e.g. Music Studio Plugins / Support / Distribution) indexed in .base"
            className={`flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition ${
              showHubEntryComposer
                ? 'border-purple-400 bg-purple-500/25 text-purple-100'
                : 'border-purple-500/40 bg-purple-500/15 text-purple-200 hover:bg-purple-500/25'
            }`}
          >
            <FolderPlus className="h-3.5 w-3.5" /> + Hub Entry
          </button>

          <button
            type="button"
            onClick={() => setShowAgentFeed((v) => !v)}
            className={`flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition ${
              showAgentFeed
                ? 'border-cyan-500/50 bg-cyan-500/20 text-cyan-200'
                : 'border-kairos-border bg-kairos-panel text-slate-300 hover:text-cyan-200'
            }`}
          >
            <Paperclip className="h-3.5 w-3.5" /> Co-Browser
          </button>
        </div>
      </div>

      {/* Inline ForestCityCreatorsLLC Repositories Quick Drawer */}
      {showFccReposDrawer && (
        <div className="border-b border-emerald-500/30 bg-kairos-panel/95 px-4 py-2.5 space-y-2 max-h-56 overflow-y-auto">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-bold text-emerald-300">
              <GitBranch className="h-3.5 w-3.5" />
              <span>ForestCityCreatorsLLC Repositories ({fccRepos.length})</span>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={fccReposFilter}
                onChange={(e) => setFccReposFilter(e.target.value)}
                placeholder="Filter repositories..."
                className="w-48 rounded border border-kairos-border bg-kairos-bg px-2.5 py-1 text-[11px] text-white focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setShowFccReposDrawer(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          {loadingFccRepos ? (
            <div className="text-xs text-slate-400">Loading ForestCityCreatorsLLC repositories...</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-1.5">
              {fccRepos
                .filter((r) => {
                  const q = fccReposFilter.trim().toLowerCase();
                  if (!q) return true;
                  return (
                    r.name.toLowerCase().includes(q) ||
                    r.description.toLowerCase().includes(q) ||
                    r.language.toLowerCase().includes(q)
                  );
                })
                .map((r) => (
                  <div
                    key={r.full_name}
                    className="flex items-center justify-between gap-2 rounded-lg border border-kairos-border bg-kairos-bg/85 px-2.5 py-1.5 text-xs"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        {r.private ? (
                          <Lock className="h-3 w-3 text-amber-300 shrink-0" />
                        ) : (
                          <Globe className="h-3 w-3 text-cyan-400 shrink-0" />
                        )}
                        <span className="font-semibold text-white truncate">{r.name}</span>
                        <span className="text-[10px] font-mono text-slate-400 shrink-0">
                          {r.language}
                        </span>
                      </div>
                      {r.description && (
                        <div className="text-[10.5px] text-slate-400 truncate">{r.description}</div>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        type="button"
                        onClick={() => {
                          navigateActiveTabTo(r.html_url, r.full_name);
                          setShowFccReposDrawer(false);
                        }}
                        className="rounded bg-emerald-500/20 border border-emerald-500/35 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 hover:bg-emerald-500/30"
                      >
                        Open
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          handleAddTab(r.html_url, r.full_name);
                          setShowFccReposDrawer(false);
                        }}
                        title="Open in New Browser Tab"
                        className="rounded border border-kairos-border bg-kairos-panel px-1.5 py-0.5 text-[10px] text-slate-300 hover:text-white"
                      >
                        +Tab
                      </button>
                      <button
                        type="button"
                        onClick={() => handleCreateRepoTask(r)}
                        title="Create Sprint Task for Repository"
                        className="rounded border border-amber-500/35 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/25"
                      >
                        🎯 Task
                      </button>
                    </div>
                  </div>
                ))}
            </div>
          )}
        </div>
      )}

      {/* Inline Structured Section Hub Entry Composer */}
      {showHubEntryComposer && (
        <form
          onSubmit={handleSaveHubEntry}
          className="flex flex-wrap items-center gap-2 border-b border-purple-500/30 bg-kairos-panel/95 px-4 py-2 text-xs"
        >
          <span className="font-bold text-purple-300">🗂️ Save Page → Section Hub:</span>
          <select
            value={hubEntrySection}
            onChange={(e) => {
              const val = e.target.value;
              setHubEntrySection(val);
              const found = vaultSections.find((s) => s.section_rel === val);
              if (found) {
                setHubEntryCollection(found.collections?.[0]?.folder || '');
              } else if (val === '__auto_music__') {
                setHubEntryCollection('Plugins');
              }
            }}
            className="rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-white"
          >
            {vaultSections.map((s) => (
              <option key={s.section_rel} value={s.section_rel}>
                {s.icon || '🗂️'} {s.title}
              </option>
            ))}
            {!vaultSections.some((s) => s.section_rel === '04_Resources/Music_Studio') && (
              <option value="__auto_music__">🎵 Music Studio (Auto-Scaffold Hub)</option>
            )}
          </select>

          <select
            value={hubEntryCollection}
            onChange={(e) => setHubEntryCollection(e.target.value)}
            className="rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-white"
          >
            {hubEntrySection === '__auto_music__' ? (
              <>
                <option value="Plugins">🎛️ Plug-ins &amp; Instruments</option>
                <option value="Addons_and_Presets">🧩 Add-ons &amp; Presets</option>
                <option value="Samples_and_Packs">🥁 Samples &amp; Packs</option>
                <option value="Support_and_Websites">🌐 Support &amp; Websites</option>
                <option value="Distribution">🚀 Online Distribution</option>
              </>
            ) : (
              (vaultSections.find((s) => s.section_rel === hubEntrySection)?.collections || []).map(
                (c) => (
                  <option key={c.folder} value={c.folder}>
                    {c.icon} {c.title}
                  </option>
                )
              )
            )}
          </select>

          <input
            type="text"
            required
            value={hubEntryTitle}
            onChange={(e) => setHubEntryTitle(e.target.value)}
            placeholder="Entry Title (e.g. Serum 2, DistroKid)"
            className="flex-1 min-w-[180px] rounded border border-kairos-border bg-kairos-bg px-2.5 py-1 text-xs text-white"
          />
          <input
            type="text"
            value={hubEntryVendor}
            onChange={(e) => setHubEntryVendor(e.target.value)}
            placeholder="Vendor / Platform (optional)"
            className="w-40 rounded border border-kairos-border bg-kairos-bg px-2.5 py-1 text-xs text-white"
          />
          <button
            type="submit"
            disabled={savingHubEntry}
            className="rounded bg-purple-500 px-3 py-1 font-semibold text-white hover:bg-purple-400 disabled:opacity-50"
          >
            {savingHubEntry ? 'Saving...' : 'Save to Hub'}
          </button>
          <button
            type="button"
            onClick={() => setShowHubEntryComposer(false)}
            className="rounded border border-kairos-border px-2 py-1 text-slate-400 hover:text-white"
          >
            Cancel
          </button>
        </form>
      )}

      {clipStatus && (
        <div
          className={`flex items-center justify-between border-b px-4 py-1.5 text-xs ${
            clipStatusKind === 'error'
              ? 'bg-rose-500/15 border-rose-500/35 text-rose-200'
              : 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
          }`}
        >
          <span>
            {clipStatusKind === 'error' ? '⚠ ' : '✓ '}
            {clipStatus}
          </span>
          <button
            type="button"
            onClick={() => setClipStatus('')}
            className="ml-2 text-slate-400 hover:text-white"
            title="Dismiss clip status"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Viewport + Collapsible Paperclip/CrewAI/Hermes Co-Browsing Sidebar */}
      <div className="flex-1 flex min-w-0 min-h-0 w-full overflow-hidden">
        <div className="flex-1 min-w-0 relative bg-[#0B101C]">
          {isElectron ? (
            <>
              {webviewLoadError?.tabId === activeTab.id && (
                <div className="absolute inset-x-4 top-4 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-[#0F1726]/95 px-4 py-3 text-xs text-slate-200 shadow-2xl">
                  <div className="min-w-0 space-y-0.5">
                    <div className="font-semibold text-amber-200">
                      Page failed to load ({webviewLoadError.errorDescription})
                    </div>
                    <div className="truncate font-mono text-[11px] text-slate-400">
                      {webviewLoadError.validatedURL}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={handleReload}
                      className="inline-flex items-center gap-1 rounded-lg bg-emerald-500 px-3 py-1.5 font-semibold text-slate-950 hover:bg-emerald-400"
                    >
                      <RotateCw className="h-3.5 w-3.5" /> Retry
                    </button>
                    <button
                      type="button"
                      onClick={handleOpenExternal}
                      className="inline-flex items-center gap-1 rounded-lg border border-kairos-border bg-kairos-card px-2.5 py-1.5 font-medium text-cyan-300 hover:text-cyan-200"
                    >
                      System Browser <ExternalLink className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setWebviewLoadError(null)}
                      title="Dismiss load warning"
                      className="rounded p-1 text-slate-400 hover:text-white"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              )}
              {React.createElement('webview', {
                key: activeTab.id,
                ref: (el: ElectronWebviewElement | null): void => {
                  if (webviewRef.current !== el) {
                    webviewDomReadyTabRef.current = null;
                  }
                  webviewRef.current = el;
                },
                src: mountedWebviewSrc,
                partition: 'persist:kairos-browser',
                allowpopups: 'true',
                className: 'w-full h-full bg-white',
              } as React.HTMLAttributes<ElectronWebviewElement> &
                React.ClassAttributes<ElectronWebviewElement> &
                Record<string, unknown>)}
            </>
          ) : (
            <div className="w-full h-full flex flex-col bg-[#0B101C]">
              <div className="flex items-center justify-between bg-kairos-panel/80 px-4 py-2 border-b border-kairos-border text-[11px] text-slate-400">
                <span>
                  Web Preview Mode (Launch via Electron `start_kairos_2.bat` for full inline
                  YouTube &amp; web `&lt;webview&gt;` playback without X-Frame-Options limits)
                </span>
                <a
                  href={effectiveCurrentUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 font-semibold text-cyan-400 hover:underline"
                >
                  Open in System Browser <ExternalLink className="h-3 w-3" />
                </a>
              </div>

              {showWebPreviewRestrictionBanner ? (
                <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-4">
                  <div className="rounded-2xl border border-emerald-500/40 bg-kairos-panel p-6 max-w-lg space-y-3 shadow-2xl">
                    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500/15 border border-emerald-500/40">
                      <Play className="h-6 w-6 text-emerald-400" />
                    </div>
                    <div className="text-sm font-bold text-white">{activeTab.title}</div>
                    <div className="text-xs font-mono text-emerald-300 break-all">
                      {effectiveCurrentUrl}
                    </div>
                    <p className="text-xs text-slate-400 leading-relaxed">
                      You are viewing KAIROS in a standard browser tab (`localhost:5173`), where
                      sites like YouTube &amp; ESPN block `&lt;iframe&gt;` embedding. In the
                      KAIROS Electron Desktop app (`start_kairos_2.bat`), this page renders
                      directly inline via Chromium `&lt;webview&gt;`.
                    </p>
                    <a
                      href={effectiveCurrentUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-2 rounded-xl bg-emerald-500 px-4 py-2 text-xs font-bold text-slate-950 hover:bg-emerald-400 transition"
                    >
                      Open {activeTab.title} in New Tab <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  </div>
                </div>
              ) : (
                <iframe
                  title={activeTab.title}
                  src={effectiveCurrentUrl}
                  className="w-full flex-1 bg-white"
                  sandbox="allow-scripts allow-same-origin allow-forms"
                />
              )}
            </div>
          )}
        </div>

        {showAgentFeed && (
          <div className="w-80 shrink-0 border-l border-kairos-border bg-kairos-panel p-3 overflow-y-auto space-y-3">
            <div className="flex items-center gap-2 text-xs font-bold text-purple-300">
              <Bot className="h-4 w-4" />
              Paperclip, CrewAI &amp; Hermes Co-Browsing Feed
            </div>
            <p className="text-[11px] text-slate-400">
              Isolated `persist:kairos-browser` session with WebAuthn/Passkey popups disabled.
              Clips can target `00_Inbox/`, Project Wikis (`02_Projects/[Project]/Docs/`), or
              `04_Resources/Hermes/`.
            </p>

            <div className="space-y-2">
              {(paperclip?.browser_events || []).length === 0 ? (
                <div className="rounded-lg border border-kairos-border bg-kairos-card p-3 text-[11px] text-slate-400">
                  No multi-agent co-browsing events yet. Dispatch `CrewAI-Research` or
                  `Hermes-Agent` with a reference URL from **Paperclip, CrewAI &amp; Hermes** to
                  watch live extraction here.
                </div>
              ) : (
                paperclip?.browser_events.map((ev, i) => (
                  <div
                    key={i}
                    className="rounded-lg border border-purple-500/30 bg-kairos-card p-2.5 text-xs space-y-1"
                  >
                    <div className="flex items-center justify-between text-[10px] text-purple-300 font-mono">
                      {/^TSK-\d{8}-\d{3}$/i.test(ev.task_id) && onExecuteUiCommands ? (
                        <button
                          type="button"
                          onClick={() =>
                            onExecuteUiCommands(
                              [
                                { type: 'navigate_tab', tab: 'projects' },
                                { type: 'open_task_drawer', task_id: ev.task_id.toUpperCase() },
                              ],
                              `Opened ${ev.task_id} from Co-Browser feed`,
                              'Co-Browser'
                            )
                          }
                          className="rounded bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.5 text-emerald-300 hover:bg-emerald-500/25"
                        >
                          🎯 {ev.task_id}
                        </button>
                      ) : (
                        <span>{ev.task_id}</span>
                      )}
                      <span>{ev.timestamp}</span>
                    </div>
                    <div className="text-slate-200">{ev.action}</div>
                    {ev.url && (
                      <button
                        type="button"
                        onClick={() => navigateActiveTabTo(ev.url, ev.task_id || undefined)}
                        className="block w-full text-left text-[10px] text-cyan-400 truncate hover:underline"
                        title={`Load ${ev.url} in active tab`}
                      >
                        {ev.url}
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

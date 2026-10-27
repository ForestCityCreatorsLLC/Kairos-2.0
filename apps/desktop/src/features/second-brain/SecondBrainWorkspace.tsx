import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  ArrowUpDown,
  CalendarPlus,
  Copy,
  Database,
  ExternalLink,
  FilePlus2,
  Folder,
  FolderGit2,
  Layers,
  LayoutGrid,
  Link,
  Lock,
  Network,
  Orbit,
  Pencil,
  Plus,
  Save,
  Search,
  Sparkles,
  Table2,
  Trash2,
  X,
} from 'lucide-react';
import {
  GraphData,
  NoteBacklinkItem,
  TaskSummary,
  UIActionCommand,
  VaultBaseQueryResult,
  VaultHealthReport,
  VaultNoteDetail,
  VaultNoteSummary,
  VaultSectionHubSummary,
  VaultStructureSnapshot,
  kairosApi,
} from '../../api/client.ts';
import { ToastKind } from '../../components/ToastCenter.tsx';

export interface SecondBrainExternalSignal {
  seq: number;
  showGraph?: boolean;
  graphMode?: '3d' | '2d';
  searchQuery?: string;
  folderFilter?: string;
}

interface SecondBrainWorkspaceProps {
  initialFolderFilter?: string;
  selectedNotePath: string;
  onSelectNote: (relPath: string, isPrivate: boolean) => void;
  refreshTick: number;
  onVaultMutated: () => void;
  externalBrainSignal?: SecondBrainExternalSignal;
  onExecuteUiCommands?: (cmds: UIActionCommand[], summary?: string, agent?: string) => void;
  onNotify?: (kind: ToastKind, title: string, detail?: string) => void;
}

const VAULT_BASE_FOLDERS = [
  '',
  '00_Inbox',
  '02_Projects',
  '04_Resources/Hermes',
  '_System',
  '01_Business',
  '03_Personal',
  '04_Resources',
  '05_Archives',
];

function randomCanvasHexId(): string {
  const chars = '0123456789abcdef';
  let out = '';
  for (let i = 0; i < 16; i += 1) {
    out += chars[Math.floor(Math.random() * 16)];
  }
  return out;
}

interface CanvasNodeItem {
  id: string;
  type?: 'text' | 'file' | 'link' | 'group' | string;
  x: number;
  y: number;
  width: number;
  height: number;
  color?: string;
  text?: string;
  file?: string;
  subpath?: string;
  url?: string;
  label?: string;
}

interface CanvasEdgeItem {
  id: string;
  fromNode: string;
  fromSide?: string;
  toNode: string;
  toSide?: string;
  toEnd?: string;
  label?: string;
  color?: string;
}

export const SecondBrainWorkspace: React.FC<SecondBrainWorkspaceProps> = ({
  initialFolderFilter = '',
  selectedNotePath,
  onSelectNote,
  refreshTick,
  onVaultMutated,
  externalBrainSignal,
  onExecuteUiCommands,
  onNotify,
}) => {
  const [folderFilter, setFolderFilter] = useState(initialFolderFilter);
  const [searchQuery, setSearchQuery] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [notes, setNotes] = useState<VaultNoteSummary[]>([]);
  const [allTasks, setAllTasks] = useState<TaskSummary[]>([]);
  const [vaultStructure, setVaultStructure] = useState<VaultStructureSnapshot | null>(null);
  const [activeNote, setActiveNote] = useState<VaultNoteDetail | null>(null);
  const [backlinks, setBacklinks] = useState<NoteBacklinkItem[]>([]);
  const [bodyDraft, setBodyDraft] = useState('');
  const [graph, setGraph] = useState<GraphData>({ nodes: [], edges: [] });
  const [showGraph, setShowGraph] = useState(true);
  const [graphMode, setGraphMode] = useState<'3d' | '2d'>('3d');
  const [yaw, setYaw] = useState(0.4);

  // Quick note & Google Doc embed state
  const [newNotePath, setNewNotePath] = useState('');
  const [creatingNote, setCreatingNote] = useState(false);
  const [gdocUrl, setGdocUrl] = useState('');
  const [showGdocBox, setShowGdocBox] = useState(false);
  const [saveBanner, setSaveBanner] = useState('');

  // `.canvas` state
  const [canvasAddKind, setCanvasAddKind] = useState<'text' | 'link' | 'file' | 'group'>('text');
  const [newCanvasCardText, setNewCanvasCardText] = useState('');
  const [editingCanvasNodeId, setEditingCanvasNodeId] = useState<string | null>(null);
  const [editingCanvasNodeValue, setEditingCanvasNodeValue] = useState('');
  const [edgeFromNode, setEdgeFromNode] = useState('');
  const [edgeToNode, setEdgeToNode] = useState('');
  const [edgeLabel, setEdgeLabel] = useState('');

  // Live `.base` Query Evaluator state
  const [baseResult, setBaseResult] = useState<VaultBaseQueryResult | null>(null);
  const [activeBaseView, setActiveBaseView] = useState('');
  const [baseFilter, setBaseFilter] = useState('');
  const [baseLoading, setBaseLoading] = useState(false);
  const [baseSortCol, setBaseSortCol] = useState<string>('');
  const [baseSortDir, setBaseSortDir] = useState<'asc' | 'desc'>('asc');
  const [editingBaseCell, setEditingBaseCell] = useState<{ relPath: string; colKey: string } | null>(null);
  const [editingBaseCellVal, setEditingBaseCellVal] = useState<string>('');

  // Section Hub Builder Modal state
  const [showHubModal, setShowHubModal] = useState(false);
  const [hubBlueprintKey, setHubBlueprintKey] = useState('music_production');
  const [hubTitle, setHubTitle] = useState('Music Studio, Plugins & Distribution');
  const [hubParentFolder, setHubParentFolder] = useState('04_Resources');
  const [hubIcon, setHubIcon] = useState('🎵');
  const [hubDescription, setHubDescription] = useState('');
  const [hubCollectionsText, setHubCollectionsText] = useState(
    'Plugins, Addons_and_Presets, Samples_and_Packs, Support_and_Websites, Distribution'
  );
  const [hubFieldsText, setHubFieldsText] = useState(
    'category, vendor, format, version, platform, status, support_url, dashboard_url'
  );
  const [hubSeedStarters, setHubSeedStarters] = useState(true);
  const [hubIsPrivate, setHubIsPrivate] = useState(false);
  const [scaffoldingHub, setScaffoldingHub] = useState(false);

  // Structured Section Entry Creator state
  const [showEntryModal, setShowEntryModal] = useState(false);
  const [entryTargetSection, setEntryTargetSection] = useState('');
  const [entryCollection, setEntryCollection] = useState('');
  const [entryTitle, setEntryTitle] = useState('');
  const [entryProps, setEntryProps] = useState<Record<string, string>>({});
  const [entryBody, setEntryBody] = useState('');
  const [entryPrivate, setEntryPrivate] = useState(false);
  const [creatingEntry, setCreatingEntry] = useState(false);

  // Interactive YAML Frontmatter Editor state
  const [addingProp, setAddingProp] = useState(false);
  const [newPropKey, setNewPropKey] = useState('');
  const [newPropVal, setNewPropVal] = useState('');
  const [editingPropKey, setEditingPropKey] = useState<string | null>(null);
  const [editingPropVal, setEditingPropVal] = useState('');

  // Link-Safe Rename / Move state
  const [showRenameBox, setShowRenameBox] = useState(false);
  const [renameDestInput, setRenameDestInput] = useState('');
  const [renameTitleInput, setRenameTitleInput] = useState('');
  const [renameUpdateLinks, setRenameUpdateLinks] = useState(true);

  // Vault Health Diagnostics state
  const [showHealthPanel, setShowHealthPanel] = useState(false);
  const [healthReport, setHealthReport] = useState<VaultHealthReport | null>(null);
  const [loadingHealth, setLoadingHealth] = useState(false);

  const isDirty = Boolean(activeNote && bodyDraft !== activeNote.body);
  const isDirtyRef = useRef(false);
  isDirtyRef.current = isDirty;
  const loadedNotePathRef = useRef('');

  const flashSave = (msg: string, ms = 2500) => {
    setSaveBanner(msg);
    window.setTimeout(() => {
      setSaveBanner((cur) => (cur === msg ? '' : cur));
    }, ms);
  };

  const safeSelectNote = (relPath: string, isPriv: boolean) => {
    if (relPath !== selectedNotePath && isDirtyRef.current) {
      const ok = window.confirm(
        `You have unsaved edits in '${activeNote?.title || selectedNotePath}'. Discard unsaved changes and switch notes?`
      );
      if (!ok) return;
      isDirtyRef.current = false;
    }
    onSelectNote(relPath, isPriv);
  };

  const openExternalUrl = (rawUrl: string, label?: string) => {
    const clean = rawUrl.trim();
    if (!clean.startsWith('http://') && !clean.startsWith('https://')) return;
    if (onExecuteUiCommands) {
      onExecuteUiCommands(
        [
          { type: 'navigate_tab', tab: 'browser' },
          { type: 'browser_navigate', url: clean, title: label || clean, new_tab: true },
        ],
        `Opened ${label || clean} in Embedded Browser`,
        'Second-Brain'
      );
      return;
    }
    window.open(clean, '_blank', 'noopener,noreferrer');
  };

  const draggingRef = useRef<{
    active: boolean;
    startX: number;
    baseYaw: number;
    moved: boolean;
  }>({
    active: false,
    startX: 0,
    baseYaw: 0,
    moved: false,
  });
  const listLoadSeqRef = useRef(0);

  useEffect(() => {
    setFolderFilter(initialFolderFilter);
  }, [initialFolderFilter]);

  useEffect(() => {
    if (!externalBrainSignal || externalBrainSignal.seq === 0) return;
    if (externalBrainSignal.showGraph !== undefined) {
      setShowGraph(externalBrainSignal.showGraph);
    }
    if (externalBrainSignal.graphMode) {
      setGraphMode(externalBrainSignal.graphMode);
    }
    if (externalBrainSignal.searchQuery !== undefined) {
      setSearchQuery(externalBrainSignal.searchQuery);
    }
    if (externalBrainSignal.folderFilter !== undefined) {
      setFolderFilter(externalBrainSignal.folderFilter);
    }
  }, [externalBrainSignal?.seq]);

  useEffect(() => {
    if (!showGraph || graphMode !== '3d') return;
    const id = window.setInterval(() => {
      if (draggingRef.current.active || document.hidden) return;
      const focusedTag = document.activeElement?.tagName;
      if (focusedTag === 'TEXTAREA' || focusedTag === 'INPUT' || focusedTag === 'SELECT') {
        return;
      }
      setYaw((y) => y + 0.012);
    }, 50);
    return () => window.clearInterval(id);
  }, [showGraph, graphMode]);

  const loadListAndGraph = async () => {
    const seq = ++listLoadSeqRef.current;
    const [nRes, gRes, tRes, sRes] = await Promise.all([
      kairosApi.searchNotes(searchQuery, folderFilter, tagFilter),
      kairosApi.getGraph(),
      kairosApi.listTasks({}),
      kairosApi.getVaultStructure().catch(() => null),
    ]);
    if (seq !== listLoadSeqRef.current) return;
    setNotes(nRes.notes);
    setGraph(gRes);
    setAllTasks(tRes.tasks);
    if (sRes) setVaultStructure(sRes);
    if (!selectedNotePath && nRes.notes.length > 0) {
      const first = nRes.notes[0];
      onSelectNote(first.rel_path, first.is_private);
    }
  };

  useEffect(() => {
    loadListAndGraph().catch(() => {});
  }, [searchQuery, folderFilter, tagFilter, refreshTick]);

  useEffect(() => {
    if (!selectedNotePath) {
      loadedNotePathRef.current = '';
      setActiveNote(null);
      setBodyDraft('');
      setBacklinks([]);
      setBaseResult(null);
      return;
    }
    let cancelled = false;
    kairosApi
      .readNote(selectedNotePath)
      .then((d) => {
        if (cancelled) return;
        const sameNote = loadedNotePathRef.current === d.rel_path;
        loadedNotePathRef.current = d.rel_path;
        setActiveNote(d);
        if (!sameNote) {
          setActiveBaseView('');
          setBaseSortCol('');
          setBaseSortDir('asc');
          setEditingBaseCell(null);
          setEditingPropKey(null);
          setShowRenameBox(false);
        }
        if (!sameNote || !isDirtyRef.current) {
          setBodyDraft(d.body);
        }
        onSelectNote(d.rel_path, d.is_private);
      })
      .catch((err) => {
        if (cancelled) return;
        loadedNotePathRef.current = '';
        setActiveNote(null);
        setBodyDraft('');
        const msg = err instanceof Error ? err.message : 'Selected note could not be opened.';
        onNotify?.('warning', 'Vault Note Unavailable', msg);
      });
    kairosApi
      .getNoteBacklinks(selectedNotePath)
      .then((r) => {
        if (!cancelled) setBacklinks(r.backlinks || []);
      })
      .catch(() => {
        if (!cancelled) setBacklinks([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedNotePath, refreshTick]);

  const isBaseFile = Boolean(activeNote?.rel_path.toLowerCase().endsWith('.base'));
  const isCanvasFile = Boolean(activeNote?.rel_path.toLowerCase().endsWith('.canvas'));
  const isMarkdownFile = Boolean(activeNote && !isBaseFile && !isCanvasFile);

  // Live `.base` query evaluation whenever a `.base` file or view tab is selected
  useEffect(() => {
    if (!activeNote || !isBaseFile) {
      setBaseResult(null);
      return;
    }
    let cancelled = false;
    setBaseLoading(true);
    kairosApi
      .queryVaultBase(activeNote.rel_path, activeBaseView)
      .then((res) => {
        if (!cancelled) setBaseResult(res);
      })
      .catch((err) => {
        if (cancelled) return;
        onNotify?.(
          'warning',
          'Obsidian Base Query Error',
          err instanceof Error ? err.message : 'Unable to evaluate .base file'
        );
      })
      .finally(() => {
        if (!cancelled) setBaseLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeNote?.rel_path, activeNote?.body, activeBaseView, isBaseFile, refreshTick]);

  // Detect active Section Hub context from `activeNote` or `folderFilter`
  const activeSectionHub: VaultSectionHubSummary | null = useMemo(() => {
    const sections = vaultStructure?.sections || [];
    if (sections.length === 0) return null;
    const probe = (activeNote?.rel_path || folderFilter || '').toLowerCase();
    if (!probe) return null;
    for (const sec of sections) {
      const secLow = sec.section_rel.toLowerCase();
      if (probe === secLow || probe.startsWith(`${secLow}/`)) {
        return sec;
      }
    }
    return null;
  }, [vaultStructure, activeNote?.rel_path, folderFilter]);

  const applyBlueprintSelection = (bpKey: string) => {
    setHubBlueprintKey(bpKey);
    const bp = vaultStructure?.blueprints.find((b) => b.key === bpKey);
    if (bp) {
      setHubTitle(bp.label);
      setHubParentFolder(bp.default_parent);
      setHubIcon(bp.icon);
      setHubDescription(bp.description);
      setHubCollectionsText(bp.collections.map((c) => c.folder).join(', '));
      setHubFieldsText(bp.schema_fields.join(', '));
      setHubSeedStarters(true);
    } else if (bpKey === 'custom') {
      setHubTitle('');
      setHubParentFolder('04_Resources');
      setHubIcon('🧩');
      setHubDescription('');
      setHubCollectionsText('Catalog, Resources_and_Portals, Guides_and_Workflows');
      setHubFieldsText('category, vendor, version, status, support_url');
      setHubSeedStarters(false);
    }
  };

  const handleScaffoldSectionHub = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hubTitle.trim() && hubBlueprintKey === 'custom') {
      onNotify?.('warning', 'Section Name Required', 'Enter a title for your custom Vault Section Hub.');
      return;
    }
    setScaffoldingHub(true);
    try {
      const bp = vaultStructure?.blueprints.find((b) => b.key === hubBlueprintKey);
      const parsedCols = hubCollectionsText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const defaultBpCols = bp ? bp.collections.map((c) => c.folder).join(', ') : '';
      const useCustomCols =
        hubBlueprintKey === 'custom' || (parsedCols.length > 0 && hubCollectionsText.trim() !== defaultBpCols);
      const parsedFields = hubFieldsText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

      const res = await kairosApi.scaffoldVaultSection({
        section_name: hubTitle.trim(),
        blueprint_key: hubBlueprintKey,
        parent_folder: hubParentFolder.trim() || '04_Resources',
        icon: hubIcon.trim() || '🧩',
        description: hubDescription.trim(),
        collections: useCustomCols ? parsedCols : undefined,
        schema_fields: parsedFields.length > 0 ? parsedFields : undefined,
        seed_starters: hubSeedStarters,
        is_private: hubIsPrivate,
      });
      setShowHubModal(false);
      setFolderFilter(res.section_rel);
      safeSelectNote(res.hub_index_rel, res.is_private);
      flashSave(`Scaffolded ${res.icon} ${res.title} (${res.section_rel}/)`, 3400);
      onVaultMutated();
      await loadListAndGraph();
    } catch (err) {
      onNotify?.(
        'error',
        'Section Hub Scaffold Failed',
        err instanceof Error ? err.message : 'Unable to scaffold Vault section'
      );
    } finally {
      setScaffoldingHub(false);
    }
  };

  const openAddEntryModal = (hub?: VaultSectionHubSummary | null, preferredCollection = '') => {
    const targetHub = hub || activeSectionHub;
    const baseFolder =
      targetHub?.section_rel || baseResult?.inferred_folder || folderFilter || '04_Resources';
    const firstCol = preferredCollection || targetHub?.collections?.[0]?.folder || '';
    const colObj = targetHub?.collections?.find((c) => c.folder === firstCol);
    const fields =
      colObj?.fields ||
      targetHub?.schema_fields ||
      baseResult?.editable_fields || ['category', 'vendor', 'status', 'support_url'];
    const initProps: Record<string, string> = {};
    for (const f of fields) {
      if (f !== 'title' && f !== 'tags') {
        initProps[f] = f === 'status' ? 'Active' : '';
      }
    }
    setEntryTargetSection(baseFolder);
    setEntryCollection(firstCol);
    setEntryTitle('');
    setEntryProps(initProps);
    setEntryBody('');
    setEntryPrivate(Boolean(targetHub?.is_private || baseFolder.toLowerCase().startsWith('03_personal/finance')));
    setShowEntryModal(true);
  };

  const handleEntryCollectionChange = (nextCol: string) => {
    setEntryCollection(nextCol);
    const hub = (vaultStructure?.sections || []).find((s) => s.section_rel === entryTargetSection);
    const colObj = hub?.collections.find((c) => c.folder === nextCol);
    if (colObj && colObj.fields.length > 0) {
      setEntryProps((prev) => {
        const next: Record<string, string> = {};
        for (const f of colObj.fields) {
          next[f] = prev[f] ?? (f === 'status' ? 'Active' : '');
        }
        return next;
      });
    }
  };

  const handleCreateSectionEntry = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!entryTitle.trim()) return;
    setCreatingEntry(true);
    try {
      const hub = (vaultStructure?.sections || []).find((s) => s.section_rel === entryTargetSection);
      const colObj = hub?.collections.find((c) => c.folder === entryCollection);
      const cleanProps: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(entryProps)) {
        if (v.trim() !== '') cleanProps[k] = v.trim();
      }
      const created = await kairosApi.createVaultSectionEntry({
        section_or_folder: entryTargetSection || '04_Resources',
        title: entryTitle.trim(),
        collection: entryCollection,
        item_type: colObj?.item_type || '',
        properties: cleanProps,
        body: entryBody.trim(),
        is_private: entryPrivate,
      });
      setShowEntryModal(false);
      flashSave(`Added '${created.title}' (${created.rel_path})`);
      onVaultMutated();
      await loadListAndGraph();
      if (!isBaseFile) {
        safeSelectNote(created.rel_path, created.is_private);
      } else if (activeNote) {
        kairosApi
          .queryVaultBase(activeNote.rel_path, activeBaseView)
          .then((r) => setBaseResult(r))
          .catch(() => {});
      }
    } catch (err) {
      onNotify?.(
        'error',
        'Create Entry Failed',
        err instanceof Error ? err.message : 'Unable to create structured entry'
      );
    } finally {
      setCreatingEntry(false);
    }
  };

  const handleSave = async () => {
    if (!activeNote) return;
    try {
      const saved = await kairosApi.writeNote(
        activeNote.rel_path,
        activeNote.frontmatter,
        bodyDraft,
        'overwrite'
      );
      setActiveNote(saved);
      setBodyDraft(saved.body);
      isDirtyRef.current = false;
      flashSave('Saved atomically to Canopy Vault');
      onVaultMutated();
      loadListAndGraph().catch(() => {});
      kairosApi
        .getNoteBacklinks(saved.rel_path)
        .then((r) => setBacklinks(r.backlinks || []))
        .catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to save note';
      onNotify?.('error', 'Failed to Save Vault Note', msg);
    }
  };

  const parseFrontmatterValueInput = (key: string, rawVal: string): unknown => {
    const trimmed = rawVal.trim();
    if (key === 'tags' || key === 'aliases' || key === 'schema_fields') {
      return trimmed
        .split(',')
        .map((s) => s.trim().replace(/^#/, ''))
        .filter(Boolean);
    }
    if (trimmed.toLowerCase() === 'true') return true;
    if (trimmed.toLowerCase() === 'false') return false;
    if (/^-?\d+(\.\d+)?$/.test(trimmed) && !key.endsWith('_date') && key !== 'version') {
      return Number(trimmed);
    }
    return trimmed;
  };

  const handlePatchProperty = async (key: string, rawVal: string) => {
    if (!activeNote || !key.trim()) return;
    try {
      const cleanK = key.trim().replace(/[^A-Za-z0-9_-]+/g, '_');
      const parsedVal = parseFrontmatterValueInput(cleanK, rawVal);
      const updated = await kairosApi.updateNoteFrontmatter(activeNote.rel_path, {
        [cleanK]: parsedVal,
      });
      setActiveNote(updated);
      setEditingPropKey(null);
      setAddingProp(false);
      setNewPropKey('');
      setNewPropVal('');
      flashSave(`Updated YAML property '${cleanK}'`);
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Property Update Failed',
        err instanceof Error ? err.message : 'Unable to update YAML frontmatter'
      );
    }
  };

  const handleDeleteProperty = async (key: string) => {
    if (!activeNote) return;
    try {
      const updated = await kairosApi.updateNoteFrontmatter(activeNote.rel_path, {}, [key]);
      setActiveNote(updated);
      flashSave(`Removed YAML property '${key}'`);
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Property Delete Failed',
        err instanceof Error ? err.message : 'Unable to remove YAML property'
      );
    }
  };

  const handleOpenRename = () => {
    if (!activeNote) return;
    setRenameDestInput(activeNote.rel_path);
    setRenameTitleInput(activeNote.title);
    setRenameUpdateLinks(true);
    setShowRenameBox((v) => !v);
  };

  const handleRenameSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeNote || !renameDestInput.trim()) return;
    if (isDirtyRef.current) {
      await handleSave();
    }
    try {
      const res = await kairosApi.renameVaultNote({
        src_rel_path: activeNote.rel_path,
        dest_rel_path: renameDestInput.trim(),
        new_title: renameTitleInput.trim(),
        update_links: renameUpdateLinks,
      });
      setShowRenameBox(false);
      loadedNotePathRef.current = res.new_rel_path;
      setActiveNote(res.note);
      setBodyDraft(res.note.body);
      onSelectNote(res.new_rel_path, res.note.is_private);
      flashSave(
        `Renamed → ${res.new_rel_path} (${res.updated_backlink_files.length} link file(s) updated)`,
        3400
      );
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Rename / Move Failed',
        err instanceof Error ? err.message : 'Unable to rename note'
      );
    }
  };

  const handleLoadVaultHealth = async () => {
    const nextOpen = !showHealthPanel;
    setShowHealthPanel(nextOpen);
    if (!nextOpen) return;
    setLoadingHealth(true);
    try {
      const rep = await kairosApi.getVaultHealth();
      setHealthReport(rep);
    } catch (err) {
      onNotify?.(
        'error',
        'Vault Health Check Failed',
        err instanceof Error ? err.message : 'Unable to audit Vault health'
      );
    } finally {
      setLoadingHealth(false);
    }
  };

  const handleCreateBrokenLinkNote = async (target: string, suggestedFolder: string) => {
    const clean = target.replace(/\.md$/i, '').trim();
    if (!clean) return;
    const fullRel = clean.includes('/') ? `${clean}.md` : `${suggestedFolder || '04_Resources'}/${clean.replace(/\s+/g, '_')}.md`;
    const title = (clean.split('/').pop() || clean).replace(/_/g, ' ');
    try {
      const created = await kairosApi.writeNote(
        fullRel,
        { title, type: 'note', status: 'Active', created_at: new Date().toISOString(), tags: ['note'] },
        `# ${title}\n\n> [!info] Created from Resolved WikiLink\n> Connected inside Canopy Vault.\n`,
        'overwrite'
      );
      flashSave(`Created missing note ${created.rel_path}`);
      onVaultMutated();
      await loadListAndGraph();
      const rep = await kairosApi.getVaultHealth();
      setHealthReport(rep);
      safeSelectNote(created.rel_path, created.is_private);
    } catch (err) {
      onNotify?.(
        'error',
        'Create Linked Note Failed',
        err instanceof Error ? err.message : 'Unable to create missing target note'
      );
    }
  };

  const handleDailyNote = async () => {
    try {
      const daily = await kairosApi.openDailyNote();
      safeSelectNote(daily.rel_path, daily.is_private);
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to open Daily Note';
      onNotify?.('error', 'Daily Note Failed', msg);
    }
  };

  const handleCreateQuickNote = async (e: React.FormEvent) => {
    e.preventDefault();
    const rawInput = newNotePath.trim();
    if (!rawInput) return;
    const hasPrivateTag = /#private\b/i.test(rawInput);
    const strippedName = rawInput.replace(/#private\b/gi, '').trim();
    if (!strippedName) return;
    const hasExt = /\.(md|canvas|base)$/i.test(strippedName);
    const pathClean = hasExt ? strippedName : `${strippedName}.md`;
    const fullRel = pathClean.includes('/')
      ? pathClean
      : `${folderFilter || '00_Inbox'}/${pathClean}`;
    const alreadyExists = notes.some((n) => n.rel_path.toLowerCase() === fullRel.toLowerCase());
    if (alreadyExists) {
      const overwriteOk = window.confirm(
        `A Canopy Vault file already exists at '${fullRel}'. Overwrite it?`
      );
      if (!overwriteOk) return;
    }
    const isPrivFolder = fullRel.toLowerCase().startsWith('03_personal/finance');
    const noteTags = hasPrivateTag || isPrivFolder ? ['note', 'private'] : ['note'];
    const baseTitle = (pathClean.split('/').pop() || pathClean).replace(/\.(md|canvas|base)$/i, '');
    try {
      const initialBody = pathClean.toLowerCase().endsWith('.canvas')
        ? JSON.stringify({ nodes: [], edges: [] }, null, 2)
        : pathClean.toLowerCase().endsWith('.base')
          ? `filters:\n  and:\n    - file.ext == "md"\nviews:\n  - type: table\n    name: "${baseTitle}"\n    order:\n      - file.name\n      - type\n      - status\n`
          : `# ${baseTitle}\n\n> [!note] Context\n> Connected to [[AGENTS]].\n`;
      const created = await kairosApi.writeNote(
        fullRel,
        pathClean.toLowerCase().endsWith('.md')
          ? { title: baseTitle, status: 'Active', created_at: new Date().toISOString(), tags: noteTags }
          : {},
        initialBody,
        'overwrite'
      );
      setNewNotePath('');
      setCreatingNote(false);
      safeSelectNote(created.rel_path, created.is_private);
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to create note';
      onNotify?.('error', 'Create Note Failed', msg);
    }
  };

  const handleEmbedGoogleDoc = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeNote || !gdocUrl.trim()) return;
    try {
      const updated = await kairosApi.linkGoogleDoc(activeNote.rel_path, gdocUrl.trim(), false);
      setActiveNote(updated);
      setBodyDraft(updated.body);
      isDirtyRef.current = false;
      setGdocUrl('');
      setShowGdocBox(false);
      flashSave('Embedded Google Doc into note');
      onVaultMutated();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to embed Google Doc';
      onNotify?.('error', 'Google Doc Embed Failed', msg);
    }
  };

  const handleRetainNoteInHermes = async () => {
    if (!activeNote) return;
    try {
      const cleanLines = bodyDraft
        .split(/\r?\n/)
        .map((ln) => ln.replace(/^#+\s*/, '').trim())
        .filter((ln) => ln.length > 0 && !ln.startsWith('> [!'));
      const takeaway = (cleanLines[0] || activeNote.title).slice(0, 180);
      const prefix = activeNote.is_private ? '[#private] ' : '';
      const res = await kairosApi.retainHermesMemory({
        fact: `${prefix}[[${activeNote.title}]] (${activeNote.rel_path}): ${takeaway}`,
        target: 'memory',
        section: 'Second Brain & Project Wiki Takeaways',
        is_private: Boolean(activeNote.is_private),
      });
      flashSave(`Retained in Hermes (${res.rel_path})`);
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to retain note in Hermes';
      onNotify?.('error', 'Hermes Retain Failed', msg);
    }
  };

  const handleDistillNoteAsHermesSkill = async () => {
    if (!activeNote) return;
    try {
      const created = await kairosApi.createHermesSkill({
        title: activeNote.title,
        category: activeNote.rel_path.startsWith('02_Projects/') ? 'Project_Wiki' : 'Second_Brain',
        trigger: `When referencing ${activeNote.title} (${activeNote.rel_path})`,
        steps_markdown: bodyDraft.slice(0, 3500),
        is_private: Boolean(activeNote.is_private),
      });
      flashSave(`Distilled Hermes Skill ${created.skill_id} (${created.rel_path})`, 3200);
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to distill Hermes skill';
      onNotify?.('error', 'Distill Skill Failed', msg);
    }
  };

  // Compute 2D or 3D-projected Galaxy coordinates
  const positionedGraph = useMemo(() => {
    const maxNodes = graph.nodes.slice(0, 55);
    const cx = 270;
    const cy = 155;
    const coords = new Map<string, { x: number; y: number; scale: number }>();

    maxNodes.forEach((n, idx) => {
      if (graphMode === '2d') {
        const ring = idx % 2 === 0 ? 115 : 68;
        const angle = (idx / Math.max(1, maxNodes.length)) * Math.PI * 2;
        coords.set(n.id, {
          x: cx + Math.cos(angle) * (ring + (idx % 3) * 18),
          y: cy + Math.sin(angle) * (ring + (idx % 3) * 12),
          scale: 1,
        });
      } else {
        const phi = Math.acos(1 - (2 * (idx + 0.5)) / Math.max(1, maxNodes.length));
        const theta = Math.PI * (1 + Math.sqrt(5)) * idx + yaw;
        const radius = 122;
        const x3 = radius * Math.sin(phi) * Math.cos(theta);
        const y3 = radius * Math.cos(phi) * 0.78;
        const z3 = radius * Math.sin(phi) * Math.sin(theta);
        const perspective = 320 / (320 - z3);
        coords.set(n.id, {
          x: cx + x3 * perspective,
          y: cy + y3 * perspective,
          scale: Math.max(0.55, Math.min(1.55, perspective)),
        });
      }
    });
    return { nodes: maxNodes, coords };
  }, [graph, graphMode, yaw]);

  // Parse JSON Canvas Spec 1.0 if active file ends with `.canvas`
  const canvasParsed = useMemo(() => {
    if (!activeNote || !isCanvasFile) return null;
    try {
      return JSON.parse(bodyDraft) as {
        nodes?: CanvasNodeItem[];
        edges?: CanvasEdgeItem[];
      };
    } catch {
      return null;
    }
  }, [activeNote, isCanvasFile, bodyDraft]);

  const describeCanvasNode = (cn: CanvasNodeItem): string => {
    const kind = cn.type || 'text';
    if (kind === 'group') return `🗂️ ${cn.label || cn.id}`;
    if (kind === 'file') return `📄 ${(cn.file || cn.id).split('/').pop() || cn.id}`;
    if (kind === 'link') return `🌐 ${cn.url || cn.id}`;
    const firstLine = (cn.text || cn.id).split('\n')[0].replace(/^#+\s*/, '').trim();
    return `📝 ${(firstLine || cn.id).slice(0, 32)}`;
  };

  const handleAddCanvasCard = async (e: React.FormEvent) => {
    e.preventDefault();
    const rawVal = newCanvasCardText.trim();
    if (!activeNote || !canvasParsed || !rawVal) return;
    const existingNodes = canvasParsed.nodes || [];
    const baseCoord = {
      id: randomCanvasHexId(),
      x: (existingNodes.length % 3) * 320,
      y: Math.floor(existingNodes.length / 3) * 190,
      width: canvasAddKind === 'group' ? 640 : 300,
      height: canvasAddKind === 'group' ? 360 : 150,
    };
    const nextCard: CanvasNodeItem =
      canvasAddKind === 'group'
        ? {
            ...baseCoord,
            type: 'group',
            label: rawVal,
            color: '5',
          }
        : canvasAddKind === 'link'
          ? {
              ...baseCoord,
              type: 'link',
              url: rawVal.startsWith('http') ? rawVal : `https://${rawVal}`,
              color: '2',
            }
          : canvasAddKind === 'file'
            ? {
                ...baseCoord,
                type: 'file',
                file: rawVal,
                color: '4',
              }
            : {
                ...baseCoord,
                type: 'text',
                text: rawVal,
                color: '5',
              };
    const updatedJson = JSON.stringify(
      {
        nodes: [...existingNodes, nextCard],
        edges: canvasParsed.edges || [],
      },
      null,
      2
    );
    try {
      const saved = await kairosApi.writeNote(activeNote.rel_path, {}, updatedJson, 'overwrite');
      setActiveNote(saved);
      setBodyDraft(saved.body);
      isDirtyRef.current = false;
      setNewCanvasCardText('');
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to add card to .canvas';
      onNotify?.('error', 'Canvas Update Failed', msg);
    }
  };

  const handleUpdateCanvasNode = async (nodeId: string, nextValue: string) => {
    const cleanVal = nextValue.trim();
    if (!activeNote || !canvasParsed || !cleanVal) {
      setEditingCanvasNodeId(null);
      return;
    }
    const nextNodes = (canvasParsed.nodes || []).map((cn) => {
      if (cn.id !== nodeId) return cn;
      const nType = cn.type || 'text';
      if (nType === 'group') return { ...cn, label: cleanVal };
      if (nType === 'file') return { ...cn, file: cleanVal };
      if (nType === 'link') {
        return { ...cn, url: cleanVal.startsWith('http') ? cleanVal : `https://${cleanVal}` };
      }
      return { ...cn, text: cleanVal };
    });
    const updatedJson = JSON.stringify(
      {
        nodes: nextNodes,
        edges: canvasParsed.edges || [],
      },
      null,
      2
    );
    try {
      const saved = await kairosApi.writeNote(activeNote.rel_path, {}, updatedJson, 'overwrite');
      setActiveNote(saved);
      setBodyDraft(saved.body);
      isDirtyRef.current = false;
      setEditingCanvasNodeId(null);
      setEditingCanvasNodeValue('');
      flashSave('Updated .canvas node');
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to edit .canvas node';
      onNotify?.('error', 'Canvas Node Edit Failed', msg);
    }
  };

  const handleAddCanvasEdge = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeNote || !canvasParsed) return;
    const nodesList = canvasParsed.nodes || [];
    const fromId = edgeFromNode || nodesList[0]?.id || '';
    const toId = edgeToNode || nodesList[1]?.id || '';
    if (!fromId || !toId || fromId === toId) {
      onNotify?.('warning', 'Select Two Distinct Nodes', 'Pick different From and To .canvas nodes to connect.');
      return;
    }
    const newEdge: CanvasEdgeItem = {
      id: randomCanvasHexId(),
      fromNode: fromId,
      fromSide: 'right',
      toNode: toId,
      toSide: 'left',
      toEnd: 'arrow',
      ...(edgeLabel.trim() ? { label: edgeLabel.trim() } : {}),
    };
    const updatedJson = JSON.stringify(
      {
        nodes: nodesList,
        edges: [...(canvasParsed.edges || []), newEdge],
      },
      null,
      2
    );
    try {
      const saved = await kairosApi.writeNote(activeNote.rel_path, {}, updatedJson, 'overwrite');
      setActiveNote(saved);
      setBodyDraft(saved.body);
      isDirtyRef.current = false;
      setEdgeLabel('');
      flashSave('Connected .canvas edge');
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to connect .canvas edge';
      onNotify?.('error', 'Canvas Edge Failed', msg);
    }
  };

  const handleDeleteCanvasEdge = async (edgeId: string) => {
    if (!activeNote || !canvasParsed) return;
    const nextEdges = (canvasParsed.edges || []).filter((ed) => ed.id !== edgeId);
    const updatedJson = JSON.stringify(
      {
        nodes: canvasParsed.nodes || [],
        edges: nextEdges,
      },
      null,
      2
    );
    try {
      const saved = await kairosApi.writeNote(activeNote.rel_path, {}, updatedJson, 'overwrite');
      setActiveNote(saved);
      setBodyDraft(saved.body);
      isDirtyRef.current = false;
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to remove .canvas edge';
      onNotify?.('error', 'Canvas Edge Remove Failed', msg);
    }
  };

  const handleDeleteCanvasCard = async (nodeId: string) => {
    if (!activeNote || !canvasParsed) return;
    const nextNodes = (canvasParsed.nodes || []).filter((cn) => cn.id !== nodeId);
    const nextEdges = (canvasParsed.edges || []).filter(
      (ed) => ed.fromNode !== nodeId && ed.toNode !== nodeId
    );
    const updatedJson = JSON.stringify(
      {
        nodes: nextNodes,
        edges: nextEdges,
      },
      null,
      2
    );
    try {
      const saved = await kairosApi.writeNote(activeNote.rel_path, {}, updatedJson, 'overwrite');
      setActiveNote(saved);
      setBodyDraft(saved.body);
      isDirtyRef.current = false;
      onVaultMutated();
      loadListAndGraph().catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to remove card from .canvas';
      onNotify?.('error', 'Canvas Update Failed', msg);
    }
  };

  const activeTaskId = useMemo(() => {
    const rawId = String(activeNote?.frontmatter?.id || '').trim();
    return /^TSK-\d{8}-\d{3}$/i.test(rawId) ? rawId.toUpperCase() : '';
  }, [activeNote]);

  const isTaskPrivate = (t: TaskSummary): boolean =>
    Boolean(
      t.tags?.some((tg) => tg.toLowerCase() === 'private') ||
        t.rel_path.toLowerCase().startsWith('03_personal/finance')
    );

  const openTaskInProjectsDrawer = (taskId: string) => {
    if (onExecuteUiCommands) {
      onExecuteUiCommands(
        [
          { type: 'navigate_tab', tab: 'projects' },
          { type: 'open_task_drawer', task_id: taskId },
        ],
        `Opened ${taskId} in Projects Task Drawer`,
        'Second-Brain'
      );
      return;
    }
    const matchTask = allTasks.find((t) => t.id.toUpperCase() === taskId.toUpperCase());
    if (matchTask) safeSelectNote(matchTask.rel_path, isTaskPrivate(matchTask));
  };

  const resolveWikiLinkToNote = (rawTarget: string) => {
    const clean = rawTarget.split('|')[0].split('#')[0].trim();
    if (!clean) return;
    const cleanLower = clean.toLowerCase();
    const matchNote = notes.find(
      (x) =>
        x.title.toLowerCase() === cleanLower ||
        x.rel_path.toLowerCase() === cleanLower ||
        x.rel_path.toLowerCase() === `${cleanLower}.md` ||
        x.rel_path.toLowerCase().endsWith(`/${cleanLower}.md`) ||
        x.rel_path.toLowerCase().endsWith(`/${cleanLower}`)
    );
    if (matchNote) {
      safeSelectNote(matchNote.rel_path, matchNote.is_private);
      return;
    }
    const matchTask = allTasks.find((t) => t.id.toLowerCase() === cleanLower);
    if (matchTask) {
      safeSelectNote(matchTask.rel_path, isTaskPrivate(matchTask));
      return;
    }
    // Fallback: attempt direct Vault read if linked file is outside the current folder filter
    const guessedPath = /\.(md|base|canvas)$/i.test(clean) ? clean : `${clean}.md`;
    kairosApi
      .readNote(guessedPath)
      .then((d) => safeSelectNote(d.rel_path, d.is_private))
      .catch(() => {
        kairosApi
          .searchNotes(clean, '')
          .then((res) => {
            if (res.notes.length > 0) {
              safeSelectNote(res.notes[0].rel_path, res.notes[0].is_private);
            }
          })
          .catch(() => {});
      });
  };

  const renderInlineInteractiveText = (text: string) => {
    const tokenRegex =
      /(!\[\[[^\]]+\]\]|\[\[[^\]]+\]\]|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|==[^=\n]+==|\bTSK-\d{8}-\d{3}\b)/g;
    const parts = text.split(tokenRegex);
    return parts.map((part, idx) => {
      if (part.startsWith('![[') && part.endsWith(']]')) {
        const inner = part.slice(3, -2);
        const [rawRef, subOrAlias] = inner.split('|');
        const [filePart, viewAnchor] = (rawRef || '').split('#');
        const cleanRef = (filePart || '').trim();
        const isEmbeddedBase = cleanRef.toLowerCase().endsWith('.base');
        const isEmbeddedCanvas = cleanRef.toLowerCase().endsWith('.canvas');
        return (
          <button
            key={idx}
            type="button"
            onClick={() => {
              if (isEmbeddedBase && viewAnchor) {
                setActiveBaseView(viewAnchor.trim());
              }
              resolveWikiLinkToNote(cleanRef);
            }}
            className="my-1 inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/35 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-200 hover:bg-emerald-500/20"
            title={`Open embedded Obsidian ${isEmbeddedBase ? 'Base (.base)' : isEmbeddedCanvas ? 'Canvas (.canvas)' : 'Note'}`}
          >
            <Database className="h-3.5 w-3.5 text-emerald-400" />
            <span>
              {isEmbeddedBase ? 'Open Live Obsidian Base: ' : 'Embedded: '}
              <span className="font-mono">{subOrAlias || cleanRef}</span>
              {viewAnchor ? ` (${viewAnchor})` : ''}
            </span>
          </button>
        );
      }
      if (part.startsWith('[[') && part.endsWith(']]')) {
        const inner = part.slice(2, -2);
        const [rawLink, alias] = inner.split('|');
        const linkTarget = (rawLink || '').trim();
        const label = (alias || linkTarget).trim();
        const isTaskLink = /^TSK-\d{8}-\d{3}$/i.test(linkTarget);
        return (
          <span key={idx} className="inline-flex items-center gap-0.5 mx-0.5 align-baseline">
            <button
              type="button"
              onClick={() => resolveWikiLinkToNote(linkTarget)}
              className="rounded bg-cyan-500/15 border border-cyan-500/30 px-1.5 py-0.5 text-[11px] font-mono text-cyan-300 hover:bg-cyan-500/25"
              title={`Open [[${linkTarget}]] in Second Brain`}
            >
              [[{label}]]
            </button>
            {isTaskLink && onExecuteUiCommands && (
              <button
                type="button"
                onClick={() => openTaskInProjectsDrawer(linkTarget.toUpperCase())}
                className="rounded bg-emerald-500/20 border border-emerald-500/35 px-1 py-0.5 text-[10px] font-semibold text-emerald-300 hover:bg-emerald-500/30"
                title={`Inspect ${linkTarget.toUpperCase()} in Projects Task Drawer`}
              >
                🎯
              </button>
            )}
          </span>
        );
      }
      const mExt = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      if (mExt) {
        return (
          <button
            key={idx}
            type="button"
            onClick={() => openExternalUrl(mExt[2], mExt[1])}
            className="mx-0.5 inline-flex items-center gap-1 rounded bg-indigo-500/15 border border-indigo-500/35 px-1.5 py-0.5 text-[11px] font-medium text-indigo-200 hover:bg-indigo-500/25"
            title={`Open ${mExt[2]}`}
          >
            <span>{mExt[1]}</span>
            <ExternalLink className="h-2.5 w-2.5" />
          </button>
        );
      }
      if (part.startsWith('==') && part.endsWith('==') && part.length > 4) {
        return (
          <mark
            key={idx}
            className="rounded bg-amber-400/25 px-1 text-amber-100"
          >
            {part.slice(2, -2)}
          </mark>
        );
      }
      if (/^TSK-\d{8}-\d{3}$/.test(part)) {
        return (
          <button
            key={idx}
            type="button"
            onClick={() => openTaskInProjectsDrawer(part)}
            className="mx-0.5 inline-flex items-center gap-0.5 rounded bg-emerald-500/15 border border-emerald-500/35 px-1.5 py-0.5 font-mono text-[11px] text-emerald-300 hover:bg-emerald-500/25"
            title={`Open ${part} in Projects Task Drawer`}
          >
            🎯 {part}
          </button>
        );
      }
      return <React.Fragment key={idx}>{part}</React.Fragment>;
    });
  };

  // Render Official Obsidian Flavored Markdown (all 13 Callout types, GFM tables, headings, checklists & embeds)
  const renderRichMarkdownBlocks = (md: string) => {
    const blocks = md.split(/\n\n+/);
    return blocks.map((blk, i) => {
      const trimmed = blk.trim();
      if (!trimmed) return null;

      // 1. Official Obsidian Callouts (`> [!type]+/- Title`)
      const mCallout = trimmed.match(
        /^>\s*\[!(NOTE|ABSTRACT|SUMMARY|TLDR|INFO|TODO|TIP|HINT|IMPORTANT|SUCCESS|CHECK|DONE|QUESTION|HELP|FAQ|WARNING|CAUTION|ATTENTION|FAILURE|FAIL|MISSING|DANGER|ERROR|BUG|EXAMPLE|QUOTE|CITE)\]([+-])?\s*(.*)\n?([\s\S]*)/i
      );
      if (mCallout) {
        const kind = mCallout[1].toUpperCase();
        const title = mCallout[3] || kind;
        const rest = (mCallout[4] || '').replace(/^>\s?/gm, '');
        const style =
          kind === 'IMPORTANT' || kind === 'ABSTRACT' || kind === 'SUMMARY' || kind === 'TLDR' || kind === 'EXAMPLE'
            ? 'border-purple-500/50 bg-purple-500/10 text-purple-200'
            : kind === 'WARNING' || kind === 'CAUTION' || kind === 'ATTENTION' || kind === 'QUESTION' || kind === 'FAQ'
              ? 'border-amber-500/50 bg-amber-500/10 text-amber-200'
              : kind === 'DANGER' || kind === 'ERROR' || kind === 'BUG' || kind === 'FAILURE' || kind === 'FAIL'
                ? 'border-red-500/50 bg-red-500/10 text-red-200'
                : kind === 'SUCCESS' || kind === 'CHECK' || kind === 'DONE' || kind === 'TIP' || kind === 'HINT'
                  ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200'
                  : 'border-cyan-500/50 bg-cyan-500/10 text-cyan-200';
        return (
          <div key={i} className={`rounded-xl border-l-4 p-3 text-xs space-y-1 ${style}`}>
            <div className="font-bold">
              [{kind}] {renderInlineInteractiveText(title)}
            </div>
            {rest && (
              <div className="whitespace-pre-wrap text-slate-200">
                {renderInlineInteractiveText(rest)}
              </div>
            )}
          </div>
        );
      }

      // 2. GFM Pipe Table (`| A | B |\n| --- | --- |`)
      const lines = trimmed.split(/\r?\n/);
      if (lines.length >= 2 && lines[0].includes('|') && /^\s*\|?[\s:\-|]+\|[\s:\-|]*$/.test(lines[1])) {
        const parseRow = (ln: string) =>
          ln
            .trim()
            .replace(/^\|/, '')
            .replace(/\|$/, '')
            .split('|')
            .map((c) => c.trim());
        const headers = parseRow(lines[0]);
        const bodyRows = lines.slice(2).filter((ln) => ln.includes('|')).map(parseRow);
        return (
          <div key={i} className="overflow-x-auto rounded-lg border border-kairos-border bg-kairos-bg/70">
            <table className="w-full text-left text-[11px]">
              <thead className="border-b border-kairos-border bg-kairos-panel text-slate-300">
                <tr>
                  {headers.map((h, hi) => (
                    <th key={hi} className="px-2.5 py-1.5 font-semibold">
                      {renderInlineInteractiveText(h)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-kairos-border/60 text-slate-200">
                {bodyRows.map((r, ri) => (
                  <tr key={ri} className="hover:bg-kairos-card/40">
                    {r.map((cell, ci) => (
                      <td key={ci} className="px-2.5 py-1.5">
                        {renderInlineInteractiveText(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }

      // 3. Fenced Code Blocks (e.g. `dataview`)
      if (trimmed.startsWith('```') && trimmed.endsWith('```')) {
        const firstNl = trimmed.indexOf('\n');
        const lang = firstNl > 3 ? trimmed.slice(3, firstNl).trim() : '';
        const codeBody = firstNl > 0 ? trimmed.slice(firstNl + 1, -3).trim() : trimmed.slice(3, -3);
        return (
          <div key={i} className="rounded-lg border border-kairos-border bg-[#070B14] p-2.5 font-mono text-[11px] text-slate-300">
            {lang && <div className="mb-1 text-[9px] uppercase tracking-wider text-slate-500">{lang}</div>}
            <pre className="overflow-x-auto whitespace-pre-wrap">{codeBody}</pre>
          </div>
        );
      }

      // 4. Headings (`#`, `##`, `###`)
      if (/^#{1,3}\s+/.test(trimmed) && lines.length === 1) {
        const level = (trimmed.match(/^#+/) || ['#'])[0].length;
        const headTxt = trimmed.replace(/^#+\s+/, '');
        const cls =
          level === 1
            ? 'text-base font-bold text-white border-b border-kairos-border/70 pb-1'
            : level === 2
              ? 'text-sm font-bold text-emerald-200 pt-1'
              : 'text-xs font-semibold text-cyan-200';
        return (
          <div key={i} className={cls}>
            {renderInlineInteractiveText(headTxt)}
          </div>
        );
      }

      return (
        <div key={i} className="whitespace-pre-wrap text-xs leading-relaxed text-slate-200">
          {renderInlineInteractiveText(blk)}
        </div>
      );
    });
  };

  const renderCellValue = (val: unknown) => {
    if (val === null || val === undefined || val === '') {
      return <span className="text-slate-600">—</span>;
    }
    if (Array.isArray(val)) {
      return (
        <div className="flex flex-wrap gap-1">
          {val.map((item, idx) => (
            <span
              key={idx}
              className="rounded bg-kairos-bg border border-kairos-border px-1.5 py-0.5 text-[10px] text-slate-300"
            >
              {String(item)}
            </span>
          ))}
        </div>
      );
    }
    const str = String(val);
    if (str.startsWith('http://') || str.startsWith('https://')) {
      let host = 'Portal';
      try {
        host = new URL(str).hostname.replace(/^www\./, '');
      } catch {
        // fallback
      }
      return (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            openExternalUrl(str, host);
          }}
          className="inline-flex items-center gap-1 rounded bg-indigo-500/15 border border-indigo-500/35 px-1.5 py-0.5 text-[10px] font-medium text-indigo-200 hover:bg-indigo-500/25"
          title={str}
        >
          <span>🌐 {host}</span>
          <ExternalLink className="h-2.5 w-2.5" />
        </button>
      );
    }
    if (str.startsWith('[[') && str.endsWith(']]')) {
      return renderInlineInteractiveText(str);
    }
    return <span>{str}</span>;
  };

  const cleanBasePropKey = (colKey: string): string => colKey.replace(/^note\./i, '').trim();

  const isEditableBaseColumn = (colKey: string): boolean => {
    const lower = colKey.toLowerCase();
    if (lower.startsWith('file.') || lower.startsWith('formula.')) return false;
    const clean = cleanBasePropKey(colKey);
    return Boolean(clean && clean.toLowerCase() !== 'id');
  };

  const formatBaseCellPlain = (val: unknown): string => {
    if (val === null || val === undefined) return '';
    if (Array.isArray(val)) return val.map((v) => String(v)).join(', ');
    return String(val);
  };

  const startBaseCellEdit = (relPath: string, colKey: string, currentVal: unknown) => {
    if (!isEditableBaseColumn(colKey)) return;
    setEditingBaseCell({ relPath, colKey });
    setEditingBaseCellVal(formatBaseCellPlain(currentVal));
  };

  const handleSaveBaseCellEdit = async (relPath: string, rawColKey: string, rawVal: string) => {
    if (!activeNote) return;
    const propKey = cleanBasePropKey(rawColKey).replace(/[^A-Za-z0-9_-]+/g, '_');
    if (!propKey) return;
    try {
      const parsedVal = parseFrontmatterValueInput(propKey, rawVal);
      await kairosApi.updateNoteFrontmatter(relPath, { [propKey]: parsedVal });
      setEditingBaseCell(null);
      setEditingBaseCellVal('');
      flashSave(`Updated '${propKey}' on ${relPath.split('/').pop() || relPath}`);
      onVaultMutated();
      const refreshed = await kairosApi.queryVaultBase(activeNote.rel_path, activeBaseView);
      setBaseResult(refreshed);
      loadListAndGraph().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Base Cell Edit Failed',
        err instanceof Error ? err.message : 'Unable to update note frontmatter from .base cell'
      );
    }
  };

  const handleToggleBaseSort = (colKey: string) => {
    if (baseSortCol === colKey) {
      if (baseSortDir === 'asc') {
        setBaseSortDir('desc');
      } else {
        setBaseSortCol('');
        setBaseSortDir('asc');
      }
    } else {
      setBaseSortCol(colKey);
      setBaseSortDir('asc');
    }
  };

  const filteredBaseRows = useMemo(() => {
    const rows = baseResult?.rows || [];
    const q = baseFilter.trim().toLowerCase();
    const matched = !q
      ? rows
      : rows.filter((r) => {
          if (r.title.toLowerCase().includes(q) || r.rel_path.toLowerCase().includes(q)) return true;
          return Object.values(r.cells).some((v) => String(v ?? '').toLowerCase().includes(q));
        });
    if (!baseSortCol) return matched;
    const dirMul = baseSortDir === 'asc' ? 1 : -1;
    return [...matched].sort((a, b) => {
      const rawA = baseSortCol === 'file.name' ? a.title : formatBaseCellPlain(a.cells[baseSortCol]);
      const rawB = baseSortCol === 'file.name' ? b.title : formatBaseCellPlain(b.cells[baseSortCol]);
      if (!rawA && !rawB) return 0;
      if (!rawA) return 1;
      if (!rawB) return -1;
      return rawA.localeCompare(rawB, undefined, { numeric: true, sensitivity: 'base' }) * dirMul;
    });
  }, [baseResult, baseFilter, baseSortCol, baseSortDir]);

  const handleCopyBaseExport = async (format: 'md' | 'csv') => {
    const cols = baseResult?.columns || [];
    if (cols.length === 0) return;
    let out = '';
    if (format === 'csv') {
      const escCsv = (s: string) => `"${s.replace(/"/g, '""')}"`;
      const header = cols.map((c) => escCsv(c.label)).join(',');
      const lines = filteredBaseRows.map((row) =>
        cols
          .map((c) =>
            escCsv(c.key === 'file.name' ? row.title : formatBaseCellPlain(row.cells[c.key]))
          )
          .join(',')
      );
      out = [header, ...lines].join('\n');
    } else {
      const escMd = (s: string) => s.replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');
      const header = `| ${cols.map((c) => escMd(c.label)).join(' | ')} |`;
      const sep = `| ${cols.map(() => '---').join(' | ')} |`;
      const lines = filteredBaseRows.map(
        (row) =>
          `| ${cols
            .map((c) =>
              escMd(c.key === 'file.name' ? `[[${row.title}]]` : formatBaseCellPlain(row.cells[c.key]))
            )
            .join(' | ')} |`
      );
      out = [header, sep, ...lines].join('\n');
    }
    try {
      await navigator.clipboard.writeText(out);
      flashSave(
        `Copied ${filteredBaseRows.length} .base rows as ${format === 'md' ? 'Markdown table' : 'CSV'}`
      );
      onNotify?.(
        'success',
        `Copied ${format.toUpperCase()} Export`,
        `${filteredBaseRows.length} rows copied to clipboard`
      );
    } catch {
      onNotify?.('warning', 'Clipboard Unavailable', 'Could not write export to system clipboard.');
    }
  };

  return (
    <div className="flex-1 flex min-w-0 bg-kairos-bg overflow-hidden relative">
      {/* Left Explorer Column: Section Hubs + Folders + Search + Vault Notes */}
      <div className="w-80 shrink-0 border-r border-kairos-border bg-kairos-panel/80 flex flex-col">
        <div className="p-3 border-b border-kairos-border space-y-2">
          <div className="flex items-center justify-between gap-1">
            <span className="text-xs font-bold text-white">Canopy Vault Explorer</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={handleDailyNote}
                title="Open Today's Daily Note"
                className="flex items-center gap-1 rounded bg-cyan-500/15 px-1.5 py-1 text-[10px] font-medium text-cyan-300 hover:bg-cyan-500/25"
              >
                <CalendarPlus className="h-3 w-3" /> Daily
              </button>
              <button
                type="button"
                onClick={() => setShowHubModal(true)}
                title="Create or Expand an Obsidian Domain Section Hub (Music Studio, Creator Media, Hardware Lab, or Any Custom Domain)"
                className="flex items-center gap-1 rounded bg-purple-500/20 border border-purple-500/35 px-1.5 py-1 text-[10px] font-semibold text-purple-200 hover:bg-purple-500/30"
              >
                <Layers className="h-3 w-3" /> + Hub
              </button>
              <button
                type="button"
                onClick={() => setCreatingNote((v) => !v)}
                title="New Markdown Note, .base Database, or .canvas Map"
                className="flex items-center gap-1 rounded bg-emerald-500/20 px-1.5 py-1 text-[10px] font-medium text-emerald-300 hover:bg-emerald-500/30"
              >
                <FilePlus2 className="h-3 w-3" /> New
              </button>
            </div>
          </div>

          {creatingNote && (
            <form onSubmit={handleCreateQuickNote} className="flex gap-1">
              <input
                type="text"
                value={newNotePath}
                onChange={(e) => setNewNotePath(e.target.value)}
                placeholder="Note.md, View.base, or Map.canvas"
                className="flex-1 rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-white"
              />
              <button
                type="submit"
                className="rounded bg-emerald-500 px-2.5 py-1 text-xs font-semibold text-slate-950"
              >
                Create
              </button>
            </form>
          )}

          {/* Dynamic Domain Section Hubs Quick-Jump Bar */}
          {vaultStructure && vaultStructure.sections.length > 0 ? (
            <div className="rounded-lg border border-purple-500/25 bg-purple-500/5 p-2 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-purple-300">
                  🧩 Domain Section Hubs ({vaultStructure.sections.length})
                </span>
                <button
                  type="button"
                  onClick={() => {
                    if (vaultStructure.bases.some((b) => b.rel_path === '_System/Dashboards/Vault_Master_Catalog.base')) {
                      safeSelectNote('_System/Dashboards/Vault_Master_Catalog.base', false);
                    }
                  }}
                  className="text-[10px] text-emerald-300 hover:underline"
                  title="Open Master Obsidian .base Catalog"
                >
                  📊 Master .base
                </button>
              </div>

              <div className="flex flex-wrap gap-1">
                {vaultStructure.sections.map((sec) => {
                  const isActiveHub = activeSectionHub?.section_rel === sec.section_rel;
                  return (
                    <button
                      key={sec.section_rel}
                      type="button"
                      onClick={() => {
                        setFolderFilter(sec.section_rel);
                        safeSelectNote(sec.hub_index_rel, sec.is_private);
                      }}
                      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium transition ${
                        isActiveHub
                          ? 'bg-purple-500/30 text-white border border-purple-400/50'
                          : 'bg-kairos-bg/80 text-slate-200 border border-kairos-border hover:border-purple-500/40'
                      }`}
                      title={`${sec.title} (${sec.section_rel}/)`}
                    >
                      <span>{sec.icon}</span>
                      <span className="truncate max-w-[140px]">{sec.title}</span>
                      <span className="text-[9px] text-slate-400">({sec.entry_count})</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setShowHubModal(true)}
              className="w-full flex items-center justify-between rounded-lg border border-dashed border-purple-500/35 bg-purple-500/10 px-2.5 py-1.5 text-left text-[11px] text-purple-200 hover:bg-purple-500/15"
            >
              <span className="flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-purple-300 shrink-0" />
                <span>Build a Vault Hub (e.g. 🎵 Music Studio, Gear, Custom)</span>
              </span>
              <span className="font-semibold text-purple-300">+ Hub</span>
            </button>
          )}

          <div className="flex items-center rounded-lg border border-kairos-border bg-kairos-bg px-2.5 py-1.5">
            <Search className="h-3.5 w-3.5 text-slate-400 mr-2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="FTS5 Search notes, #tags, [[links]]..."
              className="w-full bg-transparent text-xs text-white focus:outline-none"
            />
          </div>

          {tagFilter && (
            <div className="flex items-center justify-between rounded-md border border-cyan-500/40 bg-cyan-500/15 px-2 py-1 text-[10px] text-cyan-200">
              <span>
                Filtered by tag: <strong className="font-mono text-white">#{tagFilter}</strong>
              </span>
              <button
                type="button"
                onClick={() => setTagFilter('')}
                className="text-cyan-300 hover:text-white"
                title="Clear #tag filter"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          )}

          <div className="flex flex-wrap gap-1">
            {VAULT_BASE_FOLDERS.map((fld) => {
              const chipLabel =
                fld === ''
                  ? 'All Vault'
                  : fld === '04_Resources/Hermes'
                    ? '🪽 Hermes'
                    : fld === '02_Projects'
                      ? '📖 Projects'
                      : fld;
              return (
                <button
                  key={fld || 'all'}
                  type="button"
                  onClick={() => setFolderFilter(fld)}
                  className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                    folderFilter === fld
                      ? 'bg-emerald-500/25 text-emerald-300 border border-emerald-500/30'
                      : 'bg-kairos-card text-slate-400 hover:text-white'
                  }`}
                >
                  {chipLabel}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto divide-y divide-kairos-border/60">
          {notes.map((n) => {
            const selected = n.rel_path === selectedNotePath;
            const extBadge = n.rel_path.endsWith('.base')
              ? 'BASE'
              : n.rel_path.endsWith('.canvas')
                ? 'CANVAS'
                : n.type === 'section_hub'
                  ? 'HUB'
                  : '';
            return (
              <button
                key={n.rel_path}
                type="button"
                onClick={() => safeSelectNote(n.rel_path, n.is_private)}
                className={`w-full text-left p-3 transition ${
                  selected
                    ? 'bg-emerald-500/10 border-l-2 border-emerald-400'
                    : 'hover:bg-kairos-card/50'
                }`}
              >
                <div className="flex items-center justify-between gap-1">
                  <span className="text-xs font-semibold text-white truncate">{n.title}</span>
                  <div className="flex items-center gap-1 shrink-0">
                    {extBadge && (
                      <span className="rounded bg-purple-500/20 border border-purple-500/30 px-1.5 py-0.5 text-[9px] font-mono text-purple-200">
                        {extBadge}
                      </span>
                    )}
                    {n.is_private && (
                      <span className="flex items-center gap-0.5 rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] text-amber-300">
                        <Lock className="h-2.5 w-2.5" /> Private
                      </span>
                    )}
                  </div>
                </div>
                <div className="mt-0.5 flex items-center gap-1 text-[10px] text-slate-500 font-mono truncate">
                  <Folder className="h-2.5 w-2.5 shrink-0" />
                  <span className="truncate">{n.rel_path}</span>
                </div>
                <p className="mt-1 text-[11px] text-slate-400 line-clamp-2">{n.excerpt}</p>
              </button>
            );
          })}
        </div>
      </div>

      {/* Right Main Area: Section Hub Bar + 3D/2D Knowledge Graph + Obsidian Markdown/YAML/Canvas/Base Editor */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-kairos-border bg-kairos-panel/70 px-4 py-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-mono text-xs text-emerald-300 truncate">
              {activeNote?.rel_path || 'Select a Canopy Vault note'}
            </span>
            {activeNote?.is_private && (
              <span className="rounded bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
                🔒 Local Gemma 4 Privacy Shield Active
              </span>
            )}
            {isDirty && (
              <span className="inline-flex items-center gap-1.5 rounded border border-amber-500/45 bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold text-amber-200">
                <span>● Unsaved (Ctrl+S)</span>
                <button
                  type="button"
                  onClick={() => {
                    if (activeNote) {
                      setBodyDraft(activeNote.body);
                      isDirtyRef.current = false;
                    }
                  }}
                  className="underline hover:text-white"
                  title="Revert unsaved edits back to saved Vault note"
                >
                  Revert
                </button>
              </span>
            )}
            {saveBanner && (
              <span className="text-[11px] text-emerald-400 font-medium">✓ {saveBanner}</span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {showGraph && (
              <div className="flex items-center rounded-md border border-kairos-border bg-kairos-bg p-0.5 text-[11px]">
                <button
                  type="button"
                  onClick={() => setGraphMode('3d')}
                  className={`flex items-center gap-1 rounded px-2 py-0.5 ${
                    graphMode === '3d'
                      ? 'bg-purple-500/25 text-purple-200 font-medium'
                      : 'text-slate-400'
                  }`}
                >
                  <Orbit className="h-3 w-3" /> 3D Galaxy
                </button>
                <button
                  type="button"
                  onClick={() => setGraphMode('2d')}
                  className={`flex items-center gap-1 rounded px-2 py-0.5 ${
                    graphMode === '2d'
                      ? 'bg-cyan-500/25 text-cyan-200 font-medium'
                      : 'text-slate-400'
                  }`}
                >
                  <Network className="h-3 w-3" /> 2D Map
                </button>
              </div>
            )}

            <button
              type="button"
              onClick={() => setShowGraph((g) => !g)}
              className="rounded-md border border-kairos-border bg-kairos-card px-2 py-1 text-xs text-slate-300 hover:text-white"
            >
              {showGraph ? 'Hide Graph' : 'Show Graph'}
            </button>

            <button
              type="button"
              onClick={handleLoadVaultHealth}
              title="Run Obsidian Vault Health & Integrity Diagnostics"
              className={`flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${
                showHealthPanel
                  ? 'border-emerald-400/50 bg-emerald-500/20 text-emerald-200'
                  : 'border-kairos-border bg-kairos-card text-slate-300 hover:text-white'
              }`}
            >
              <Activity className="h-3 w-3" /> Health
            </button>

            {activeNote && (
              <button
                type="button"
                onClick={handleOpenRename}
                title="Link-safe Rename or Move (automatically updates [[WikiLinks]] and .canvas files)"
                className="flex items-center gap-1 rounded-md border border-kairos-border bg-kairos-card px-2 py-1 text-xs text-slate-200 hover:border-cyan-500/40 hover:text-cyan-200"
              >
                <FolderGit2 className="h-3 w-3" /> Rename / Move
              </button>
            )}

            {activeTaskId && onExecuteUiCommands && (
              <button
                type="button"
                onClick={() => openTaskInProjectsDrawer(activeTaskId)}
                title={`Inspect ${activeTaskId} in Projects Task Drawer`}
                className="rounded-md border border-emerald-500/40 bg-emerald-500/15 px-2.5 py-1 text-xs font-medium text-emerald-200 hover:bg-emerald-500/25"
              >
                🎯 Task Drawer
              </button>
            )}

            <button
              type="button"
              disabled={!activeNote}
              onClick={handleRetainNoteInHermes}
              title="Retain key takeaway from this note into 04_Resources/Hermes/MEMORY.md"
              className="rounded-md border border-purple-500/35 bg-purple-500/15 px-2 py-1 text-xs font-medium text-purple-200 hover:bg-purple-500/25 disabled:opacity-45"
            >
              🪽 Retain
            </button>

            <button
              type="button"
              disabled={!activeNote}
              onClick={handleDistillNoteAsHermesSkill}
              title="Distill this note into a reusable Hermes SKL-*.md Skill"
              className="rounded-md border border-amber-500/35 bg-amber-500/15 px-2 py-1 text-xs font-medium text-amber-200 hover:bg-amber-500/25 disabled:opacity-45"
            >
              🪽 Distill
            </button>

            <button
              type="button"
              disabled={!activeNote}
              onClick={() => setShowGdocBox((v) => !v)}
              className="flex items-center gap-1 rounded-md border border-cyan-500/30 bg-cyan-500/15 px-2 py-1 text-xs text-cyan-300 hover:bg-cyan-500/25 disabled:opacity-45"
            >
              <Link className="h-3 w-3" /> Google Doc
            </button>

            <button
              type="button"
              disabled={!activeNote}
              onClick={handleSave}
              className="flex items-center gap-1 rounded-md bg-emerald-500 px-3 py-1 text-xs font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-45"
            >
              <Save className="h-3.5 w-3.5" /> Save
            </button>
          </div>
        </div>

        {/* Active Section Hub Companion Bar (`📘 Hub MOC` | `📊 Live .base` | `🗺️ .canvas Map` | Collections | `➕ Add Entry`) */}
        {activeSectionHub && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-purple-500/25 bg-purple-500/10 px-4 py-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-bold text-white mr-1">
                {activeSectionHub.icon} {activeSectionHub.title}
              </span>
              <button
                type="button"
                onClick={() => safeSelectNote(activeSectionHub.hub_index_rel, activeSectionHub.is_private)}
                className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                  activeNote?.rel_path === activeSectionHub.hub_index_rel
                    ? 'bg-purple-500 text-white'
                    : 'bg-kairos-bg/80 text-purple-200 hover:bg-purple-500/25'
                }`}
              >
                📘 Hub MOC
              </button>
              {activeSectionHub.base_rel && (
                <button
                  type="button"
                  onClick={() => safeSelectNote(activeSectionHub.base_rel, activeSectionHub.is_private)}
                  className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                    activeNote?.rel_path === activeSectionHub.base_rel
                      ? 'bg-emerald-500 text-slate-950 font-semibold'
                      : 'bg-kairos-bg/80 text-emerald-300 hover:bg-emerald-500/20'
                  }`}
                >
                  📊 Live .base Catalog
                </button>
              )}
              {activeSectionHub.canvas_rel && (
                <button
                  type="button"
                  onClick={() => safeSelectNote(activeSectionHub.canvas_rel, activeSectionHub.is_private)}
                  className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                    activeNote?.rel_path === activeSectionHub.canvas_rel
                      ? 'bg-cyan-500 text-slate-950 font-semibold'
                      : 'bg-kairos-bg/80 text-cyan-300 hover:bg-cyan-500/20'
                  }`}
                >
                  🗺️ Ecosystem .canvas
                </button>
              )}
              <span className="text-slate-600 mx-0.5">|</span>
              {activeSectionHub.collections.map((col) => {
                const colRel = col.rel_path || `${activeSectionHub.section_rel}/${col.folder}`;
                return (
                  <button
                    key={col.folder}
                    type="button"
                    onClick={() => {
                      setFolderFilter(colRel);
                      if (activeSectionHub.base_rel && isBaseFile) {
                        setActiveBaseView(`${col.icon} ${col.title}`);
                      }
                    }}
                    className={`rounded px-2 py-0.5 text-[10px] ${
                      folderFilter === colRel
                        ? 'bg-emerald-500/25 text-emerald-200 border border-emerald-500/40'
                        : 'bg-kairos-bg/60 text-slate-300 hover:text-white'
                    }`}
                    title={col.description || colRel}
                  >
                    {col.icon} {col.title} ({col.entry_count ?? 0})
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              onClick={() => openAddEntryModal(activeSectionHub)}
              className="flex items-center gap-1 rounded-md bg-emerald-500 px-2.5 py-1 text-[11px] font-semibold text-slate-950 hover:bg-emerald-400"
            >
              <Plus className="h-3 w-3" /> Add Entry
            </button>
          </div>
        )}

        {/* Link-Safe Rename / Move Bar */}
        {showRenameBox && activeNote && (
          <form
            onSubmit={handleRenameSubmit}
            className="flex flex-wrap items-center gap-2 border-b border-cyan-500/30 bg-kairos-panel px-4 py-2 text-xs"
          >
            <span className="font-semibold text-cyan-300">Rename / Move:</span>
            <input
              type="text"
              required
              value={renameDestInput}
              onChange={(e) => setRenameDestInput(e.target.value)}
              placeholder="New relative path or filename (e.g. 04_Resources/Music_Studio/Plugins/Serum_2.md)"
              className="flex-1 min-w-[240px] rounded border border-kairos-border bg-kairos-bg px-2.5 py-1 font-mono text-xs text-white"
            />
            {isMarkdownFile && (
              <input
                type="text"
                value={renameTitleInput}
                onChange={(e) => setRenameTitleInput(e.target.value)}
                placeholder="Note title"
                className="w-48 rounded border border-kairos-border bg-kairos-bg px-2.5 py-1 text-xs text-white"
              />
            )}
            <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-300">
              <input
                type="checkbox"
                checked={renameUpdateLinks}
                onChange={(e) => setRenameUpdateLinks(e.target.checked)}
              />
              Refactor `[[WikiLinks]]` &amp; `.canvas`
            </label>
            <button
              type="submit"
              className="rounded bg-cyan-500 px-3 py-1 font-semibold text-slate-950 hover:bg-cyan-400"
            >
              Apply
            </button>
            <button
              type="button"
              onClick={() => setShowRenameBox(false)}
              className="rounded border border-kairos-border px-2 py-1 text-slate-400 hover:text-white"
            >
              Cancel
            </button>
          </form>
        )}

        {/* Vault Health & Integrity Diagnostics Bar */}
        {showHealthPanel && (
          <div className="border-b border-emerald-500/30 bg-kairos-panel/95 px-4 py-3 text-xs space-y-2 max-h-60 overflow-y-auto">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-bold text-white">🩺 Obsidian Vault Health &amp; Integrity</span>
                {healthReport && (
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                      healthReport.health_score >= 90
                        ? 'bg-emerald-500/20 text-emerald-300'
                        : healthReport.health_score >= 70
                          ? 'bg-amber-500/20 text-amber-300'
                          : 'bg-red-500/20 text-red-300'
                    }`}
                  >
                    Score: {healthReport.health_score}/100 ({healthReport.status.toUpperCase()})
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => setShowHealthPanel(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {loadingHealth || !healthReport ? (
              <div className="text-slate-400">Auditing Vault links, `.base` YAML &amp; `.canvas` JSON...</div>
            ) : (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-3 text-[11px] text-slate-300">
                  <span>📝 Markdown Notes: <b>{healthReport.counts.markdown_notes}</b></span>
                  <span>🧩 Section Hubs: <b>{healthReport.counts.section_hubs}</b></span>
                  <span>📊 Bases (`.base`): <b>{healthReport.counts.bases}</b></span>
                  <span>🗺️ Canvases (`.canvas`): <b>{healthReport.counts.canvases}</b></span>
                  <span>🎯 Project Tasks: <b>{healthReport.counts.tasks}</b></span>
                  <span>🔗 Broken Links: <b>{healthReport.broken_links.length}</b></span>
                </div>
                {healthReport.broken_links.length > 0 && (
                  <div className="space-y-1">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-amber-300">
                      Unresolved `[[WikiLinks]]` (1-Click Create)
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
                      {healthReport.broken_links.slice(0, 8).map((bl, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between gap-2 rounded border border-kairos-border bg-kairos-bg px-2.5 py-1"
                        >
                          <div className="min-w-0 truncate">
                            <span className="font-mono text-amber-200">[[{bl.target}]]</span>
                            <span className="text-[10px] text-slate-500 ml-1.5">in {bl.source_path}</span>
                          </div>
                          <button
                            type="button"
                            onClick={() => handleCreateBrokenLinkNote(bl.target, bl.suggested_folder)}
                            className="shrink-0 rounded bg-emerald-500/20 border border-emerald-500/35 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 hover:bg-emerald-500/30"
                          >
                            + Create
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {healthReport.syntax_issues.length > 0 && (
                  <div className="rounded border border-red-500/30 bg-red-500/10 p-2 text-[11px] text-red-200">
                    Syntax issues detected in {healthReport.syntax_issues.map((s) => s.rel_path).join(', ')}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {showGdocBox && (
          <form
            onSubmit={handleEmbedGoogleDoc}
            className="flex items-center gap-2 border-b border-kairos-border bg-kairos-panel px-4 py-2"
          >
            <input
              type="url"
              required
              value={gdocUrl}
              onChange={(e) => setGdocUrl(e.target.value)}
              placeholder="Paste Google Doc / Sheet / Slide URL to embed into this Obsidian note..."
              className="flex-1 rounded border border-kairos-border bg-kairos-bg px-3 py-1 text-xs text-white"
            />
            <button
              type="submit"
              className="rounded bg-cyan-500 px-3 py-1 text-xs font-semibold text-slate-950"
            >
              Embed
            </button>
          </form>
        )}

        {/* Collapsible 3D Galaxy / 2D WikiLink Knowledge Graph */}
        {showGraph && (
          <div
            onMouseDown={(e) => {
              draggingRef.current = {
                active: true,
                startX: e.clientX,
                baseYaw: yaw,
                moved: false,
              };
            }}
            onMouseMove={(e) => {
              if (!draggingRef.current.active) return;
              const dx = e.clientX - draggingRef.current.startX;
              if (Math.abs(dx) > 4) {
                draggingRef.current.moved = true;
              }
              setYaw(draggingRef.current.baseYaw + dx * 0.01);
            }}
            onMouseUp={() => {
              draggingRef.current.active = false;
            }}
            onMouseLeave={() => {
              draggingRef.current.active = false;
            }}
            className="h-64 shrink-0 border-b border-kairos-border bg-[#060912] relative overflow-hidden flex items-center justify-between px-4 cursor-grab active:cursor-grabbing select-none"
          >
            <svg viewBox="0 0 540 310" className="w-full h-full max-w-2xl mx-auto">
              {graph.edges.map((e, i) => {
                const s = positionedGraph.coords.get(e.source);
                const t = positionedGraph.coords.get(e.target);
                if (!s || !t) return null;
                return (
                  <line
                    key={i}
                    x1={s.x}
                    y1={s.y}
                    x2={t.x}
                    y2={t.y}
                    stroke={
                      e.kind === 'depends_on'
                        ? '#F59E0B'
                        : e.kind === 'canvas_file'
                          ? '#8B5CF6'
                          : '#1E3A5F'
                    }
                    strokeOpacity={0.75}
                    strokeWidth={e.kind === 'depends_on' ? 1.5 : 1.0}
                  />
                );
              })}
              {positionedGraph.nodes.map((n) => {
                const c = positionedGraph.coords.get(n.id);
                if (!c) return null;
                const isSelected = n.id === selectedNotePath;
                const fill = n.is_private
                  ? '#F59E0B'
                  : n.type === 'section_hub'
                    ? '#A855F7'
                    : n.id.startsWith('04_Resources/Hermes/')
                      ? '#EC4899'
                      : n.type === 'task'
                        ? '#10B981'
                        : n.type === 'canvas' || n.type === 'base'
                          ? '#8B5CF6'
                          : '#06B6D4';
                const r = (isSelected ? 7.5 : n.type === 'section_hub' ? 6.0 : 4.8) * c.scale;
                return (
                  <g
                    key={n.id}
                    onClick={() => {
                      if (draggingRef.current.moved) {
                        draggingRef.current.moved = false;
                        return;
                      }
                      safeSelectNote(n.id, n.is_private);
                    }}
                    className="cursor-pointer"
                  >
                    <circle
                      cx={c.x}
                      cy={c.y}
                      r={r}
                      fill={fill}
                      fillOpacity={Math.min(1, 0.45 + c.scale * 0.45)}
                      stroke={isSelected ? '#FFFFFF' : 'none'}
                      strokeWidth={2}
                    />
                    <text
                      x={c.x + r + 3}
                      y={c.y + 3}
                      fill="#CBD5E1"
                      fontSize={Math.max(7.5, 8.5 * c.scale)}
                      className="pointer-events-none"
                    >
                      {n.label.slice(0, 22)}
                    </text>
                  </g>
                );
              })}
            </svg>

            <div className="hidden xl:block w-64 rounded-xl border border-kairos-border bg-kairos-panel/90 p-3 text-[11px] space-y-1.5">
              <div className="font-semibold text-white">
                {graphMode === '3d' ? '3D Galaxy Sphere (Drag to Orbit)' : '2D WikiLink Map'}
              </div>
              <div className="flex items-center gap-2 text-slate-300">
                <span className="h-2.5 w-2.5 rounded-full bg-purple-400" /> Section Hubs, `.base` &amp; `.canvas`
              </div>
              <div className="flex items-center gap-2 text-slate-300">
                <span className="h-2.5 w-2.5 rounded-full bg-cyan-400" /> Knowledge &amp; Catalog Notes
              </div>
              <div className="flex items-center gap-2 text-slate-300">
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" /> Project Tasks (`TSK-*`)
              </div>
              <div className="flex items-center gap-2 text-slate-300">
                <span className="h-2.5 w-2.5 rounded-full bg-pink-500" /> Hermes Memory &amp; Skills
              </div>
              <div className="flex items-center gap-2 text-slate-300">
                <span className="h-2.5 w-2.5 rounded-full bg-amber-400" /> `#private` / Finance
              </div>
              <div className="pt-1 text-[10px] text-slate-400">
                {graph.nodes.length} indexed nodes • {graph.edges.length} graph edges
              </div>
            </div>
          </div>
        )}

        {/* Split Editor + Live Preview / .base Database Engine / .canvas Spec 1.0 Whiteboard */}
        {activeNote ? (
          <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 min-h-0 overflow-hidden">
            <textarea
              value={bodyDraft}
              onChange={(e) => setBodyDraft(e.target.value)}
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
                  e.preventDefault();
                  handleSave();
                }
              }}
              className="w-full h-full resize-none border-r border-kairos-border bg-kairos-bg p-4 font-mono text-xs leading-relaxed text-slate-100 focus:outline-none"
            />

            <div className="h-full overflow-y-auto p-4 space-y-4 bg-kairos-panel/40">
              {/* Interactive YAML Frontmatter Properties Inspector & Editor */}
              {isMarkdownFile && (
                <div className="rounded-xl border border-kairos-border bg-kairos-panel p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      YAML Frontmatter Properties ({Object.keys(activeNote.frontmatter).length})
                    </span>
                    <button
                      type="button"
                      onClick={() => setAddingProp((v) => !v)}
                      className="inline-flex items-center gap-1 rounded bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 hover:bg-emerald-500/25"
                    >
                      <Plus className="h-2.5 w-2.5" /> Property
                    </button>
                  </div>

                  {addingProp && (
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        handlePatchProperty(newPropKey, newPropVal);
                      }}
                      className="flex flex-wrap gap-1.5 pt-1"
                    >
                      <input
                        type="text"
                        required
                        value={newPropKey}
                        onChange={(e) => setNewPropKey(e.target.value)}
                        placeholder="key (e.g. support_url, vendor, format)"
                        className="w-44 rounded border border-kairos-border bg-kairos-bg px-2 py-1 font-mono text-[11px] text-white"
                      />
                      <input
                        type="text"
                        value={newPropVal}
                        onChange={(e) => setNewPropVal(e.target.value)}
                        placeholder="value (URL, text, or comma list)"
                        className="flex-1 min-w-[140px] rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[11px] text-white"
                      />
                      <button
                        type="submit"
                        className="rounded bg-emerald-500 px-2.5 py-1 text-[11px] font-semibold text-slate-950"
                      >
                        Save
                      </button>
                    </form>
                  )}

                  {Object.keys(activeNote.frontmatter).length > 0 && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5 text-xs">
                      {Object.entries(activeNote.frontmatter)
                        .filter(([k]) => k !== 'collections')
                        .map(([k, v]) => {
                          const rawStr = Array.isArray(v)
                            ? v.join(', ')
                            : typeof v === 'object' && v !== null
                              ? JSON.stringify(v)
                              : String(v ?? '');
                          const isUrl = rawStr.startsWith('http://') || rawStr.startsWith('https://');
                          const isEditingThis = editingPropKey === k;
                          return (
                            <div
                              key={k}
                              className="group flex items-center justify-between gap-1.5 rounded-lg border border-kairos-border/60 bg-kairos-bg/60 px-2.5 py-1"
                            >
                              {isEditingThis ? (
                                <form
                                  onSubmit={(e) => {
                                    e.preventDefault();
                                    handlePatchProperty(k, editingPropVal);
                                  }}
                                  className="flex items-center gap-1 w-full"
                                >
                                  <span className="text-[10px] font-mono text-slate-400">{k}:</span>
                                  <input
                                    type="text"
                                    value={editingPropVal}
                                    onChange={(e) => setEditingPropVal(e.target.value)}
                                    className="flex-1 rounded border border-cyan-500/40 bg-kairos-bg px-1.5 py-0.5 text-[11px] text-white"
                                  />
                                  <button
                                    type="submit"
                                    className="rounded bg-cyan-500 px-1.5 py-0.5 text-[10px] font-semibold text-slate-950"
                                  >
                                    OK
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setEditingPropKey(null)}
                                    className="text-[10px] text-slate-400"
                                  >
                                    ✕
                                  </button>
                                </form>
                              ) : (
                                <>
                                  <div className="min-w-0 truncate flex items-center gap-1">
                                    <span className="text-slate-500 font-mono text-[11px]">{k}:</span>
                                    {isUrl ? (
                                      <button
                                        type="button"
                                        onClick={() => openExternalUrl(rawStr, k)}
                                        className="inline-flex items-center gap-1 rounded bg-indigo-500/15 border border-indigo-500/35 px-1.5 py-0.5 text-[10px] font-medium text-indigo-200 hover:bg-indigo-500/25 truncate"
                                        title={rawStr}
                                      >
                                        <span>🌐 Open Site</span>
                                        <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                                      </button>
                                    ) : rawStr.startsWith('[[') && rawStr.endsWith(']]') ? (
                                      <span className="truncate">{renderInlineInteractiveText(rawStr)}</span>
                                    ) : (
                                      <span className="text-emerald-300 font-mono text-[11px] truncate">
                                        {rawStr || '—'}
                                      </span>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition shrink-0">
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setEditingPropKey(k);
                                        setEditingPropVal(rawStr);
                                      }}
                                      title={`Edit ${k}`}
                                      className="p-0.5 text-slate-400 hover:text-cyan-300"
                                    >
                                      <Pencil className="h-3 w-3" />
                                    </button>
                                    {k !== 'id' && k !== 'title' && (
                                      <button
                                        type="button"
                                        onClick={() => handleDeleteProperty(k)}
                                        title={`Remove ${k}`}
                                        className="p-0.5 text-slate-400 hover:text-red-300"
                                      >
                                        <Trash2 className="h-3 w-3" />
                                      </button>
                                    )}
                                  </div>
                                </>
                              )}
                            </div>
                          );
                        })}
                    </div>
                  )}
                </div>
              )}

              {/* Clickable `#tag` Filter Chips */}
              {activeNote.tags.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] text-slate-400">Tags:</span>
                  {activeNote.tags.map((tg) => {
                    const cleanTg = tg.replace(/^#/, '');
                    const isActiveTag = tagFilter.toLowerCase() === cleanTg.toLowerCase();
                    return (
                      <button
                        key={cleanTg}
                        type="button"
                        onClick={() =>
                          setTagFilter((prev) =>
                            prev.toLowerCase() === cleanTg.toLowerCase() ? '' : cleanTg
                          )
                        }
                        title="Click to filter Vault Explorer by this #tag"
                        className={`rounded px-2 py-0.5 font-mono text-[10.5px] transition ${
                          isActiveTag
                            ? 'bg-emerald-500/30 border border-emerald-400 text-white'
                            : 'bg-purple-500/15 border border-purple-500/30 text-purple-200 hover:bg-purple-500/25'
                        }`}
                      >
                        #{cleanTg}
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Outgoing WikiLinks */}
              {activeNote.wikilinks.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] text-slate-400">WikiLinks:</span>
                  {activeNote.wikilinks.map((wl) => (
                    <button
                      key={wl}
                      type="button"
                      onClick={() => resolveWikiLinkToNote(wl)}
                      className="rounded bg-cyan-500/15 border border-cyan-500/30 px-2 py-0.5 text-[11px] text-cyan-300 hover:bg-cyan-500/25"
                    >
                      [[{wl}]]
                    </button>
                  ))}
                </div>
              )}

              {/* Incoming Backlinks (`Linked Mentions`) */}
              {backlinks.length > 0 && (
                <div className="rounded-xl border border-cyan-500/25 bg-kairos-panel/80 p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-cyan-300">
                      Linked Mentions / Backlinks ({backlinks.length})
                    </span>
                    <span className="text-[10px] text-slate-500">Incoming Vault Edges</span>
                  </div>
                  <div className="space-y-1.5 max-h-44 overflow-y-auto pr-1">
                    {backlinks.map((bl) => (
                      <div
                        key={bl.rel_path}
                        className="flex items-start justify-between gap-2 rounded-lg border border-kairos-border bg-kairos-bg/70 p-2"
                      >
                        <button
                          type="button"
                          onClick={() => safeSelectNote(bl.rel_path, bl.is_private)}
                          className="flex-1 min-w-0 text-left hover:opacity-90"
                        >
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs font-semibold text-white truncate">
                              {bl.title}
                            </span>
                            <span
                              className={`rounded px-1.5 py-0.5 text-[9px] font-mono ${
                                bl.edge_kind === 'depends_on'
                                  ? 'bg-amber-500/20 text-amber-300'
                                  : bl.edge_kind === 'canvas_file'
                                    ? 'bg-purple-500/20 text-purple-300'
                                    : 'bg-cyan-500/15 text-cyan-300'
                              }`}
                            >
                              {bl.edge_kind === 'depends_on'
                                ? '⛓ depends_on'
                                : bl.edge_kind === 'canvas_file'
                                  ? '🗺️ canvas'
                                  : '🔗 wikilink'}
                            </span>
                            {bl.is_private && (
                              <span className="text-[9px] text-amber-300">🔒</span>
                            )}
                          </div>
                          <div className="text-[10px] font-mono text-slate-500 truncate">
                            {bl.rel_path}
                          </div>
                          {bl.excerpt && (
                            <div className="mt-0.5 text-[11px] text-slate-400 line-clamp-1">
                              {bl.excerpt}
                            </div>
                          )}
                        </button>
                        {bl.task_id && onExecuteUiCommands && (
                          <button
                            type="button"
                            onClick={() => openTaskInProjectsDrawer(bl.task_id)}
                            title={`Open ${bl.task_id} in Projects Task Drawer`}
                            className="shrink-0 rounded bg-emerald-500/15 border border-emerald-500/35 px-2 py-1 text-[10px] font-mono text-emerald-300 hover:bg-emerald-500/25"
                          >
                            🎯 {bl.task_id}
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 1. Official Live Obsidian `.base` Multi-View Database Engine */}
              {isBaseFile ? (
                <div className="rounded-xl border border-emerald-500/30 bg-kairos-panel p-3 space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Database className="h-4 w-4 text-emerald-400" />
                      <span className="text-xs font-bold text-emerald-300">
                        Obsidian Bases Live Engine (`.base` YAML Query)
                      </span>
                      {baseLoading && (
                        <span className="text-[10px] text-slate-400">Evaluating...</span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <input
                        type="text"
                        value={baseFilter}
                        onChange={(e) => setBaseFilter(e.target.value)}
                        placeholder="Filter rows..."
                        className="w-40 rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[11px] text-white focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => handleCopyBaseExport('md')}
                        title="Copy evaluated .base table as Obsidian Markdown table"
                        className="flex items-center gap-1 rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[10px] font-medium text-slate-300 hover:border-cyan-500/40 hover:text-cyan-200"
                      >
                        <Copy className="h-3 w-3" /> Copy MD
                      </button>
                      <button
                        type="button"
                        onClick={() => handleCopyBaseExport('csv')}
                        title="Copy evaluated .base table as CSV"
                        className="flex items-center gap-1 rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[10px] font-medium text-slate-300 hover:border-cyan-500/40 hover:text-cyan-200"
                      >
                        <Copy className="h-3 w-3" /> Copy CSV
                      </button>
                      <button
                        type="button"
                        onClick={() => openAddEntryModal(activeSectionHub)}
                        className="flex items-center gap-1 rounded bg-emerald-500 px-2.5 py-1 text-[11px] font-semibold text-slate-950 hover:bg-emerald-400"
                      >
                        <Plus className="h-3 w-3" /> Add Entry
                      </button>
                    </div>
                  </div>

                  {/* `.base` View Switcher Tabs (`table` & `cards`) */}
                  {baseResult && baseResult.views.length > 0 && (
                    <div className="flex flex-wrap gap-1 border-b border-kairos-border pb-2">
                      {baseResult.views.map((v) => {
                        const isSelectedView =
                          (baseResult.active_view?.name || '') === v.name;
                        return (
                          <button
                            key={v.name}
                            type="button"
                            onClick={() => setActiveBaseView(v.name)}
                            className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium transition ${
                              isSelectedView
                                ? 'bg-emerald-500/25 text-emerald-200 border border-emerald-500/40'
                                : 'bg-kairos-bg text-slate-400 hover:text-white'
                            }`}
                          >
                            {v.type === 'cards' ? (
                              <LayoutGrid className="h-3 w-3" />
                            ) : (
                              <Table2 className="h-3 w-3" />
                            )}
                            <span>{v.name}</span>
                          </button>
                        );
                      })}
                    </div>
                  )}

                  {baseResult?.errors && baseResult.errors.length > 0 && (
                    <div className="rounded border border-amber-500/35 bg-amber-500/10 p-2 text-[11px] text-amber-200">
                      {baseResult.errors.join(' • ')}
                    </div>
                  )}

                  {/* Cards Gallery View (`type: cards`) */}
                  {baseResult?.active_view?.type === 'cards' ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                      {filteredBaseRows.map((row) => (
                        <div
                          key={row.rel_path}
                          onClick={() => safeSelectNote(row.rel_path, row.is_private)}
                          className="cursor-pointer rounded-xl border border-kairos-border bg-kairos-bg/80 p-3 hover:border-emerald-500/40 transition space-y-1.5"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-bold text-white truncate">
                              {row.title}
                            </span>
                            {row.is_private && (
                              <span className="text-[10px] text-amber-300">🔒</span>
                            )}
                          </div>
                          <div className="text-[10px] font-mono text-slate-500 truncate">
                            {row.folder}
                          </div>
                          <div className="space-y-1 pt-1 text-[11px]">
                            {(baseResult.columns || [])
                              .filter((c) => c.key !== 'file.name')
                              .map((col) => (
                                <div key={col.key} className="flex items-center justify-between gap-2">
                                  <span className="text-slate-500 text-[10px]">{col.label}:</span>
                                  <span className="text-slate-200 truncate">
                                    {renderCellValue(row.cells[col.key])}
                                  </span>
                                </div>
                              ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    /* Dynamic Table View (`type: table`) */
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-[11px]">
                        <thead className="border-b border-kairos-border text-slate-400">
                          <tr>
                            {(baseResult?.columns || []).map((col) => {
                              const isSorted = baseSortCol === col.key;
                              return (
                                <th key={col.key} className="py-1.5 pr-3 font-semibold">
                                  <button
                                    type="button"
                                    onClick={() => handleToggleBaseSort(col.key)}
                                    className="inline-flex items-center gap-1 text-left hover:text-emerald-300 transition"
                                    title={`Sort by ${col.label}${isEditableBaseColumn(col.key) ? ' (double-click or click pencil on cells to edit YAML inline)' : ''}`}
                                  >
                                    <span>{col.label}</span>
                                    <ArrowUpDown
                                      className={`h-2.5 w-2.5 ${
                                        isSorted ? 'text-emerald-400' : 'text-slate-600'
                                      }`}
                                    />
                                    {isSorted && (
                                      <span className="text-[10px] text-emerald-300">
                                        {baseSortDir === 'asc' ? '↑' : '↓'}
                                      </span>
                                    )}
                                  </button>
                                </th>
                              );
                            })}
                            {onExecuteUiCommands && <th className="py-1.5 text-right">Action</th>}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-kairos-border/60">
                          {filteredBaseRows.map((row) => (
                            <tr
                              key={row.rel_path}
                              onClick={() => safeSelectNote(row.rel_path, row.is_private)}
                              className="cursor-pointer hover:bg-kairos-card/60"
                            >
                              {(baseResult?.columns || []).map((col) => {
                                const editable = isEditableBaseColumn(col.key);
                                const isCellEditing =
                                  editingBaseCell?.relPath === row.rel_path &&
                                  editingBaseCell?.colKey === col.key;
                                return (
                                  <td
                                    key={col.key}
                                    onDoubleClick={(e) => {
                                      if (!editable) return;
                                      e.stopPropagation();
                                      startBaseCellEdit(row.rel_path, col.key, row.cells[col.key]);
                                    }}
                                    className="group py-1.5 pr-3 text-slate-200"
                                  >
                                    {col.key === 'file.name' ? (
                                      <span className="font-semibold text-emerald-300">
                                        {row.title}
                                        {row.is_private ? ' 🔒' : ''}
                                      </span>
                                    ) : isCellEditing ? (
                                      <form
                                        onSubmit={(e) => {
                                          e.preventDefault();
                                          e.stopPropagation();
                                          handleSaveBaseCellEdit(
                                            row.rel_path,
                                            col.key,
                                            editingBaseCellVal
                                          );
                                        }}
                                        onClick={(e) => e.stopPropagation()}
                                        className="flex items-center gap-1"
                                      >
                                        <input
                                          type="text"
                                          autoFocus
                                          value={editingBaseCellVal}
                                          onChange={(e) => setEditingBaseCellVal(e.target.value)}
                                          onKeyDown={(e) => {
                                            if (e.key === 'Escape') {
                                              e.stopPropagation();
                                              setEditingBaseCell(null);
                                            }
                                          }}
                                          className="w-28 rounded border border-emerald-500/50 bg-kairos-bg px-1.5 py-0.5 text-[11px] text-white focus:outline-none"
                                        />
                                        <button
                                          type="submit"
                                          className="rounded bg-emerald-500 px-1.5 py-0.5 text-[10px] font-bold text-slate-950 hover:bg-emerald-400"
                                          title="Save YAML property"
                                        >
                                          ✓
                                        </button>
                                        <button
                                          type="button"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            setEditingBaseCell(null);
                                          }}
                                          className="rounded border border-kairos-border bg-kairos-bg px-1 py-0.5 text-[10px] text-slate-400 hover:text-white"
                                          title="Cancel"
                                        >
                                          ×
                                        </button>
                                      </form>
                                    ) : (
                                      <div className="inline-flex items-center gap-1 max-w-full">
                                        <span className="truncate">
                                          {renderCellValue(row.cells[col.key])}
                                        </span>
                                        {editable && (
                                          <button
                                            type="button"
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              startBaseCellEdit(
                                                row.rel_path,
                                                col.key,
                                                row.cells[col.key]
                                              );
                                            }}
                                            title={`Edit '${cleanBasePropKey(col.key)}' inline`}
                                            className="opacity-0 group-hover:opacity-100 rounded p-0.5 text-slate-500 hover:bg-emerald-500/15 hover:text-emerald-300 transition"
                                          >
                                            <Pencil className="h-2.5 w-2.5" />
                                          </button>
                                        )}
                                      </div>
                                    )}
                                  </td>
                                );
                              })}
                              {onExecuteUiCommands && (
                                <td className="py-1.5 text-right">
                                  {row.task_id ? (
                                    <button
                                      type="button"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        openTaskInProjectsDrawer(row.task_id);
                                      }}
                                      className="rounded bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.5 text-[10px] text-emerald-300 hover:bg-emerald-500/25"
                                    >
                                      🎯 {row.task_id}
                                    </button>
                                  ) : (
                                    <span className="text-[10px] font-mono text-slate-500">
                                      {row.type}
                                    </span>
                                  )}
                                </td>
                              )}
                            </tr>
                          ))}
                          {filteredBaseRows.length === 0 && (
                            <tr>
                              <td
                                colSpan={(baseResult?.columns.length || 3) + 1}
                                className="py-6 text-center text-slate-500"
                              >
                                No Vault notes match this `.base` view yet. Click <b>+ Add Entry</b> above to add your first item!
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* `.base` Column Summaries Footer */}
                  {baseResult && Object.keys(baseResult.summaries || {}).length > 0 && (
                    <div className="flex flex-wrap items-center gap-3 border-t border-kairos-border pt-2 text-[10px] text-slate-400">
                      <span>Rows: <b className="text-white">{filteredBaseRows.length}</b></span>
                      {Object.entries(baseResult.summaries).map(([prop, info]) => (
                        <span key={prop}>
                          {prop} ({info.formula}): <b className="text-emerald-300">{String(info.value)}</b>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ) : canvasParsed?.nodes ? (
                /* 2. Official JSON Canvas Spec 1.0 (`.canvas`) Whiteboard Builder */
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-purple-300">
                      JSON Canvas Spec 1.0 Ecosystem Map (`.canvas`)
                    </span>
                    <span className="text-[10px] text-slate-400">
                      {canvasParsed.nodes.length} node{canvasParsed.nodes.length === 1 ? '' : 's'} •{' '}
                      {(canvasParsed.edges || []).length} edge{(canvasParsed.edges || []).length === 1 ? '' : 's'}
                    </span>
                  </div>
                  <form onSubmit={handleAddCanvasCard} className="flex gap-1.5">
                    <select
                      value={canvasAddKind}
                      onChange={(e) =>
                        setCanvasAddKind(e.target.value as 'text' | 'link' | 'file' | 'group')
                      }
                      className="rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-xs text-slate-200"
                    >
                      <option value="text">📝 Text Card</option>
                      <option value="link">🌐 Website URL</option>
                      <option value="file">📄 Vault File</option>
                      <option value="group">🗂️ Group Container</option>
                    </select>
                    <input
                      type="text"
                      value={newCanvasCardText}
                      onChange={(e) => setNewCanvasCardText(e.target.value)}
                      placeholder={
                        canvasAddKind === 'group'
                          ? 'Group label (e.g. Studio Synths & FX)...'
                          : canvasAddKind === 'link'
                            ? 'https://studio.youtube.com or https://artists.spotify.com...'
                            : canvasAddKind === 'file'
                              ? '04_Resources/Music_Studio/_Hub_Index.md'
                              : 'Add new whiteboard card to .canvas...'
                      }
                      className="flex-1 rounded border border-kairos-border bg-kairos-bg px-2.5 py-1 text-xs text-white"
                    />
                    <button
                      type="submit"
                      className="flex items-center gap-1 rounded bg-purple-500 px-2.5 py-1 text-xs font-semibold text-white hover:bg-purple-400"
                    >
                      <Plus className="h-3 w-3" /> Add Node
                    </button>
                  </form>

                  {/* Directional `.canvas` Edge Builder (`fromNode` -> `toNode`) */}
                  {canvasParsed.nodes.length >= 2 && (
                    <form
                      onSubmit={handleAddCanvasEdge}
                      className="flex flex-wrap items-center gap-1.5 rounded-lg border border-purple-500/25 bg-kairos-panel/70 p-2 text-xs"
                    >
                      <span className="text-[10.5px] font-semibold text-purple-300">
                        Connect Nodes:
                      </span>
                      <select
                        value={edgeFromNode || canvasParsed.nodes[0]?.id || ''}
                        onChange={(e) => setEdgeFromNode(e.target.value)}
                        className="max-w-[170px] rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[11px] text-white"
                      >
                        {canvasParsed.nodes.map((cn) => (
                          <option key={`from-${cn.id}`} value={cn.id}>
                            {describeCanvasNode(cn)}
                          </option>
                        ))}
                      </select>
                      <span className="text-purple-300 font-bold">→</span>
                      <select
                        value={edgeToNode || canvasParsed.nodes[1]?.id || ''}
                        onChange={(e) => setEdgeToNode(e.target.value)}
                        className="max-w-[170px] rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[11px] text-white"
                      >
                        {canvasParsed.nodes.map((cn) => (
                          <option key={`to-${cn.id}`} value={cn.id}>
                            {describeCanvasNode(cn)}
                          </option>
                        ))}
                      </select>
                      <input
                        type="text"
                        value={edgeLabel}
                        onChange={(e) => setEdgeLabel(e.target.value)}
                        placeholder="Edge label (optional)..."
                        className="flex-1 min-w-[110px] rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[11px] text-white"
                      />
                      <button
                        type="submit"
                        className="inline-flex items-center gap-1 rounded bg-purple-500/25 border border-purple-400/45 px-2.5 py-1 text-[11px] font-semibold text-purple-100 hover:bg-purple-500/40"
                      >
                        <Link className="h-3 w-3" /> Connect Edge
                      </button>
                    </form>
                  )}

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                    {canvasParsed.nodes.map((cn) => {
                      const nType = cn.type || 'text';
                      const isEditingCard = editingCanvasNodeId === cn.id;
                      const currentRawVal =
                        nType === 'group'
                          ? cn.label || ''
                          : nType === 'file'
                            ? cn.file || ''
                            : nType === 'link'
                              ? cn.url || ''
                              : cn.text || '';
                      if (nType === 'group') {
                        return (
                          <div
                            key={cn.id}
                            className="md:col-span-2 relative flex items-center justify-between gap-2 rounded-xl border border-dashed border-purple-400/45 bg-purple-500/5 px-3 py-2 text-xs font-bold text-purple-200"
                          >
                            {isEditingCard ? (
                              <form
                                onSubmit={(e) => {
                                  e.preventDefault();
                                  handleUpdateCanvasNode(cn.id, editingCanvasNodeValue);
                                }}
                                className="flex flex-1 items-center gap-1.5"
                              >
                                <input
                                  type="text"
                                  autoFocus
                                  value={editingCanvasNodeValue}
                                  onChange={(e) => setEditingCanvasNodeValue(e.target.value)}
                                  className="flex-1 rounded border border-purple-400/50 bg-kairos-bg px-2 py-1 text-xs font-normal text-white"
                                />
                                <button
                                  type="submit"
                                  className="rounded bg-purple-500 px-2 py-0.5 text-[10px] text-white"
                                >
                                  Save
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setEditingCanvasNodeId(null)}
                                  className="text-[10px] text-slate-400"
                                >
                                  Cancel
                                </button>
                              </form>
                            ) : (
                              <span>🗂️ Group Container: {cn.label || cn.id}</span>
                            )}
                            <div className="flex items-center gap-1">
                              <button
                                type="button"
                                onClick={() => {
                                  setEditingCanvasNodeId(cn.id);
                                  setEditingCanvasNodeValue(currentRawVal);
                                }}
                                title="Rename group label"
                                className="text-slate-400 hover:text-cyan-300"
                              >
                                <Pencil className="h-3 w-3" />
                              </button>
                              <button
                                type="button"
                                onClick={() => handleDeleteCanvasCard(cn.id)}
                                className="text-slate-400 hover:text-red-300"
                              >
                                <X className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </div>
                        );
                      }
                      return (
                        <div
                          key={cn.id}
                          className="group relative rounded-xl border border-purple-500/35 bg-purple-500/10 p-3 pr-12 text-xs text-slate-200 whitespace-pre-wrap shadow space-y-1.5"
                        >
                          <div className="absolute top-2 right-2 flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => {
                                setEditingCanvasNodeId(cn.id);
                                setEditingCanvasNodeValue(currentRawVal);
                              }}
                              title="Edit .canvas node inline"
                              className="rounded p-0.5 text-slate-400 opacity-70 hover:bg-cyan-500/20 hover:text-cyan-300 hover:opacity-100"
                            >
                              <Pencil className="h-3 w-3" />
                            </button>
                            <button
                              type="button"
                              onClick={() => handleDeleteCanvasCard(cn.id)}
                              title="Remove node from .canvas"
                              className="rounded p-0.5 text-slate-400 opacity-70 hover:bg-red-500/20 hover:text-red-300 hover:opacity-100"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                          {isEditingCard ? (
                            <form
                              onSubmit={(e) => {
                                e.preventDefault();
                                handleUpdateCanvasNode(cn.id, editingCanvasNodeValue);
                              }}
                              className="space-y-1.5"
                            >
                              <textarea
                                rows={nType === 'text' ? 3 : 1}
                                autoFocus
                                value={editingCanvasNodeValue}
                                onChange={(e) => setEditingCanvasNodeValue(e.target.value)}
                                className="w-full rounded border border-purple-400/50 bg-kairos-bg p-1.5 font-mono text-[11px] text-white"
                              />
                              <div className="flex justify-end gap-1">
                                <button
                                  type="button"
                                  onClick={() => setEditingCanvasNodeId(null)}
                                  className="rounded border border-kairos-border px-2 py-0.5 text-[10px] text-slate-400"
                                >
                                  Cancel
                                </button>
                                <button
                                  type="submit"
                                  className="rounded bg-purple-500 px-2 py-0.5 text-[10px] font-semibold text-white"
                                >
                                  Save Node
                                </button>
                              </div>
                            </form>
                          ) : nType === 'file' && cn.file ? (
                            <div className="space-y-1">
                              <div className="text-[10px] uppercase tracking-wider text-cyan-300 font-semibold">
                                📄 Vault File Node
                              </div>
                              <div className="font-mono text-[11px] text-white break-all">{cn.file}</div>
                              <button
                                type="button"
                                onClick={() => resolveWikiLinkToNote(cn.file!)}
                                className="mt-1 inline-flex items-center gap-1 rounded bg-cyan-500/20 border border-cyan-500/35 px-2 py-0.5 text-[10px] font-semibold text-cyan-200 hover:bg-cyan-500/30"
                              >
                                Open in Second Brain →
                              </button>
                            </div>
                          ) : nType === 'link' && cn.url ? (
                            <div className="space-y-1">
                              <div className="text-[10px] uppercase tracking-wider text-indigo-300 font-semibold">
                                🌐 External Portal Node
                              </div>
                              <div className="font-mono text-[11px] text-indigo-100 break-all">{cn.url}</div>
                              <button
                                type="button"
                                onClick={() => openExternalUrl(cn.url!, cn.url)}
                                className="mt-1 inline-flex items-center gap-1 rounded bg-indigo-500/20 border border-indigo-500/35 px-2 py-0.5 text-[10px] font-semibold text-indigo-200 hover:bg-indigo-500/30"
                              >
                                Launch Website <ExternalLink className="h-2.5 w-2.5" />
                              </button>
                            </div>
                          ) : (
                            <div>{renderInlineInteractiveText(cn.text || cn.id)}</div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Connected `.canvas` Directional Edges List */}
                  {(canvasParsed.edges || []).length > 0 && (
                    <div className="rounded-xl border border-purple-500/25 bg-kairos-panel/60 p-2.5 space-y-1.5">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-purple-300">
                        Connected Canvas Edges ({(canvasParsed.edges || []).length})
                      </div>
                      <div className="space-y-1">
                        {(canvasParsed.edges || []).map((ed) => {
                          const fromObj = canvasParsed.nodes?.find((n) => n.id === ed.fromNode);
                          const toObj = canvasParsed.nodes?.find((n) => n.id === ed.toNode);
                          return (
                            <div
                              key={ed.id}
                              className="flex items-center justify-between gap-2 rounded-lg border border-kairos-border bg-kairos-bg/70 px-2.5 py-1 text-[11px]"
                            >
                              <div className="min-w-0 truncate text-slate-200">
                                <span className="font-medium text-purple-200">
                                  {fromObj ? describeCanvasNode(fromObj) : ed.fromNode}
                                </span>
                                <span className="mx-1.5 text-purple-400">→</span>
                                <span className="font-medium text-cyan-200">
                                  {toObj ? describeCanvasNode(toObj) : ed.toNode}
                                </span>
                                {ed.label && (
                                  <span className="ml-2 rounded bg-purple-500/20 px-1.5 py-0.5 text-[10px] text-purple-200">
                                    {ed.label}
                                  </span>
                                )}
                              </div>
                              <button
                                type="button"
                                onClick={() => handleDeleteCanvasEdge(ed.id)}
                                title="Delete edge"
                                className="rounded p-0.5 text-slate-400 hover:bg-red-500/20 hover:text-red-300 shrink-0"
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                /* 3. Rich Obsidian Flavored Markdown & Callout Reader */
                <div className="rounded-xl border border-kairos-border bg-kairos-card/50 p-4 space-y-3">
                  {renderRichMarkdownBlocks(bodyDraft)}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
            <div className="rounded-2xl border border-kairos-border bg-kairos-panel/80 p-6 max-w-lg space-y-3 shadow-xl">
              <div className="text-sm font-bold text-white">
                Select a Canopy Vault Note or Build a New Domain Hub
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                Pick a Markdown note, `.canvas` ecosystem map, or `.base` database from the left
                explorer—or scaffold a complete Domain Section Hub (like <b>🎵 Music Studio, Plugins &amp; Distribution</b> or any custom topic).
              </p>
              <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setShowHubModal(true)}
                  className="flex items-center gap-1.5 rounded-lg bg-purple-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-purple-400"
                >
                  <Layers className="h-3.5 w-3.5" /> 🧩 + Build Section Hub
                </button>
                <button
                  type="button"
                  onClick={handleDailyNote}
                  className="flex items-center gap-1.5 rounded-lg bg-cyan-500/20 border border-cyan-500/40 px-3 py-1.5 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/30"
                >
                  <CalendarPlus className="h-3.5 w-3.5" /> Open Daily Note
                </button>
                <button
                  type="button"
                  onClick={() => setCreatingNote(true)}
                  className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-400"
                >
                  <FilePlus2 className="h-3.5 w-3.5" /> + New Note
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Modal 1: Adaptable Obsidian Vault Section Hub Builder */}
      {showHubModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <form
            onSubmit={handleScaffoldSectionHub}
            className="w-full max-w-2xl rounded-2xl border border-purple-500/40 bg-kairos-panel p-5 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto"
          >
            <div className="flex items-center justify-between border-b border-kairos-border pb-3">
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <Layers className="h-4 w-4 text-purple-400" />
                  Build or Expand an Obsidian Vault Section Hub
                </h3>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  Scaffolds `_Hub_Index.md` MOC + typed Collection folders + live `.base` database + JSON Canvas 1.0 `.canvas` map + reusable note template.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowHubModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Domain Blueprint Selector */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-semibold text-slate-300">
                1. Choose a Preset Blueprint or 100% Custom Domain
              </label>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {(vaultStructure?.blueprints || [
                  {
                    key: 'music_production',
                    label: 'Music Studio, Plugins & Distribution',
                    icon: '🎵',
                    default_parent: '04_Resources',
                    default_folder: 'Music_Studio',
                    description: 'Plugins, add-ons, samples, support websites & YouTube/Spotify/SoundCloud setup.',
                    schema_fields: [],
                    collections: [],
                  },
                ]).map((bp) => (
                  <button
                    key={bp.key}
                    type="button"
                    onClick={() => applyBlueprintSelection(bp.key)}
                    className={`rounded-xl border p-2.5 text-left text-xs transition ${
                      hubBlueprintKey === bp.key
                        ? 'border-purple-400 bg-purple-500/20 text-white'
                        : 'border-kairos-border bg-kairos-bg text-slate-300 hover:border-purple-500/40'
                    }`}
                  >
                    <div className="font-bold truncate">
                      {bp.icon} {bp.label}
                    </div>
                    <div className="text-[10px] text-slate-400 line-clamp-2 mt-0.5">
                      {bp.description}
                    </div>
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => applyBlueprintSelection('custom')}
                  className={`rounded-xl border p-2.5 text-left text-xs transition ${
                    hubBlueprintKey === 'custom'
                      ? 'border-emerald-400 bg-emerald-500/20 text-white'
                      : 'border-kairos-border bg-kairos-bg text-slate-300 hover:border-emerald-500/40'
                  }`}
                >
                  <div className="font-bold">✨ Custom Domain Hub</div>
                  <div className="text-[10px] text-slate-400 mt-0.5">
                    Design any custom topic, collections &amp; YAML properties from scratch.
                  </div>
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
              <div className="sm:col-span-2">
                <label className="block text-[11px] text-slate-400 mb-1">Section Title</label>
                <input
                  type="text"
                  value={hubTitle}
                  onChange={(e) => setHubTitle(e.target.value)}
                  placeholder="e.g. Music Studio, Photography Rig, AI Lab..."
                  className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-1.5 text-white"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Parent Vault Folder</label>
                <select
                  value={hubParentFolder}
                  onChange={(e) => setHubParentFolder(e.target.value)}
                  className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-white"
                >
                  <option value="04_Resources">04_Resources</option>
                  <option value="01_Business">01_Business</option>
                  <option value="03_Personal">03_Personal</option>
                  <option value="03_Personal/Finance">03_Personal/Finance (🔒)</option>
                </select>
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Icon</label>
                <input
                  type="text"
                  value={hubIcon}
                  onChange={(e) => setHubIcon(e.target.value)}
                  className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-1.5 text-white"
                />
              </div>
            </div>

            <div className="space-y-2 text-xs">
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">
                  Collection Subfolders (comma-separated — expandable anytime)
                </label>
                <input
                  type="text"
                  value={hubCollectionsText}
                  onChange={(e) => setHubCollectionsText(e.target.value)}
                  placeholder="Plugins, Addons_and_Presets, Samples_and_Packs, Support_and_Websites, Distribution"
                  className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-1.5 font-mono text-[11px] text-white"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">
                  YAML Frontmatter &amp; `.base` Columns (comma-separated)
                </label>
                <input
                  type="text"
                  value={hubFieldsText}
                  onChange={(e) => setHubFieldsText(e.target.value)}
                  placeholder="category, vendor, format, version, platform, status, support_url, dashboard_url"
                  className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-1.5 font-mono text-[11px] text-white"
                />
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 pt-1 text-xs">
              <div className="flex flex-wrap items-center gap-4">
                <label className="inline-flex items-center gap-1.5 text-slate-300">
                  <input
                    type="checkbox"
                    checked={hubSeedStarters}
                    onChange={(e) => setHubSeedStarters(e.target.checked)}
                  />
                  Seed starter guides &amp; checklists (e.g. YouTube, Spotify, SoundCloud)
                </label>
                <label className="inline-flex items-center gap-1.5 text-amber-300">
                  <input
                    type="checkbox"
                    checked={hubIsPrivate}
                    onChange={(e) => setHubIsPrivate(e.target.checked)}
                  />
                  🔒 Local-Only (`#private`)
                </label>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowHubModal(false)}
                  className="rounded-lg border border-kairos-border px-3 py-1.5 text-slate-300 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={scaffoldingHub}
                  className="rounded-lg bg-purple-500 px-4 py-1.5 font-semibold text-white hover:bg-purple-400 disabled:opacity-50"
                >
                  {scaffoldingHub ? 'Scaffolding...' : '🧩 Scaffold Section Hub'}
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* Modal 2: Add Structured Catalog Entry to Section Hub / `.base` */}
      {showEntryModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <form
            onSubmit={handleCreateSectionEntry}
            className="w-full max-w-xl rounded-2xl border border-emerald-500/40 bg-kairos-panel p-5 shadow-2xl space-y-3.5 max-h-[90vh] overflow-y-auto text-xs"
          >
            <div className="flex items-center justify-between border-b border-kairos-border pb-2.5">
              <div>
                <h3 className="text-sm font-bold text-white">
                  ➕ Add Structured Catalog Entry
                </h3>
                <p className="text-[11px] text-slate-400">
                  Creates an Obsidian Markdown note with typed YAML frontmatter indexed automatically in `.base` &amp; 3D Graph.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowEntryModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Target Hub / Folder</label>
                <input
                  type="text"
                  value={entryTargetSection}
                  onChange={(e) => setEntryTargetSection(e.target.value)}
                  className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 font-mono text-[11px] text-white"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Collection Subfolder</label>
                {(() => {
                  const hub = (vaultStructure?.sections || []).find(
                    (s) => s.section_rel === entryTargetSection
                  );
                  if (hub && hub.collections.length > 0) {
                    return (
                      <select
                        value={entryCollection}
                        onChange={(e) => handleEntryCollectionChange(e.target.value)}
                        className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-white"
                      >
                        {hub.collections.map((c) => (
                          <option key={c.folder} value={c.folder}>
                            {c.icon} {c.title} ({c.folder})
                          </option>
                        ))}
                      </select>
                    );
                  }
                  return (
                    <input
                      type="text"
                      value={entryCollection}
                      onChange={(e) => setEntryCollection(e.target.value)}
                      placeholder="Optional subfolder (e.g. Plugins)"
                      className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-white"
                    />
                  );
                })()}
              </div>
            </div>

            <div>
              <label className="block text-[11px] text-slate-400 mb-1">Entry Title</label>
              <input
                type="text"
                required
                value={entryTitle}
                onChange={(e) => setEntryTitle(e.target.value)}
                placeholder="e.g. FabFilter Pro-Q 4, Serum 2, Splice Drum Kit, DistroKid Setup..."
                className="w-full rounded border border-kairos-border bg-kairos-bg px-3 py-1.5 text-white"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {Object.entries(entryProps).map(([pk, pv]) => (
                <div key={pk}>
                  <label className="block text-[10px] font-mono text-slate-400 mb-0.5">{pk}</label>
                  <input
                    type="text"
                    value={pv}
                    onChange={(e) =>
                      setEntryProps((prev) => ({ ...prev, [pk]: e.target.value }))
                    }
                    placeholder={pk.endsWith('_url') ? 'https://...' : pk}
                    className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1 text-white"
                  />
                </div>
              ))}
            </div>

            <div>
              <label className="block text-[11px] text-slate-400 mb-1">
                Optional Markdown Notes / Setup Checklist
              </label>
              <textarea
                rows={3}
                value={entryBody}
                onChange={(e) => setEntryBody(e.target.value)}
                placeholder="Leave blank to auto-generate callout + clickable support portal links, or add custom Markdown notes..."
                className="w-full rounded border border-kairos-border bg-kairos-bg p-2.5 text-white"
              />
            </div>

            <div className="flex items-center justify-between pt-1">
              <label className="inline-flex items-center gap-1.5 text-amber-300">
                <input
                  type="checkbox"
                  checked={entryPrivate}
                  onChange={(e) => setEntryPrivate(e.target.checked)}
                />
                🔒 Local-Only (`#private`)
              </label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowEntryModal(false)}
                  className="rounded-lg border border-kairos-border px-3 py-1.5 text-slate-300"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingEntry}
                  className="rounded-lg bg-emerald-500 px-4 py-1.5 font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
                >
                  {creatingEntry ? 'Saving...' : 'Save to Vault'}
                </button>
              </div>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};

import React, { useEffect, useMemo, useState } from 'react';
import {
  Archive,
  ArrowRight,
  BookOpen,
  Edit3,
  Folder,
  Inbox,
  Layers,
  Plus,
  Rocket,
  Save,
  Sparkles,
  X,
} from 'lucide-react';
import {
  ProjectTreeItem,
  STANDARD_DEPARTMENTS,
  VaultNoteSummary,
  VaultSectionHubSummary,
  kairosApi,
} from '../../api/client.ts';
import { ToastKind } from '../../components/ToastCenter.tsx';

interface InboxWorkspaceProps {
  projects?: ProjectTreeItem[];
  refreshTick: number;
  onVaultMutated: () => void;
  onOpenNoteInSecondBrain: (relPath: string) => void;
  onNavigateToProjects: () => void;
  onNotify?: (kind: ToastKind, title: string, detail?: string) => void;
}

const FILING_DESTINATIONS = [
  { label: '04_Resources / Hermes (Knowledge)', value: '04_Resources/Hermes' },
  { label: '01_Business / Operations', value: '01_Business/Operations' },
  { label: '03_Personal / Personal_Growth', value: '03_Personal/Personal_Growth' },
  { label: '03_Personal / Finance (🔒 Local)', value: '03_Personal/Finance' },
  { label: '04_Resources / Code_and_Research', value: '04_Resources/Code_and_Research' },
  { label: '05_Archives', value: '05_Archives' },
];

const AI_AGENT_OPTIONS = [
  'None',
  'Gemma-4',
  'Gemini-Pro',
  'CrewAI-Research',
  'CrewAI-Dev',
  'CrewAI-PM',
  'Hermes-Agent',
  'Hermes-Synthesizer',
];

export const InboxWorkspace: React.FC<InboxWorkspaceProps> = ({
  projects = [],
  refreshTick,
  onVaultMutated,
  onOpenNoteInSecondBrain,
  onNavigateToProjects,
  onNotify,
}) => {
  const [items, setItems] = useState<VaultNoteSummary[]>([]);
  const [captureTitle, setCaptureTitle] = useState('');
  const [captureBody, setCaptureBody] = useState('');
  const [targetProject, setTargetProject] = useState('KAIROS_2_0');
  const [customProjectMode, setCustomProjectMode] = useState(false);
  const [targetDepartment, setTargetDepartment] = useState<string>('Software_Development');
  const [targetList, setTargetList] = useState('Sprint_01');
  const [targetPriority, setTargetPriority] = useState<number>(2);
  const [targetAgent, setTargetAgent] = useState('None');
  const [statusBanner, setStatusBanner] = useState('');
  const [expandedPath, setExpandedPath] = useState<string | null>(null);
  const [inlineDraft, setInlineDraft] = useState('');
  const [inlineFm, setInlineFm] = useState<Record<string, unknown>>({});
  const [savingInline, setSavingInline] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [busyItemPath, setBusyItemPath] = useState<string | null>(null);
  const [vaultSections, setVaultSections] = useState<VaultSectionHubSummary[]>([]);
  const [targetSectionHub, setTargetSectionHub] = useState('04_Resources/Music_Studio');
  const [targetHubCollection, setTargetHubCollection] = useState('Plugins');

  const filingDestinations = useMemo(() => {
    const merged = [...FILING_DESTINATIONS];
    const seen = new Set(merged.map((d) => d.value));
    for (const sec of vaultSections) {
      const icon = sec.icon || '🗂️';
      if (sec.section_rel && !seen.has(sec.section_rel)) {
        seen.add(sec.section_rel);
        merged.push({
          label: `${icon} ${sec.title} (Hub Root)`,
          value: sec.section_rel,
        });
      }
      for (const col of sec.collections || []) {
        const colPath = col.rel_path || `${sec.section_rel}/${col.folder}`;
        if (colPath && !seen.has(colPath)) {
          seen.add(colPath);
          merged.push({
            label: `${icon} ${sec.title} / ${col.title}`,
            value: colPath,
          });
        }
      }
    }
    return merged;
  }, [vaultSections]);

  const flashBanner = (msg: string) => {
    setStatusBanner(msg);
  };

  useEffect(() => {
    if (!statusBanner) return;
    const t = window.setTimeout(() => setStatusBanner(''), 4200);
    return () => window.clearTimeout(t);
  }, [statusBanner]);

  const loadInbox = async () => {
    const res = await kairosApi.searchNotes('', '00_Inbox');
    setItems(res.notes);
  };

  useEffect(() => {
    let cancelled = false;
    kairosApi
      .searchNotes('', '00_Inbox')
      .then((res) => {
        if (!cancelled) setItems(res.notes);
      })
      .catch(() => {});
    kairosApi
      .getVaultStructure()
      .then((res) => {
        if (cancelled) return;
        const secs = res.sections || [];
        setVaultSections(secs);
        if (secs.length > 0 && !secs.some((s) => s.section_rel === targetSectionHub)) {
          const firstHub = secs[0];
          setTargetSectionHub(firstHub.section_rel);
          setTargetHubCollection(firstHub.collections?.[0]?.folder || '');
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [refreshTick]);

  const activeHubCollections = useMemo(() => {
    const found = vaultSections.find((s) => s.section_rel === targetSectionHub);
    if (found && found.collections.length > 0) {
      return found.collections;
    }
    if (targetSectionHub.toLowerCase().includes('music_studio')) {
      return [
        { folder: 'Plugins', title: 'Plug-ins & Instruments', icon: '🎛️', item_type: 'plugin', fields: [] },
        { folder: 'Addons_and_Presets', title: 'Add-ons, Presets & Expansions', icon: '🧩', item_type: 'addon', fields: [] },
        { folder: 'Samples_and_Packs', title: 'Samples, Loops & Drum Kits', icon: '🥁', item_type: 'sample_pack', fields: [] },
        { folder: 'Support_and_Websites', title: 'Support Portals & Websites', icon: '🌐', item_type: 'support_portal', fields: [] },
        { folder: 'Distribution', title: 'Online Distribution Setup', icon: '🚀', item_type: 'distribution_platform', fields: [] },
      ];
    }
    return [];
  }, [vaultSections, targetSectionHub]);

  // Keep targetProject valid when projects tree hydrates
  useEffect(() => {
    if (!customProjectMode && projects.length > 0 && !projects.some((p) => p.name === targetProject)) {
      const preferred =
        projects.find((p) => p.name === 'KAIROS_2_0')?.name || projects[0].name;
      setTargetProject(preferred);
    }
  }, [projects, customProjectMode, targetProject]);

  // Merge standard 5 departments + any custom categories present on the selected project
  const availableDepartments = useMemo(() => {
    const map = new Map<
      string,
      { id: string; label: string; defaultList: string; emoji: string }
    >();
    for (const std of STANDARD_DEPARTMENTS) {
      map.set(std.id, {
        id: std.id,
        label: std.label,
        defaultList: std.defaultList,
        emoji: std.emoji,
      });
    }
    const projNode = projects.find((p) => p.name === targetProject);
    if (projNode) {
      for (const dept of projNode.departments) {
        if (!map.has(dept.name)) {
          map.set(dept.name, {
            id: dept.name,
            label: dept.name.replace(/_/g, ' '),
            defaultList: dept.lists[0]?.name || 'General',
            emoji: '📂',
          });
        } else if (dept.lists.length > 0) {
          const existing = map.get(dept.name)!;
          map.set(dept.name, { ...existing, defaultList: dept.lists[0].name });
        }
      }
    }
    return Array.from(map.values());
  }, [projects, targetProject]);

  const handleDepartmentChange = (deptId: string) => {
    setTargetDepartment(deptId);
    const match = availableDepartments.find((d) => d.id === deptId);
    if (match) {
      setTargetList(match.defaultList);
    }
  };

  const handleQuickCapture = async (e: React.FormEvent) => {
    e.preventDefault();
    if (capturing || (!captureTitle.trim() && !captureBody.trim())) return;
    setCapturing(true);
    try {
      const title = captureTitle.trim() || captureBody.trim().slice(0, 48);
      const isPriv = /#private\b/i.test(title) || /#private\b/i.test(captureBody);
      const tags = isPriv ? ['inbox', 'capture', 'private'] : ['inbox', 'capture'];
      const slug = title.replace(/[^A-Za-z0-9_-]+/g, '_').slice(0, 40) || 'Capture';
      const rel = `00_Inbox/Capture_${Date.now()}_${slug}.md`;
      await kairosApi.writeNote(
        rel,
        {
          title,
          type: 'inbox_capture',
          created_at: new Date().toISOString(),
          tags,
        },
        `# 📥 ${title}\n\n${captureBody.trim() || title}\n`,
        'overwrite'
      );
      setCaptureTitle('');
      setCaptureBody('');
      flashBanner(`Saved '${title}' to 00_Inbox/${isPriv ? ' (🔒 Local-Only #private)' : ''}`);
      onVaultMutated();
      loadInbox().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Quick Capture Failed',
        err instanceof Error ? err.message : 'Unable to save Inbox capture'
      );
    } finally {
      setCapturing(false);
    }
  };

  const handleToggleInlineExpand = async (relPath: string) => {
    if (expandedPath === relPath) {
      setExpandedPath(null);
      return;
    }
    try {
      const detail = await kairosApi.readNote(relPath);
      setExpandedPath(relPath);
      setInlineDraft(detail.body);
      setInlineFm(detail.frontmatter || {});
    } catch (err) {
      onNotify?.(
        'error',
        'Failed to Read Capture',
        err instanceof Error ? err.message : 'Unable to load Inbox note'
      );
    }
  };

  const handleSaveInlineCapture = async (relPath: string) => {
    setSavingInline(true);
    try {
      await kairosApi.writeNote(relPath, inlineFm, inlineDraft, 'overwrite');
      flashBanner(`Updated capture ${relPath}`);
      setExpandedPath(null);
      onVaultMutated();
      loadInbox().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Failed to Save Capture',
        err instanceof Error ? err.message : 'Unable to save Inbox note'
      );
    } finally {
      setSavingInline(false);
    }
  };

  const handlePromote = async (relPath: string) => {
    if (busyItemPath) return;
    setBusyItemPath(relPath);
    try {
      const cleanProject = targetProject.trim() || 'KAIROS_2_0';
      const res = await kairosApi.promoteInboxNote({
        src_rel_path: relPath,
        project: cleanProject,
        department: targetDepartment,
        list_name: targetList.trim() || 'Sprint_01',
        priority: targetPriority,
        ai_agent: targetAgent,
      });
      const tid = String(res.task.frontmatter.id || '');
      flashBanner(
        `Promoted to Project Task ${tid} (P${targetPriority}) in ${cleanProject}/${targetDepartment}/${targetList}!`
      );
      if (expandedPath === relPath) setExpandedPath(null);
      onVaultMutated();
      loadInbox().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Task Promotion Failed',
        err instanceof Error ? err.message : 'Unable to promote Inbox capture to task'
      );
    } finally {
      setBusyItemPath(null);
    }
  };

  const handlePromoteToSectionHub = async (relPath: string) => {
    if (busyItemPath) return;
    setBusyItemPath(relPath);
    try {
      const colObj = activeHubCollections.find((c) => c.folder === targetHubCollection);
      const res = await kairosApi.promoteInboxToSection({
        src_rel_path: relPath,
        section_or_folder: targetSectionHub || '04_Resources/Music_Studio',
        collection: targetHubCollection,
        item_type: colObj?.item_type || '',
      });
      flashBanner(
        `Promoted capture into Section Hub entry '${res.entry.title}' (${res.entry.rel_path})!`
      );
      onNotify?.('success', 'Promoted to Section Hub', res.entry.rel_path);
      if (expandedPath === relPath) setExpandedPath(null);
      onVaultMutated();
      loadInbox().catch(() => {});
      kairosApi
        .getVaultStructure()
        .then((s) => setVaultSections(s.sections || []))
        .catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Hub Entry Promotion Failed',
        err instanceof Error ? err.message : 'Unable to promote Inbox capture to Section Hub'
      );
    } finally {
      setBusyItemPath(null);
    }
  };

  const handleSendToProjectWiki = async (relPath: string) => {
    if (busyItemPath) return;
    setBusyItemPath(relPath);
    try {
      const cleanProject = (targetProject.trim() || 'KAIROS_2_0').replace(/\s+/g, '_');
      const wikiFolder = `02_Projects/${cleanProject}/Docs`;
      const moved = await kairosApi.moveInboxNote(relPath, wikiFolder);
      flashBanner(`Published capture to ${cleanProject} Documentation Wiki (${moved.rel_path})`);
      if (expandedPath === relPath) setExpandedPath(null);
      onVaultMutated();
      loadInbox().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Wiki Publish Failed',
        err instanceof Error ? err.message : 'Unable to move capture to Project Wiki'
      );
    } finally {
      setBusyItemPath(null);
    }
  };

  const handleRetainInHermes = async (item: VaultNoteSummary) => {
    if (busyItemPath) return;
    setBusyItemPath(item.rel_path);
    try {
      const prefix = item.is_private ? '[#private] ' : '';
      const fact = `${prefix}${item.title}: ${(item.excerpt || '').slice(0, 180)}`;
      const res = await kairosApi.retainHermesMemory({
        fact,
        target: 'memory',
        section: 'Inbox & Research Takeaways',
        is_private: item.is_private,
      });
      flashBanner(`Retained takeaway in Hermes (${res.rel_path})`);
      onVaultMutated();
    } catch (err) {
      onNotify?.(
        'error',
        'Hermes Retain Failed',
        err instanceof Error ? err.message : 'Unable to retain takeaway'
      );
    } finally {
      setBusyItemPath(null);
    }
  };

  const handleDistillAsSkill = async (item: VaultNoteSummary) => {
    if (busyItemPath) return;
    setBusyItemPath(item.rel_path);
    try {
      const cleanProject = (targetProject.trim() || 'KAIROS_2_0').replace(/\s+/g, '_');
      const fullNote = await kairosApi.readNote(item.rel_path);
      const created = await kairosApi.createHermesSkill({
        title: item.title,
        trigger: `Apply workflow captured from Inbox note: ${item.title}`,
        steps_markdown: (fullNote.body || item.excerpt || item.title).slice(0, 1400),
        category: 'Inbox Distillation',
        project: cleanProject,
        is_private: item.is_private,
      });
      flashBanner(
        `Distilled Inbox note into Hermes Skill ${created.skill_id} (${created.rel_path})`
      );
      onVaultMutated();
    } catch (err) {
      onNotify?.(
        'error',
        'Skill Distillation Failed',
        err instanceof Error ? err.message : 'Unable to distill Inbox note'
      );
    } finally {
      setBusyItemPath(null);
    }
  };

  const handleMove = async (relPath: string, destFolder: string) => {
    if (busyItemPath) return;
    setBusyItemPath(relPath);
    try {
      const moved = await kairosApi.moveInboxNote(relPath, destFolder);
      flashBanner(`Filed note into ${moved.rel_path}`);
      if (expandedPath === relPath) setExpandedPath(null);
      onVaultMutated();
      loadInbox().catch(() => {});
    } catch (err) {
      onNotify?.(
        'error',
        'Inbox Triage Failed',
        err instanceof Error ? err.message : 'Unable to move capture'
      );
    } finally {
      setBusyItemPath(null);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-5 bg-kairos-bg space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-base font-bold text-white flex items-center gap-2">
            <Inbox className="h-4 w-4 text-cyan-400" />
            Inbox Capture & Triage Hub (`00_Inbox/`)
          </h1>
          <p className="text-xs text-slate-400">
            Drop quick ideas, voice memos, and Browser web clips here—then 1-click promote them
            into any Project Category (`02_Projects/[Project]/[Category]/`), publish to a Project
            Wiki (`Docs/`), or retain durable takeaways in Hermes `MEMORY.md`.
          </p>
        </div>

        <button
          type="button"
          onClick={onNavigateToProjects}
          className="flex items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/15 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/25"
        >
          View Projects Rollup <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>

      {statusBanner && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-4 py-2 text-xs text-emerald-300">
          ✓ {statusBanner}
        </div>
      )}

      {/* Top Row: Quick Capture + Default Project/Category/Wiki Promotion Target */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <form
          onSubmit={handleQuickCapture}
          className="lg:col-span-2 rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-2.5"
        >
          <div className="flex items-center gap-1.5 text-xs font-bold text-white">
            <Sparkles className="h-3.5 w-3.5 text-emerald-400" /> Quick Capture to `00_Inbox/`
          </div>
          <input
            type="text"
            value={captureTitle}
            onChange={(e) => setCaptureTitle(e.target.value)}
            placeholder="Capture title or headline..."
            className="w-full rounded-lg border border-kairos-border bg-kairos-bg px-3 py-1.5 text-xs text-white"
          />
          <textarea
            value={captureBody}
            onChange={(e) => setCaptureBody(e.target.value)}
            rows={3}
            placeholder="Raw notes, links, [[WikiLinks]], or #tags (add #private for Local Gemma 4 Hard-Lock)..."
            className="w-full rounded-lg border border-kairos-border bg-kairos-bg p-3 text-xs text-slate-200"
          />
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={capturing}
              className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3.5 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
            >
              <Plus className="h-3.5 w-3.5" /> {capturing ? 'Capturing...' : 'Capture Note'}
            </button>
          </div>
        </form>

        <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-2.5">
          <div className="text-xs font-bold text-amber-300">
            Default Project, Category &amp; Wiki Target
          </div>
          <p className="text-[11px] text-slate-400">
            Choose Project → Category → List inside `02_Projects/`:
          </p>
          <div className="space-y-2 text-xs">
            {projects.length > 0 && !customProjectMode ? (
              <select
                value={targetProject}
                onChange={(e) => {
                  if (e.target.value === '__custom__') {
                    setCustomProjectMode(true);
                  } else {
                    setTargetProject(e.target.value);
                  }
                }}
                className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-white"
              >
                {projects.map((p) => (
                  <option key={p.name} value={p.name}>
                    🚀 {p.name.replace(/_/g, ' ')} ({p.task_count} tasks)
                  </option>
                ))}
                <option value="__custom__">✨ Custom / New Project...</option>
              </select>
            ) : (
              <div className="flex gap-1.5">
                <input
                  type="text"
                  value={targetProject}
                  onChange={(e) => setTargetProject(e.target.value)}
                  placeholder="Project (e.g. KAIROS_2_0)"
                  className="flex-1 rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-white"
                />
                {projects.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setCustomProjectMode(false)}
                    className="rounded border border-kairos-border bg-kairos-card px-2 py-1 text-[10px] text-slate-300 hover:text-white"
                  >
                    List
                  </button>
                )}
              </div>
            )}

            <select
              value={targetDepartment}
              onChange={(e) => handleDepartmentChange(e.target.value)}
              className="w-full rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-emerald-300"
            >
              {availableDepartments.map((dept) => (
                <option key={dept.id} value={dept.id}>
                  {dept.emoji} {dept.label}
                </option>
              ))}
            </select>

            <div className="grid grid-cols-3 gap-2">
              <input
                type="text"
                value={targetList}
                onChange={(e) => setTargetList(e.target.value)}
                placeholder="List / Sprint (e.g. Sprint_01)"
                className="rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-white"
              />
              <select
                value={targetPriority}
                onChange={(e) => setTargetPriority(Number(e.target.value))}
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-amber-300"
              >
                <option value={1}>P1 Urgent</option>
                <option value={2}>P2 High</option>
                <option value={3}>P3 Normal</option>
                <option value={4}>P4 Low</option>
              </select>
              <select
                value={targetAgent}
                onChange={(e) => setTargetAgent(e.target.value)}
                className="rounded border border-kairos-border bg-kairos-bg px-2 py-1.5 text-purple-300"
              >
                {AI_AGENT_OPTIONS.map((agent) => (
                  <option key={agent} value={agent}>
                    {agent === 'None' ? 'AI: None' : agent}
                  </option>
                ))}
              </select>
            </div>

            <div className="pt-2 border-t border-kairos-border space-y-1.5">
              <div className="flex items-center gap-1 text-[11px] font-bold text-purple-300">
                <Layers className="h-3 w-3 text-purple-400" />
                <span>Obsidian Section Hub Target (`.base` Catalog)</span>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                <select
                  value={targetSectionHub}
                  onChange={(e) => {
                    const nextSec = e.target.value;
                    setTargetSectionHub(nextSec);
                    const hub = vaultSections.find((s) => s.section_rel === nextSec);
                    setTargetHubCollection(hub?.collections?.[0]?.folder || 'Plugins');
                  }}
                  className="rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[11px] text-white"
                >
                  {vaultSections.map((sec) => (
                    <option key={sec.section_rel} value={sec.section_rel}>
                      {sec.icon} {sec.title}
                    </option>
                  ))}
                  {!vaultSections.some((s) => s.section_rel === '04_Resources/Music_Studio') && (
                    <option value="04_Resources/Music_Studio">
                      🎵 Music Studio (Auto-Scaffold)
                    </option>
                  )}
                </select>
                <select
                  value={targetHubCollection}
                  onChange={(e) => setTargetHubCollection(e.target.value)}
                  className="rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[11px] text-purple-200"
                >
                  {activeHubCollections.length > 0 ? (
                    activeHubCollections.map((c) => (
                      <option key={c.folder} value={c.folder}>
                        {c.icon} {c.title}
                      </option>
                    ))
                  ) : (
                    <option value="">Hub Root</option>
                  )}
                </select>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Unprocessed 00_Inbox Queue */}
      <div className="space-y-2.5">
        <div className="text-xs font-bold text-slate-300">
          Unprocessed Captures ({items.length})
        </div>

        {items.length === 0 ? (
          <div className="rounded-xl border border-kairos-border bg-kairos-panel p-8 text-center text-xs text-slate-400">
            Inbox Zero! All captures in `00_Inbox/` have been triaged.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {items.map((item) => (
              <div
                key={item.rel_path}
                className="rounded-xl border border-kairos-border bg-kairos-panel p-4 flex flex-col justify-between gap-3"
              >
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => onOpenNoteInSecondBrain(item.rel_path)}
                      className="text-sm font-bold text-white hover:text-emerald-300 text-left truncate"
                    >
                      {item.title}
                    </button>
                    <div className="flex items-center gap-1 shrink-0">
                      {item.is_private && (
                        <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                          🔒 Local
                        </span>
                      )}
                        <span className="rounded bg-cyan-500/15 px-2 py-0.5 text-[10px] text-cyan-300">
                          {item.type}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleToggleInlineExpand(item.rel_path)}
                          title="Read or edit full Markdown capture inline"
                          className="inline-flex items-center gap-1 rounded border border-kairos-border bg-kairos-card px-2 py-0.5 text-[10px] text-slate-300 hover:border-emerald-500/40 hover:text-white"
                        >
                          {expandedPath === item.rel_path ? (
                            <>
                              <X className="h-2.5 w-2.5" /> Close
                            </>
                          ) : (
                            <>
                              <Edit3 className="h-2.5 w-2.5" /> Read / Edit
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                    <div className="font-mono text-[10px] text-slate-500">{item.rel_path}</div>
                    {expandedPath === item.rel_path ? (
                      <div className="space-y-2 pt-1">
                        <textarea
                          rows={6}
                          value={inlineDraft}
                          onChange={(e) => setInlineDraft(e.target.value)}
                          className="w-full rounded-lg border border-emerald-500/40 bg-kairos-bg p-2.5 font-mono text-xs text-slate-100 focus:outline-none"
                        />
                        <div className="flex justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => setExpandedPath(null)}
                            className="rounded border border-kairos-border px-2.5 py-1 text-[11px] text-slate-400 hover:text-white"
                          >
                            Cancel
                          </button>
                          <button
                            type="button"
                            disabled={savingInline}
                            onClick={() => handleSaveInlineCapture(item.rel_path)}
                            className="inline-flex items-center gap-1 rounded bg-emerald-500 px-2.5 py-1 text-[11px] font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
                          >
                            <Save className="h-3 w-3" /> {savingInline ? 'Saving...' : 'Save Capture'}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-slate-300 line-clamp-3">{item.excerpt}</p>
                    )}
                  </div>

                <div className="space-y-2 pt-2 border-t border-kairos-border">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <button
                      type="button"
                      disabled={Boolean(busyItemPath)}
                      onClick={() => handlePromote(item.rel_path)}
                      className="flex items-center gap-1 rounded-lg bg-emerald-500/20 border border-emerald-500/40 px-2.5 py-1 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-50"
                    >
                      <Rocket className="h-3 w-3" /> Promote to Task
                    </button>

                    <button
                      type="button"
                      disabled={Boolean(busyItemPath)}
                      onClick={() => handlePromoteToSectionHub(item.rel_path)}
                      title={`Promote into structured Section Hub entry (${targetSectionHub}/${targetHubCollection || ''}) & index in .base`}
                      className="flex items-center gap-1 rounded-lg border border-purple-500/45 bg-purple-500/15 px-2.5 py-1 text-xs font-semibold text-purple-200 hover:bg-purple-500/25 disabled:opacity-50"
                    >
                      <Layers className="h-3 w-3" /> → Hub Entry
                    </button>

                    <button
                      type="button"
                      disabled={Boolean(busyItemPath)}
                      onClick={() => handleSendToProjectWiki(item.rel_path)}
                      title={`Move into 02_Projects/${targetProject}/Docs/ Project Wiki`}
                      className="flex items-center gap-1 rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-2.5 py-1 text-xs font-medium text-cyan-200 hover:bg-cyan-500/25 disabled:opacity-50"
                    >
                      <BookOpen className="h-3 w-3" /> → {targetProject.replace(/_/g, ' ')} Wiki
                    </button>

                    <button
                      type="button"
                      disabled={Boolean(busyItemPath)}
                      onClick={() => handleRetainInHermes(item)}
                      title="Retain durable takeaway in 04_Resources/Hermes/MEMORY.md"
                      className="rounded-lg border border-purple-500/40 bg-purple-500/15 px-2 py-1 text-[11px] font-semibold text-purple-200 hover:bg-purple-500/25 disabled:opacity-50"
                    >
                      🪽 Retain in Hermes
                    </button>

                    <button
                      type="button"
                      disabled={Boolean(busyItemPath)}
                      onClick={() => handleDistillAsSkill(item)}
                      title="Distill this Inbox capture into a reusable Hermes SKL-*.md Skill"
                      className="rounded-lg border border-amber-500/40 bg-amber-500/15 px-2 py-1 text-[11px] font-semibold text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
                    >
                      🪽 Distill Skill
                    </button>

                    <button
                      type="button"
                      disabled={Boolean(busyItemPath)}
                      onClick={() => handleMove(item.rel_path, '05_Archives/Triaged_Inbox')}
                      title="Archive capture into 05_Archives/Triaged_Inbox/"
                      className="flex items-center gap-1 rounded-lg border border-slate-600/80 bg-kairos-card px-2 py-1 text-[11px] font-medium text-slate-300 hover:border-amber-500/40 hover:text-amber-200 disabled:opacity-50"
                    >
                      <Archive className="h-3 w-3" /> Archive
                    </button>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <Folder className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                    <select
                      value=""
                      disabled={Boolean(busyItemPath)}
                      onChange={(e) => {
                        if (e.target.value) handleMove(item.rel_path, e.target.value);
                      }}
                      className="w-full rounded border border-kairos-border bg-kairos-bg px-2 py-1 text-[11px] text-slate-300 disabled:opacity-50"
                    >
                      <option value="" disabled>
                        File into Second Brain folder...
                      </option>
                      {filingDestinations.map((d) => (
                        <option key={d.value} value={d.value}>
                          {d.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

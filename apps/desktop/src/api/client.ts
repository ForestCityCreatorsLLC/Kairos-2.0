/**
 * Typed REST + WebSocket API Client for KAIROS 2.0 Core (`127.0.0.1:8420`)
 * and Isolated KAIROS Voice Sidecar (`127.0.0.1:8421`).
 */

export const CORE_BASE = 'http://127.0.0.1:8420';
export const VOICE_BASE = 'http://127.0.0.1:8421';
export const CORE_WS = 'ws://127.0.0.1:8420/ws/events';
export const VOICE_WS = 'ws://127.0.0.1:8421/ws/voice';

export type TaskStatus = 'Backlog' | 'To Do' | 'In Progress' | 'Review' | 'Blocked' | 'Done';
export type BrainMode = 'auto' | 'gemma-4' | 'gemini' | 'hybrid';
export type PersonaRole = 'companion' | 'pm' | 'dev' | 'creative' | 'owner';
export type ToneMode = 'DEFAULT' | 'CODE_RED';
export type ProjectsSubView = 'list' | 'board' | 'gantt' | 'calendar' | 'docs' | 'rollup';

export type UIActionCommand =
  | {
      type: 'navigate_tab';
      tab:
        | 'assistant'
        | 'inbox'
        | 'projects'
        | 'second-brain'
        | 'browser'
        | 'paperclip'
        | 'settings';
    }
  | { type: 'select_project_scope'; project: string; department: string; list: string }
  | { type: 'set_projects_view'; view: ProjectsSubView }
  | { type: 'open_task_drawer'; task_id: string }
  | { type: 'close_task_drawer' }
  | {
      type: 'filter_projects_tasks';
      keyword?: string;
      ai_agent?: string;
      priority?: number;
    }
  | { type: 'open_note'; rel_path: string }
  | { type: 'set_second_brain_graph'; show: boolean; mode: '3d' | '2d' }
  | { type: 'filter_second_brain'; query?: string; folder?: string }
  | { type: 'browser_navigate'; url: string; title?: string; new_tab?: boolean }
  | {
      type: 'browser_control';
      action: 'back' | 'forward' | 'reload' | 'home' | 'new_tab' | 'close_tab';
    }
  | { type: 'browser_clip'; dest_folder?: string }
  | { type: 'set_persona'; persona: PersonaRole }
  | { type: 'set_tone_mode'; tone_mode: ToneMode }
  | { type: 'set_brain_mode'; brain_mode: BrainMode }
  | { type: 'set_left_sidebar'; collapsed: boolean }
  | { type: 'set_chat_drawer'; open: boolean }
  | { type: 'set_command_palette'; open: boolean }
  | { type: 'trigger_api_verify'; live?: boolean };

export const STANDARD_DEPARTMENTS = [
  { id: 'Software_Development', label: 'Software Development', defaultList: 'Sprint_01', emoji: '💻' },
  { id: 'Marketing_and_Branding', label: 'Marketing & Branding', defaultList: 'Campaigns', emoji: '📣' },
  { id: 'Documentation', label: 'Documentation', defaultList: 'Specs_and_Guides', emoji: '📄' },
  { id: 'Website', label: 'Website', defaultList: 'Web_Launch', emoji: '🌐' },
  { id: 'Merch', label: 'Merch', defaultList: 'Printful_Drops', emoji: '👕' },
] as const;

export interface TaskSummary {
  id: string;
  rel_path: string;
  title: string;
  type: string;
  status: TaskStatus;
  priority: number;
  project: string;
  department: string;
  list: string;
  parent_task: string;
  depends_on: string[];
  assignee: string;
  ai_agent: string;
  start_date: string;
  due_date: string;
  time_estimate_hrs: number;
  time_logged_hrs: number;
  tags: string[];
  checklist_total: number;
  checklist_done: number;
}

export interface RollupMetrics {
  scope: { project: string; department: string; list: string };
  total_tasks: number;
  progress_pct: number;
  by_status: Record<string, number>;
  by_department?: Record<string, number>;
  time_estimate_hrs: number;
  time_logged_hrs: number;
  overdue_task_ids: string[];
  blocked_task_ids: string[];
}

export interface ProjectTreeItem {
  name: string;
  task_count: number;
  progress_pct: number;
  departments: {
    name: string;
    task_count: number;
    lists: { name: string; task_count: number }[];
  }[];
}

export interface VaultNoteSummary {
  rel_path: string;
  title: string;
  type: string;
  folder_top: string;
  is_private: boolean;
  tags: string[];
  wikilinks: string[];
  frontmatter: Record<string, unknown>;
  excerpt: string;
  mtime: number;
}

export interface VaultNoteDetail {
  rel_path: string;
  abs_path: string;
  title: string;
  frontmatter: Record<string, unknown>;
  body: string;
  wikilinks: string[];
  tags: string[];
  is_private: boolean;
}

export interface NoteBacklinkItem {
  rel_path: string;
  title: string;
  type: string;
  folder_top: string;
  edge_kind: string;
  is_private: boolean;
  excerpt: string;
  task_id: string;
}

export interface GraphData {
  nodes: {
    id: string;
    label: string;
    type: string;
    group: string;
    is_private: boolean;
  }[];
  edges: {
    source: string;
    target: string;
    kind: string;
  }[];
}

export interface VaultCollectionMeta {
  folder: string;
  title: string;
  icon: string;
  item_type: string;
  fields: string[];
  rel_path?: string;
  entry_count?: number;
  description?: string;
}

export interface VaultSectionHubSummary {
  hub_id: string;
  title: string;
  icon: string;
  domain: string;
  section_rel: string;
  hub_index_rel: string;
  base_rel: string;
  canvas_rel: string;
  template_rel: string;
  schema_fields: string[];
  collections: VaultCollectionMeta[];
  entry_count: number;
  is_private: boolean;
}

export interface VaultBlueprintSpec {
  key: string;
  label: string;
  icon: string;
  default_parent: string;
  default_folder: string;
  description: string;
  schema_fields: string[];
  collections: VaultCollectionMeta[];
}

export interface VaultStructureSnapshot {
  ok: boolean;
  sections: VaultSectionHubSummary[];
  folders: string[];
  bases: { rel_path: string; title: string; folder: string }[];
  canvases: { rel_path: string; title: string; folder: string }[];
  templates: { rel_path: string; title: string }[];
  blueprints: VaultBlueprintSpec[];
}

export interface VaultBaseQueryResult {
  ok: boolean;
  valid_yaml: boolean;
  base_rel_path: string;
  errors: string[];
  views: { name: string; type: 'table' | 'cards' | 'list' | 'map' }[];
  active_view: { name: string; type: 'table' | 'cards' | 'list' | 'map' } | null;
  columns: { key: string; label: string }[];
  rows: {
    rel_path: string;
    title: string;
    is_private: boolean;
    type: string;
    folder: string;
    tags: string[];
    task_id: string;
    cells: Record<string, unknown>;
  }[];
  total_rows?: number;
  summaries: Record<string, { formula: string; value: unknown }>;
  inferred_folder: string;
  editable_fields?: string[];
}

export interface VaultHealthReport {
  ok: boolean;
  status: 'healthy' | 'attention' | 'issues';
  health_score: number;
  counts: {
    total_files: number;
    markdown_notes: number;
    bases: number;
    canvases: number;
    tasks: number;
    section_hubs: number;
  };
  broken_links: {
    source_path: string;
    target: string;
    edge_kind: string;
    suggested_folder: string;
  }[];
  orphan_notes: { rel_path: string; title: string }[];
  syntax_issues: { rel_path: string; kind: 'canvas' | 'base'; errors: string[] }[];
}

export interface CalendarEventItem {
  id: string;
  title: string;
  category: string;
  start_time: string;
  end_time: string;
  location: string;
  linked_task: string;
  linked_task_id?: string;
  linked_project?: string;
  rel_path: string;
}

export interface HermesSkillItem {
  skill_id: string;
  title: string;
  category: string;
  trigger: string;
  source_task: string;
  project: string;
  updated_at: string;
  is_private: boolean;
  rel_path: string;
  excerpt: string;
}

export interface HermesStatusSnapshot {
  memory_rel: string;
  private_memory_rel?: string;
  memory_archive_rel?: string;
  user_rel: string;
  skills_dir_rel: string;
  memory_body: string;
  user_body: string;
  skill_count: number;
  max_memory_bullets?: number;
  skills: HermesSkillItem[];
}

export interface ArchivedTaskSummary {
  id: string;
  title: string;
  project: string;
  department: string;
  list: string;
  archived_at: string;
  archived_by: string;
  rel_path: string;
}

export interface PaperclipSnapshot {
  active_count: number;
  active_locks: {
    lock_id: string;
    task_id: string;
    agent: string;
    crew_type: string;
    checked_out_at: string;
    step: string;
    elapsed_sec?: number;
  }[];
  recent_runs: {
    task_id: string;
    agent: string;
    crew_type: string;
    status: string;
    duration_ms: number;
    summary: string;
    artifact_rel_path?: string;
    hermes_skill_rel_path?: string;
    degraded?: boolean;
    finished_at: string;
  }[];
  browser_events: {
    timestamp: string;
    task_id: string;
    action: string;
    url: string;
  }[];
}

export interface VramTelemetrySnapshot {
  gpu_envelope_gb: number;
  vram_ceiling_gb: number;
  active_resident_vram_gb: number;
  headroom_gb: number;
  dwm_safety_headroom_gb?: number;
  full_stack_budget_gb?: number;
  within_vram_ceiling: boolean;
}

export interface VoiceStateSnapshot {
  status: 'IDLE' | 'LISTENING' | 'THINKING' | 'SPEAKING' | 'MUTED';
  muted: boolean;
  hold_seconds: number;
  hands_free?: boolean;
  wake_word_only?: boolean;
  neural_tts?: boolean;
  stt_provider?: string;
  tts_voice?: string;
  prosody_mode?: 'mutter' | 'normal';
  vad_threshold?: number;
  is_thinking_aloud?: boolean;
  last_barge_in_latency_ms?: number;
  kokoro_local_ready?: boolean;
  whisper_local_ready?: boolean;
  last_transcript: string;
  last_reply: string;
  vu_level: number;
  last_ui_commands?: UIActionCommand[];
  last_mutter_clauses?: string[];
  vram_telemetry?: VramTelemetrySnapshot;
  event?: string;
  mutter_clauses?: string[];
}

export interface VoiceTtsPayload {
  ok: boolean;
  fallback_browser_tts?: boolean;
  audio_base64?: string;
  mime_type?: string;
  clean_text: string;
  voice?: string;
  provider?: string;
  prosody_mode?: 'mutter' | 'normal';
  privacy_locked?: boolean;
}

export interface AssistantTurn {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  agent?: string;
  persona?: PersonaRole;
  tone_mode?: ToneMode;
  privacy_locked?: boolean;
  actions?: string[];
}

export interface AssistantSessionSummary {
  session_id: string;
  title: string;
  persona: PersonaRole;
  tone_mode: ToneMode;
  updated_at: string;
  turn_count: number;
  rel_path: string;
  last_preview: string;
}

export interface AssistantSessionDetail {
  session_id: string;
  title: string;
  persona: PersonaRole;
  tone_mode: ToneMode;
  updated_at: string;
  rel_path: string;
  turns: AssistantTurn[];
}

export interface AssistantChatResponse {
  reply: string;
  spoken_reply?: string;
  mutter_clauses?: string[];
  vision_context?: {
    source: string;
    width: number;
    height: number;
    capture_ms: number;
    privacy_locked: boolean;
  } | null;
  agent: string;
  route_reason: string;
  privacy_locked: boolean;
  latency_ms?: number;
  created_task_id?: string;
  created_project?: string;
  calendar_blocked_at?: string;
  assigned_agent?: string;
  ui_commands?: UIActionCommand[];
  actions?: string[];
  session?: AssistantSessionDetail | null;
}

export interface VoiceAudioCommandResponse extends VoiceStateSnapshot {
  transcript: string;
  wake_word_ignored?: boolean;
  stt?: {
    ok: boolean;
    text: string;
    provider: string;
    privacy_locked: boolean;
    error?: string;
  };
  core_response: AssistantChatResponse | null;
  tts: VoiceTtsPayload | null;
}

export interface EnvApiCheckItem {
  id: string;
  name: string;
  env_keys: string[] | string;
  env_keys_label?: string;
  configured: boolean;
  masked: string;
  masked_key: string;
  status: string;
  detail: string;
}

export interface EnvVerificationReport {
  live_probed: boolean;
  live_tested: boolean;
  env_file_exists: boolean;
  configured_count: number;
  total_integrations: number;
  total_count: number;
  warnings_count: number;
  checks: EnvApiCheckItem[];
}

interface RequestJsonInit extends RequestInit {
  timeoutMs?: number;
}

async function requestJson<T>(url: string, init?: RequestJsonInit): Promise<T> {
  const { timeoutMs = 45000, signal: callerSignal, headers: callerHeaders, ...restInit } = init || {};
  const controller = !callerSignal && timeoutMs > 0 ? new AbortController() : null;
  let timedOut = false;
  const timer =
    controller !== null
      ? globalThis.setTimeout(() => {
          timedOut = true;
          controller.abort();
        }, timeoutMs)
      : null;

  try {
    const res = await fetch(url, {
      ...restInit,
      headers: {
        'Content-Type': 'application/json',
        ...(callerHeaders || {}),
      },
      signal: callerSignal ?? controller?.signal,
    });
    if (!res.ok) {
      const errText = await res.text();
      let cleanDetail = errText;
      try {
        const parsed = JSON.parse(errText) as { detail?: string };
        if (parsed && typeof parsed.detail === 'string') {
          cleanDetail = parsed.detail;
        }
      } catch {
        // keep raw text fallback
      }
      throw new Error(`HTTP ${res.status}: ${cleanDetail}`);
    }
    return (await res.json()) as T;
  } catch (err) {
    if (timedOut) {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s (${url})`);
    }
    throw err;
  } finally {
    if (timer !== null) {
      globalThis.clearTimeout(timer);
    }
  }
}

export const kairosApi = {
  getHealth: () =>
    requestJson<{
      status: string;
      version: string;
      operator_name?: string;
      project_root?: string;
      vault_path: string;
      vault_exists: boolean;
      lmstudio_model: string;
      lmstudio_url: string;
      gemini_configured: boolean;
      gemini_model?: string;
      rollup: RollupMetrics;
      paperclip: PaperclipSnapshot;
      hermes_skill_count?: number;
    }>(`${CORE_BASE}/api/health`, { timeoutMs: 8000 }),

  verifyEnvApis: (live = false) =>
    requestJson<EnvVerificationReport>(
      `${CORE_BASE}/api/settings/verify-apis?live=${live ? 'true' : 'false'}`,
      { timeoutMs: 65000 }
    ),

  getProjectsTree: () =>
    requestJson<{
      projects: ProjectTreeItem[];
      rollup: RollupMetrics;
      archived_projects?: string[];
    }>(`${CORE_BASE}/api/projects/tree`),

  resyncProjects: () =>
    requestJson<{
      indexed_files: number;
      projects: ProjectTreeItem[];
      rollup: RollupMetrics;
      archived_projects?: string[];
    }>(`${CORE_BASE}/api/projects/resync`, { method: 'POST' }),

  getArchivedProjects: () =>
    requestJson<{ archived_projects: string[] }>(`${CORE_BASE}/api/projects/archived`),

  getArchivedTasks: (project = '') => {
    const q = new URLSearchParams();
    if (project) q.set('project', project);
    const qs = q.toString();
    return requestJson<{ archived_tasks: ArchivedTaskSummary[] }>(
      `${CORE_BASE}/api/projects/archived-tasks${qs ? `?${qs}` : ''}`
    );
  },

  restoreTask: (taskId: string) =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/tasks/${encodeURIComponent(taskId)}/restore`, {
      method: 'POST',
    }),

  unarchiveProject: (archive_name: string) =>
    requestJson<{ ok: boolean; project: string; restored_rel: string }>(
      `${CORE_BASE}/api/projects/unarchive`,
      {
        method: 'POST',
        body: JSON.stringify({ archive_name }),
      }
    ),

  listTasks: (filters: {
    project?: string;
    department?: string;
    list_name?: string;
    status?: string;
    ai_agent?: string;
  }) => {
    const q = new URLSearchParams();
    if (filters.project) q.set('project', filters.project);
    if (filters.department) q.set('department', filters.department);
    if (filters.list_name) q.set('list_name', filters.list_name);
    if (filters.status) q.set('status', filters.status);
    if (filters.ai_agent) q.set('ai_agent', filters.ai_agent);
    return requestJson<{ tasks: TaskSummary[]; rollup: RollupMetrics }>(
      `${CORE_BASE}/api/tasks?${q.toString()}`
    );
  },

  getTaskDetail: (taskId: string) =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/tasks/${encodeURIComponent(taskId)}`),

  createTask: (payload: {
    title: string;
    project?: string;
    department?: string;
    list?: string;
    status?: TaskStatus;
    priority?: number;
    due_date?: string;
    start_date?: string;
    assignee?: string;
    ai_agent?: string;
    parent_task?: string;
    depends_on?: string[];
    time_estimate_hrs?: number;
    description?: string;
    checklist?: string[];
    tags?: string[];
  }) =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/tasks`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateTask: (
    taskId: string,
    payload: {
      title?: string;
      status?: TaskStatus;
      priority?: number;
      department?: string;
      assignee?: string;
      ai_agent?: string;
      parent_task?: string;
      depends_on?: string[];
      start_date?: string;
      due_date?: string;
      gcal_event_id?: string;
      time_estimate_hrs?: number;
      time_logged_delta?: number;
      description?: string;
      toggle_checklist_index?: number;
      add_checklist_item?: string;
      log_entry?: string;
    }
  ) =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/tasks/${encodeURIComponent(taskId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ task_id: taskId, ...payload }),
    }),

  deleteTask: (taskId: string, permanent = false, actor = 'Jaime') =>
    requestJson<{
      ok: boolean;
      task_id: string;
      project: string;
      mode: 'archived' | 'deleted';
      archived_rel_path: string;
    }>(
      `${CORE_BASE}/api/tasks/${encodeURIComponent(taskId)}?permanent=${
        permanent ? 'true' : 'false'
      }&actor=${encodeURIComponent(actor)}`,
      {
        method: 'DELETE',
      }
    ),

  searchNotes: (query = '', folder = '', tag = '') => {
    const q = new URLSearchParams();
    if (query) q.set('query', query);
    if (folder) q.set('folder', folder);
    if (tag) q.set('tag', tag);
    return requestJson<{ notes: VaultNoteSummary[] }>(`${CORE_BASE}/api/vault/notes?${q.toString()}`);
  },

  readNote: (relPath: string) =>
    requestJson<VaultNoteDetail>(
      `${CORE_BASE}/api/vault/note?path=${encodeURIComponent(relPath)}`
    ),

  writeNote: (
    file_path: string,
    frontmatter: Record<string, unknown>,
    body: string,
    mode: 'overwrite' | 'append' = 'overwrite'
  ) =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/vault/note`, {
      method: 'POST',
      body: JSON.stringify({ file_path, frontmatter, body, mode }),
    }),

  openDailyNote: () =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/vault/daily-note`, { method: 'POST' }),

  getGraph: () => requestJson<GraphData>(`${CORE_BASE}/api/vault/graph`),

  getNoteBacklinks: (relPath: string) =>
    requestJson<{ path: string; count: number; backlinks: NoteBacklinkItem[] }>(
      `${CORE_BASE}/api/vault/backlinks?path=${encodeURIComponent(relPath)}`
    ),

  getVaultStructure: () =>
    requestJson<VaultStructureSnapshot>(`${CORE_BASE}/api/vault/structure`),

  scaffoldVaultSection: (payload: {
    section_name?: string;
    blueprint_key?: string;
    parent_folder?: string;
    icon?: string;
    description?: string;
    collections?: unknown[];
    schema_fields?: string[];
    external_links?: { label: string; url: string }[];
    seed_starters?: boolean;
    is_private?: boolean;
  }) =>
    requestJson<{
      ok: boolean;
      hub_id: string;
      title: string;
      icon: string;
      blueprint_key: string;
      section_rel: string;
      hub_index_rel: string;
      base_rel: string;
      canvas_rel: string;
      template_rel: string;
      collections: VaultCollectionMeta[];
      collection_rels: string[];
      seeded_entry_rels: string[];
      is_private: boolean;
    }>(`${CORE_BASE}/api/vault/sections`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  createVaultSectionEntry: (payload: {
    section_or_folder?: string;
    title: string;
    collection?: string;
    item_type?: string;
    properties?: Record<string, unknown>;
    body?: string;
    checklist?: string[];
    tags?: string[];
    aliases?: string[];
    is_private?: boolean;
  }) =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/vault/sections/entries`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  queryVaultBase: (relPath: string, view = '') => {
    const q = new URLSearchParams();
    q.set('path', relPath);
    if (view) q.set('view', view);
    return requestJson<VaultBaseQueryResult>(`${CORE_BASE}/api/vault/base-query?${q.toString()}`);
  },

  updateNoteFrontmatter: (
    file_path: string,
    updates: Record<string, unknown>,
    remove_keys: string[] = []
  ) =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/vault/note/frontmatter`, {
      method: 'PATCH',
      body: JSON.stringify({ file_path, updates, remove_keys }),
    }),

  renameVaultNote: (payload: {
    src_rel_path: string;
    dest_rel_path: string;
    new_title?: string;
    update_links?: boolean;
  }) =>
    requestJson<{
      ok: boolean;
      old_rel_path: string;
      new_rel_path: string;
      updated_backlink_files: string[];
      note: VaultNoteDetail;
    }>(`${CORE_BASE}/api/vault/note/rename`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getVaultHealth: () => requestJson<VaultHealthReport>(`${CORE_BASE}/api/vault/health`),

  getCalendarEvents: () =>
    requestJson<{ ok: boolean; event_count: number; events: CalendarEventItem[] }>(
      `${CORE_BASE}/api/calendar/events`
    ),

  timeBlockTask: (task_id: string, start_time_iso: string, duration_hrs?: number, category = 'Business') =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/calendar/time-block`, {
      method: 'POST',
      body: JSON.stringify({ task_id, start_time_iso, duration_hrs, category }),
    }),

  createCalendarEvent: (payload: {
    title: string;
    start_time_iso: string;
    duration_hrs?: number;
    category?: string;
    project?: string;
    notes?: string;
  }) =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/calendar/events`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateCalendarEvent: (
    eventId: string,
    payload: {
      new_date_iso?: string;
      start_time_iso?: string;
      duration_hrs?: number;
      title?: string;
      category?: string;
    }
  ) =>
    requestJson<VaultNoteDetail>(
      `${CORE_BASE}/api/calendar/events/${encodeURIComponent(eventId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(payload),
      }
    ),

  deleteCalendarEvent: (eventId: string) =>
    requestJson<{ ok: boolean; deleted_id: string; rel_path: string }>(
      `${CORE_BASE}/api/calendar/events/${encodeURIComponent(eventId)}`,
      {
        method: 'DELETE',
      }
    ),

  clipWebpage: (url: string, title = '', dest_folder = '00_Inbox', html_or_text = '') =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/browser/clip`, {
      method: 'POST',
      body: JSON.stringify({ url, title, dest_folder, html_or_text }),
    }),

  getPaperclipStatus: () =>
    requestJson<{
      paperclip: PaperclipSnapshot;
      audit_logs: Record<string, unknown>[];
      hermes?: HermesStatusSnapshot;
    }>(`${CORE_BASE}/api/paperclip/status`),

  getHermesStatus: () => requestJson<HermesStatusSnapshot>(`${CORE_BASE}/api/hermes/status`),

  retainHermesMemory: (payload: {
    fact: string;
    target?: 'memory' | 'user';
    section?: string;
    is_private?: boolean;
  }) =>
    requestJson<{
      ok: boolean;
      rel_path: string;
      target: string;
      retained: string;
      privacy_locked?: boolean;
      archived_overflow_count?: number;
    }>(`${CORE_BASE}/api/hermes/retain`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  createHermesSkill: (payload: {
    title: string;
    category?: string;
    trigger?: string;
    steps_markdown?: string;
    source_task_id?: string;
    project?: string;
    is_private?: boolean;
  }) =>
    requestJson<{
      ok: boolean;
      skill_id: string;
      title: string;
      rel_path: string;
      privacy_locked: boolean;
    }>(`${CORE_BASE}/api/hermes/skills`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  distillTaskWithHermes: (task_id: string) =>
    requestJson<{
      ok: boolean;
      skill_id: string;
      title: string;
      rel_path: string;
      privacy_locked: boolean;
    }>(`${CORE_BASE}/api/hermes/distill-task`, {
      method: 'POST',
      body: JSON.stringify({ task_id }),
    }),

  dispatchCrew: (task_id: string, crew_name: string, reference_url = '') =>
    requestJson<{ status: string; task_id: string; crew: string }>(
      `${CORE_BASE}/api/paperclip/dispatch-crew`,
      {
        method: 'POST',
        body: JSON.stringify({ task_id, crew_name, reference_url }),
      }
    ),

  releasePaperclipLock: (taskId: string, reason = 'Manual operator force-unlock', actor = 'Jaime') =>
    requestJson<{
      ok: boolean;
      released: boolean;
      task_id: string;
      previous_agent?: string;
      elapsed_sec?: number;
      actor?: string;
      reason?: string;
    }>(`${CORE_BASE}/api/paperclip/locks/${encodeURIComponent(taskId)}/release`, {
      method: 'POST',
      body: JSON.stringify({ actor, reason }),
    }),

  // KAIROS Conversational Virtual Assistant APIs
  listAssistantSessions: () =>
    requestJson<{ sessions: AssistantSessionSummary[] }>(`${CORE_BASE}/api/assistant/sessions`),

  listArchivedAssistantSessions: () =>
    requestJson<{ sessions: AssistantSessionSummary[] }>(
      `${CORE_BASE}/api/assistant/archived-sessions`
    ),

  restoreAssistantSession: (sessionId: string) =>
    requestJson<AssistantSessionDetail>(
      `${CORE_BASE}/api/assistant/sessions/${encodeURIComponent(sessionId)}/restore`,
      {
        method: 'POST',
      }
    ),

  createAssistantSession: (payload: {
    title?: string;
    persona?: PersonaRole;
    tone_mode?: ToneMode;
  }) =>
    requestJson<AssistantSessionDetail>(`${CORE_BASE}/api/assistant/sessions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getAssistantSession: (sessionId: string) =>
    requestJson<AssistantSessionDetail>(
      `${CORE_BASE}/api/assistant/sessions/${encodeURIComponent(sessionId)}`
    ),

  renameAssistantSession: (sessionId: string, title: string) =>
    requestJson<AssistantSessionDetail>(
      `${CORE_BASE}/api/assistant/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      }
    ),

  deleteAssistantSession: (sessionId: string, permanent = false) =>
    requestJson<{
      ok: boolean;
      session_id: string;
      mode: 'archived' | 'deleted';
      archived_rel_path: string;
    }>(
      `${CORE_BASE}/api/assistant/sessions/${encodeURIComponent(sessionId)}?permanent=${
        permanent ? 'true' : 'false'
      }`,
      {
        method: 'DELETE',
      }
    ),

  sendAssistantChat: (payload: {
    prompt: string;
    session_id?: string;
    mode: BrainMode;
    persona?: PersonaRole;
    tone_mode?: ToneMode;
    active_note_path?: string;
    active_task_id?: string;
    active_browser_url?: string;
    active_browser_title?: string;
    image_data_url?: string;
    project_scope?: string;
    department_scope?: string;
    current_tab?: string;
    current_view?: string;
  }) =>
    requestJson<AssistantChatResponse>(`${CORE_BASE}/api/assistant/chat`, {
      method: 'POST',
      body: JSON.stringify(payload),
      timeoutMs: 65000,
    }),

  sendKairosCommand: (
    prompt: string,
    mode: BrainMode,
    active_note_path = '',
    extra?: {
      session_id?: string;
      persona?: PersonaRole;
      tone_mode?: ToneMode;
      active_task_id?: string;
      active_browser_url?: string;
      active_browser_title?: string;
      image_data_url?: string;
      project_scope?: string;
      department_scope?: string;
      current_tab?: string;
      current_view?: string;
    }
  ) =>
    requestJson<AssistantChatResponse>(`${CORE_BASE}/api/kairos/command`, {
      method: 'POST',
      body: JSON.stringify({
        prompt,
        mode,
        active_note_path,
        ...extra,
      }),
      timeoutMs: 65000,
    }),

  voiceAction: (action: 'play' | 'pause' | 'stop' | 'extend-hold') =>
    requestJson<VoiceStateSnapshot>(`${VOICE_BASE}/api/voice/${action}`, { method: 'POST' }),

  triggerVoiceBargeIn: () =>
    requestJson<VoiceStateSnapshot>(`${VOICE_BASE}/api/voice/barge-in`, { method: 'POST' }),

  getVoiceState: () =>
    requestJson<VoiceStateSnapshot>(`${VOICE_BASE}/api/voice/state`, { timeoutMs: 8000 }),

  updateVoiceConfig: (payload: {
    hands_free?: boolean;
    wake_word_only?: boolean;
    neural_tts?: boolean;
    hold_seconds?: number;
    tts_voice?: string;
  }) =>
    requestJson<VoiceStateSnapshot>(`${VOICE_BASE}/api/voice/config`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  sendVoiceAudioCommand: (payload: {
    audio_base64: string;
    mime_type: string;
    mode: BrainMode;
    active_note_path?: string;
    active_task_id?: string;
    active_browser_url?: string;
    active_browser_title?: string;
    session_id?: string;
    persona?: PersonaRole;
    tone_mode?: ToneMode;
    project_scope?: string;
    department_scope?: string;
    current_tab?: string;
    current_view?: string;
    synthesize_speech?: boolean;
  }) =>
    requestJson<VoiceAudioCommandResponse>(`${VOICE_BASE}/api/voice/audio-command`, {
      method: 'POST',
      body: JSON.stringify(payload),
      timeoutMs: 65000,
    }),

  synthesizeVoiceTts: (payload: {
    text: string;
    active_note_path?: string;
    is_private?: boolean;
    voice?: string;
  }) =>
    requestJson<VoiceTtsPayload>(`${VOICE_BASE}/api/voice/tts`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  createProjectStructure: (
    project: string,
    department = 'Software_Development',
    list_name = 'Sprint_01',
    scaffold_standard_departments = true
  ) =>
    requestJson<{
      project: string;
      department: string;
      list: string;
      project_index_rel: string;
      canvas_rel?: string;
      list_index_rel: string;
    }>(`${CORE_BASE}/api/projects/structure`, {
      method: 'POST',
      body: JSON.stringify({
        project,
        department,
        list_name,
        scaffold_standard_departments,
      }),
    }),

  createProjectTasksBase: (project: string) =>
    requestJson<{
      ok: boolean;
      project: string;
      base_rel_path: string;
      note: VaultNoteDetail;
    }>(`${CORE_BASE}/api/projects/${encodeURIComponent(project)}/base`, {
      method: 'POST',
    }),

  archiveProject: (project: string, department = '') =>
    requestJson<{ ok: boolean; archived_rel: string }>(`${CORE_BASE}/api/projects/archive`, {
      method: 'POST',
      body: JSON.stringify({ project, department }),
    }),

  moveInboxNote: (src_rel_path: string, dest_folder: string) =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/inbox/move`, {
      method: 'POST',
      body: JSON.stringify({ src_rel_path, dest_folder }),
    }),

  promoteInboxNote: (payload: {
    src_rel_path: string;
    project?: string;
    department?: string;
    list_name?: string;
    priority?: number;
    ai_agent?: string;
  }) =>
    requestJson<{ task: VaultNoteDetail; archived_capture: string }>(
      `${CORE_BASE}/api/inbox/promote`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    ),

  promoteInboxToSection: (payload: {
    src_rel_path: string;
    section_or_folder?: string;
    collection?: string;
    item_type?: string;
    vendor?: string;
    properties?: Record<string, unknown>;
  }) =>
    requestJson<{
      entry: VaultNoteDetail;
      archived_capture: string;
      extracted_url: string;
    }>(`${CORE_BASE}/api/inbox/promote-to-section`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  linkGoogleDoc: (note_path: string, google_doc_url: string, pull_summary = false) =>
    requestJson<VaultNoteDetail>(`${CORE_BASE}/api/connectors/gsuite-link`, {
      method: 'POST',
      body: JSON.stringify({ note_path, google_doc_url, pull_summary }),
    }),

  syncGitHubRepo: (repo_name: string, action: 'status' | 'pull' = 'status') =>
    requestJson<{ ok: boolean; repo: string; action?: string; output?: string; message?: string }>(
      `${CORE_BASE}/api/connectors/github-sync`,
      {
        method: 'POST',
        body: JSON.stringify({ repo_name, action }),
      }
    ),

  listGitHubOrgRepos: (org = 'ForestCityCreatorsLLC') =>
    requestJson<{
      ok: boolean;
      org: string;
      org_url: string;
      authenticated_pat: boolean;
      browser_env_login_configured: boolean;
      api_status: string;
      repo_count: number;
      private_count: number;
      repos: {
        name: string;
        full_name: string;
        html_url: string;
        description: string;
        private: boolean;
        visibility: string;
        language: string;
        default_branch: string;
        updated_at: string;
      }[];
    }>(`${CORE_BASE}/api/connectors/github-org-repos?org=${encodeURIComponent(org)}`),

  syncGitHubOrgToVault: (org = 'ForestCityCreatorsLLC') =>
    requestJson<{
      ok: boolean;
      org: string;
      org_url: string;
      authenticated_pat: boolean;
      browser_env_login_configured: boolean;
      api_status: string;
      repo_count: number;
      private_count: number;
      catalog_rel_path: string;
      note: VaultNoteDetail;
      repos: {
        name: string;
        full_name: string;
        html_url: string;
        description: string;
        private: boolean;
        visibility: string;
        language: string;
        default_branch: string;
        updated_at: string;
      }[];
    }>(`${CORE_BASE}/api/connectors/github-org-sync`, {
      method: 'POST',
      body: JSON.stringify({ org }),
    }),

  syncCodeChangesToVault: (summary = '') =>
    requestJson<{
      ok: boolean;
      ledger_updated: boolean;
      ledger_rel_path: string;
      added: string[];
      modified: string[];
      deleted: string[];
      tracked_file_count: number;
    }>(`${CORE_BASE}/api/vault/sync-code-changes`, {
      method: 'POST',
      body: JSON.stringify({ summary, actor: 'UI-Sync' }),
    }),

  getCognitiveVoiceTelemetry: () =>
    requestJson<{
      ok: boolean;
      kv_prefix_pinned: boolean;
      cloud_circuit_breaker_sec: number;
      lag_threshold_sec: number;
      prefill_watchdog_sec: number;
      thought_cadence_sec: number;
      vram_envelope: {
        gpu_envelope_gb: number;
        vram_ceiling_gb: number;
        active_resident_vram_gb: number;
        full_stack_budget_gb: number;
        dwm_safety_headroom_gb: number;
        headroom_gb: number;
        within_vram_ceiling: boolean;
        components_gb: Record<string, number>;
      };
      episodic_memory: {
        device: string;
        gpu_vram_mb: number;
        last_query_ms: number;
        db_path: string;
      };
      local_kv_stats: {
        last_ttft_ms: number;
        last_cache_hit_ratio: number;
      };
      voice_tools: string[];
    }>(`${CORE_BASE}/api/voice/cognitive-telemetry`),

  verifyLmStudioKvCache: () =>
    requestJson<{
      ok: boolean;
      online: boolean;
      model: string;
      warmed_ttft_ms: number | null;
      meets_150ms_sla: boolean;
      cache_hit_ratio?: number;
      index_0_pinned: boolean;
      total_handshake_ms?: number;
      error?: string;
    }>(`${CORE_BASE}/api/voice/verify-kv-cache`, {
      method: 'POST',
    }),
};

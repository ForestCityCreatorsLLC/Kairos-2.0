"""FastAPI + WebSocket Core Server (`api.py` on port `8420`).

Connects the React/Electron Desktop UI and KAIROS Voice Sidecar to:
- Canopy Vault (`VaultEngine` + `ShadowIndex`)
- Full Internal Projects Operations (`Project -> Department -> List/Sprint`, Kanban, Gantt, Time Tracking, Rollups)
- Conversational KAIROS Virtual Assistant (`KairosAssistant` — Personas, Tone Matrix, Vault Sessions & Live APIs)
- Dual-AI Router (`Gemma 4` local + `Gemini` cloud with smart non-private failover)
- Paperclip Atomic Task Broker + CrewAI Multi-Agent Workflows
- `.env` API Key & Live Endpoint Verifier
"""

from __future__ import annotations

import asyncio
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from services.kairos_core.assistant import PERSONA_METADATA
from services.kairos_core.config import PROJECT_ROOT, settings
from services.kairos_core.env_verifier import verify_env_apis
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.net_guard import (
    SSRFBlockedError,
    safe_fetch_public_text,
    validate_entity_id,
    validate_public_http_url,
)
from services.kairos_core.paperclip_crew import PaperclipLockConflictError
from services.kairos_core.schemas import (
    CreateTaskInput,
    InboxCaptureInput,
    PromoteInboxToSectionInput,
    RenameVaultNoteInput,
    UpdateNoteFrontmatterInput,
    UpdateTaskInput,
    VaultSectionEntryInput,
    VaultSectionScaffoldInput,
    WriteNoteInput,
)
from services.kairos_core.tool_registry import get_vram_envelope_telemetry
from services.kairos_core.vault_sync_hook import sync_codebase_changes_to_vault
from services.kairos_core.watcher import VaultWatcherDaemon

_ws_clients: List[WebSocket] = []
_ws_lock = threading.RLock()
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_bundle = create_mcp_bundle()


def _broadcast_from_thread(payload: Dict[str, Any]) -> None:
    if _event_loop is None:
        return
    with _ws_lock:
        targets = list(_ws_clients)
    for ws in targets:
        asyncio.run_coroutine_threadsafe(_safe_ws_send(ws, payload), _event_loop)


async def _safe_ws_send(ws: WebSocket, payload: Dict[str, Any]) -> None:
    try:
        await ws.send_json(payload)
    except Exception:
        with _ws_lock:
            if ws in _ws_clients:
                _ws_clients.remove(ws)


_bundle["assistant"].on_broadcast = _broadcast_from_thread

_watcher = VaultWatcherDaemon(
    _bundle["vault"],
    _bundle["index"],
    _bundle["crew"],
    on_change_broadcast=_broadcast_from_thread,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    if _bundle["vault"].vault_path == settings.vault_path.resolve():
        try:
            sync_codebase_changes_to_vault(
                _bundle["vault"],
                _bundle["index"],
                _bundle["router"],
                actor="KAIROS-BootSync",
            )
        except Exception:
            pass
    _watcher.start()
    yield
    _watcher.stop()


app = FastAPI(title="KAIROS 2.0 Core API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https?://(127\.0\.0\.1|localhost)(:\d+)?|app://.*)$",
    allow_methods=["*"],
    allow_headers=["*"],
)


class KairosCommandRequest(BaseModel):
    prompt: str
    mode: str = "auto"
    active_note_path: str = ""
    active_task_id: str = ""
    active_browser_url: str = ""
    active_browser_title: str = ""
    session_id: str = ""
    persona: str = "companion"
    tone_mode: str = "DEFAULT"
    project_scope: str = "KAIROS_2_0"
    department_scope: str = "Software_Development"
    current_tab: str = ""
    current_view: str = ""


class AssistantCreateSessionRequest(BaseModel):
    title: str = ""
    persona: str = "companion"
    tone_mode: str = "DEFAULT"


class AssistantRenameSessionRequest(BaseModel):
    title: str


class AssistantChatRequest(BaseModel):
    prompt: str
    session_id: str = ""
    mode: str = "auto"
    persona: str = "companion"
    tone_mode: str = "DEFAULT"
    active_note_path: str = ""
    active_task_id: str = ""
    active_browser_url: str = ""
    active_browser_title: str = ""
    project_scope: str = "KAIROS_2_0"
    department_scope: str = "Software_Development"
    current_tab: str = ""
    current_view: str = ""


class CrewDispatchRequest(BaseModel):
    task_id: str
    crew_name: str = "CrewAI-Research"
    reference_url: str = ""


class PaperclipReleaseLockRequest(BaseModel):
    actor: str = "Jaime"
    reason: str = "Manual operator force-unlock"


class BrowserClipRequest(BaseModel):
    url: str
    html_or_text: str = ""
    title: str = ""
    dest_folder: str = "00_Inbox"


class TimeBlockRequest(BaseModel):
    task_id: str
    start_time_iso: str
    duration_hrs: Optional[float] = None
    category: str = "Business"


class ProjectStructureRequest(BaseModel):
    project: str
    department: str = "Software_Development"
    list_name: str = "Sprint_01"
    scaffold_standard_departments: bool = True


class ProjectArchiveRequest(BaseModel):
    project: str
    department: str = ""


class ProjectUnarchiveRequest(BaseModel):
    archive_name: str


class StandaloneCalendarEventRequest(BaseModel):
    title: str
    start_time_iso: str
    duration_hrs: float = 1.0
    category: str = "Business"
    project: str = ""
    notes: str = ""


class UpdateCalendarEventRequest(BaseModel):
    new_date_iso: str = ""
    start_time_iso: str = ""
    duration_hrs: Optional[float] = None
    title: Optional[str] = None
    category: Optional[str] = None


class HermesRetainRequest(BaseModel):
    fact: str
    target: str = "memory"
    section: str = ""
    is_private: bool = False


class HermesCreateSkillRequest(BaseModel):
    title: str
    category: str = "Workflow"
    trigger: str = ""
    steps_markdown: str = ""
    source_task_id: str = ""
    project: str = ""
    is_private: bool = False


class HermesDistillTaskRequest(BaseModel):
    task_id: str


class InboxMoveRequest(BaseModel):
    src_rel_path: str
    dest_folder: str


class InboxPromoteRequest(BaseModel):
    src_rel_path: str
    project: str = "KAIROS_2_0"
    department: str = "Software_Development"
    list_name: str = "Sprint_01"
    priority: int = 2
    ai_agent: str = "None"


class GSuiteLinkRequest(BaseModel):
    note_path: str
    google_doc_url: str
    pull_summary: bool = False


class GitHubSyncRequest(BaseModel):
    repo_name: str
    action: str = "status"


class GitHubOrgSyncRequest(BaseModel):
    org: str = "ForestCityCreatorsLLC"


class VaultCodeSyncRequest(BaseModel):
    summary: str = ""
    actor: str = "KAIROS-ManualSync"


@app.get("/api/health")
def get_health() -> Dict[str, Any]:
    vault = _bundle["vault"]
    index = _bundle["index"]
    paperclip = _bundle["paperclip"]
    hermes = _bundle.get("hermes")
    hermes_skills = len(hermes.list_skills(allow_private=True)) if hermes is not None else 0
    return {
        "status": "online",
        "version": "2.0.0",
        "operator_name": settings.operator_name,
        "project_root": str(PROJECT_ROOT),
        "vault_path": str(vault.vault_path),
        "vault_exists": vault.vault_path.exists(),
        "lmstudio_model": settings.lmstudio_model,
        "lmstudio_url": settings.lmstudio_base_url,
        "gemini_configured": bool(settings.gemini_api_key),
        "gemini_model": settings.gemini_model,
        "rollup": index.get_rollup(),
        "paperclip": paperclip.get_snapshot(),
        "hermes_skill_count": hermes_skills,
        "kv_prefix_pinned": True,
        "vram_envelope": get_vram_envelope_telemetry(cfg=settings),
    }


@app.get("/api/voice/cognitive-telemetry")
def get_cognitive_voice_telemetry() -> Dict[str, Any]:
    """Return 16 GB RTX 5070 Ti VRAM envelope, KV cache pinning state, CPU episodic store stats & voice tools."""
    assistant = _bundle["assistant"]
    router = _bundle["router"]
    vec_store = assistant.cognitive_state.vector_store
    return {
        "ok": True,
        "kv_prefix_pinned": True,
        "cloud_circuit_breaker_sec": settings.cloud_timeout_sec,
        "lag_threshold_sec": settings.lag_threshold_sec,
        "prefill_watchdog_sec": settings.prefill_watchdog_sec,
        "thought_cadence_sec": settings.thought_cadence_sec,
        "vram_envelope": get_vram_envelope_telemetry(cfg=settings),
        "episodic_memory": {
            "device": "cpu",
            "gpu_vram_mb": 0,
            "last_query_ms": vec_store.last_query_ms,
            "db_path": str(vec_store.db_path),
        },
        "local_kv_stats": {
            "last_ttft_ms": router.local_llm.last_ttft_ms,
            "last_cache_hit_ratio": router.local_llm.last_cache_hit_ratio,
        },
        "voice_tools": [t.name for t in assistant.voice_tools.schema.standard_tools],
    }


@app.post("/api/voice/verify-kv-cache")
def post_verify_kv_cache() -> Dict[str, Any]:
    """Execute 2-turn LM Studio KV prefix cache handshake and report TTFT & cached token ratio."""
    return _bundle["router"].local_llm.verify_lm_studio_kv_cache()


@app.get("/api/settings/verify-apis")
def get_verified_apis(live: bool = False) -> Dict[str, Any]:
    """Audit `.env` API keys (masked) and optionally run live endpoint connectivity handshakes."""
    return verify_env_apis(settings, live=live)


@app.get("/api/projects/tree")
def get_projects_tree() -> Dict[str, Any]:
    return {
        "projects": _bundle["index"].get_projects_hierarchy(),
        "rollup": _bundle["index"].get_rollup(),
        "archived_projects": _bundle["vault"].list_archived_projects(),
    }


@app.post("/api/projects/resync")
def resync_projects_tree() -> Dict[str, Any]:
    """Force an immediate full rebuild of `ShadowIndex` from `02_Projects/` on disk."""
    count = _bundle["index"].rebuild_all()
    _broadcast_from_thread({"event": "projects_resynced", "indexed_files": count})
    return {
        "indexed_files": count,
        "projects": _bundle["index"].get_projects_hierarchy(),
        "rollup": _bundle["index"].get_rollup(),
        "archived_projects": _bundle["vault"].list_archived_projects(),
    }


@app.get("/api/projects/archived")
def get_archived_projects() -> Dict[str, Any]:
    return {"archived_projects": _bundle["vault"].list_archived_projects()}


@app.get("/api/projects/archived-tasks")
def get_archived_tasks(project: str = "") -> Dict[str, Any]:
    return {"archived_tasks": _bundle["vault"].list_archived_tasks(project=project)}


@app.post("/api/projects/unarchive")
def unarchive_project_endpoint(req: ProjectUnarchiveRequest) -> Dict[str, Any]:
    restored = _bundle["vault"].unarchive_project(req.archive_name)
    if restored is None:
        raise HTTPException(status_code=404, detail=f"Archived project '{req.archive_name}' not found")
    _bundle["index"].rebuild_all()
    rel = _bundle["vault"].to_rel_path(restored)
    _broadcast_from_thread({"event": "project_restored", "restored_rel": rel, "project": restored.name})
    return {"ok": True, "project": restored.name, "restored_rel": rel}


@app.get("/api/tasks")
def list_tasks(
    project: str = "",
    department: str = "",
    list_name: str = "",
    status: str = "",
    ai_agent: str = "",
) -> Dict[str, Any]:
    tasks = _bundle["index"].list_tasks(
        project=project,
        department=department,
        list_name=list_name,
        status=status,
        ai_agent=ai_agent,
    )
    rollup = _bundle["index"].get_rollup(
        project=project,
        department=department,
        list_name=list_name,
    )
    return {"tasks": tasks, "rollup": rollup}


@app.get("/api/tasks/{task_id}")
def get_task_detail(task_id: str) -> Dict[str, Any]:
    try:
        p = _bundle["vault"].find_task_file(task_id)
        return _bundle["vault"].read_note(_bundle["vault"].to_rel_path(p))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/tasks")
def create_task(req: CreateTaskInput) -> Dict[str, Any]:
    created = _bundle["vault"].create_task(req)
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(created["rel_path"]))
    _broadcast_from_thread({"event": "task_created", "task_id": created["frontmatter"]["id"]})
    if req.ai_agent.startswith(("CrewAI", "Hermes")):
        crew_svc = _bundle["crew"]
        idx_svc = _bundle["index"]
        vault_svc = _bundle["vault"]
        tid_created = created["frontmatter"]["id"]

        def _auto_crew_worker() -> None:
            try:
                res = crew_svc.execute_task_with_crew(tid_created, req.ai_agent)
                for key in ("artifact_rel_path", "hermes_skill_rel_path", "clipped_rel_path"):
                    rel_out = res.get(key)
                    if rel_out:
                        idx_svc.index_file(vault_svc.resolve_safe_path(str(rel_out)))
                try:
                    idx_svc.index_file(vault_svc.find_task_file(tid_created))
                except FileNotFoundError:
                    pass
                _broadcast_from_thread(
                    {"event": "crew_completed", "task_id": tid_created, "crew": req.ai_agent}
                )
            except Exception as exc:
                _broadcast_from_thread(
                    {"event": "crew_error", "task_id": tid_created, "error": str(exc)}
                )

        threading.Thread(target=_auto_crew_worker, daemon=True).start()
    return created


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, req: UpdateTaskInput) -> Dict[str, Any]:
    req.task_id = task_id
    active_lock = _bundle["paperclip"].get_active_lock(task_id)
    if active_lock is not None and req.actor != active_lock.get("agent"):
        raise HTTPException(
            status_code=409,
            detail=f"Paperclip Lock Conflict: `{task_id}` is currently checked out by `{active_lock['agent']}`",
        )
    try:
        old_path = _bundle["vault"].find_task_file(task_id)
        updated = _bundle["vault"].update_task(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    new_path = _bundle["vault"].resolve_safe_path(updated["rel_path"])
    if old_path.resolve() != new_path.resolve():
        _bundle["index"].remove_path(old_path)
    _bundle["index"].index_file(new_path)
    _broadcast_from_thread({"event": "task_updated", "task_id": task_id})
    return updated


@app.delete("/api/tasks/{task_id}")
def delete_or_archive_task_endpoint(
    task_id: str,
    permanent: bool = False,
    actor: str = "Jaime",
) -> Dict[str, Any]:
    active_lock = _bundle["paperclip"].get_active_lock(task_id)
    if active_lock is not None and actor != active_lock.get("agent"):
        raise HTTPException(
            status_code=409,
            detail=f"Paperclip Lock Conflict: `{task_id}` is currently checked out by `{active_lock['agent']}`",
        )
    try:
        old_path = _bundle["vault"].find_task_file(task_id)
        proj_folder = _bundle["vault"]._find_parent_project_folder(old_path)
        res = _bundle["vault"].delete_or_archive_task(
            task_id, permanent=permanent, actor=actor
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _bundle["index"].remove_file(old_path)
    if res.get("archived_rel_path"):
        _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(res["archived_rel_path"]))
    if proj_folder is not None and proj_folder.exists():
        for sib in proj_folder.rglob("TSK-*.md"):
            _bundle["index"].index_file(sib)
        proj_idx = proj_folder / "_Project_Index.md"
        if proj_idx.is_file():
            _bundle["index"].index_file(proj_idx)

    _broadcast_from_thread(
        {
            "event": "task_deleted" if permanent else "task_archived",
            "task_id": res["task_id"],
            "mode": res["mode"],
        }
    )
    return res


@app.post("/api/tasks/{task_id}/restore")
def restore_archived_task_endpoint(task_id: str, actor: str = "Jaime") -> Dict[str, Any]:
    try:
        restored = _bundle["vault"].restore_archived_task(task_id, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    old_arch_rel = str(restored.get("old_archived_rel_path") or "")
    if old_arch_rel:
        _bundle["index"].remove_file(_bundle["vault"].resolve_safe_path(old_arch_rel))
    new_abs = _bundle["vault"].resolve_safe_path(restored["rel_path"])
    _bundle["index"].index_file(new_abs)
    proj_folder = _bundle["vault"]._find_parent_project_folder(new_abs)
    if proj_folder is not None and (proj_folder / "_Project_Index.md").is_file():
        _bundle["index"].index_file(proj_folder / "_Project_Index.md")
    _broadcast_from_thread({"event": "task_restored", "task_id": restored["task_id"]})
    return restored


@app.get("/api/vault/notes")
def search_notes(query: str = "", folder: str = "", tag: str = "") -> Dict[str, Any]:
    tags = [tag] if tag.strip() else None
    notes = _bundle["index"].search_vault(query=query, folder=folder, tags=tags, limit=120)
    return {"notes": notes}


@app.get("/api/vault/note")
def read_note(
    path: Optional[str] = Query(default=None),
    rel_path: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    eff_path = path if path is not None else rel_path
    if eff_path is None:
        raise HTTPException(status_code=422, detail="Query parameter 'path' is required")
    try:
        return _bundle["vault"].read_note(eff_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/vault/note")
def write_note(req: WriteNoteInput) -> Dict[str, Any]:
    try:
        target = _bundle["vault"].resolve_safe_path(req.file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Enforce Paperclip checkout lock if writing directly to an active TSK-*.md file
    m_tsk = re.match(r"^(TSK-\d{8}-\d{3})\b", target.stem, flags=re.IGNORECASE)
    candidate_tid = m_tsk.group(1).upper() if m_tsk else str((req.frontmatter or {}).get("id") or "").strip().upper()
    if candidate_tid and re.match(r"^TSK-\d{8}-\d{3}$", candidate_tid):
        active_lock = _bundle["paperclip"].get_active_lock(candidate_tid)
        if active_lock is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Paperclip Lock Conflict: `{candidate_tid}` is currently checked out by "
                    f"`{active_lock['agent']}`"
                ),
            )

    try:
        saved = _bundle["vault"].write_note(req.file_path, req.frontmatter, req.body, mode=req.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(saved["rel_path"]))
    _broadcast_from_thread({"event": "note_saved", "rel_path": saved["rel_path"]})
    return saved


@app.post("/api/vault/daily-note")
def open_or_create_daily_note() -> Dict[str, Any]:
    today = datetime.now().strftime("%Y-%m-%d")
    rel = f"03_Personal/Calendar/{today}.md"
    target = _bundle["vault"].resolve_safe_path(rel)
    if not target.exists():
        _bundle["vault"].write_note(
            rel,
            {"title": f"Daily System Note — {today}", "type": "daily", "date": today, "tags": ["daily-note"]},
            (
                f"# 📅 Daily System Note — {today}\n\n"
                f"> [!IMPORTANT] Top 3 Executive Priorities\n"
                f"> - [ ] Review active Project tasks across `02_Projects/KAIROS_2_0/`\n"
                f"> - [ ] Triage `00_Inbox/` captures\n"
                f"> - [ ] Check in with KAIROS Virtual Assistant\n\n"
                f"## 🧠 Notes & Links\n- Connected to [[AGENTS]]\n"
            ),
        )
        _bundle["index"].index_file(target)
    return _bundle["vault"].read_note(rel)


@app.get("/api/vault/graph")
def get_second_brain_graph() -> Dict[str, Any]:
    return _bundle["index"].get_graph_data()


@app.get("/api/vault/backlinks")
def get_note_backlinks(
    path: Optional[str] = Query(default=None),
    rel_path: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    eff_path = path if path is not None else rel_path
    if eff_path is None:
        raise HTTPException(status_code=422, detail="Query parameter 'path' is required")
    items = _bundle["index"].get_backlinks(eff_path)
    return {"path": eff_path, "count": len(items), "backlinks": items}


@app.get("/api/vault/structure")
def get_vault_structure() -> Dict[str, Any]:
    """Return all auto-discovered Section Hubs, Collections, Folders, `.base` Catalogs, `.canvas` Maps & Blueprints."""
    return _bundle["index"].discover_vault_structure()


@app.post("/api/vault/sections")
def post_scaffold_vault_section(req: VaultSectionScaffoldInput) -> Dict[str, Any]:
    """Scaffold or expand an Obsidian Section Hub (`_Hub_Index.md` + `.base` + `.canvas` + Collections + Templates)."""
    if not req.section_name.strip() and req.blueprint_key.strip().lower() in ("", "auto", "custom"):
        raise HTTPException(
            status_code=400,
            detail="Provide `section_name` or select a built-in `blueprint_key`.",
        )
    try:
        res = _bundle["vault"].scaffold_vault_section(
            req.section_name,
            blueprint_key=req.blueprint_key,
            parent_folder=req.parent_folder,
            icon=req.icon,
            description=req.description,
            collections=req.collections or None,
            schema_fields=req.schema_fields or None,
            external_links=req.external_links or None,
            seed_starters=req.seed_starters,
            is_private=req.is_private,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _bundle["index"].rebuild_all()
    _broadcast_from_thread(
        {
            "event": "vault_section_scaffolded",
            "section_rel": res["section_rel"],
            "hub_index_rel": res["hub_index_rel"],
        }
    )
    return res


@app.post("/api/vault/sections/entries")
def post_create_vault_section_entry(req: VaultSectionEntryInput) -> Dict[str, Any]:
    """Create a structured Obsidian catalog entry inside a Vault Section Hub or subfolder."""
    try:
        saved = _bundle["vault"].create_section_entry(
            section_or_folder=req.section_or_folder,
            title=req.title,
            collection=req.collection,
            item_type=req.item_type,
            properties=req.properties,
            body=req.body,
            checklist=req.checklist,
            tags=req.tags,
            aliases=req.aliases,
            is_private=req.is_private,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(saved["rel_path"]))
    _broadcast_from_thread({"event": "note_saved", "rel_path": saved["rel_path"]})
    return saved


@app.get("/api/vault/base-query")
def get_vault_base_query(
    path: Optional[str] = Query(default=None),
    rel_path: Optional[str] = Query(default=None),
    view: str = "",
) -> Dict[str, Any]:
    """Evaluate an Obsidian `.base` database YAML file against the live ShadowIndex."""
    eff_path = path if path is not None else rel_path
    if eff_path is None:
        raise HTTPException(status_code=422, detail="Query parameter 'path' is required")
    try:
        return _bundle["index"].evaluate_base(eff_path, view_name=view)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/vault/note/frontmatter")
def patch_vault_note_frontmatter(req: UpdateNoteFrontmatterInput) -> Dict[str, Any]:
    """Atomically patch or remove YAML frontmatter properties on an Obsidian Markdown note."""
    try:
        target = _bundle["vault"].resolve_safe_path(req.file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    m_tsk = re.match(r"^(TSK-\d{8}-\d{3})\b", target.stem, flags=re.IGNORECASE)
    if m_tsk:
        candidate_tid = m_tsk.group(1).upper()
        active_lock = _bundle["paperclip"].get_active_lock(candidate_tid)
        if active_lock is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Paperclip Lock Conflict: `{candidate_tid}` is currently checked out by "
                    f"`{active_lock['agent']}`"
                ),
            )

    try:
        saved = _bundle["vault"].update_note_frontmatter(
            req.file_path,
            updates=req.updates,
            remove_keys=req.remove_keys,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(saved["rel_path"]))
    _broadcast_from_thread({"event": "note_saved", "rel_path": saved["rel_path"]})
    return saved


@app.post("/api/vault/note/rename")
def post_rename_vault_note(req: RenameVaultNoteInput) -> Dict[str, Any]:
    """Link-safe rename/move of a Vault note with automatic `[[WikiLink]]` and `.canvas` reference refactoring."""
    try:
        src_target = _bundle["vault"].resolve_safe_path(req.src_rel_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    m_tsk = re.match(r"^(TSK-\d{8}-\d{3})\b", src_target.stem, flags=re.IGNORECASE)
    if m_tsk:
        candidate_tid = m_tsk.group(1).upper()
        active_lock = _bundle["paperclip"].get_active_lock(candidate_tid)
        if active_lock is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Paperclip Lock Conflict: `{candidate_tid}` is currently checked out by "
                    f"`{active_lock['agent']}`"
                ),
            )

    try:
        res = _bundle["vault"].rename_or_move_note(
            req.src_rel_path,
            req.dest_rel_path,
            new_title=req.new_title,
            update_links=req.update_links,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _bundle["index"].remove_file(src_target)
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(res["new_rel_path"]))
    for updated_rel in res.get("updated_backlink_files") or []:
        _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(updated_rel))

    _broadcast_from_thread(
        {
            "event": "note_renamed",
            "old_rel_path": res["old_rel_path"],
            "new_rel_path": res["new_rel_path"],
        }
    )
    return res


@app.get("/api/vault/health")
def get_vault_health() -> Dict[str, Any]:
    """Run an Obsidian Vault health & integrity check (broken links, orphan notes, `.base` & `.canvas` syntax)."""
    return _bundle["index"].audit_vault_health()


@app.get("/api/calendar/events")
def get_calendar_events() -> Dict[str, Any]:
    return _bundle["connectors"].gcal_sync_events()


@app.post("/api/calendar/events")
def create_standalone_calendar_event(req: StandaloneCalendarEventRequest) -> Dict[str, Any]:
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Event title is required")
    try:
        evt = _bundle["connectors"].create_calendar_event(
            title=req.title,
            start_time_iso=req.start_time_iso,
            duration_hrs=req.duration_hrs,
            category=req.category,
            project=req.project,
            notes=req.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(evt["rel_path"]))
    _broadcast_from_thread({"event": "calendar_updated"})
    return evt


@app.patch("/api/calendar/events/{event_id}")
def update_calendar_event_endpoint(event_id: str, req: UpdateCalendarEventRequest) -> Dict[str, Any]:
    try:
        updated = _bundle["connectors"].update_calendar_event(
            event_id,
            new_date_iso=req.new_date_iso,
            start_time_iso=req.start_time_iso,
            duration_hrs=req.duration_hrs,
            title=req.title,
            category=req.category,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(updated["rel_path"]))
    linked_tid = str(updated.get("frontmatter", {}).get("linked_task") or "").strip().strip("[]")
    if linked_tid:
        try:
            _bundle["index"].index_file(_bundle["vault"].find_task_file(linked_tid))
        except FileNotFoundError:
            pass
    _broadcast_from_thread({"event": "calendar_updated", "event_id": event_id})
    return updated


@app.delete("/api/calendar/events/{event_id}")
def delete_calendar_event_endpoint(event_id: str) -> Dict[str, Any]:
    try:
        clean_id = validate_entity_id(event_id, "event_id")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rel_evt = f"03_Personal/Calendar/{clean_id}.md"
    linked_tid = ""
    try:
        pre_note = _bundle["vault"].read_note(rel_evt)
        linked_tid = str(pre_note.get("frontmatter", {}).get("linked_task") or "").strip().strip("[]")
    except Exception:
        pass
    try:
        res = _bundle["connectors"].delete_calendar_event(clean_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _bundle["index"].remove_file(_bundle["vault"].resolve_safe_path(res["rel_path"]))
    if linked_tid:
        try:
            _bundle["index"].index_file(_bundle["vault"].find_task_file(linked_tid))
        except FileNotFoundError:
            pass
    _broadcast_from_thread({"event": "calendar_updated", "deleted_event_id": clean_id})
    return res


@app.post("/api/calendar/time-block")
def create_calendar_time_block(req: TimeBlockRequest) -> Dict[str, Any]:
    active_lock = _bundle["paperclip"].get_active_lock(req.task_id)
    if active_lock is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Paperclip Lock Conflict: `{req.task_id}` is currently checked out by "
                f"`{active_lock['agent']}`"
            ),
        )
    try:
        evt = _bundle["connectors"].time_block_task_on_calendar(
            task_id=req.task_id,
            start_time_iso=req.start_time_iso,
            duration_hrs=req.duration_hrs,
            category=req.category,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(evt["rel_path"]))
    try:
        _bundle["index"].index_file(_bundle["vault"].find_task_file(req.task_id))
    except FileNotFoundError:
        pass
    _broadcast_from_thread({"event": "calendar_updated"})
    return evt


@app.post("/api/browser/clip")
def clip_webpage_to_vault(req: BrowserClipRequest) -> Dict[str, Any]:
    clean_url = (req.url or "").strip()
    if clean_url and not clean_url.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="Browser clip URL must use http:// or https://",
        )
    raw_content = req.html_or_text
    if not raw_content and clean_url:
        try:
            raw_content = safe_fetch_public_text(
                clean_url,
                user_agent="KAIROS-2.0-Clipper/1.0",
                timeout=8.0,
                max_bytes=2_000_000,
            )
        except SSRFBlockedError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raw_content = f"Clipped URL: {clean_url} ({exc})"
    try:
        saved = _bundle["vault"].defuddle_clip_to_vault(
            url=clean_url,
            raw_html_or_text=raw_content,
            title=req.title,
            dest_folder=req.dest_folder,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(saved["rel_path"]))
    _broadcast_from_thread({"event": "clip_saved", "rel_path": saved["rel_path"]})
    return saved


@app.get("/api/paperclip/status")
def get_paperclip_status() -> Dict[str, Any]:
    return {
        "paperclip": _bundle["paperclip"].get_snapshot(),
        "audit_logs": _bundle["router"].read_recent_audit_logs(limit=40),
        "hermes": _bundle["hermes"].get_status(),
    }


@app.post("/api/paperclip/locks/{task_id}/release")
def release_paperclip_lock(
    task_id: str,
    req: Optional[PaperclipReleaseLockRequest] = None,
) -> Dict[str, Any]:
    try:
        res = _bundle["paperclip"].force_release_lock(
            task_id,
            actor=(req.actor if req else "Jaime"),
            reason=(req.reason if req else "Manual operator force-unlock"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _broadcast_from_thread({"event": "paperclip_lock_released", "task_id": res["task_id"]})
    return res


@app.get("/api/hermes/status")
def get_hermes_status() -> Dict[str, Any]:
    return _bundle["hermes"].get_status()


@app.post("/api/hermes/retain")
def post_hermes_retain(req: HermesRetainRequest) -> Dict[str, Any]:
    if not req.fact.strip():
        raise HTTPException(status_code=400, detail="Fact cannot be empty")
    res = _bundle["hermes"].retain_memory(
        req.fact,
        target=req.target,
        section=req.section,
        is_private=req.is_private,
    )
    _broadcast_from_thread({"event": "hermes_updated", "rel_path": res["rel_path"]})
    return res


@app.post("/api/hermes/skills")
def post_hermes_create_skill(req: HermesCreateSkillRequest) -> Dict[str, Any]:
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Skill title cannot be empty")
    res = _bundle["hermes"].create_skill(
        title=req.title,
        category=req.category,
        trigger=req.trigger,
        steps_markdown=req.steps_markdown,
        source_task_id=req.source_task_id,
        project=req.project,
        is_private=req.is_private,
    )
    _broadcast_from_thread({"event": "hermes_updated", "rel_path": res["rel_path"]})
    return res


@app.post("/api/hermes/distill-task")
def post_hermes_distill_task(req: HermesDistillTaskRequest) -> Dict[str, Any]:
    try:
        res = _bundle["hermes"].distill_from_task(req.task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _broadcast_from_thread({"event": "hermes_updated", "rel_path": res["rel_path"]})
    return res


@app.post("/api/paperclip/dispatch-crew")
def dispatch_crew_job(req: CrewDispatchRequest) -> Dict[str, Any]:
    try:
        clean_tid = validate_entity_id(req.task_id, "task_id")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if req.reference_url.strip():
        try:
            validate_public_http_url(req.reference_url)
        except SSRFBlockedError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ConnectionError:
            pass
    active_lock = _bundle["paperclip"].get_active_lock(clean_tid)
    if active_lock is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Paperclip Lock Conflict: `{clean_tid}` is already checked out by `{active_lock['agent']}`",
        )
    crew_svc = _bundle["crew"]
    idx_svc = _bundle["index"]
    vault_svc = _bundle["vault"]

    def _worker() -> None:
        try:
            res = crew_svc.execute_task_with_crew(
                task_id=clean_tid,
                crew_name=req.crew_name,
                reference_url=req.reference_url,
            )
            for key in ("artifact_rel_path", "hermes_skill_rel_path", "clipped_rel_path"):
                rel_out = res.get(key)
                if rel_out:
                    idx_svc.index_file(vault_svc.resolve_safe_path(str(rel_out)))
            try:
                idx_svc.index_file(vault_svc.find_task_file(clean_tid))
            except FileNotFoundError:
                pass
            _broadcast_from_thread(
                {"event": "crew_completed", "task_id": clean_tid, "crew": req.crew_name}
            )
        except Exception as exc:
            _broadcast_from_thread(
                {"event": "crew_error", "task_id": clean_tid, "error": str(exc)}
            )

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "dispatched", "task_id": clean_tid, "crew": req.crew_name}


@app.post("/api/projects/structure")
def create_project_structure(req: ProjectStructureRequest) -> Dict[str, Any]:
    try:
        created = _bundle["vault"].create_project_structure(
            project=req.project,
            department=req.department,
            list_name=req.list_name,
            scaffold_standard_departments=req.scaffold_standard_departments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _bundle["index"].rebuild_all()
    _broadcast_from_thread({"event": "project_structure_created", **created})
    return created


@app.post("/api/projects/{project}/base")
def create_or_refresh_project_tasks_base(project: str) -> Dict[str, Any]:
    """Generate or refresh `02_Projects/<Project>/Docs/Project_Tasks.base` live Obsidian Base database."""
    try:
        res = _bundle["vault"].ensure_project_tasks_base(project)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _bundle["index"].rebuild_all()
    _broadcast_from_thread(
        {
            "event": "project_base_created",
            "project": res["project"],
            "base_rel_path": res["base_rel_path"],
        }
    )
    return res


@app.post("/api/projects/archive")
def archive_project(req: ProjectArchiveRequest) -> Dict[str, Any]:
    try:
        dest = _bundle["vault"].archive_completed_project(req.project, req.department or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if dest is None:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{req.project}'{'/' + req.department if req.department else ''} not found",
        )
    _bundle["index"].rebuild_all()
    rel = _bundle["vault"].to_rel_path(dest)
    _broadcast_from_thread({"event": "project_archived", "archived_rel": rel})
    return {"ok": True, "archived_rel": rel}


@app.post("/api/inbox")
def create_inbox_capture_endpoint(req: InboxCaptureInput) -> Dict[str, Any]:
    """Create a raw capture inside `00_Inbox/` and index it immediately in SQLite WAL."""
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Inbox capture title is required")
    try:
        saved = _bundle["vault"].create_inbox_capture(
            title=req.title,
            body=req.body,
            source=req.source,
            tags=req.tags,
            is_private=req.is_private,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(saved["rel_path"]))
    _broadcast_from_thread({"event": "inbox_captured", "rel_path": saved["rel_path"]})
    return saved


@app.post("/api/inbox/move")
def move_inbox_note(req: InboxMoveRequest) -> Dict[str, Any]:
    try:
        old_abs = _bundle["vault"].resolve_safe_path(req.src_rel_path)
        moved = _bundle["vault"].move_note(req.src_rel_path, req.dest_folder)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _bundle["index"].remove_file(old_abs)
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(moved["rel_path"]))
    _broadcast_from_thread({"event": "note_moved", "rel_path": moved["rel_path"]})
    return moved


@app.post("/api/inbox/promote")
def promote_inbox_to_task(req: InboxPromoteRequest) -> Dict[str, Any]:
    try:
        old_abs = _bundle["vault"].resolve_safe_path(req.src_rel_path)
        promoted = _bundle["vault"].promote_inbox_note_to_task(
            src_rel_path=req.src_rel_path,
            project=req.project,
            department=req.department,
            list_name=req.list_name,
            priority=req.priority,
            ai_agent=req.ai_agent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _bundle["index"].remove_file(old_abs)
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(promoted["archived_capture"]))
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(promoted["task"]["rel_path"]))
    tid = promoted["task"]["frontmatter"]["id"]
    _broadcast_from_thread({"event": "task_created", "task_id": tid})
    return promoted


@app.post("/api/inbox/promote-to-section")
def promote_inbox_to_section_entry(req: PromoteInboxToSectionInput) -> Dict[str, Any]:
    """Promote an `00_Inbox/` capture or web clip into a typed Section Hub catalog entry and archive raw capture."""
    try:
        old_abs = _bundle["vault"].resolve_safe_path(req.src_rel_path)
        pre_sec_dir = _bundle["vault"].resolve_safe_path(
            (req.section_or_folder or "04_Resources/Music_Studio").strip()
        )
        had_hub = (pre_sec_dir / "_Hub_Index.md").is_file() or (pre_sec_dir.parent / "_Hub_Index.md").is_file()
        promoted = _bundle["vault"].promote_inbox_note_to_section_entry(
            req.src_rel_path,
            section_or_folder=req.section_or_folder,
            collection=req.collection,
            item_type=req.item_type,
            vendor=req.vendor,
            properties=req.properties,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not had_hub:
        _bundle["index"].rebuild_all()
    else:
        _bundle["index"].remove_file(old_abs)
        _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(promoted["archived_capture"]))
        _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(promoted["entry"]["rel_path"]))

    _broadcast_from_thread(
        {
            "event": "inbox_promoted_to_section",
            "entry_rel_path": promoted["entry"]["rel_path"],
            "archived_capture": promoted["archived_capture"],
        }
    )
    return promoted


@app.post("/api/connectors/gsuite-link")
def link_google_workspace_doc(req: GSuiteLinkRequest) -> Dict[str, Any]:
    try:
        saved = _bundle["connectors"].gsuite_link_doc(
            note_path=req.note_path,
            google_doc_url=req.google_doc_url,
            pull_summary=req.pull_summary,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(saved["rel_path"]))
    _broadcast_from_thread({"event": "note_saved", "rel_path": saved["rel_path"]})
    return saved


@app.post("/api/connectors/github-sync")
def sync_github_repository(req: GitHubSyncRequest) -> Dict[str, Any]:
    return _bundle["connectors"].github_sync_repo(repo_name=req.repo_name, action=req.action)


@app.get("/api/connectors/github-org-repos")
def get_github_org_repositories(org: str = "ForestCityCreatorsLLC") -> Dict[str, Any]:
    return _bundle["connectors"].list_github_org_repos(org=org)


@app.post("/api/connectors/github-org-sync")
def sync_github_org_repositories_to_vault(req: GitHubOrgSyncRequest) -> Dict[str, Any]:
    synced = _bundle["connectors"].sync_github_org_repos_to_vault(org=req.org)
    _bundle["index"].index_file(_bundle["vault"].resolve_safe_path(synced["catalog_rel_path"]))
    _broadcast_from_thread(
        {
            "event": "github_org_synced",
            "org": synced["org"],
            "catalog_rel_path": synced["catalog_rel_path"],
        }
    )
    return synced


@app.post("/api/vault/sync-code-changes")
def sync_code_changes_endpoint(req: VaultCodeSyncRequest) -> Dict[str, Any]:
    res = sync_codebase_changes_to_vault(
        _bundle["vault"],
        _bundle["index"],
        _bundle["router"],
        summary_note=req.summary,
        actor=req.actor,
    )
    _broadcast_from_thread({"event": "vault_code_synced", "ledger_rel_path": res["ledger_rel_path"]})
    return res


# ==============================================================================
# KAIROS 2.0 Conversational Virtual Assistant Endpoints
# ==============================================================================


@app.get("/api/assistant/personas")
def get_assistant_personas() -> Dict[str, Any]:
    return {"personas": PERSONA_METADATA}


@app.get("/api/assistant/sessions")
def list_assistant_sessions() -> Dict[str, Any]:
    sessions = _bundle["assistant"].list_sessions(limit=40)
    return {"sessions": sessions}


@app.get("/api/assistant/archived-sessions")
def list_archived_assistant_sessions() -> Dict[str, Any]:
    sessions = _bundle["assistant"].list_archived_sessions(limit=40)
    return {"sessions": sessions}


@app.post("/api/assistant/sessions")
def create_assistant_session(req: AssistantCreateSessionRequest) -> Dict[str, Any]:
    created = _bundle["assistant"].create_session(
        title=req.title,
        persona=req.persona,
        tone_mode=req.tone_mode,
    )
    _broadcast_from_thread({"event": "assistant_session_created", "session_id": created["session_id"]})
    return created


@app.post("/api/assistant/sessions/{session_id}/restore")
def restore_assistant_session(session_id: str) -> Dict[str, Any]:
    try:
        restored = _bundle["assistant"].restore_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _broadcast_from_thread({"event": "assistant_session_restored", "session_id": restored["session_id"]})
    return restored


@app.get("/api/assistant/sessions/{session_id}")
def get_assistant_session(session_id: str) -> Dict[str, Any]:
    try:
        return _bundle["assistant"].get_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/assistant/sessions/{session_id}")
def rename_assistant_session(session_id: str, req: AssistantRenameSessionRequest) -> Dict[str, Any]:
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Session title cannot be empty")
    try:
        updated = _bundle["assistant"].rename_session(session_id, req.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _broadcast_from_thread({"event": "assistant_session_updated", "session_id": updated["session_id"]})
    return updated


@app.delete("/api/assistant/sessions/{session_id}")
def delete_assistant_session(session_id: str, permanent: bool = False) -> Dict[str, Any]:
    try:
        res = _bundle["assistant"].delete_session(session_id, permanent=permanent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _broadcast_from_thread({"event": "assistant_session_deleted", "session_id": res["session_id"]})
    return res


@app.post("/api/assistant/chat")
def post_assistant_chat(req: AssistantChatRequest) -> Dict[str, Any]:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Empty prompt")
    try:
        res = _bundle["assistant"].chat(
            req.prompt,
            session_id=req.session_id,
            mode=req.mode,
            persona=req.persona,
            tone_mode=req.tone_mode,
            active_note_path=req.active_note_path,
            active_task_id=req.active_task_id,
            active_browser_url=req.active_browser_url,
            active_browser_title=req.active_browser_title,
            project_scope=req.project_scope,
            department_scope=req.department_scope,
            current_tab=req.current_tab,
            current_view=req.current_view,
            persist_session=True,
        )
    except PaperclipLockConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _broadcast_from_thread(
        {
            "event": "assistant_turn",
            "session_id": (res.get("session") or {}).get("session_id", ""),
        }
    )
    return res


@app.post("/api/kairos/command")
def execute_kairos_command(req: KairosCommandRequest) -> Dict[str, Any]:
    """Unified KAIROS Top-Bar Voice & Text Command + Platform Navigator + Conversational Assistant Endpoint."""
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Empty prompt")
    try:
        res = _bundle["assistant"].chat(
            req.prompt,
            session_id=req.session_id,
            mode=req.mode,
            persona=req.persona,
            tone_mode=req.tone_mode,
            active_note_path=req.active_note_path,
            active_task_id=req.active_task_id,
            active_browser_url=req.active_browser_url,
            active_browser_title=req.active_browser_title,
            project_scope=req.project_scope,
            department_scope=req.department_scope,
            current_tab=req.current_tab,
            current_view=req.current_view,
            persist_session=True,
        )
    except PaperclipLockConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _broadcast_from_thread(
        {
            "event": "assistant_turn",
            "session_id": (res.get("session") or {}).get("session_id", ""),
        }
    )
    return res


@app.websocket("/ws/events")
async def websocket_events(ws: WebSocket) -> None:
    await ws.accept()
    with _ws_lock:
        _ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        with _ws_lock:
            if ws in _ws_clients:
                _ws_clients.remove(ws)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=settings.core_port)

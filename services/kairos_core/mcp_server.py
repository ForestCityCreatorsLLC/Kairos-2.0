"""Official `FastMCP` Server (`second_brain_mcp` — `mcp_server.py`).

Exposes Canopy Vault CRUD, Projects Task Engine (`Project -> Category -> List`), Custom Categories,
Project Wiki (`Docs/`), Rollups, Monthly Calendar (`EVT-*.md`), Google Workspace, GitHub,
Browser Clipper, and Paperclip + CrewAI + Hermes Continuity tools (18 tools total) to any MCP client
(Antigravity, Claude Desktop, Cursor, Gemini Live, or local Gemma 4).
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Optional

try:
    from mcp.server.mcpserver import MCPServer
except ModuleNotFoundError:  # pragma: no cover - mcp 1.x fallback
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore[no-redef]

from services.kairos_core.assistant import KairosAssistant
from services.kairos_core.config import KairosSettings, settings
from services.kairos_core.connectors import ExternalConnectors
from services.kairos_core.hermes import HermesEngine
from services.kairos_core.paperclip_crew import (
    CrewAIOrchestrator,
    PaperclipBroker,
    PaperclipLockConflictError,
)
from services.kairos_core.router import DualAIRouter
from services.kairos_core.schemas import CreateTaskInput, UpdateTaskInput
from services.kairos_core.shadow_index import ShadowIndex
from services.kairos_core.vault_engine import VaultEngine


def create_mcp_bundle(
    vault_path_override: Optional[Any] = None,
    *,
    vault_path: Optional[Any] = None,
    cfg: Optional[KairosSettings] = None,
) -> Dict[str, Any]:
    """Instantiate the shared Vault, ShadowIndex, Router, Paperclip, CrewAI, Assistant, and FastMCP server."""
    from pathlib import Path

    eff_cfg = cfg or settings
    raw_vp = vault_path if vault_path is not None else vault_path_override
    v_path = Path(raw_vp) if raw_vp else eff_cfg.vault_path
    vault = VaultEngine(v_path)
    index = ShadowIndex(vault)
    index.rebuild_all()
    router = DualAIRouter(
        audit_path=v_path / "_System" / "Logs" / "AI_Audit_Log.jsonl",
        cfg=eff_cfg,
        vault=vault,
    )
    paperclip = PaperclipBroker()

    def _refresh_task(task_id: str) -> None:
        try:
            p = vault.find_task_file(task_id)
            index.index_file(p)
        except Exception:
            pass

    hermes = HermesEngine(vault, index, router)
    crew = CrewAIOrchestrator(vault, router, paperclip, on_task_updated=_refresh_task, hermes=hermes)
    connectors = ExternalConnectors(vault, router, cfg=eff_cfg)
    assistant = KairosAssistant(vault, index, router, connectors, crew, cfg=eff_cfg, hermes=hermes)

    mcp = MCPServer("second_brain_mcp")

    @mcp.tool()
    def vault_search(
        query: str = "",
        folder: str = "",
        tags: Optional[List[str]] = None,
        frontmatter_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform full-text + YAML property search across the Obsidian Vault."""
        results = index.search_vault(
            query=query,
            folder=folder,
            tags=tags,
            frontmatter_filter=frontmatter_filter,
        )
        router.log_audit(
            agent="MCP",
            route_reason="vault_query",
            tool="vault_search",
            target=folder or query or "all",
        )
        return results

    @mcp.tool()
    def vault_read_note(file_path: str) -> Dict[str, Any]:
        """Read a Markdown file and return parsed `{frontmatter, body, wikilinks, tags, is_private}`."""
        note = vault.read_note(file_path)
        router.log_audit(
            agent="MCP",
            route_reason="privacy_hard_lock_local" if note["is_private"] else "vault_read",
            tool="vault_read_note",
            target=note["rel_path"],
        )
        return note

    @mcp.tool()
    def vault_write_note(
        file_path: str,
        frontmatter: Optional[Dict[str, Any]] = None,
        body: str = "",
        mode: str = "overwrite",
    ) -> Dict[str, Any]:
        """Create or overwrite/append an Obsidian Markdown note with YAML frontmatter."""
        res = vault.write_note(file_path=file_path, frontmatter=frontmatter, body=body, mode=mode)
        index.index_file(vault.resolve_safe_path(res["rel_path"]))
        router.log_audit(
            agent="MCP",
            route_reason="vault_write",
            tool="vault_write_note",
            target=res["rel_path"],
        )
        return res

    @mcp.tool()
    def vault_clip_webpage(
        url: str,
        raw_html_or_text: str = "",
        title: str = "",
        dest_folder: str = "00_Inbox",
    ) -> Dict[str, Any]:
        """Defuddle-clean HTML or webpage text into token-efficient Markdown in `00_Inbox/`."""
        saved = vault.defuddle_clip_to_vault(
            url=url,
            raw_html_or_text=raw_html_or_text or f"Clipped URL: {url}",
            title=title,
            dest_folder=dest_folder,
        )
        index.index_file(vault.resolve_safe_path(saved["rel_path"]))
        router.log_audit(
            agent="MCP",
            route_reason="vault_write",
            tool="vault_clip_webpage",
            target=saved["rel_path"],
        )
        return saved

    @mcp.tool()
    def projects_create_task(
        title: str,
        project: str = "KAIROS_2_0",
        department: str = "Software_Development",
        list_name: str = "Sprint_01",
        priority: int = 3,
        due_date: str = "",
        ai_agent: str = "None",
        description: str = "",
    ) -> Dict[str, Any]:
        """Auto-generate the next `TSK-YYYYMMDD-XXX` ID and write to `02_Projects/[Project]/[Department]/[List]/Tasks/`."""
        created = vault.create_task(
            CreateTaskInput(
                title=title,
                project=project,
                department=department,
                list=list_name,
                priority=priority,
                due_date=due_date,
                ai_agent=ai_agent,
                description=description,
            )
        )
        index.index_file(vault.resolve_safe_path(created["rel_path"]))
        router.log_audit(
            agent="MCP",
            route_reason="local_vault_crud",
            tool="projects_create_task",
            target=created["frontmatter"]["id"],
        )
        return created

    @mcp.tool()
    def projects_update_task(
        task_id: str,
        status: Optional[str] = None,
        time_logged_delta: float = 0.0,
        log_entry: Optional[str] = None,
        actor: str = "Jaime",
        priority: Optional[int] = None,
        department: Optional[str] = None,
        ai_agent: Optional[str] = None,
        start_date: Optional[str] = None,
        due_date: Optional[str] = None,
        parent_task: Optional[str] = None,
        depends_on: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Update Task YAML status/category/dependencies/time/agent and append a timestamped entry to `## Activity & AI Log`."""
        active_lock = paperclip.get_active_lock(task_id)
        if active_lock is not None and actor != active_lock.get("agent"):
            raise PaperclipLockConflictError(
                f"Paperclip Lock Conflict: `{task_id}` is currently checked out by `{active_lock['agent']}`"
            )
        old_path = vault.find_task_file(task_id)
        updated = vault.update_task(
            UpdateTaskInput(
                task_id=task_id,
                status=status,  # type: ignore[arg-type]
                time_logged_delta=time_logged_delta,
                log_entry=log_entry,
                actor=actor,
                priority=priority,
                department=department,
                ai_agent=ai_agent,
                start_date=start_date,
                due_date=due_date,
                parent_task=parent_task,
                depends_on=depends_on,
            )
        )
        new_path = vault.resolve_safe_path(updated["rel_path"])
        if old_path.resolve() != new_path.resolve():
            index.remove_path(old_path)
        index.index_file(new_path)
        router.log_audit(
            agent=actor,
            route_reason="local_vault_crud",
            tool="projects_update_task",
            target=task_id,
        )
        return updated

    @mcp.tool()
    def projects_archive_task(
        task_id: str,
        permanent: bool = False,
        actor: str = "Jaime",
    ) -> Dict[str, Any]:
        """Soft-archive a task (`TSK-*.md`) to `05_Archives/Tasks/[Project]/` (or delete permanently if `permanent=True`)."""
        active_lock = paperclip.get_active_lock(task_id)
        if active_lock is not None and actor != active_lock.get("agent"):
            raise PaperclipLockConflictError(
                f"Paperclip Lock Conflict: `{task_id}` is currently checked out by `{active_lock['agent']}`"
            )
        old_path = vault.find_task_file(task_id)
        proj_folder = vault._find_parent_project_folder(old_path)
        res = vault.delete_or_archive_task(task_id, permanent=permanent, actor=actor)
        index.remove_file(old_path)
        if res.get("archived_rel_path"):
            index.index_file(vault.resolve_safe_path(res["archived_rel_path"]))
        if proj_folder is not None and proj_folder.exists():
            for sib in proj_folder.rglob("TSK-*.md"):
                index.index_file(sib)
            proj_idx = proj_folder / "_Project_Index.md"
            if proj_idx.is_file():
                index.index_file(proj_idx)
        router.log_audit(
            agent=actor,
            route_reason="local_vault_crud",
            tool="projects_archive_task",
            target=res["task_id"],
        )
        return res

    @mcp.tool()
    def projects_create_structure(
        project: str,
        department: str = "Software_Development",
        list_name: str = "Sprint_01",
        scaffold_standard_departments: bool = False,
    ) -> Dict[str, Any]:
        """Scaffold a new project template or add a custom Category/List (`02_Projects/[Project]/[Category]/[List]/Tasks/`)."""
        created = vault.create_project_structure(
            project=project,
            department=department,
            list_name=list_name,
            scaffold_standard_departments=scaffold_standard_departments,
        )
        index.rebuild_all()
        router.log_audit(
            agent="MCP",
            route_reason="local_vault_crud",
            tool="projects_create_structure",
            target=f"{created['project']}/{created['department']}/{created['list']}",
        )
        return created

    @mcp.tool()
    def projects_create_wiki_note(
        project: str,
        title: str,
        body: str = "",
        department: str = "",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create or update a Project Documentation Wiki page in `02_Projects/[Project]/Docs/[slug].md`."""
        safe_proj = re.sub(r"[^A-Za-z0-9_\- ]+", "_", project.strip().strip("[]")).strip().replace(" ", "_") or "KAIROS_2_0"
        vault.create_project_structure(
            project=safe_proj,
            department=department.strip() or "Documentation",
            list_name="Specs_and_Guides",
            scaffold_standard_departments=False,
        )
        slug = re.sub(r"[^A-Za-z0-9_\- ]+", "", title.strip()).strip().replace(" ", "_")[:64] or "Project_Wiki_Note"
        docs_rel_dir = (
            f"02_Projects/{safe_proj}/{re.sub(r'[^A-Za-z0-9_-]+', '_', department.strip())}/Docs"
            if department.strip()
            else f"02_Projects/{safe_proj}/Docs"
        )
        rel_path = f"{docs_rel_dir}/{slug}.md"
        today_str = datetime.now().strftime("%Y-%m-%d")
        clean_title = title.strip() or slug.replace("_", " ")
        eff_body = body.strip() or (
            f"# 📘 {clean_title}\n\n"
            f"> Project Wiki Note for [[02_Projects/{safe_proj}/_Project_Index|{safe_proj.replace('_', ' ')}]] (`{today_str}`)\n\n"
            "## Summary\nDocumented via `second_brain_mcp`.\n"
        )
        saved = vault.write_note(
            rel_path,
            {
                "title": clean_title,
                "type": "project_wiki",
                "project": f"[[{safe_proj}]]",
                "department": department.strip() or "Documentation",
                "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "tags": tags or ["project-wiki", safe_proj.lower()],
            },
            eff_body + "\n",
            mode="overwrite",
        )
        index.index_file(vault.resolve_safe_path(saved["rel_path"]))
        router.log_audit(
            agent="MCP",
            route_reason="local_vault_crud",
            tool="projects_create_wiki_note",
            target=saved["rel_path"],
        )
        return saved

    @mcp.tool()
    def projects_get_rollup(
        project: str = "",
        department: str = "",
        list_name: str = "",
    ) -> Dict[str, Any]:
        """Aggregate task counts by status & department, completion %, logged hours, and overdue/blocked tasks."""
        return index.get_rollup(project=project, department=department, list_name=list_name)

    @mcp.tool()
    def calendar_create_event(
        title: str,
        start_time_iso: str,
        duration_hrs: float = 1.0,
        category: str = "Business",
        project: str = "",
        linked_task: str = "",
        notes: str = "",
    ) -> Dict[str, Any]:
        """Create a standalone Calendar Event (`EVT-YYYYMMDD-XXX.md`) in `03_Personal/Calendar/`."""
        evt = connectors.create_calendar_event(
            title=title,
            start_time_iso=start_time_iso,
            duration_hrs=duration_hrs,
            category=category,
            project=project,
            linked_task=linked_task,
            notes=notes,
        )
        index.index_file(vault.resolve_safe_path(evt["rel_path"]))
        router.log_audit(
            agent="MCP",
            route_reason="local_vault_crud",
            tool="calendar_create_event",
            target=evt["rel_path"],
        )
        return evt

    @mcp.tool()
    def gcal_sync_events(days_ahead: int = 7, days_behind: int = 1) -> Dict[str, Any]:
        """Two-way sync between Google Calendar and `03_Personal/Calendar/`."""
        res = connectors.gcal_sync_events(days_ahead=days_ahead, days_behind=days_behind)
        index.rebuild_all()
        return res

    @mcp.tool()
    def gsuite_link_doc(
        note_path: str,
        google_doc_url: str,
        pull_summary: bool = False,
    ) -> Dict[str, Any]:
        """Embed a Google Doc/Sheet/Slide iframe into a note and optionally summarize it."""
        res = connectors.gsuite_link_doc(note_path, google_doc_url, pull_summary=pull_summary)
        index.index_file(vault.resolve_safe_path(res["rel_path"]))
        return res

    @mcp.tool()
    def github_sync_repo(repo_name: str, action: str = "status") -> Dict[str, Any]:
        """Run Git status/pull inside `04_Resources/Code_and_Research/[repo_name]`."""
        return connectors.github_sync_repo(repo_name=repo_name, action=action)

    @mcp.tool()
    def paperclip_run_crew(
        task_id: str,
        crew_name: str = "CrewAI-Research",
        reference_url: str = "",
    ) -> Dict[str, Any]:
        """Checkout `task_id` via Paperclip and execute a multi-agent CrewAI workflow."""
        res = crew.execute_task_with_crew(
            task_id=task_id,
            crew_name=crew_name,
            reference_url=reference_url,
        )
        index.rebuild_all()
        return res

    @mcp.tool()
    def hermes_recall(query: str, include_private: bool = False) -> Dict[str, Any]:
        """Recall curated Hermes memory (`MEMORY.md`, `USER.md`) and matching procedural `SKL-*.md` skills."""
        return {
            "context": hermes.recall_context(query, allow_private=include_private),
            "status": hermes.get_status(),
        }

    @mcp.tool()
    def hermes_retain_memory(fact: str, target: str = "memory", section: str = "") -> Dict[str, Any]:
        """Retain a durable lesson or preference into Hermes `MEMORY.md` or `USER.md`."""
        return hermes.retain_memory(fact, target=target, section=section)

    @mcp.tool()
    def hermes_distill_task(task_id: str) -> Dict[str, Any]:
        """Distill a completed or active project task into a reusable Hermes `SKL-*.md` skill note."""
        return hermes.distill_from_task(task_id)

    return {
        "mcp": mcp,
        "vault": vault,
        "index": index,
        "router": router,
        "paperclip": paperclip,
        "hermes": hermes,
        "crew": crew,
        "connectors": connectors,
        "assistant": assistant,
        "navigator": assistant.navigator,
        "mcp_tools": {
            "vault_search": vault_search,
            "vault_read_note": vault_read_note,
            "vault_write_note": vault_write_note,
            "vault_clip_webpage": vault_clip_webpage,
            "projects_create_task": projects_create_task,
            "projects_update_task": projects_update_task,
            "projects_archive_task": projects_archive_task,
            "projects_create_structure": projects_create_structure,
            "projects_create_wiki_note": projects_create_wiki_note,
            "projects_get_rollup": projects_get_rollup,
            "calendar_create_event": calendar_create_event,
            "gcal_sync_events": gcal_sync_events,
            "gsuite_link_doc": gsuite_link_doc,
            "github_sync_repo": github_sync_repo,
            "paperclip_run_crew": paperclip_run_crew,
            "hermes_recall": hermes_recall,
            "hermes_retain_memory": hermes_retain_memory,
            "hermes_distill_task": hermes_distill_task,
        },
    }


if __name__ == "__main__":
    bundle = create_mcp_bundle()
    bundle["mcp"].run()

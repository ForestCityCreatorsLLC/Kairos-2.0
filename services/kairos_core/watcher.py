"""Loop-Safe `watchdog` Vault Listener & Projects Automation Daemon (`watcher.py`)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from watchdog.events import FileSystemEvent, FileSystemEventHandler, FileSystemMovedEvent
from watchdog.observers import Observer

from services.kairos_core.paperclip_crew import CrewAIOrchestrator
from services.kairos_core.shadow_index import ShadowIndex
from services.kairos_core.vault_engine import VaultEngine, parse_markdown_note


class _VaultWatchdogHandler(FileSystemEventHandler):
    def __init__(
        self,
        vault: VaultEngine,
        index: ShadowIndex,
        crew: CrewAIOrchestrator,
        on_change_broadcast: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        super().__init__()
        self.vault = vault
        self.index = index
        self.crew = crew
        self.on_change_broadcast = on_change_broadcast

    def _handle_fs_change(self, src_path: str, deleted: bool = False) -> None:
        path = Path(src_path)
        if path.suffix.lower() not in (".md", ".canvas", ".base"):
            return
        try:
            rel = self.vault.to_rel_path(path)
        except ValueError:
            return
        if rel.startswith((".obsidian/", "_System/Cache/", "_System/Logs/", ".git/")):
            return

        if deleted or not path.exists():
            self.index.remove_file(path)
            if self.on_change_broadcast:
                self.on_change_broadcast({"event": "deleted", "rel_path": rel})
            return

        # Ignore writes originated by KAIROS's own atomic_write_markdown to prevent infinite loops
        if self.vault.hash_guard.should_ignore_watchdog_event(path):
            return

        self.index.index_file(path)

        # External edit automations (e.g., user edited YAML directly inside Obsidian Desktop)
        if path.suffix.lower() == ".md" and rel.startswith("02_Projects/"):
            fm, _ = parse_markdown_note(path.read_text(encoding="utf-8", errors="replace"))
            if path.stem.startswith("TSK-"):
                proj_folder = self.vault._find_parent_project_folder(path)
                if proj_folder is not None:
                    self.vault.recalculate_project_progress(proj_folder)
                ai_agent = str(fm.get("ai_agent") or "None")
                status = str(fm.get("status") or "")
                # Rule 1: Auto-dispatch externally saved Tasks assigned to CrewAI or Hermes
                if ai_agent.startswith(("CrewAI", "Hermes")) and status == "To Do":
                    task_id = str(fm.get("id") or path.stem)
                    if self.crew.paperclip.get_active_lock(task_id) is None:
                        threading.Thread(
                            target=self._safe_bg_crew,
                            args=(task_id, ai_agent),
                            daemon=True,
                        ).start()
            elif path.name == "_Project_Index.md" and str(fm.get("status")) == "Completed":
                self.vault.archive_completed_project(path.parent)
                self.index.rebuild_all()

        if self.on_change_broadcast:
            self.on_change_broadcast({"event": "updated", "rel_path": rel})

    def _safe_bg_crew(self, task_id: str, crew_name: str) -> None:
        try:
            res = self.crew.execute_task_with_crew(task_id=task_id, crew_name=crew_name)
            for key in ("artifact_rel_path", "hermes_skill_rel_path", "clipped_rel_path"):
                rel_out = res.get(key)
                if rel_out:
                    self.index.index_file(self.vault.resolve_safe_path(str(rel_out)))
            try:
                self.index.index_file(self.vault.find_task_file(task_id))
            except FileNotFoundError:
                pass
            if self.on_change_broadcast:
                self.on_change_broadcast({"event": "crew_completed", "task_id": task_id, "crew": crew_name})
        except Exception as exc:
            if self.on_change_broadcast:
                self.on_change_broadcast({"event": "crew_error", "task_id": task_id, "error": str(exc)})

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle_fs_change(str(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle_fs_change(str(event.src_path))

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle_fs_change(str(event.src_path), deleted=True)

    def on_moved(self, event: FileSystemMovedEvent) -> None:
        if not event.is_directory:
            self._handle_fs_change(str(event.src_path), deleted=True)
            self._handle_fs_change(str(event.dest_path), deleted=False)


class VaultWatcherDaemon:
    """Manages background `watchdog` observer over `Vault_Root/`."""

    def __init__(
        self,
        vault: VaultEngine,
        index: ShadowIndex,
        crew: CrewAIOrchestrator,
        on_change_broadcast: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._observer = Observer()
        self._handler = _VaultWatchdogHandler(vault, index, crew, on_change_broadcast)
        self._vault_path = vault.vault_path
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._observer.schedule(self._handler, str(self._vault_path), recursive=True)
            self._observer.daemon = True
            self._observer.start()
            self._started = True

    def stop(self) -> None:
        if self._started:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._started = False

"""Paperclip Atomic Task Checkout Broker & CrewAI Multi-Agent Engine (`paperclip_crew.py`)."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from services.kairos_core.net_guard import (
    SSRFBlockedError,
    safe_fetch_public_text,
    validate_entity_id,
)
from services.kairos_core.router import DualAIRouter
from services.kairos_core.schemas import UpdateTaskInput
from services.kairos_core.vault_engine import VaultEngine

if TYPE_CHECKING:
    from services.kairos_core.hermes import HermesEngine


class PaperclipLockConflictError(RuntimeError):
    """Raised when an agent or operator attempts to mutate a task checked out by another holder."""


class PaperclipBroker:
    """In-house Paperclip task control plane: atomic checkout locks & live agent execution feed."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_locks: Dict[str, Dict[str, Any]] = {}
        self._recent_runs: List[Dict[str, Any]] = []
        self._browser_events: List[Dict[str, Any]] = []

    def get_active_lock(self, task_id: str) -> Optional[Dict[str, Any]]:
        clean_id = (task_id or "").strip().removesuffix(".md")
        with self._lock:
            existing = self._active_locks.get(clean_id)
            return dict(existing) if existing is not None else None

    def checkout_task(
        self,
        task_id: str,
        agent_name: str = "",
        crew_type: str = "single",
        *,
        agent: str = "",
    ) -> Dict[str, Any]:
        """Acquire an atomic checkout lock on `task_id` so two agents never collide on the same `.md` file."""
        clean_id = validate_entity_id(task_id, "task_id")
        eff_agent = (agent_name or agent or "Agent").strip()
        with self._lock:
            existing = self._active_locks.get(clean_id)
            if existing is not None:
                raise PaperclipLockConflictError(
                    f"Paperclip Lock Conflict: `{clean_id}` is already checked out by `{existing['agent']}`"
                )
            lock_info = {
                "lock_id": f"pclip_{uuid.uuid4().hex[:8]}",
                "task_id": clean_id,
                "agent": eff_agent,
                "crew_type": crew_type,
                "checked_out_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "started_mono": time.monotonic(),
                "step": "Checked out task & reading Obsidian context",
            }
            self._active_locks[clean_id] = lock_info
            return dict(lock_info)

    def acquire_lock(
        self,
        task_id: str,
        agent_name: str = "Agent",
        crew_type: str = "single",
    ) -> Dict[str, Any]:
        """Alias for `checkout_task` used by platform synergy & API lock-enforcement suites."""
        return self.checkout_task(task_id, agent_name=agent_name, crew_type=crew_type)

    def release_lock(
        self,
        task_id: str,
        agent_name: str = "",
        status: str = "completed",
    ) -> None:
        """Alias for `release_task` used by platform synergy & API lock-enforcement suites."""
        _ = agent_name
        self.release_task(task_id, status=status)

    def update_step(self, task_id: str, step_text: str, browser_url: str = "") -> None:
        with self._lock:
            if task_id in self._active_locks:
                self._active_locks[task_id]["step"] = step_text
            if browser_url:
                self._browser_events.insert(
                    0,
                    {
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "task_id": task_id,
                        "action": step_text,
                        "url": browser_url,
                    },
                )
                del self._browser_events[40:]

    def release_task(
        self,
        task_id: str,
        status: str = "completed",
        summary: str = "",
        artifact_rel_path: str = "",
        hermes_skill_rel_path: str = "",
    ) -> None:
        clean_id = task_id.strip()
        with self._lock:
            info = self._active_locks.pop(clean_id, None)
            elapsed_ms = (
                int((time.monotonic() - info["started_mono"]) * 1000) if info else 0
            )
            self._recent_runs.insert(
                0,
                {
                    "task_id": clean_id,
                    "agent": info["agent"] if info else "System",
                    "crew_type": info["crew_type"] if info else "single",
                    "status": status,
                    "duration_ms": elapsed_ms,
                    "summary": summary[:280],
                    "artifact_rel_path": artifact_rel_path,
                    "hermes_skill_rel_path": hermes_skill_rel_path,
                    "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            del self._recent_runs[50:]

    def force_release_lock(
        self,
        task_id: str,
        actor: str = "Jaime",
        reason: str = "Manual operator force-unlock",
    ) -> Dict[str, Any]:
        """Force-unlock a stuck or orphaned Paperclip checkout lock and record an audit run entry."""
        clean_id = validate_entity_id(task_id, "task_id")
        with self._lock:
            info = self._active_locks.pop(clean_id, None)
            if info is None:
                return {"ok": True, "released": False, "task_id": clean_id, "previous_agent": None}
            elapsed_ms = int((time.monotonic() - float(info.get("started_mono") or time.monotonic())) * 1000)
            self._recent_runs.insert(
                0,
                {
                    "task_id": clean_id,
                    "agent": info.get("agent", "Unknown"),
                    "crew_type": info.get("crew_type", "single"),
                    "status": "force_released",
                    "duration_ms": max(0, elapsed_ms),
                    "summary": f"Force-unlocked by {actor}: {reason}"[:280],
                    "artifact_rel_path": "",
                    "hermes_skill_rel_path": "",
                    "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            del self._recent_runs[50:]
            return {
                "ok": True,
                "released": True,
                "task_id": clean_id,
                "previous_agent": info.get("agent"),
                "duration_ms": max(0, elapsed_ms),
            }

    def get_snapshot(self) -> Dict[str, Any]:
        now_mono = time.monotonic()
        with self._lock:
            locks = [
                {
                    **{k: v for k, v in item.items() if k != "started_mono"},
                    "elapsed_sec": max(
                        0, int(now_mono - float(item.get("started_mono") or now_mono))
                    ),
                }
                for item in self._active_locks.values()
            ]
            return {
                "active_count": len(locks),
                "active_locks": locks,
                "recent_runs": list(self._recent_runs[:25]),
                "browser_events": list(self._browser_events[:20]),
            }


class CrewAIOrchestrator:
    """Executes multi-agent CrewAI & persistent Hermes workflows locked via Paperclip."""

    CREW_PROFILES: Dict[str, List[Dict[str, str]]] = {
        "CrewAI-Research": [
            {"role": "Lead Web & Vault Researcher", "goal": "Gather factual technical context & references"},
            {"role": "Canopy Vault Scribe", "goal": "Synthesize clean Obsidian Markdown into 04_Resources/"},
        ],
        "CrewAI-Dev": [
            {"role": "Principal Systems Architect", "goal": "Design clean modular implementation plan"},
            {"role": "Verification Engineer", "goal": "Define concrete test cases and edge-case checks"},
        ],
        "CrewAI-PM": [
            {"role": "Projects Technical PM", "goal": "Decompose scope into actionable checklist steps & estimates"},
        ],
        "Hermes-Agent": [
            {
                "role": "Hermes Autonomous Continuity Operator",
                "goal": "Execute task using retained MEMORY.md & reusable Skills, then distill new institutional knowledge",
            },
        ],
        "Hermes-Synthesizer": [
            {
                "role": "Hermes Knowledge & Skill Synthesizer",
                "goal": "Synthesize repeatable SOPs, architectural lessons, and reusable Vault skills from this task",
            },
        ],
    }

    def __init__(
        self,
        vault: VaultEngine,
        router: DualAIRouter,
        paperclip: PaperclipBroker,
        on_task_updated: Optional[Callable[[str], None]] = None,
        hermes: Optional["HermesEngine"] = None,
    ) -> None:
        self.vault = vault
        self.router = router
        self.paperclip = paperclip
        self.on_task_updated = on_task_updated
        self.hermes = hermes

    def execute_task_with_crew(
        self,
        task_id: str,
        crew_name: str = "CrewAI-Research",
        reference_url: str = "",
    ) -> Dict[str, Any]:
        """Acquire Paperclip lock, run multi-role Crew workflow, write artifacts to Vault, and move Task -> `Review`."""
        lock = self.paperclip.checkout_task(task_id, agent_name=crew_name, crew_type=crew_name)
        try:
            task_path = self.vault.find_task_file(task_id)
            note = self.vault.read_note(self.vault.to_rel_path(task_path))
            title = note["title"]
            is_priv = note["is_private"]

            clipped_note_rel = ""
            if reference_url.strip():
                if is_priv:
                    self.paperclip.update_step(
                        task_id, "Skipped outbound reference_url clip due to #private lock"
                    )
                else:
                    self.paperclip.update_step(
                        task_id, f"Co-browsing & clipping {reference_url}", browser_url=reference_url
                    )
                    try:
                        raw_html = safe_fetch_public_text(
                            reference_url,
                            user_agent="KAIROS-2.0-Paperclip-Crew/1.0",
                            timeout=8.0,
                            max_bytes=2_000_000,
                        )
                        clipped = self.vault.defuddle_clip_to_vault(
                            url=reference_url,
                            raw_html_or_text=raw_html[:80000],
                            title=f"Crew Clip — {title[:40]}",
                            dest_folder="04_Resources/Code_and_Research",
                        )
                        clipped_note_rel = clipped["rel_path"]
                    except SSRFBlockedError:
                        raise
                    except Exception:
                        pass

            roles = self.CREW_PROFILES.get(crew_name, self.CREW_PROFILES["CrewAI-Research"])
            proj_name = str(note["frontmatter"].get("project") or "KAIROS_2_0").strip("[]")
            hermes_ctx = ""
            if self.hermes is not None:
                try:
                    recalled = self.hermes.recall_context(
                        f"{title} {note['body'][:240]}",
                        project=proj_name,
                        allow_private=is_priv,
                    )
                    if recalled.get("context_text"):
                        hermes_ctx = f"\n\nHermes Retained Knowledge:\n{recalled['context_text']}"
                except Exception:
                    pass

            accumulated_context = (
                f"Task ID: {task_id}\nTitle: {title}\nProject: {proj_name}\nBody:\n{note['body']}{hermes_ctx}"
            )
            role_outputs: List[str] = []
            role_oks: List[bool] = []

            for idx, r_spec in enumerate(roles, start=1):
                role_title = r_spec["role"]
                self.paperclip.update_step(task_id, f"[{idx}/{len(roles)}] {role_title} executing...")
                prompt = (
                    f"Role: {role_title}\nGoal: {r_spec['goal']}\n\n"
                    f"Produce a concise, actionable deliverable for task `{task_id}` ({title})."
                )
                ai_res = self.router.generate(
                    prompt,
                    context=accumulated_context,
                    mode="gemma-4" if is_priv else "auto",
                    is_private=is_priv,
                    target_path=note["rel_path"],
                    tool_name=f"crew:{crew_name}",
                )
                role_oks.append(bool(ai_res.get("ok")))
                step_md = f"### {role_title}\n{ai_res.get('text') or ''}"
                role_outputs.append(step_md)
                accumulated_context += f"\n\n{step_md}"

            deliverable_md = "\n\n".join(role_outputs)
            artifact_rel = f"04_Resources/Code_and_Research/{task_id}_{crew_name}_Report.md"
            artifact_tags = ["crewai", "paperclip", "deliverable"]
            if is_priv:
                artifact_tags.append("private")
            self.vault.write_note(
                artifact_rel,
                frontmatter={
                    "title": f"{task_id} — {crew_name} Deliverable",
                    "type": "crew_deliverable",
                    "linked_task": f"[[{task_id}]]",
                    "crew": crew_name,
                    "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    "tags": artifact_tags,
                },
                body=f"# 🤖 {crew_name} Deliverable for [[{task_id}]]\n\n{deliverable_md}\n",
                mode="overwrite",
            )

            clip_ref = f" + clipped `[[{clipped_note_rel}]]`" if clipped_note_rel else ""
            hermes_skill_rel = ""
            if self.hermes is not None:
                try:
                    if crew_name.startswith("Hermes"):
                        self.paperclip.update_step(
                            task_id, "Hermes distilling reusable skill & updating MEMORY.md..."
                        )
                        distilled = self.hermes.distill_from_task(task_id, deliverable_md)
                        hermes_skill_rel = distilled["skill"]["rel_path"]
                    else:
                        self.hermes.retain_memory(
                            f"Completed `{crew_name}` deliverable for `{title}` (`{task_id}`) in `{proj_name}`.",
                            target="memory",
                            section="Project Decisions & Lessons",
                            source=f"[[{artifact_rel}]]",
                            is_private=is_priv,
                        )
                except Exception:
                    pass

            any_role_ok = any(role_oks)
            next_task_status = "Review" if any_role_ok else "In Progress"
            run_status = "completed" if any_role_ok else "degraded_offline"
            hermes_ref = f" + distilled Hermes skill `[[{hermes_skill_rel}]]`" if hermes_skill_rel else ""
            status_clause = (
                "moved status to `Review`."
                if any_role_ok
                else "kept status `In Progress` (LLM endpoints offline; saved degraded fallback draft)."
            )
            updated = self.vault.update_task(
                UpdateTaskInput(
                    task_id=task_id,
                    status=next_task_status,  # type: ignore[arg-type]
                    actor=crew_name,
                    log_entry=(
                        f"Paperclip lock `{lock['lock_id']}` {run_status}. "
                        f"Wrote deliverable `[[{artifact_rel}]]`{clip_ref}{hermes_ref} and {status_clause}"
                    ),
                )
            )
            if self.on_task_updated:
                self.on_task_updated(task_id)
            self.paperclip.release_task(
                task_id,
                status=run_status,
                summary=f"Saved {artifact_rel}",
                artifact_rel_path=artifact_rel,
                hermes_skill_rel_path=hermes_skill_rel,
            )
            return {
                "ok": True,
                "degraded": not any_role_ok,
                "task_id": task_id,
                "crew": crew_name,
                "artifact_rel_path": artifact_rel,
                "clipped_rel_path": clipped_note_rel,
                "hermes_skill_rel_path": hermes_skill_rel,
                "task": updated,
            }
        except Exception as exc:
            self.paperclip.release_task(task_id, status="error", summary=str(exc))
            raise

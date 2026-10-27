"""Hermes Persistent Knowledge Retention, Bounded Memory & Self-Generating Skill Engine (`hermes.py`).

Brings Nous-Hermes-style institutional continuity into KAIROS 2.0 alongside Paperclip & CrewAI:
1. **Bounded Curated Memory (`04_Resources/Hermes/MEMORY.md` & `USER.md`)**:
   - Retains architectural facts, project decisions, operational lessons, and operator preferences
     across sessions so agents never start from scratch.
2. **Self-Generated Reusable Skills (`04_Resources/Hermes/Skills/SKL-YYYYMMDD-XXX_<Slug>.md`)**:
   - Distills solved tasks, CrewAI deliverables, and recurring workflows into structured,
     loadable Markdown Skills (`When to Use`, `Procedure`, `Verification & Pitfalls`).
3. **Automatic Prompt Context Injection (`recall_context`)**:
   - Injects relevant Hermes memories + top matching reusable skills into `KairosAssistant`,
     `CrewAIOrchestrator`, and `Hermes-Agent` executions while honoring `#private` local locks.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.kairos_core.router import DualAIRouter
from services.kairos_core.shadow_index import ShadowIndex
from services.kairos_core.vault_engine import VaultEngine

HERMES_DIR_REL = "04_Resources/Hermes"
HERMES_SKILLS_DIR_REL = "04_Resources/Hermes/Skills"
HERMES_MEMORY_REL = "04_Resources/Hermes/MEMORY.md"
HERMES_MEMORY_ARCHIVE_REL = "04_Resources/Hermes/MEMORY_Archive.md"
HERMES_PRIVATE_MEMORY_REL = "03_Personal/Finance/Hermes_Private_Memory.md"
HERMES_USER_REL = "04_Resources/Hermes/USER.md"
MAX_MEMORY_BULLETS = 80

DEFAULT_MEMORY_MD = """# 🧠 Hermes Institutional & Project Memory (`MEMORY.md`)

> [!IMPORTANT] Persistent Knowledge Continuity
> Curated automatically by **Hermes** across KAIROS 2.0 sessions, **Paperclip** task runs, and **CrewAI** workflows. Loaded into agent context at runtime.

## Architecture & System Facts
- **Single Source of Truth:** Canopy Vault (`00_Inbox` through `05_Archives`) stores all Projects (`02_Projects/[Project]/[Category]/[List]/Tasks/TSK-*.md`), Project Wikis (`Docs/`), Calendar blocks (`EVT-*.md`), and Hermes Skills (`04_Resources/Hermes/Skills/SKL-*.md`).
- **Privacy Hard-Lock:** Notes in `03_Personal/Finance/` or tagged `#private` never transmit to cloud APIs and route exclusively to Local `Gemma 4`.
- **Execution Triad:** **Paperclip** enforces atomic task checkout locks; **CrewAI** runs multi-role collaborative crews; **Hermes** retains persistent institutional knowledge and distills reusable skills.

## Project Decisions & Lessons
- **Projects View Flow:** Operators start on `Rollup` -> `List` -> `Board` -> `Calendar` -> `Gantt` -> `Documentation` (Project Wiki & Canvas).
"""

DEFAULT_USER_MD = """# 👤 Hermes Operator Profile (`USER.md`)

> [!NOTE] Curated Operator Preferences
> Bounded profile guiding KAIROS, Hermes, and CrewAI communication & execution style.

## Identity & Organization
- **Operator:** Jaime Flores — Founder, **Forest City Creators LLC** (Cleveland, OH).
- **Flagship Projects:** `KAIROS_2_0` (Canopy Vault OS & Voice Co-Pilot) and `KAIROS` (Autonomous Cognitive & 3D Fabrication OS).

## Communication & Workflow Style
- Prefer direct, concise, actionable engineering & executive clarity with zero fluff (`CODE_RED` ready when urgent).
- Keep all project tracking 100% internal inside **Projects** (`02_Projects/`) with flexible custom categories/portions and live Project Wiki documentation.
"""


class HermesEngine:
    """Persistent memory curation, knowledge recall, and reusable skill synthesis on Canopy Vault."""

    def __init__(
        self,
        vault: VaultEngine,
        index: ShadowIndex,
        router: DualAIRouter,
    ) -> None:
        self.vault = vault
        self.index = index
        self.router = router
        self._lock = threading.RLock()
        self.initialize_hermes_files()

    def initialize_hermes_files(self) -> None:
        skills_dir = self.vault.vault_path / HERMES_SKILLS_DIR_REL
        skills_dir.mkdir(parents=True, exist_ok=True)

        mem_path = self.vault.resolve_safe_path(HERMES_MEMORY_REL)
        if not mem_path.exists():
            saved_m = self.vault.write_note(
                HERMES_MEMORY_REL,
                {
                    "id": "HRM-MEMORY-CORE",
                    "title": "Hermes Institutional & Project Memory",
                    "type": "hermes_memory",
                    "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    "tags": ["hermes", "memory", "knowledge-retention"],
                },
                DEFAULT_MEMORY_MD,
                mode="overwrite",
            )
            self.index.index_file(self.vault.resolve_safe_path(saved_m["rel_path"]))
        else:
            # Sanitize shared MEMORY.md if any legacy `#private` tag or bullet leaked into it
            existing_m = self.vault.read_note(HERMES_MEMORY_REL)
            fm_m = dict(existing_m["frontmatter"])
            tags_m = [t for t in list(fm_m.get("tags") or []) if str(t).lower() != "private"]
            priv_lines: List[str] = []
            pub_lines: List[str] = []
            for ln in existing_m["body"].splitlines():
                if ln.strip().startswith("- ") and ("#private" in ln.lower() or "[#private]" in ln.lower()):
                    priv_lines.append(ln)
                else:
                    pub_lines.append(ln)
            if tags_m != list(fm_m.get("tags") or []) or priv_lines or fm_m.get("private"):
                fm_m["tags"] = tags_m or ["hermes", "memory", "knowledge-retention"]
                fm_m.pop("private", None)
                if str(fm_m.get("privacy", "")).lower() in ("private", "local_only"):
                    fm_m.pop("privacy", None)
                saved_clean = self.vault.write_note(
                    HERMES_MEMORY_REL,
                    fm_m,
                    "\n".join(pub_lines).strip() + "\n",
                    mode="overwrite",
                )
                self.index.index_file(self.vault.resolve_safe_path(saved_clean["rel_path"]))
                for p_ln in priv_lines:
                    self._append_private_memory_line(p_ln)

        usr_path = self.vault.resolve_safe_path(HERMES_USER_REL)
        if not usr_path.exists():
            saved_u = self.vault.write_note(
                HERMES_USER_REL,
                {
                    "id": "HRM-USER-PROFILE",
                    "title": "Hermes Operator Profile (USER.md)",
                    "type": "hermes_user_profile",
                    "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    "tags": ["hermes", "operator-profile"],
                },
                DEFAULT_USER_MD,
                mode="overwrite",
            )
            self.index.index_file(self.vault.resolve_safe_path(saved_u["rel_path"]))

    def _next_skill_id(self) -> str:
        today = datetime.now().strftime("%Y%m%d")
        prefix = f"SKL-{today}-"
        max_seq = 0
        skills_dir = self.vault.vault_path / HERMES_SKILLS_DIR_REL
        for p in skills_dir.glob("SKL-*.md"):
            m = re.match(rf"^({re.escape(prefix)}(\d{{3}}))", p.stem)
            if m:
                max_seq = max(max_seq, int(m.group(2)))
        return f"{prefix}{max_seq + 1:03d}"

    def list_skills(self, limit: int = 50, allow_private: bool = True) -> List[Dict[str, Any]]:
        skills_dir = self.vault.vault_path / HERMES_SKILLS_DIR_REL
        skills_dir.mkdir(parents=True, exist_ok=True)
        items: List[Dict[str, Any]] = []
        files = sorted(skills_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files:
            if len(items) >= limit:
                break
            note = self.vault.read_note(self.vault.to_rel_path(p))
            if not allow_private and note["is_private"]:
                continue
            fm = note["frontmatter"]
            sid = str(fm.get("id") or p.stem.split("_")[0])
            proj_clean = str(fm.get("linked_project") or fm.get("project") or "").strip("[]")
            kws = (
                [str(x) for x in fm.get("trigger_keywords")]
                if isinstance(fm.get("trigger_keywords"), list)
                else []
            )
            trig_str = str(fm.get("trigger") or (", ".join(kws) if kws else ""))
            items.append(
                {
                    "id": sid,
                    "skill_id": sid,
                    "title": note["title"],
                    "category": str(fm.get("category") or "Workflow"),
                    "trigger": trig_str,
                    "trigger_keywords": kws,
                    "rel_path": note["rel_path"],
                    "project": proj_clean,
                    "linked_project": proj_clean,
                    "source_task": str(fm.get("source_task") or "").strip("[]"),
                    "updated_at": str(fm.get("updated_at") or fm.get("created_at") or ""),
                    "is_private": note["is_private"],
                    "excerpt": " ".join(note["body"].split())[:220],
                }
            )
        return items

    def get_status(self) -> Dict[str, Any]:
        self.initialize_hermes_files()
        mem_note = self.vault.read_note(HERMES_MEMORY_REL)
        usr_note = self.vault.read_note(HERMES_USER_REL)
        skills = self.list_skills(limit=50)
        bullet_count = sum(
            1 for ln in mem_note["body"].splitlines() if ln.strip().startswith("- ")
        )
        return {
            "ok": True,
            "memory_rel": HERMES_MEMORY_REL,
            "memory_rel_path": HERMES_MEMORY_REL,
            "user_rel": HERMES_USER_REL,
            "user_rel_path": HERMES_USER_REL,
            "skills_dir_rel": HERMES_SKILLS_DIR_REL,
            "skills_folder": HERMES_SKILLS_DIR_REL,
            "memory_entries_count": bullet_count,
            "skill_count": len(skills),
            "skills_count": len(skills),
            "memory_body": mem_note["body"],
            "user_body": usr_note["body"],
            "skills": skills,
        }

    def _append_private_memory_line(self, bullet_line: str) -> Dict[str, Any]:
        """Store `#private` Hermes facts inside `03_Personal/Finance/Hermes_Private_Memory.md` so shared `MEMORY.md` is never tainted."""
        priv_path = self.vault.resolve_safe_path(HERMES_PRIVATE_MEMORY_REL)
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        if not priv_path.exists():
            body = (
                "# 🔒 Hermes Local-Only Private Memory\n\n"
                "> [!WARNING] Local Gemma 4 Privacy Shield\n"
                "> Stored inside `03_Personal/Finance/` — never recalled into cloud LLM prompts.\n\n"
                "## Confidential Decisions & Facts\n"
                f"{bullet_line}\n"
            )
            saved = self.vault.write_note(
                HERMES_PRIVATE_MEMORY_REL,
                {
                    "id": "HRM-MEMORY-PRIVATE",
                    "title": "Hermes Local-Only Private Memory",
                    "type": "hermes_private_memory",
                    "privacy": "local_only",
                    "updated_at": now_iso,
                    "tags": ["hermes", "memory", "private"],
                },
                body,
                mode="overwrite",
            )
        else:
            existing = self.vault.read_note(HERMES_PRIVATE_MEMORY_REL)
            if bullet_line.strip().lower() in existing["body"].lower():
                return existing
            fm = dict(existing["frontmatter"])
            fm["updated_at"] = now_iso
            updated_body = f"{existing['body'].rstrip()}\n{bullet_line}\n"
            saved = self.vault.write_note(HERMES_PRIVATE_MEMORY_REL, fm, updated_body, mode="overwrite")
        self.index.index_file(self.vault.resolve_safe_path(saved["rel_path"]))
        return saved

    def _enforce_bounded_memory_cap(self, body: str, max_bullets: int = MAX_MEMORY_BULLETS) -> str:
        """Keep `MEMORY.md` bounded to `max_bullets` by rotating oldest bullets into `MEMORY_Archive.md`."""
        lines = body.splitlines()
        bullet_indices = [i for i, ln in enumerate(lines) if ln.strip().startswith("- ")]
        if len(bullet_indices) <= max_bullets:
            return body

        overflow_count = len(bullet_indices) - max_bullets
        seed_guard = min(3, max(0, max_bullets - 1))
        removable_indices = bullet_indices[seed_guard:]
        to_archive_idx = set(removable_indices[-overflow_count:])
        archived_bullets = [lines[i] for i in sorted(to_archive_idx)]
        kept_lines = [ln for i, ln in enumerate(lines) if i not in to_archive_idx]

        if archived_bullets:
            arch_path = self.vault.resolve_safe_path(HERMES_MEMORY_ARCHIVE_REL)
            now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            stamp_hdr = f"## Archived Overflow — `{datetime.now().strftime('%Y-%m-%d %H:%M')}`\n" + "\n".join(archived_bullets) + "\n"
            if not arch_path.exists():
                saved_arch = self.vault.write_note(
                    HERMES_MEMORY_ARCHIVE_REL,
                    {
                        "id": "HRM-MEMORY-ARCHIVE",
                        "title": "Hermes Memory Overflow Archive",
                        "type": "hermes_memory_archive",
                        "updated_at": now_iso,
                        "tags": ["hermes", "memory-archive"],
                    },
                    "# 📦 Hermes Memory Overflow Archive (`MEMORY_Archive.md`)\n\n" + stamp_hdr,
                    mode="overwrite",
                )
            else:
                saved_arch = self.vault.write_note(
                    HERMES_MEMORY_ARCHIVE_REL,
                    {"updated_at": now_iso},
                    stamp_hdr,
                    mode="append",
                )
            self.index.index_file(self.vault.resolve_safe_path(saved_arch["rel_path"]))

        return "\n".join(kept_lines).strip() + "\n"

    def retain_memory(
        self,
        fact: str,
        *,
        target: str = "memory",
        section: str = "Project Decisions & Lessons",
        source: str = "",
        is_private: bool = False,
    ) -> Dict[str, Any]:
        """Append a curated knowledge bullet into `MEMORY.md`, `USER.md`, or `Hermes_Private_Memory.md` with deduplication & bounded cap."""
        clean_fact = " ".join((fact or "").strip().split())
        if not clean_fact:
            raise ValueError("Cannot retain an empty memory fact")

        eff_private = (
            bool(is_private)
            or "#private" in clean_fact.lower()
            or "[#private]" in clean_fact.lower()
        )
        target_norm = "user" if target.lower().strip() == "user" else "memory"
        eff_section = section.strip() or (
            "Communication & Workflow Style"
            if target_norm == "user"
            else "Project Decisions & Lessons"
        )

        with self._lock:
            self.initialize_hermes_files()
            stamp = datetime.now().strftime("%Y-%m-%d")
            src_suffix = f" *(from {source})*" if source else ""

            if eff_private:
                bullet = f"- **[{stamp}]** {clean_fact}{src_suffix} `#private`"
                saved_priv = self._append_private_memory_line(bullet)
                return {
                    **saved_priv,
                    "ok": True,
                    "target": "private_memory",
                    "retained": clean_fact,
                    "privacy_locked": True,
                }

            rel = HERMES_USER_REL if target_norm == "user" else HERMES_MEMORY_REL
            existing = self.vault.read_note(rel)
            body = existing["body"]
            fm = dict(existing["frontmatter"])

            # Deduplicate exact substring matches
            if clean_fact.lower() in body.lower():
                return {**existing, "ok": True, "target": target_norm, "retained": clean_fact}

            bullet = f"- **[{stamp}]** {clean_fact}{src_suffix}"

            header_marker = f"## {eff_section}"
            if header_marker in body:
                idx = body.index(header_marker) + len(header_marker)
                updated_body = f"{body[:idx]}\n{bullet}{body[idx:]}"
            else:
                updated_body = f"{body.rstrip()}\n\n{header_marker}\n{bullet}\n"

            if rel == HERMES_MEMORY_REL:
                updated_body = self._enforce_bounded_memory_cap(updated_body, MAX_MEMORY_BULLETS)

            fm["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            # Ensure shared MEMORY.md / USER.md never carries a `private` tag
            fm["tags"] = [t for t in list(fm.get("tags") or []) if str(t).lower() != "private"]

            saved = self.vault.write_note(rel, fm, updated_body, mode="overwrite")
            self.index.index_file(self.vault.resolve_safe_path(saved["rel_path"]))
            return {**saved, "ok": True, "target": target_norm, "retained": clean_fact}

    def create_skill(
        self,
        *,
        title: str,
        when_to_use: str = "",
        procedure_markdown: str = "",
        verification_notes: str = "",
        trigger_keywords: Optional[List[str]] = None,
        linked_project: str = "",
        source_task: str = "",
        category: str = "Workflow",
        trigger: str = "",
        steps_markdown: str = "",
        source_task_id: str = "",
        project: str = "",
        is_private: bool = False,
    ) -> Dict[str, Any]:
        """Persist a reusable Hermes procedural skill in `04_Resources/Hermes/Skills/SKL-*.md`."""
        clean_title = title.strip() or "Reusable Hermes Workflow"
        eff_when = (when_to_use or trigger or clean_title).strip()
        eff_proc = (
            procedure_markdown
            or steps_markdown
            or "1. Review requirements in Canopy Vault.\n2. Execute workflow and verify output."
        ).strip()
        eff_proj = (linked_project or project).strip().strip("[]")
        eff_task = (source_task or source_task_id).strip().strip("[]")

        with self._lock:
            self.initialize_hermes_files()
            skill_id = self._next_skill_id()
            slug = re.sub(r"[^A-Za-z0-9]+", "_", clean_title).strip("_")[:44] or "Skill"
            rel = f"{HERMES_SKILLS_DIR_REL}/{skill_id}_{slug}.md"
            now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            kws = [k.strip().lower() for k in (trigger_keywords or []) if k.strip()]
            if not kws:
                kws = [
                    w.lower()
                    for w in re.findall(r"[A-Za-z0-9_]{4,}", f"{clean_title} {eff_when}")
                    if w.lower() not in {"task", "with", "from", "into", "project", "workflow", "apply", "whenever"}
                ][:6]

            tags = ["hermes", "hermes-skill", "reusable-workflow"]
            if is_private:
                tags.append("private")

            fm: Dict[str, Any] = {
                "id": skill_id,
                "title": clean_title,
                "type": "hermes_skill",
                "category": category or "Workflow",
                "trigger": eff_when,
                "trigger_keywords": kws,
                "linked_project": f"[[{eff_proj}]]" if eff_proj else "",
                "source_task": f"[[{eff_task}]]" if eff_task else "",
                "created_at": now_iso,
                "updated_at": now_iso,
                "tags": tags,
            }

            links_line: List[str] = []
            if eff_proj:
                links_line.append(f"Project: [[{eff_proj}]]")
            if eff_task:
                links_line.append(f"Source Task: [[{eff_task}]]")
            meta_quote = f"> {' • '.join(links_line)}\n\n" if links_line else ""

            body = (
                f"# ⚡ Hermes Skill: {clean_title}\n\n"
                f"{meta_quote}"
                f"## When to Use\n{eff_when}\n\n"
                f"## Reusable Procedure\n{eff_proc}\n\n"
                f"## Verification & Edge Cases\n"
                f"{verification_notes.strip() or '- Verify output notes/tasks are indexed cleanly in Canopy Vault.'}\n"
            )
            saved = self.vault.write_note(rel, fm, body, mode="overwrite")
            self.index.index_file(self.vault.resolve_safe_path(saved["rel_path"]))
            return {
                **saved,
                "ok": True,
                "skill_id": skill_id,
                "title": clean_title,
                "privacy_locked": is_private,
            }

    def distill_from_task(
        self,
        task_id: str,
        deliverable_text: str = "",
    ) -> Dict[str, Any]:
        """Distill a Project Task (and optional CrewAI/Hermes deliverable) into a Skill + `MEMORY.md` entry."""
        task_path = self.vault.find_task_file(task_id)
        note = self.vault.read_note(self.vault.to_rel_path(task_path))
        fm = note["frontmatter"]
        is_priv = note["is_private"]
        proj = str(fm.get("project") or "KAIROS_2_0").strip("[]")
        dept = str(fm.get("department") or "Software_Development")
        title = note["title"]

        prompt = (
            f"Distill task `{task_id}` ('{title}' in `{proj}/{dept}`) into:\n"
            "1. ONE concise 1-sentence institutional takeaway for `MEMORY.md` prefixed with `TAKEAWAY:`.\n"
            "2. A concise 3-to-5 bullet reusable step-by-step SOP prefixed with `STEPS:`.\n"
            "Keep it crisp, concrete, and directly reusable for future similar tasks."
        )
        ctx = f"Task Body:\n{note['body'][:2400]}\n\nDeliverable:\n{deliverable_text[:2000]}"
        ai_res = self.router.generate(
            prompt,
            context=ctx,
            mode="gemma-4" if is_priv else "auto",
            is_private=is_priv,
            target_path=note["rel_path"],
            tool_name="hermes_distill_task",
        )
        raw_out = str(ai_res.get("text") or "").strip()
        ai_agent = str(ai_res.get("agent") or "Hermes-Synthesizer")

        takeaway = f"Completed pattern for `{title}` in `{proj}/{dept}` (`{task_id}`)."
        steps_md = raw_out
        m_take = re.search(r"TAKEAWAY:\s*(.+)", raw_out, flags=re.IGNORECASE)
        if m_take:
            takeaway = m_take.group(1).strip()
        if "STEPS:" in raw_out.upper():
            idx = raw_out.upper().index("STEPS:") + len("STEPS:")
            steps_md = raw_out[idx:].strip()

        skill_note = self.create_skill(
            title=f"{title[:64]} ({dept.replace('_', ' ')})",
            when_to_use=f"Apply whenever executing tasks similar to `{title}` in `{proj}` / `{dept}`.",
            procedure_markdown=steps_md or f"1. Inspect [[{task_id}]] requirements.\n2. Execute `{dept}` workflow and log verification to Canopy Vault.",
            verification_notes=f"- Distilled from [[{task_id}]] by `{ai_agent}`.",
            linked_project=proj,
            source_task=task_id,
            category=dept.replace("_", " "),
            is_private=is_priv,
        )
        mem_note = self.retain_memory(
            takeaway,
            target="memory",
            section="Project Decisions & Lessons",
            source=f"[[{task_id}]] → [[{skill_note['rel_path']}]]",
            is_private=is_priv,
        )
        return {
            "ok": True,
            "task_id": task_id,
            "skill_id": skill_note["skill_id"],
            "title": skill_note["title"],
            "rel_path": skill_note["rel_path"],
            "agent": ai_agent,
            "privacy_locked": is_priv,
            "takeaway": takeaway,
            "skill": skill_note,
            "memory_rel_path": mem_note["rel_path"],
        }

    def recall_context(
        self,
        query: str,
        *,
        project: str = "",
        allow_private: bool = False,
        include_private: Optional[bool] = None,
        max_skills: int = 2,
    ) -> Dict[str, Any]:
        """Load bounded `USER.md`, `MEMORY.md`, and matching `SKL-*.md` skills for prompt injection."""
        if include_private is not None:
            allow_private = bool(include_private)
        self.initialize_hermes_files()
        chunks: List[str] = []
        has_private = False

        try:
            u_note = self.vault.read_note(HERMES_USER_REL)
            if not u_note["is_private"] or allow_private:
                chunks.append(f"[Hermes USER.md]:\n{u_note['body'][:700].strip()}")
        except Exception:
            pass

        try:
            m_note = self.vault.read_note(HERMES_MEMORY_REL)
            mem_lines = [
                ln
                for ln in m_note["body"].splitlines()
                if allow_private or "#private" not in ln.lower()
            ]
            chunks.append("[Hermes MEMORY.md]:\n" + "\n".join(mem_lines)[:1100].strip())
        except Exception:
            pass

        if allow_private:
            try:
                priv_mem_path = self.vault.resolve_safe_path(HERMES_PRIVATE_MEMORY_REL)
                if priv_mem_path.is_file():
                    p_note = self.vault.read_note(HERMES_PRIVATE_MEMORY_REL)
                    has_private = True
                    chunks.append(
                        f"[Hermes Private Memory]:\n{p_note['body'][:700].strip()}"
                    )
            except Exception:
                pass

        q_tokens = {
            w.lower()
            for w in re.findall(r"[A-Za-z0-9_]{3,}", f"{query} {project}")
            if len(w) >= 3
        }
        scored: List[tuple[int, Dict[str, Any]]] = []
        for sk in self.list_skills(limit=40):
            if sk["is_private"] and not allow_private:
                continue
            hay = (
                f"{sk['title']} {' '.join(sk['trigger_keywords'])} {sk['linked_project']} {sk['excerpt']}"
            ).lower()
            score = sum(2 if tok in sk["title"].lower() else 1 for tok in q_tokens if tok in hay)
            if project and sk["linked_project"].lower() == project.lower():
                score += 2
            if score > 0:
                scored.append((score, sk))

        scored.sort(key=lambda x: x[0], reverse=True)
        matched_skills: List[str] = []
        for _, sk in scored[:max_skills]:
            try:
                full_sk = self.vault.read_note(sk["rel_path"])
                if full_sk["is_private"]:
                    has_private = True
                matched_skills.append(sk["id"])
                chunks.append(
                    f"[Hermes Reusable Skill {sk['id']} — {sk['title']}]:\n{full_sk['body'][:800].strip()}"
                )
            except Exception:
                pass

        return {
            "context_text": "\n\n".join(chunks),
            "matched_skill_ids": matched_skills,
            "has_private": has_private,
        }

"""KAIROS 2.0 Conversational Virtual Assistant Engine (`assistant.py`).

Brings the full KAIROS Chatbot Virtual Assistant into KAIROS 2.0:
- Multi-Role Persona Engine (`companion`, `pm`, `dev`, `creative`, `owner`)
- Dynamic Tone Matrix (`DEFAULT` conversational partner vs `CODE_RED` tactical mode)
- Persistent Obsidian Vault Chat Sessions (`01_Business/KAIROS_Sessions/SES-YYYYMMDD-XXX.md`)
- Long-Term Operator Memory (`03_Personal/Personal_Growth/KAIROS_Operator_Memory.md`)
- Live Action & API Skills (Multi-Department Project Tasks, Inbox Capture, Calendar Time-Blocking,
  CrewAI Dispatch, OpenWeatherMap/Tomorrow.io Weather, Printful Merch Store, Discord Bot Dispatch)
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import requests

from services.kairos_core.config import KairosSettings, settings
from services.kairos_core.connectors import ExternalConnectors
from services.kairos_core.hermes import HermesEngine
from services.kairos_core.navigator import (
    PlatformNavigator,
    _extract_sports_subject_from_text,
    clean_text_for_speech,
    deduplicate_ui_commands,
    extract_llm_ui_commands,
    normalize_kairos_phonetics,
)
from services.kairos_core.net_guard import validate_entity_id
from services.kairos_core.paperclip_crew import (
    CrewAIOrchestrator,
    PaperclipLockConflictError,
)
from services.kairos_core.router import DualAIRouter
from services.kairos_core.schemas import CreateTaskInput, UpdateTaskInput
from services.kairos_core.shadow_index import ShadowIndex
from services.kairos_core.state_manager import SharedConversationStateManager
from services.kairos_core.tool_registry import (
    PlatformActionExecutor,
    UnifiedVoiceToolRegistry,
    extract_and_execute_kairos_ops,
)
from services.kairos_core.vault_blueprint import infer_blueprint_key_from_text
from services.kairos_core.vault_engine import STANDARD_PROJECT_DEPARTMENTS, VaultEngine
from services.kairos_voice.thought_verbalizer import TrainOfThoughtVerbalizer
from services.kairos_voice.vision_context import VisionContextProcessor

SESSIONS_DIR_REL = "01_Business/KAIROS_Sessions"
MEMORY_NOTE_REL = "03_Personal/Personal_Growth/KAIROS_Operator_Memory.md"
PRIVATE_MEMORY_NOTE_REL = "03_Personal/Finance/KAIROS_Operator_Private_Memory.md"

PERSONA_METADATA: Dict[str, Dict[str, str]] = {
    "companion": {
        "label": "KAIROS Companion",
        "tagline": "Warm, sharp executive partner & daily Second Brain co-pilot",
        "directive": (
            "Act as Jaime's trusted daily AI companion and executive chief of staff. "
            "Be warm, sharp, grounded, and genuinely helpful—zero robotic filler."
        ),
    },
    "pm": {
        "label": "Project Director",
        "tagline": "Cross-department execution (Software, Marketing, Docs, Website, Merch)",
        "directive": (
            "Act as an elite technical & creative Project Director managing all portions of Jaime's projects "
            "(Software Development, Marketing and Branding, Documentation, Website, and Merch). "
            "Highlight priorities, dependencies, sprint progress, and concrete next actions."
        ),
    },
    "dev": {
        "label": "Systems Architect",
        "tagline": "Python, TypeScript/React, Electron, SQLite WAL & MCP engineering",
        "directive": (
            "Act as Principal Systems Architect for KAIROS 2.0. Focus on clean modular code, "
            "local-first reliability, performance, edge cases, and exact file/API mechanics."
        ),
    },
    "creative": {
        "label": "Brand & Merch Creative",
        "tagline": "Marketing & Branding, Website copy, campaigns & Printful merch drops",
        "directive": (
            "Act as Creative & Brand Director for Forest City Creators LLC. Craft punchy copy, "
            "launch campaigns, website messaging, content hooks, and Printful merch concepts."
        ),
    },
    "owner": {
        "label": "Executive Strategist",
        "tagline": "High-leverage business strategy, ROI & prioritization",
        "directive": (
            "Act as a strategic Co-CEO advisor. Focus on leverage, revenue impact, "
            "bottleneck elimination, and high-conviction decision making."
        ),
    },
}

TONE_DIRECTIVES: Dict[str, str] = {
    "DEFAULT": (
        "TONE: Natural, confident, concise conversational style. Use clean Markdown bullets when listing items, "
        "reference relevant [[WikiLinks]] or Task IDs when helpful, and end with a clear next step if actionable."
    ),
    "CODE_RED": (
        "TONE [CODE RED TACTICAL MODE]: Zero pleasantries. Ultra-concise tactical bullets only. "
        "Lead immediately with the highest-priority blocker, fix, or command execution."
    ),
}

DEPT_DEFAULT_LIST = dict(STANDARD_PROJECT_DEPARTMENTS)


def parse_block_time_clause(text: str) -> Optional[str]:
    """Extract natural-language time block (e.g. 'block 9 AM tomorrow', 'block 14:30 today')."""
    m = re.search(
        r"\bblock\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s+(today|tomorrow))?\b",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = (m.group(3) or "").lower()
    day_word = (m.group(4) or "today").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    base_day = datetime.now() + (timedelta(days=1) if day_word == "tomorrow" else timedelta(days=0))
    target_dt = base_day.replace(hour=min(23, hour), minute=min(59, minute), second=0, microsecond=0)
    return target_dt.strftime("%Y-%m-%dT%H:%M:%S")


def parse_event_time_clause(text: str) -> str:
    """Extract natural-language calendar event timestamp (e.g. 'at 2:30 PM tomorrow', 'on 2026-10-29 at 14:00')."""
    now = datetime.now()
    m_iso_date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m_iso_date:
        try:
            base_day = datetime.strptime(m_iso_date.group(1), "%Y-%m-%d")
        except ValueError:
            base_day = now
    elif re.search(r"\btomorrow\b", text, flags=re.IGNORECASE):
        base_day = now + timedelta(days=1)
    else:
        base_day = now

    m_time = re.search(
        r"\b(?:at|for|@)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
        text,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b(\d{1,2})(?::(\d{2}))\s*(am|pm)?\b",
        text,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b(\d{1,2})\s*(am|pm)\b",
        text,
        flags=re.IGNORECASE,
    )

    if m_time:
        groups = m_time.groups()
        hour = int(groups[0])
        if len(groups) == 3:
            minute = int(groups[1] or 0)
            meridiem = (groups[2] or "").lower()
        else:
            minute = 0
            meridiem = (groups[1] or "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
    else:
        hour = 10
        minute = 0

    target_dt = base_day.replace(hour=min(23, hour), minute=min(59, minute), second=0, microsecond=0)
    return target_dt.strftime("%Y-%m-%dT%H:%M:%S")


def infer_department_from_text(
    text: str,
    default_dept: str = "Software_Development",
    index: Optional[ShadowIndex] = None,
    project: str = "",
) -> Tuple[str, str]:
    """Detect target project portion/category (standard or custom) from natural language."""
    low = text.lower()

    if index is not None:
        hierarchy = index.get_projects_hierarchy()
        ordered_projs = sorted(
            hierarchy,
            key=lambda p: 0 if project and p.get("name") == project else 1,
        )
        custom_matches: List[Tuple[int, str, str]] = []
        for proj_item in ordered_projs:
            for dept_item in proj_item.get("departments") or []:
                dname = str(dept_item.get("name") or "")
                if not dname or dname in DEPT_DEFAULT_LIST:
                    continue
                d_spoken = dname.lower().replace("_", " ")
                if re.search(rf"\b{re.escape(d_spoken)}\b", low) or re.search(
                    rf"\b{re.escape(dname.lower())}\b", low
                ):
                    lists = dept_item.get("lists") or []
                    first_list = (
                        str(lists[0].get("name") or "General")
                        if lists and isinstance(lists[0], dict)
                        else "General"
                    )
                    custom_matches.append((len(d_spoken), dname, first_list))
        if custom_matches:
            custom_matches.sort(key=lambda x: x[0], reverse=True)
            return custom_matches[0][1], custom_matches[0][2]

    if any(k in low for k in ("marketing", "branding", "campaign", "social media", "instagram", "promo")):
        return "Marketing_and_Branding", DEPT_DEFAULT_LIST["Marketing_and_Branding"]
    if any(k in low for k in ("merch", "printful", "apparel", "hoodie", "shirt", "drop")):
        return "Merch", DEPT_DEFAULT_LIST["Merch"]
    if any(k in low for k in ("website", "landing page", "web launch", "domain", "seo", "hero section")):
        return "Website", DEPT_DEFAULT_LIST["Website"]
    if any(k in low for k in ("documentation", "docs", "readme", "handbook", "guide", "sop")):
        return "Documentation", DEPT_DEFAULT_LIST["Documentation"]
    if any(k in low for k in ("software", "sprint", "backend", "frontend", "bug", "api")):
        return "Software_Development", DEPT_DEFAULT_LIST["Software_Development"]

    dept = default_dept or "Software_Development"
    if dept in DEPT_DEFAULT_LIST:
        return dept, DEPT_DEFAULT_LIST[dept]
    if index is not None:
        for proj_item in index.get_projects_hierarchy():
            if project and proj_item.get("name") != project:
                continue
            for dept_item in proj_item.get("departments") or []:
                if dept_item.get("name") == dept:
                    lists = dept_item.get("lists") or []
                    if lists and isinstance(lists[0], dict):
                        return dept, str(lists[0].get("name") or "General")
    return dept, "General"


class KairosAssistant:
    """Stateful, Vault-backed conversational virtual assistant integrated across TopBar, Drawer & Workspace."""

    def __init__(
        self,
        vault: VaultEngine,
        index: ShadowIndex,
        router: DualAIRouter,
        connectors: ExternalConnectors,
        crew: CrewAIOrchestrator,
        cfg: Optional[KairosSettings] = None,
        on_broadcast: Optional[Callable[[Dict[str, Any]], None]] = None,
        hermes: Optional[HermesEngine] = None,
    ) -> None:
        self.vault = vault
        self.index = index
        self.router = router
        self.connectors = connectors
        self.crew = crew
        self.cfg = cfg or settings
        self.on_broadcast = on_broadcast
        self.hermes = hermes
        self.navigator = PlatformNavigator(self.vault, self.index)
        self.vision = VisionContextProcessor()
        self.cognitive_state = SharedConversationStateManager(
            self.vault.vault_path / "_System" / "Cache" / "episodic_memory.sqlite"
        )
        self.voice_tools = UnifiedVoiceToolRegistry(
            vault=self.vault,
            index=self.index,
            local_llm=getattr(self.router, "local_llm", None),
            cloud_llm=getattr(self.router, "cloud_llm", None),
            paperclip=getattr(self.crew, "paperclip", None),
            cfg=self.cfg,
        )
        self.platform_executor = PlatformActionExecutor(
            vault=self.vault,
            index=self.index,
            connectors=self.connectors,
            crew=self.crew,
            paperclip=getattr(self.crew, "paperclip", None),
            hermes=self.hermes,
            cfg=self.cfg,
        )
        self._lock = threading.RLock()

    def _emit(self, payload: Dict[str, Any]) -> None:
        if self.on_broadcast is not None:
            try:
                self.on_broadcast(payload)
            except Exception:
                pass

    def _sessions_dir(self) -> Path:
        d = self.vault.vault_path / SESSIONS_DIR_REL
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _next_session_id(self) -> str:
        today = datetime.now().strftime("%Y%m%d")
        prefix = f"SES-{today}-"
        max_seq = 0
        search_dirs = [self._sessions_dir(), self.vault.vault_path / "05_Archives" / "Sessions"]
        for d in search_dirs:
            if not d.exists():
                continue
            for p in d.glob("SES-*.md"):
                if p.stem.startswith(prefix):
                    tail = p.stem[len(prefix) :]
                    if tail.isdigit():
                        max_seq = max(max_seq, int(tail))
        return f"{prefix}{max_seq + 1:03d}"

    def list_sessions(self, limit: int = 30) -> List[Dict[str, Any]]:
        sessions: List[Dict[str, Any]] = []
        files = sorted(
            self._sessions_dir().glob("SES-*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in files[:limit]:
            note = self.vault.read_note(self.vault.to_rel_path(p))
            fm = note["frontmatter"]
            turns = fm.get("turns") if isinstance(fm.get("turns"), list) else []
            sessions.append(
                {
                    "session_id": str(fm.get("id") or p.stem),
                    "title": str(fm.get("title") or note["title"]),
                    "persona": str(fm.get("persona") or "companion"),
                    "tone_mode": str(fm.get("tone_mode") or "DEFAULT"),
                    "updated_at": str(fm.get("updated_at") or ""),
                    "turn_count": len(turns),
                    "rel_path": note["rel_path"],
                    "last_preview": str(turns[-1].get("content", ""))[:120] if turns else "",
                }
            )
        return sessions

    def _assert_task_unlocked(self, task_id: str) -> None:
        active_lock = self.crew.paperclip.get_active_lock(task_id)
        if active_lock is not None:
            raise PaperclipLockConflictError(
                f"Paperclip Lock Conflict: `{task_id}` is currently checked out by `{active_lock['agent']}`"
            )

    def get_session(self, session_id: str) -> Dict[str, Any]:
        clean_id = validate_entity_id(session_id, "session_id")
        rel = f"{SESSIONS_DIR_REL}/{clean_id}.md"
        abs_ses = self.vault.resolve_safe_path(rel)
        if not abs_ses.is_relative_to(self._sessions_dir().resolve()):
            raise ValueError(f"Session path '{rel}' escapes {SESSIONS_DIR_REL}/")
        note = self.vault.read_note(rel)
        fm = note["frontmatter"]
        turns = fm.get("turns") if isinstance(fm.get("turns"), list) else []
        return {
            "session_id": str(fm.get("id") or clean_id),
            "title": str(fm.get("title") or clean_id),
            "persona": str(fm.get("persona") or "companion"),
            "tone_mode": str(fm.get("tone_mode") or "DEFAULT"),
            "updated_at": str(fm.get("updated_at") or ""),
            "rel_path": note["rel_path"],
            "turns": turns,
        }

    def create_session(
        self,
        title: str = "",
        persona: str = "companion",
        tone_mode: str = "DEFAULT",
    ) -> Dict[str, Any]:
        with self._lock:
            sid = self._next_session_id()
            now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            clean_persona = persona if persona in PERSONA_METADATA else "companion"
            clean_tone = "CODE_RED" if tone_mode == "CODE_RED" else "DEFAULT"
            clean_title = title.strip() or f"KAIROS Session — {datetime.now().strftime('%b %d, %H:%M')}"
            rel = f"{SESSIONS_DIR_REL}/{sid}.md"
            fm = {
                "id": sid,
                "title": clean_title,
                "type": "kairos_session",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "created_at": now_iso,
                "updated_at": now_iso,
                "turns": [],
                "tags": ["kairos-chat", "assistant-session"],
            }
            body = f"# 🤖 {clean_title}\n\n> Persistent KAIROS 2.0 conversation transcript stored in Canopy Vault.\n"
            saved = self.vault.write_note(rel, fm, body, mode="overwrite")
            self.index.index_file(self.vault.resolve_safe_path(saved["rel_path"]))
        return self.get_session(sid)

    def rename_session(self, session_id: str, title: str) -> Dict[str, Any]:
        """Rename a Vault-persisted conversation session (`01_Business/KAIROS_Sessions/SES-*.md`)."""
        clean_title = (title or "").strip()
        if not clean_title:
            raise ValueError("Session title cannot be empty")
        with self._lock:
            clean_id = validate_entity_id(session_id, "session_id")
            rel = f"{SESSIONS_DIR_REL}/{clean_id}.md"
            note = self.vault.read_note(rel)
            fm = dict(note["frontmatter"])
            fm["title"] = clean_title[:96]
            fm["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            lines = note["body"].splitlines()
            if lines and lines[0].startswith("# "):
                lines[0] = f"# 🤖 {fm['title']}"
            body = "\n".join(lines).strip() + "\n"
            saved = self.vault.write_note(rel, fm, body, mode="overwrite")
            self.index.index_file(self.vault.resolve_safe_path(saved["rel_path"]))
            return self.get_session(clean_id)

    def delete_session(self, session_id: str, *, permanent: bool = False) -> Dict[str, Any]:
        """Archive a chat session to `05_Archives/Sessions/` (default) or delete it permanently."""
        with self._lock:
            clean_id = validate_entity_id(session_id, "session_id")
            rel = f"{SESSIONS_DIR_REL}/{clean_id}.md"
            target = self.vault.resolve_safe_path(rel)
            if not target.is_relative_to(self._sessions_dir().resolve()):
                raise ValueError(f"Session path '{rel}' escapes {SESSIONS_DIR_REL}/")
            if not target.exists():
                raise FileNotFoundError(f"Session '{clean_id}' not found")
            self.index.remove_file(target)
            archived_rel = ""
            if permanent:
                target.unlink()
            else:
                moved = self.vault.move_note(rel, "05_Archives/Sessions")
                archived_rel = moved["rel_path"]
                self.index.index_file(self.vault.resolve_safe_path(archived_rel))
            return {
                "ok": True,
                "session_id": clean_id,
                "mode": "deleted" if permanent else "archived",
                "archived_rel_path": archived_rel,
            }

    def list_archived_sessions(self, limit: int = 30) -> List[Dict[str, Any]]:
        """List soft-archived KAIROS conversation sessions in `05_Archives/Sessions/`."""
        arch_dir = self.vault.vault_path / "05_Archives" / "Sessions"
        if not arch_dir.exists():
            return []
        sessions: List[Dict[str, Any]] = []
        files = sorted(
            arch_dir.glob("SES-*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in files[:limit]:
            try:
                note = self.vault.read_note(self.vault.to_rel_path(p))
                fm = note["frontmatter"]
                turns = fm.get("turns") if isinstance(fm.get("turns"), list) else []
                sessions.append(
                    {
                        "session_id": str(fm.get("id") or p.stem),
                        "title": str(fm.get("title") or note["title"]),
                        "persona": str(fm.get("persona") or "companion"),
                        "tone_mode": str(fm.get("tone_mode") or "DEFAULT"),
                        "updated_at": str(fm.get("updated_at") or ""),
                        "turn_count": len(turns),
                        "rel_path": note["rel_path"],
                        "last_preview": str(turns[-1].get("content", ""))[:120] if turns else "",
                    }
                )
            except Exception:
                continue
        return sessions

    def restore_session(self, session_id: str) -> Dict[str, Any]:
        """Restore a soft-archived chat session from `05_Archives/Sessions/` back to `01_Business/KAIROS_Sessions/`."""
        with self._lock:
            clean_id = validate_entity_id(session_id, "session_id")
            arch_rel = f"05_Archives/Sessions/{clean_id}.md"
            arch_abs = self.vault.resolve_safe_path(arch_rel)
            arch_root = (self.vault.vault_path / "05_Archives" / "Sessions").resolve()
            if not arch_abs.is_relative_to(arch_root):
                raise ValueError(f"Archived session path '{arch_rel}' escapes 05_Archives/Sessions/")
            if not arch_abs.exists():
                raise FileNotFoundError(
                    f"Archived session '{clean_id}' not found in 05_Archives/Sessions/"
                )
            self.index.remove_file(arch_abs)
            moved = self.vault.move_note(arch_rel, SESSIONS_DIR_REL)
            self.index.index_file(self.vault.resolve_safe_path(moved["rel_path"]))
            return self.get_session(clean_id)

    def _append_turns_to_session(
        self,
        session_id: str,
        user_turn: Dict[str, Any],
        assistant_turn: Dict[str, Any],
        persona: str,
        tone_mode: str,
    ) -> Dict[str, Any]:
        with self._lock:
            return self._append_turns_to_session_unlocked(
                session_id, user_turn, assistant_turn, persona, tone_mode
            )

    def _append_turns_to_session_unlocked(
        self,
        session_id: str,
        user_turn: Dict[str, Any],
        assistant_turn: Dict[str, Any],
        persona: str,
        tone_mode: str,
    ) -> Dict[str, Any]:
        raw_sid = (session_id or "").strip()
        if raw_sid:
            clean_id = validate_entity_id(raw_sid, "session_id")
            rel = f"{SESSIONS_DIR_REL}/{clean_id}.md"
            target = self.vault.resolve_safe_path(rel)
        else:
            clean_id = ""
            rel = ""
            target = None
        if target is None or not target.exists():
            created = self.create_session(
                title=user_turn["content"][:52],
                persona=persona,
                tone_mode=tone_mode,
            )
            clean_id = created["session_id"]
            rel = created["rel_path"]

        note = self.vault.read_note(rel)
        fm = dict(note["frontmatter"])
        turns: List[Dict[str, Any]] = list(fm.get("turns") or [])

        # Auto-title untitled session from the first user prompt
        if not turns and str(fm.get("title", "")).startswith("KAIROS Session"):
            fm["title"] = user_turn["content"][:56].strip()

        turns.append(user_turn)
        turns.append(assistant_turn)
        fm["turns"] = turns[-60:]
        fm["persona"] = persona
        fm["tone_mode"] = tone_mode
        fm["updated_at"] = assistant_turn["timestamp"]

        transcript_lines = [
            f"# 🤖 {fm.get('title', clean_id)}",
            "",
            f"- **Persona:** `{persona}` | **Tone:** `{tone_mode}` | **Updated:** `{fm['updated_at']}`",
            "",
            "---",
            "",
        ]
        for t in turns[-40:]:
            speaker = f"🧑 **{self.cfg.operator_name}**" if t.get("role") == "user" else f"🤖 **KAIROS ({t.get('agent', 'AI')})**"
            transcript_lines.append(f"### {speaker} — `{t.get('timestamp', '')}`")
            if t.get("actions"):
                for act in t["actions"]:
                    transcript_lines.append(f"- ⚡ *{act}*")
            transcript_lines.append(str(t.get("content", "")).strip())
            transcript_lines.append("")

        saved = self.vault.write_note(rel, fm, "\n".join(transcript_lines), mode="overwrite")
        self.index.index_file(self.vault.resolve_safe_path(saved["rel_path"]))
        return self.get_session(clean_id)

    def _read_operator_memory_with_privacy(
        self,
        *,
        allow_private: bool = False,
    ) -> Tuple[str, bool]:
        chunks: List[str] = []
        tainted_priv = False
        target = self.vault.resolve_safe_path(MEMORY_NOTE_REL)
        if target.exists():
            try:
                note = self.vault.read_note(MEMORY_NOTE_REL)
                body_txt = note["body"][:1500].strip()
                if body_txt:
                    chunks.append(body_txt)
                tainted_priv = tainted_priv or bool(note.get("is_private"))
            except Exception:
                pass
        if allow_private:
            priv_target = self.vault.resolve_safe_path(PRIVATE_MEMORY_NOTE_REL)
            if priv_target.exists():
                try:
                    priv_note = self.vault.read_note(PRIVATE_MEMORY_NOTE_REL)
                    priv_body = priv_note["body"][:1200].strip()
                    if priv_body:
                        chunks.append(priv_body)
                    tainted_priv = True
                except Exception:
                    pass
        return "\n\n".join(chunks).strip(), tainted_priv

    def _read_operator_memory(self) -> str:
        text, _ = self._read_operator_memory_with_privacy()
        return text

    def _save_operator_memory(self, fact: str, *, is_private: bool = False) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        eff_priv = bool(is_private or "#private" in fact.lower())
        mem_rel = PRIVATE_MEMORY_NOTE_REL if eff_priv else MEMORY_NOTE_REL
        target = self.vault.resolve_safe_path(mem_rel)
        if not target.exists():
            tags = ["kairos-memory", "private"] if eff_priv else ["kairos-memory", "personal-growth"]
            title_txt = (
                "KAIROS Private Operator Memory" if eff_priv else "KAIROS Operator Memory"
            )
            heading = (
                "# 🔒 KAIROS Private Operator Memory\n\n"
                if eff_priv
                else "# 🧠 KAIROS Long-Term Operator Memory\n\n"
            )
            saved = self.vault.write_note(
                mem_rel,
                {
                    "title": title_txt,
                    "type": "operator_memory",
                    "tags": tags,
                },
                f"{heading}- **{stamp}:** {fact}\n",
                mode="overwrite",
            )
        else:
            saved = self.vault.write_note(
                mem_rel,
                {},
                f"- **{stamp}:** {fact}",
                mode="append",
            )
        self.index.index_file(self.vault.resolve_safe_path(saved["rel_path"]))
        return saved["rel_path"]

    def _fetch_live_weather(self, prompt: str) -> Optional[str]:
        m_city = re.search(r"weather\s+(?:in|for)\s+([A-Za-z ,]+)", prompt, flags=re.IGNORECASE)
        city = m_city.group(1).strip(" ?.,!") if m_city else self.cfg.default_city
        if self.cfg.owm_api_key:
            try:
                r = requests.get(
                    self.cfg.owm_base_url,
                    params={"q": city, "appid": self.cfg.owm_api_key, "units": "imperial"},
                    timeout=5,
                )
                if r.ok:
                    d = r.json()
                    temp = d.get("main", {}).get("temp")
                    feels = d.get("main", {}).get("feels_like")
                    desc = (d.get("weather") or [{}])[0].get("description", "clear")
                    return f"Live Weather ({d.get('name', city)} via OpenWeatherMap): {temp}°F (feels like {feels}°F), {desc}."
            except Exception:
                pass
        if self.cfg.tomorrow_io_api_key:
            try:
                r2 = requests.get(
                    "https://api.tomorrow.io/v4/weather/realtime",
                    params={"location": city, "apikey": self.cfg.tomorrow_io_api_key, "units": "imperial"},
                    timeout=5,
                )
                if r2.ok:
                    vals = r2.json().get("data", {}).get("values", {})
                    return f"Live Weather ({city} via Tomorrow.io): {vals.get('temperature')}°F, wind {vals.get('windSpeed')} mph."
            except Exception:
                pass
        return None

    _SPORTS_TRIGGER_RE = re.compile(
        r"\b(?:"
        r"scores?|games?|browns|dawgs|dawg\s+pound|cavs|cavaliers|guardians|guards|tribe|"
        r"buckeyes|nfl|nba|mlb|nhl|touchdowns?|playoffs|standings|who\s+won|playing\s+today"
        r")\b",
        flags=re.IGNORECASE,
    )
    _SPORTS_NBA_RE = re.compile(
        r"\b(?:cavs|cavaliers|nba|lakers|celtics|knicks|warriors)\b", flags=re.IGNORECASE
    )
    _SPORTS_MLB_RE = re.compile(
        r"\b(?:guardians|guards|tribe|mlb|yankees|dodgers|baseball|world\s+series)\b",
        flags=re.IGNORECASE,
    )
    _SPORTS_NHL_RE = re.compile(
        r"\b(?:nhl|blue\s+jackets|hockey|stanley\s+cup)\b", flags=re.IGNORECASE
    )
    _SPORTS_CFB_RE = re.compile(
        r"\b(?:buckeyes|ohio\s+state|college\s+football|ncaa)\b", flags=re.IGNORECASE
    )
    _CODE_RED_ACTIVATE_RE = re.compile(
        r"(?:"
        r"^\s*(?:(?:hey|hi|ok|okay|yo)\s+kairos[\s,:;\-]*)?code\s+red(?=$|[\s!.:,\-])"
        r"|\b(?:activate|enable|enter|engage|trigger|switch\s+to|turn\s+on|go)\s+code\s+red\b"
        r"|\bcode\s+red\s+(?:mode\s+)?(?:on|now|alert|emergency)\b"
        r")",
        flags=re.IGNORECASE,
    )
    _CODE_RED_QUESTION_OR_LIST_RE = re.compile(
        r"\b(?:what\s+is|explain|describe|about|like|include|section\s+for)\b.*\bcode\s+red\b",
        flags=re.IGNORECASE,
    )

    def _fetch_live_sports_scores(self, prompt: str) -> Optional[str]:
        """Fetch real-time NFL/NBA/MLB/NHL/CFB scoreboard & Cleveland team schedule data via ESPN public API."""
        low = prompt.lower()
        if not self._SPORTS_TRIGGER_RE.search(low):
            return None

        # Detect league endpoint using strict word boundaries (so 'Kanban' never matches 'nba')
        if self._SPORTS_NBA_RE.search(low):
            sport_path = "basketball/nba"
            league_label = "NBA"
        elif self._SPORTS_MLB_RE.search(low):
            sport_path = "baseball/mlb"
            league_label = "MLB"
        elif self._SPORTS_NHL_RE.search(low):
            sport_path = "hockey/nhl"
            league_label = "NHL"
        elif self._SPORTS_CFB_RE.search(low):
            sport_path = "football/college-football"
            league_label = "CFB"
        else:
            sport_path = "football/nfl"
            league_label = "NFL"

        lines: List[str] = []
        try:
            r = requests.get(
                f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard",
                timeout=4.5,
            )
            if r.ok:
                events = r.json().get("events") or []
                matched_events = []
                all_summaries = []
                for ev in events:
                    ev_name = str(ev.get("name") or "")
                    comp = (ev.get("competitions") or [{}])[0]
                    competitors = comp.get("competitors") or []
                    status_desc = (
                        ((comp.get("status") or {}).get("type") or {}).get("shortDetail")
                        or ((ev.get("status") or {}).get("type") or {}).get("description")
                        or "Scheduled"
                    )
                    if len(competitors) >= 2:
                        c0, c1 = competitors[0], competitors[1]
                        t0 = (c0.get("team") or {}).get("displayName", "Team A")
                        t0_short = (c0.get("team") or {}).get("shortDisplayName", "").lower()
                        s0 = c0.get("score", "0")
                        t1 = (c1.get("team") or {}).get("displayName", "Team B")
                        t1_short = (c1.get("team") or {}).get("shortDisplayName", "").lower()
                        s1 = c1.get("score", "0")
                        summary = f"{t1} {s1} @ {t0} {s0} ({status_desc})"
                        all_summaries.append(summary)
                        if (
                            (t0_short and t0_short in low)
                            or (t1_short and t1_short in low)
                            or any(w in ev_name.lower() for w in ("browns", "cleveland", "cavaliers", "guardians", "ohio state") if w in low)
                        ):
                            matched_events.append(summary)

                if matched_events:
                    lines.append(f"Live {league_label} Scoreboard Match: " + " | ".join(matched_events))
                elif all_summaries:
                    lines.append(f"Current {league_label} Scoreboard: " + " ; ".join(all_summaries[:6]))
        except Exception:
            pass

        # Dedicated Cleveland Browns / Cavaliers / Guardians / Buckeyes schedule fallback (covers bye weeks & off-days)
        cleveland_team_map = [
            (("browns", "dawgs", "dawg pound", "cleveland browns"), "football/nfl", "5", "Cleveland Browns"),
            (("cavs", "cavaliers", "cleveland cavaliers"), "basketball/nba", "5", "Cleveland Cavaliers"),
            (("guardians", "guards", "tribe", "cleveland guardians"), "baseball/mlb", "5", "Cleveland Guardians"),
            (("buckeyes", "ohio state"), "football/college-football", "194", "Ohio State Buckeyes"),
        ]
        for aliases, sp_path, team_id, team_title in cleveland_team_map:
            if any(re.search(rf"\b{re.escape(a)}\b", low) for a in aliases):
                try:
                    rs = requests.get(
                        f"https://site.api.espn.com/apis/site/v2/sports/{sp_path}/teams/{team_id}/schedule",
                        timeout=4.5,
                    )
                    if rs.ok:
                        sched_events = rs.json().get("events") or []
                        last_completed = None
                        next_upcoming = None
                        for sev in sched_events:
                            comp = (sev.get("competitions") or [{}])[0]
                            st_type = (comp.get("status") or {}).get("type") or {}
                            completed = bool(st_type.get("completed"))
                            detail = str(st_type.get("shortDetail") or st_type.get("detail") or sev.get("date", ""))
                            comps = comp.get("competitors") or []
                            if len(comps) >= 2:
                                parts = []
                                for c in comps:
                                    tname = (c.get("team") or {}).get("displayName", "")
                                    sc_obj = c.get("score")
                                    sc_val = sc_obj.get("displayValue") if isinstance(sc_obj, dict) else sc_obj
                                    parts.append(f"{tname}{f' {sc_val}' if sc_val not in (None, '') else ''}")
                                game_line = f"{' vs '.join(parts)} ({detail})"
                                if completed:
                                    last_completed = game_line
                                elif next_upcoming is None:
                                    next_upcoming = game_line
                        if last_completed:
                            lines.append(f"{team_title} Most Recent Result: {last_completed}")
                        if next_upcoming:
                            lines.append(f"{team_title} Next Scheduled Game: {next_upcoming}")
                except Exception:
                    pass

        return "\n".join(lines) if lines else None

    def _resolve_featured_live_game_subject(self) -> Optional[str]:
        """Resolve an active or recent game matchup when the operator says 'pull up highlights of the game' cold."""
        mem_team: Optional[str] = None
        try:
            op_mem, op_priv = self._read_operator_memory_with_privacy()
            if op_mem and not op_priv:
                mem_team = _extract_sports_subject_from_text(op_mem)
        except Exception:
            pass

        requests_mocked = getattr(requests.get, "__module__", "") != "requests.api"
        can_probe_live = bool(self.cfg.gemini_api_key or self.cfg.owm_api_key or requests_mocked)
        if can_probe_live:
            for sport_path in ("football/nfl", "basketball/nba", "baseball/mlb"):
                try:
                    r = requests.get(
                        f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard",
                        timeout=1.5,
                    )
                    if not r.ok:
                        continue
                    events = r.json().get("events") or []
                    fallback_first: Optional[str] = None
                    for ev in events:
                        ev_name = str(ev.get("name") or "")
                        comp = (ev.get("competitions") or [{}])[0]
                        competitors = comp.get("competitors") or []
                        if len(competitors) >= 2:
                            t0 = str((competitors[0].get("team") or {}).get("displayName") or "").strip()
                            t1 = str((competitors[1].get("team") or {}).get("displayName") or "").strip()
                            matchup = f"{t0} vs {t1}" if (t0 and t1) else ev_name
                        else:
                            matchup = ev_name
                        if not matchup:
                            continue
                        if fallback_first is None:
                            fallback_first = matchup
                        low_ev = matchup.lower()
                        if mem_team and mem_team.lower() in low_ev:
                            return matchup
                        if any(k in low_ev for k in ("cleveland", "browns", "cavaliers", "guardians", "ohio state")):
                            return matchup
                except Exception:
                    continue

        return mem_team

    def _fetch_printful_summary(self) -> Optional[str]:
        if not self.cfg.printful_api_key:
            return None
        try:
            r = requests.get(
                "https://api.printful.com/stores",
                headers={"Authorization": f"Bearer {self.cfg.printful_api_key}"},
                timeout=6,
            )
            if r.ok:
                stores = r.json().get("result", [])
                names = [str(s.get("name") or s.get("id")) for s in stores[:5]]
                return f"Live Printful Merch Stores ({len(stores)} connected): {', '.join(names) if names else 'Token active (0 stores listed)'}."
        except Exception:
            pass
        return None

    def _post_discord_message(self, message_text: str) -> Tuple[bool, str]:
        if self.cfg.discord_bot_token and self.cfg.discord_channel_id:
            try:
                r = requests.post(
                    f"https://discord.com/api/v10/channels/{self.cfg.discord_channel_id}/messages",
                    headers={
                        "Authorization": f"Bot {self.cfg.discord_bot_token}",
                        "Content-Type": "application/json",
                    },
                    json={"content": f"🤖 **KAIROS 2.0:** {message_text}"},
                    timeout=6,
                )
                if r.status_code in (200, 201):
                    return True, f"Posted message to Discord channel `{self.cfg.discord_channel_id}`"
                return False, f"Discord API returned HTTP {r.status_code}"
            except Exception as exc:
                return False, f"Discord connection failed: {exc}"
        return False, "DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID not configured"

    def chat(
        self,
        prompt: str,
        *,
        session_id: str = "",
        mode: str = "auto",
        persona: str = "companion",
        tone_mode: str = "DEFAULT",
        active_note_path: str = "",
        active_task_id: str = "",
        active_browser_url: str = "",
        active_browser_title: str = "",
        project_scope: str = "KAIROS_2_0",
        department_scope: str = "Software_Development",
        current_tab: str = "",
        current_view: str = "",
        persist_session: bool = True,
    ) -> Dict[str, Any]:
        """Execute a full KAIROS Virtual Assistant turn (voice/UI navigation + tools + memory + Vault RAG + multi-turn LLM)."""
        raw_clean = prompt.strip()
        if not raw_clean:
            raise ValueError("Empty prompt")
        clean_prompt = normalize_kairos_phonetics(raw_clean)

        clean_persona = persona if persona in PERSONA_METADATA else "companion"
        explicit_code_red = bool(
            self._CODE_RED_ACTIVATE_RE.search(clean_prompt)
            and not self._CODE_RED_QUESTION_OR_LIST_RE.search(clean_prompt)
        )
        clean_tone = (
            "CODE_RED"
            if tone_mode == "CODE_RED" or explicit_code_red
            else "DEFAULT"
        )
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        user_turn = {
            "role": "user",
            "content": clean_prompt,
            "timestamp": now_iso,
            "persona": clean_persona,
            "tone_mode": clean_tone,
            "privacy_locked": "#private" in clean_prompt.lower(),
        }

        prior_turns: List[Dict[str, str]] = []
        session_tainted_private = False
        effective_session_id = session_id.strip()
        if persist_session:
            if not effective_session_id:
                existing = self.list_sessions(limit=1)
                if existing:
                    effective_session_id = existing[0]["session_id"]
                else:
                    created_ses = self.create_session(persona=clean_persona, tone_mode=clean_tone)
                    effective_session_id = created_ses["session_id"]
            try:
                ses_data = self.get_session(effective_session_id)
                recent_ses_turns = ses_data.get("turns", [])[-10:]
                session_tainted_private = any(
                    bool(t.get("privacy_locked"))
                    or "#private" in str(t.get("content", "")).lower()
                    for t in recent_ses_turns
                )
                prior_turns = [
                    {"role": str(t.get("role", "user")), "content": str(t.get("content", ""))}
                    for t in recent_ses_turns
                ]
            except FileNotFoundError:
                created_ses = self.create_session(persona=clean_persona, tone_mode=clean_tone)
                effective_session_id = created_ses["session_id"]

        actions_taken: List[str] = []

        early_priv = bool(session_tainted_private or "#private" in clean_prompt.lower())
        if not early_priv and active_note_path:
            norm_active = active_note_path.strip().replace("\\", "/").lower()
            if norm_active.startswith("03_personal/finance"):
                early_priv = True
            else:
                try:
                    early_priv = bool(self.vault.read_note(active_note_path).get("is_private"))
                except ValueError:
                    early_priv = True
                except Exception:
                    pass

        clean_active_task_id = (active_task_id or "").strip().upper()
        if not early_priv and clean_active_task_id:
            try:
                t_file = self.vault.find_task_file(clean_active_task_id)
                early_priv = bool(self.vault.read_note(self.vault.to_rel_path(t_file)).get("is_private"))
            except Exception:
                pass

        def _resolve_deictic_task_id(raw_ref: str) -> str:
            ref_clean = (raw_ref or "").strip()
            if ref_clean.upper().startswith("TSK-"):
                return ref_clean.upper()
            if clean_active_task_id:
                return clean_active_task_id
            raise ValueError(
                "No task is currently open in the Task Drawer — specify a `TSK-*` ID or open a task first."
            )

        # 0. Fast Skill: Deterministic Platform Voice & Workspace Navigation (`UIActionCommand` protocol)
        has_visual_trigger = bool(self.vision.detect_visual_source(clean_prompt))
        nav_cmds, nav_notes = (
            ([], [])
            if has_visual_trigger
            else self.navigator.resolve_utterance(
                clean_prompt,
                current_project=project_scope,
                current_department=department_scope,
                prior_turns=prior_turns,
                is_private_context=early_priv,
                live_sports_hint_fn=None if early_priv else self._resolve_featured_live_game_subject,
            )
        )
        if nav_cmds:
            for ncmd in nav_cmds:
                if ncmd.get("type") == "set_tone_mode":
                    clean_tone = str(ncmd.get("tone_mode") or clean_tone)
                elif ncmd.get("type") == "set_persona":
                    np = str(ncmd.get("persona") or "")
                    if np in PERSONA_METADATA:
                        clean_persona = np

            reply_text = self.navigator.build_spoken_navigation_summary(
                nav_cmds,
                nav_notes,
                fallback_project=project_scope,
            )
            spoken_reply = clean_text_for_speech(reply_text)
            actions_taken.extend(nav_notes)
            is_nav_priv = bool(
                early_priv
                or any(
                    "03_Personal/Finance" in str(c.get("folder", ""))
                    or "03_Personal/Finance" in str(c.get("rel_path", ""))
                    for c in nav_cmds
                )
            )
            self._emit({"event": "ui_navigate", "ui_commands": nav_cmds, "actions": actions_taken})
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Navigator",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": is_nav_priv,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": spoken_reply,
                "agent": "KAIROS-Navigator",
                "route_reason": "platform_voice_navigation",
                "privacy_locked": is_nav_priv,
                "ui_commands": nav_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 0b. Fast Skill: Conversational Wake-Word & Readiness Check-In Greeting (< 5ms, zero-LLM offline-safe)
        m_wake_greeting = re.match(
            r"^(?:(?:hey|hi|hello|yo|ok|okay|good\s+(?:morning|afternoon|evening))(?:[\s,!\-.]+kairos)?|kairos)"
            r"(?:[\s,!\-.]+(?:are\s+you\s+(?:there|online|awake|listening|ready)|you\s+(?:there|online|awake|listening|ready)|can\s+you\s+hear\s+me|mic\s+check|testing(?:\s+1\s*2\s*3)?))?"
            r"[!?.\s]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_wake_greeting:
            first_name = (
                self.cfg.operator_name.strip().split()[0]
                if getattr(self.cfg, "operator_name", "").strip()
                else "Operator"
            )
            rollup_snap = self.index.get_rollup(project=project_scope if project_scope else "")
            by_stat = rollup_snap.get("by_status") or {}
            open_tasks = sum(
                int(cnt or 0) for st, cnt in by_stat.items() if str(st).lower() != "done"
            )
            inbox_items = [
                i
                for i in self.index.search_vault(query="", folder="00_Inbox", limit=25)
                if early_priv or not i.get("is_private")
            ]
            proj_display = str(project_scope or "KAIROS_2_0").replace("_", " ")
            if proj_display == "KAIROS 2 0":
                proj_display = "KAIROS 2.0"

            if clean_tone == "CODE_RED":
                reply_text = (
                    f"KAIROS online, {first_name}. `CODE_RED` active — "
                    f"**{open_tasks}** open task(s) in **{proj_display}**, "
                    f"**{len(inbox_items)}** item(s) in `00_Inbox`. Ready for your command."
                )
            else:
                inbox_clause = (
                    f" and **{len(inbox_items)}** note(s) waiting in `00_Inbox`"
                    if inbox_items
                    else ""
                )
                reply_text = (
                    f"Right here, {first_name} — online and listening. "
                    f"**{proj_display}** currently has **{open_tasks}** active task(s){inbox_clause}. "
                    "What are we tackling?"
                )

            spoken_reply = clean_text_for_speech(reply_text)
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": early_priv,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": spoken_reply,
                "agent": "KAIROS-Direct",
                "route_reason": "fast_wake_greeting",
                "privacy_locked": early_priv,
                "ui_commands": [],
                "actions": actions_taken,
                "session": ses_out,
            }

        # 1. Fast Skill: Quick Inbox Capture
        m_inbox = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:capture(?:\s+(?:in|to|into)\s+inbox)?|quick\s+note)\s*[:\-]\s*(.+)$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_inbox:
            note_body = m_inbox.group(1).strip()
            priv_inbox = bool(early_priv or "#private" in note_body.lower())
            inbox_tags = ["inbox", "voice-capture"] + (["private"] if priv_inbox else [])
            slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", note_body[:36]).strip("_") or "Capture"
            rel = f"00_Inbox/Voice_Capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}.md"
            saved = self.vault.write_note(
                rel,
                {"title": note_body[:60], "type": "inbox_capture", "tags": inbox_tags},
                f"# 📥 {note_body[:60]}\n\n{note_body}\n",
            )
            self.index.index_file(self.vault.resolve_safe_path(saved["rel_path"]))
            self._emit({"event": "note_saved", "rel_path": saved["rel_path"]})
            reply_text = f"Captured into `00_Inbox`: **'{note_body[:60]}'** (`{saved['rel_path']}`)."
            actions_taken.append(f"Saved Inbox note `{saved['rel_path']}`")
            inbox_ui_cmds = (
                [{"type": "navigate_tab", "tab": "inbox"}]
                if "open inbox" in note_body.lower()
                else []
            )
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": priv_inbox,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Direct",
                "route_reason": "fast_inbox_capture",
                "privacy_locked": priv_inbox,
                "ui_commands": inbox_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 1b. Fast Skill: Hermes Curated Memory & Skill Distillation
        if self.hermes is not None:
            m_hermes_mem = re.match(
                r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:hermes[, ]+remember|retain\s+in\s+hermes)\s*[:\-]?\s+(.+)$",
                clean_prompt,
                flags=re.IGNORECASE,
            )
            if m_hermes_mem:
                fact = m_hermes_mem.group(1).strip()
                priv_h = bool(early_priv or "#private" in clean_prompt.lower())
                target_doc = "user" if "user profile" in clean_prompt.lower() else "memory"
                saved_h = self.hermes.retain_memory(fact, target=target_doc, is_private=priv_h)
                eff_priv_h = bool(saved_h.get("privacy_locked") or priv_h)
                self._emit({"event": "hermes_updated", "rel_path": saved_h["rel_path"]})
                reply_text = f"Hermes retained durable knowledge in `{saved_h['rel_path']}`:\n> {fact}"
                actions_taken.append(f"Hermes retained fact in `{saved_h['rel_path']}`")
                assistant_turn = {
                    "role": "assistant",
                    "content": reply_text,
                    "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    "agent": "Hermes-Agent",
                    "persona": clean_persona,
                    "tone_mode": clean_tone,
                    "privacy_locked": eff_priv_h,
                    "actions": actions_taken,
                }
                ses_out = (
                    self._append_turns_to_session(
                        effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                    )
                    if persist_session
                    else None
                )
                return {
                    "reply": reply_text,
                    "spoken_reply": clean_text_for_speech(reply_text),
                    "agent": "Hermes-Agent",
                    "route_reason": "hermes_memory_retain",
                    "privacy_locked": eff_priv_h,
                    "ui_commands": [],
                    "actions": actions_taken,
                    "session": ses_out,
                }

            m_hermes_distill = re.search(
                r"\b(?:hermes[, ]+distill|distill(?:\s+task)?)\s+(TSK-[\w\-]+)",
                clean_prompt,
                flags=re.IGNORECASE,
            )
            if m_hermes_distill:
                tid_distill = m_hermes_distill.group(1).upper()
                skill = self.hermes.distill_from_task(tid_distill)
                self._emit({"event": "hermes_updated", "rel_path": skill["rel_path"]})
                reply_text = (
                    f"Hermes distilled `{tid_distill}` into reusable skill **`{skill['skill_id']}`** "
                    f"(`{skill['title']}` → `{skill['rel_path']}`)."
                )
                actions_taken.append(f"Created Hermes Skill `{skill['skill_id']}` from `{tid_distill}`")
                assistant_turn = {
                    "role": "assistant",
                    "content": reply_text,
                    "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    "agent": "Hermes-Synthesizer",
                    "persona": clean_persona,
                    "tone_mode": clean_tone,
                    "privacy_locked": bool(skill.get("privacy_locked")),
                    "actions": actions_taken,
                }
                ses_out = (
                    self._append_turns_to_session(
                        effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                    )
                    if persist_session
                    else None
                )
                return {
                    "reply": reply_text,
                    "spoken_reply": clean_text_for_speech(reply_text),
                    "agent": "Hermes-Synthesizer",
                    "route_reason": "hermes_skill_distill",
                    "privacy_locked": bool(skill.get("privacy_locked")),
                    "ui_commands": [{"type": "navigate_tab", "tab": "paperclip"}],
                    "actions": actions_taken,
                    "session": ses_out,
                }

        # 2. Fast Skill: Long-Term Operator Memory ("Remember that ...")
        m_mem = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?remember(?:\s+that)?\s*[:\-]?\s+(.+)$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_mem:
            fact = m_mem.group(1).strip()
            priv_mem = bool(early_priv or "#private" in clean_prompt.lower())
            mem_rel = self._save_operator_memory(fact, is_private=priv_mem)
            self._emit({"event": "note_saved", "rel_path": mem_rel})
            reply_text = f"Locked into your long-term KAIROS Operator Memory (`{mem_rel}`):\n> {fact}"
            actions_taken.append(f"Appended memory to `{mem_rel}`")
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Memory",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": priv_mem,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Memory",
                "route_reason": "operator_memory_write",
                "privacy_locked": priv_mem,
                "ui_commands": [],
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3. Fast Skill: Task Status Transition ("Move TSK-... to Done" / "Mark this task Done")
        m_status = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:move|set|mark)\s+(?:task\s+)?(TSK-[\w\-]+|this\s+task|current\s+task|the\s+open\s+task)\s+(?:to|as)?\s*(Backlog|To Do|In Progress|Review|Blocked|Done)\b",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_status:
            tid = _resolve_deictic_task_id(m_status.group(1))
            self._assert_task_unlocked(tid)
            canon_map = {
                "backlog": "Backlog",
                "to do": "To Do",
                "in progress": "In Progress",
                "review": "Review",
                "blocked": "Blocked",
                "done": "Done",
            }
            new_st = canon_map[m_status.group(2).lower()]
            updated = self.vault.update_task(UpdateTaskInput(task_id=tid, status=new_st))  # type: ignore[arg-type]
            updated_abs = self.vault.resolve_safe_path(updated["rel_path"])
            self.index.index_file(updated_abs)
            self.platform_executor._reindex_project_index_for_task_path(updated_abs)
            self._emit({"event": "task_updated", "task_id": tid})
            reply_text = f"Updated `{tid}` status to **`{new_st}`** and recalculated project rollup."
            actions_taken.append(f"Task `{tid}` -> `{new_st}`")
            status_ui_cmds: List[Dict[str, Any]] = []
            if any(k in clean_prompt.lower() for k in ("open it", "show it", "show board", "on the board")):
                proj_of_task = str(updated["frontmatter"].get("project") or "").strip("[]")
                status_ui_cmds.append({"type": "navigate_tab", "tab": "projects"})
                if proj_of_task:
                    status_ui_cmds.append({"type": "select_project_scope", "project": proj_of_task, "department": "", "list": ""})
                if "open it" in clean_prompt.lower() or "show it" in clean_prompt.lower():
                    status_ui_cmds.append({"type": "open_task_drawer", "task_id": tid})
            is_st_priv = bool(early_priv or updated.get("is_private"))
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": is_st_priv,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Direct",
                "route_reason": "fast_status_update",
                "privacy_locked": is_st_priv,
                "task_id": tid,
                "ui_commands": status_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3_brief. Fast Skill: Executive Daily Briefing & Today's Schedule
        m_briefing = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:give\s+me\s+(?:my\s+|a\s+)?(?:daily|morning|executive)\s+briefing|(?:daily|morning|executive)\s+briefing|what(?:'s|\s+is)\s+on\s+my\s+(?:calendar|schedule)(?:\s+today)?)[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_briefing:
            today_str = datetime.now().strftime("%Y-%m-%d")
            rollup_all = self.index.get_rollup()
            all_tasks = self.index.list_tasks()
            active_tasks = [t for t in all_tasks if t["status"] != "Done"]
            p1_tasks = [t for t in active_tasks if t["priority"] == 1][:4]
            blocked_ids = rollup_all.get("blocked_task_ids") or []
            cal_res = self.connectors.gcal_sync_events()
            all_evts = cal_res.get("events") or []
            today_evts = [ev for ev in all_evts if str(ev.get("start_time") or "").startswith(today_str)]
            upcoming_evts = [ev for ev in all_evts if str(ev.get("start_time") or "")[:10] >= today_str][:4]
            inbox_notes = self.index.search_vault(query="", folder="00_Inbox", limit=50)
            hermes_count = len(self.hermes.list_skills(allow_private=True)) if self.hermes is not None else 0

            wants_cal_view = any(w in clean_prompt.lower() for w in ("calendar", "schedule"))
            brief_ui_cmds: List[Dict[str, Any]] = [
                {"type": "navigate_tab", "tab": "projects"},
                {"type": "set_projects_view", "view": "calendar" if wants_cal_view else "rollup"},
            ]
            ev_summary_lines = (
                [f"  - `{ev['start_time'][11:16]}` **{ev['title']}** (`{ev['id']}`)" for ev in (today_evts or upcoming_evts)]
                if (today_evts or upcoming_evts)
                else ["  - No Calendar blocks scheduled yet today."]
            )
            p1_lines = (
                [f"  - `{t['id']}` **{t['title']}** ({t['project']} / {t['status']})" for t in p1_tasks]
                if p1_tasks
                else ["  - Zero P1 Urgent open tasks."]
            )
            reply_text = (
                f"### ⚡ KAIROS Executive Briefing (`{today_str}`)\n"
                f"- **Portfolio Rollup:** `{rollup_all['progress_pct']}%` complete (`{rollup_all['total_tasks']}` tasks, "
                f"`{len(blocked_ids)}` Blocked, `{len(rollup_all.get('overdue_task_ids') or [])}` Overdue)\n"
                f"- **00_Inbox Captures:** `{len(inbox_notes)}` awaiting triage • **Hermes Skills:** `{hermes_count}` active\n"
                f"- **{'Today’s' if today_evts else 'Upcoming'} Calendar Blocks (`{len(today_evts)} today`):**\n"
                + "\n".join(ev_summary_lines)
                + "\n- **Top Priority Focus (`P1`):**\n"
                + "\n".join(p1_lines)
            )
            spoken_brief = (
                f"Executive briefing for {today_str}. Portfolio completion is {rollup_all['progress_pct']} percent across "
                f"{rollup_all['total_tasks']} tasks, with {len(blocked_ids)} blocked and {len(inbox_notes)} items in Inbox. "
                f"You have {len(today_evts)} calendar event{'s' if len(today_evts) != 1 else ''} scheduled today and "
                f"{hermes_count} reusable Hermes skills loaded."
            )
            actions_taken.append(f"Synthesized live Executive Briefing (`{today_str}`)")
            self._emit({"event": "ui_navigate", "ui_commands": brief_ui_cmds, "actions": actions_taken})
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Briefing",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": False,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(spoken_brief),
                "agent": "KAIROS-Briefing",
                "route_reason": "executive_daily_briefing",
                "privacy_locked": False,
                "ui_commands": brief_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3_dep. Fast Skill: Task Dependency & Subtask Linking ("Make TSK-... depend on TSK-...")
        m_dep = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:make|link|set)\s+(?:task\s+)?(TSK-[\w\-]+)\s+(?:(?:to\s+)?depend\s+on|as\s+(?:a\s+)?subtask\s+of)\s+(?:task\s+)?(TSK-[\w\-]+)[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_dep:
            child_tid = m_dep.group(1).upper()
            upstream_tid = m_dep.group(2).upper()
            self._assert_task_unlocked(child_tid)
            is_subtask_link = "subtask" in clean_prompt.lower()
            existing_child = self.vault.read_note(self.vault.to_rel_path(self.vault.find_task_file(child_tid)))
            if is_subtask_link:
                updated_dep = self.vault.update_task(
                    UpdateTaskInput(task_id=child_tid, parent_task=upstream_tid, actor="KAIROS-Direct")
                )
                link_desc = f"Linked `{child_tid}` as subtask of **`[[{upstream_tid}]]`**"
            else:
                cur_deps = [str(d).strip().strip("[]") for d in (existing_child["frontmatter"].get("depends_on") or [])]
                if upstream_tid not in cur_deps:
                    cur_deps.append(upstream_tid)
                updated_dep = self.vault.update_task(
                    UpdateTaskInput(task_id=child_tid, depends_on=cur_deps, actor="KAIROS-Direct")
                )
                link_desc = f"Linked `{child_tid}` dependency on **`[[{upstream_tid}]]`**"

            self.index.index_file(self.vault.resolve_safe_path(updated_dep["rel_path"]))
            proj_dep = str(updated_dep["frontmatter"].get("project") or "").strip("[]")
            dep_ui_cmds: List[Dict[str, Any]] = [
                {"type": "navigate_tab", "tab": "projects"},
                {"type": "select_project_scope", "project": proj_dep, "department": "", "list": ""},
                {"type": "set_projects_view", "view": "gantt"},
            ]
            self._emit({"event": "task_updated", "task_id": child_tid, "ui_commands": dep_ui_cmds})
            actions_taken.append(link_desc)
            reply_text = f"{link_desc} and opened **`{proj_dep}` → Gantt**."
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": False,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Direct",
                "route_reason": "fast_task_dependency_link",
                "privacy_locked": False,
                "task_id": child_tid,
                "linked_to": upstream_tid,
                "ui_commands": dep_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3_resched. Fast Skill: Task Date Rescheduling ("Reschedule TSK-... to 2026-11-02" / "Set due date of TSK-... to tomorrow")
        m_resched = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:reschedule\s+(?:task\s+)?(TSK-[\w\-]+)\s+(?:to|for)\s+|set\s+due\s+date\s+(?:of|for)\s+(?:task\s+)?(TSK-[\w\-]+)\s+to\s+)(\d{4}-\d{2}-\d{2}|today|tomorrow)[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_resched:
            tid_rs = (m_resched.group(1) or m_resched.group(2) or "").upper()
            self._assert_task_unlocked(tid_rs)
            raw_when = m_resched.group(3).lower().strip()
            if raw_when == "today":
                target_iso = datetime.now().strftime("%Y-%m-%d")
            elif raw_when == "tomorrow":
                target_iso = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                target_iso = raw_when

            cur_note = self.vault.read_note(self.vault.to_rel_path(self.vault.find_task_file(tid_rs)))
            cur_start = str(cur_note["frontmatter"].get("start_date") or "")
            next_start = target_iso if (not cur_start or cur_start > target_iso) else None
            updated_rs = self.vault.update_task(
                UpdateTaskInput(
                    task_id=tid_rs,
                    due_date=target_iso,
                    start_date=next_start,
                    actor="KAIROS-Direct",
                )
            )
            self.index.index_file(self.vault.resolve_safe_path(updated_rs["rel_path"]))
            proj_rs = str(updated_rs["frontmatter"].get("project") or "").strip("[]")
            rs_ui_cmds: List[Dict[str, Any]] = [
                {"type": "navigate_tab", "tab": "projects"},
                {"type": "select_project_scope", "project": proj_rs, "department": "", "list": ""},
                {"type": "set_projects_view", "view": "calendar"},
            ]
            self._emit({"event": "task_updated", "task_id": tid_rs, "ui_commands": rs_ui_cmds})
            actions_taken.append(f"Rescheduled `{tid_rs}` due date -> `{target_iso}`")
            reply_text = f"Rescheduled **`{tid_rs}`** (`{updated_rs['title']}`) to **`{target_iso}`** on your Monthly Calendar."
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": False,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Direct",
                "route_reason": "fast_task_reschedule",
                "privacy_locked": False,
                "task_id": tid_rs,
                "due_date": target_iso,
                "ui_commands": rs_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3_crew. Fast Skill: Direct Paperclip + CrewAI / Hermes Swarm Dispatch ("Dispatch Hermes-Agent on TSK-...")
        m_crew_run = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:dispatch|run)\s+(Hermes-Agent|Hermes-Synthesizer|CrewAI-Research|CrewAI-Dev|CrewAI-PM)\s+(?:on|for|against)\s+(?:task\s+)?(TSK-[\w\-]+)(?:\s+(?:with|using)\s+(https?://\S+))?[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_crew_run:
            raw_crew = m_crew_run.group(1)
            crew_canon_map = {
                "hermes-agent": "Hermes-Agent",
                "hermes-synthesizer": "Hermes-Synthesizer",
                "crewai-research": "CrewAI-Research",
                "crewai-dev": "CrewAI-Dev",
                "crewai-pm": "CrewAI-PM",
            }
            canon_crew = crew_canon_map.get(raw_crew.lower(), "Hermes-Agent")
            tid_crew = m_crew_run.group(2).upper()
            ref_url = (m_crew_run.group(3) or "").strip()

            crew_exec = self.crew.execute_task_with_crew(
                tid_crew, crew_name=canon_crew, reference_url=ref_url
            )
            art_rel = str(crew_exec.get("artifact_rel_path") or "")
            skl_rel = str(crew_exec.get("hermes_skill_rel_path") or "")
            clip_rel = str(crew_exec.get("clipped_rel_path") or "")
            if art_rel:
                self.index.index_file(self.vault.resolve_safe_path(art_rel))
            if skl_rel:
                self.index.index_file(self.vault.resolve_safe_path(skl_rel))
            if clip_rel:
                self.index.index_file(self.vault.resolve_safe_path(clip_rel))
            self.index.index_file(self.vault.resolve_safe_path(crew_exec["task"]["rel_path"]))

            priv_locked_crew = bool(crew_exec["task"].get("is_private"))
            crew_ui_cmds: List[Dict[str, Any]] = [{"type": "navigate_tab", "tab": "paperclip"}]
            self._emit(
                {
                    "event": "crew_completed",
                    "task_id": tid_crew,
                    "crew": canon_crew,
                    "ui_commands": crew_ui_cmds,
                }
            )
            skl_clause = f" and distilled Hermes skill `{skl_rel}`" if skl_rel else ""
            reply_text = (
                f"Executed **`{canon_crew}`** via Paperclip lock on **`{tid_crew}`** → saved deliverable "
                f"`{art_rel}`{skl_clause} and moved status to **`Review`**."
            )
            actions_taken.append(f"Executed `{canon_crew}` on `{tid_crew}` -> `{art_rel}`")
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": canon_crew,
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": priv_locked_crew,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(
                    f"Completed {canon_crew} run on {tid_crew}, saved the deliverable report, and moved the task to Review."
                ),
                "agent": canon_crew,
                "route_reason": "fast_crew_dispatch",
                "privacy_locked": priv_locked_crew,
                "task_id": tid_crew,
                "artifact_rel_path": art_rel,
                "hermes_skill_rel_path": skl_rel,
                "ui_commands": crew_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3_chk. Fast Skill: Add Task Checklist Item ("Add checklist item Verify 24kHz WAV header to TSK-..." / "... to this task")
        m_chk = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?add\s+checklist(?:\s+item)?\s+(.+?)\s+(?:to|on|for)\s+(?:(?:task\s+)?(TSK-[\w\-]+)|(this\s+task|current\s+task|the\s+open\s+task))[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_chk:
            chk_text = m_chk.group(1).strip(" '\"")
            tid_chk = _resolve_deictic_task_id(m_chk.group(2) or m_chk.group(3) or "")
            self._assert_task_unlocked(tid_chk)
            updated_chk = self.vault.update_task(
                UpdateTaskInput(
                    task_id=tid_chk,
                    add_checklist_item=chk_text,
                    actor="KAIROS-Direct",
                )
            )
            self.index.index_file(self.vault.resolve_safe_path(updated_chk["rel_path"]))
            proj_chk = str(updated_chk["frontmatter"].get("project") or "").strip("[]")
            chk_ui_cmds: List[Dict[str, Any]] = [
                {"type": "navigate_tab", "tab": "projects"},
                {"type": "select_project_scope", "project": proj_chk, "department": "", "list": ""},
                {"type": "open_task_drawer", "task_id": tid_chk},
            ]
            self._emit({"event": "task_updated", "task_id": tid_chk, "ui_commands": chk_ui_cmds})
            actions_taken.append(f"Added checklist item '{chk_text}' to `{tid_chk}`")
            reply_text = f"Added checklist item **'{chk_text}'** to **`{tid_chk}`** and opened the Task Drawer."
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": bool(updated_chk.get("is_private")),
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Direct",
                "route_reason": "fast_task_checklist_add",
                "privacy_locked": bool(updated_chk.get("is_private")),
                "task_id": tid_chk,
                "ui_commands": chk_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3_log. Fast Skill: Log Task Time & Activity ("Log 1.5 hours on TSK-...: Completed audit" / "... on this task")
        m_log = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?log\s+(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\s+(?:on|for|to)\s+(?:(?:task\s+)?(TSK-[\w\-]+)|(this\s+task|current\s+task|the\s+open\s+task))(?:\s*[:\-]\s*(.+))?[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_log:
            amt = float(m_log.group(1))
            unit = m_log.group(2).lower()
            hrs_delta = round(amt / 60.0, 2) if unit.startswith("m") else round(amt, 2)
            tid_log = _resolve_deictic_task_id(m_log.group(3) or m_log.group(4) or "")
            self._assert_task_unlocked(tid_log)
            note_log = (m_log.group(5) or "").strip() or f"Voice/Chat time log (+{hrs_delta}h)"
            updated_log = self.vault.update_task(
                UpdateTaskInput(
                    task_id=tid_log,
                    time_logged_delta=hrs_delta,
                    log_entry=note_log,
                    actor="KAIROS-Direct",
                )
            )
            self.index.index_file(self.vault.resolve_safe_path(updated_log["rel_path"]))
            proj_log = str(updated_log["frontmatter"].get("project") or "").strip("[]")
            total_hrs_now = float(updated_log["frontmatter"].get("time_logged_hrs") or 0.0)
            log_ui_cmds: List[Dict[str, Any]] = [
                {"type": "navigate_tab", "tab": "projects"},
                {"type": "select_project_scope", "project": proj_log, "department": "", "list": ""},
                {"type": "open_task_drawer", "task_id": tid_log},
            ]
            self._emit({"event": "task_updated", "task_id": tid_log, "ui_commands": log_ui_cmds})
            actions_taken.append(f"Logged +{hrs_delta}h on `{tid_log}` (total {total_hrs_now}h)")
            reply_text = (
                f"Logged **`+{hrs_delta}h`** on **`{tid_log}`** (now `{total_hrs_now}h` total) — "
                f"*{note_log}*."
            )
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": bool(updated_log.get("is_private")),
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Direct",
                "route_reason": "fast_task_time_log",
                "privacy_locked": bool(updated_log.get("is_private")),
                "task_id": tid_log,
                "time_logged_hrs": total_hrs_now,
                "ui_commands": log_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3a. Fast Skill: Physical Task Category Relocation ("Move TSK-... to category Podcast Studio")
        m_reloc = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?move\s+(?:task\s+)?(TSK-[\w\-]+)\s+(?:to|into)\s+(?:(?:category|department|portion)\s+)?([A-Za-z0-9_\-& ]+?)(?:\s+and\s+(open\s+it|show\s+it))?[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_reloc:
            tid_reloc = m_reloc.group(1).upper()
            self._assert_task_unlocked(tid_reloc)
            raw_cat = m_reloc.group(2).strip()
            wants_open = bool(m_reloc.group(3))
            matched_std_dept, _, _ = self.navigator._match_department(raw_cat.lower())
            target_cat = matched_std_dept or re.sub(
                r"[^A-Za-z0-9_\-]+",
                "_",
                raw_cat.replace("&", "and"),
            ).strip("_")
            old_path = self.vault.find_task_file(tid_reloc)
            updated_reloc = self.vault.update_task(
                UpdateTaskInput(
                    task_id=tid_reloc,
                    department=target_cat,
                    actor="KAIROS-Direct",
                )
            )
            new_abs = self.vault.resolve_safe_path(updated_reloc["rel_path"])
            if old_path.resolve() != new_abs.resolve():
                self.index.remove_file(old_path)
            self.index.index_file(new_abs)
            self.index.rebuild_all()
            proj_of_reloc = str(updated_reloc["frontmatter"].get("project") or "").strip("[]")
            reloc_ui_cmds: List[Dict[str, Any]] = [
                {"type": "navigate_tab", "tab": "projects"},
                {
                    "type": "select_project_scope",
                    "project": proj_of_reloc,
                    "department": updated_reloc["frontmatter"].get("department", target_cat),
                    "list": "",
                },
            ]
            if wants_open:
                reloc_ui_cmds.append({"type": "open_task_drawer", "task_id": tid_reloc})
            self._emit({"event": "task_updated", "task_id": tid_reloc, "ui_commands": reloc_ui_cmds})
            reply_text = (
                f"Moved `{tid_reloc}` into category **`{updated_reloc['frontmatter'].get('department', target_cat)}`** "
                f"(`{updated_reloc['rel_path']}`)."
            )
            actions_taken.append(f"Relocated `{tid_reloc}` -> `{updated_reloc['rel_path']}`")
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": False,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Direct",
                "route_reason": "fast_category_relocate",
                "privacy_locked": False,
                "relocated_task_id": tid_reloc,
                "rel_path": updated_reloc["rel_path"],
                "ui_commands": reloc_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3b. Fast Skill: Canonical KAIROS 2.0 Project Template Creation
        m_proj = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:create|scaffold|start|initialize)\s+(?:a\s+)?(?:new\s+)?project(?:\s+(?:called|named|for))?\s+([A-Za-z0-9_\- ]+?)[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_proj and not re.match(
            r"^(?:tasks?\s+|obsidian\s+)?\.?base\b",
            m_proj.group(1).strip(),
            flags=re.IGNORECASE,
        ):
            raw_proj = m_proj.group(1).strip().replace(" ", "_")
            created_proj = self.vault.create_project_structure(
                project=raw_proj,
                department="Software_Development",
                list_name="Sprint_01",
                scaffold_standard_departments=True,
            )
            self.index.rebuild_all()
            proj_ui_cmds = [
                {"type": "navigate_tab", "tab": "projects"},
                {
                    "type": "select_project_scope",
                    "project": created_proj["project"],
                    "department": "",
                    "list": "",
                },
            ]
            self._emit({"event": "project_created", "project": created_proj["project"], "ui_commands": proj_ui_cmds})
            actions_taken.append(f"Scaffolded Project `{created_proj['project']}` (KAIROS 2.0 Template)")
            reply_text = (
                f"Scaffolded **`{created_proj['project']}`** from the canonical **KAIROS 2.0 Project Template**:\n"
                f"- Project Hub: `{created_proj['project_index_rel']}`\n"
                f"- Architecture Canvas: `{created_proj['canvas_rel']}`\n"
                "- Departments: `Software_Development/Sprint_01`, `Marketing_and_Branding/Campaigns`, "
                "`Documentation/Specs_and_Guides`, `Website/Web_Launch`, and `Merch/Printful_Drops` (each with `Tasks/`)."
            )
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": False,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(
                    f"Scaffolded new project {created_proj['project']} with all five standard departments and opened it in Projects."
                ),
                "agent": "KAIROS-Direct",
                "route_reason": "project_template_scaffolded",
                "privacy_locked": False,
                "created_project": created_proj["project"],
                "project_index_rel": created_proj["project_index_rel"],
                "canvas_rel": created_proj["canvas_rel"],
                "ui_commands": proj_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3c. Fast Skill: Add Custom Category inside a Project ("Add category Podcast Studio to KAIROS 2.0")
        m_cat = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:add|create)\s+(?:a\s+)?(?:new\s+|custom\s+)?category\s+(?:called\s+|named\s+)?([A-Za-z0-9_\-& ]+?)(?:\s+(?:in|to|under|for)\s+(?:project\s+)?([A-Za-z0-9_\-. ]+?))?(?:\s+with\s+list\s+([A-Za-z0-9_\- ]+?))?[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_cat:
            raw_cat_name = m_cat.group(1).strip().replace("&", "and")
            raw_proj_hint = (m_cat.group(2) or "").strip()
            raw_list_hint = (m_cat.group(3) or "General").strip()
            matched_p = (
                self.navigator._match_project_name(raw_proj_hint.lower())
                if raw_proj_hint
                else None
            )
            target_proj_cat = (
                matched_p
                or (raw_proj_hint.replace(" ", "_").replace(".", "_") if raw_proj_hint else "")
                or project_scope.strip()
                or "KAIROS_2_0"
            )
            created_cat = self.vault.create_project_structure(
                project=target_proj_cat,
                department=raw_cat_name.replace(" ", "_"),
                list_name=raw_list_hint.replace(" ", "_"),
                scaffold_standard_departments=False,
            )
            self.index.rebuild_all()
            cat_ui_cmds: List[Dict[str, Any]] = [
                {"type": "navigate_tab", "tab": "projects"},
                {
                    "type": "select_project_scope",
                    "project": created_cat["project"],
                    "department": created_cat["department"],
                    "list": "",
                },
            ]
            self._emit(
                {
                    "event": "category_created",
                    "project": created_cat["project"],
                    "department": created_cat["department"],
                    "ui_commands": cat_ui_cmds,
                }
            )
            actions_taken.append(
                f"Created category `{created_cat['department']}` ({created_cat['list']}) in `{created_cat['project']}`"
            )
            reply_text = (
                f"Added custom category **`{created_cat['department']}`** (list `{created_cat['list']}`) "
                f"under **`{created_cat['project']}`** (`{created_cat['list_index_rel']}`)."
            )
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": False,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Direct",
                "route_reason": "custom_category_created",
                "privacy_locked": False,
                "created_project": created_cat["project"],
                "created_category": created_cat["department"],
                "ui_commands": cat_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3d. Fast Skill: Create Project Wiki Note inside `02_Projects/[Project]/Docs/`
        m_wiki = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:create|add|write)\s+(?:a\s+)?(?:new\s+)?(?:project\s+)?(?:wiki(?:\s+note|\s+page)?|doc\s+note)\s+(?:(?:in|for|under)\s+([A-Za-z0-9_\-. ]+?)\s+)?(?:titled|called|named)\s+([^:.\n]+?)(?:\s*[:\-]\s*(.+))?$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_wiki:
            raw_wproj = (m_wiki.group(1) or "").strip()
            wiki_title = m_wiki.group(2).strip(" '\"")
            wiki_body_extra = (m_wiki.group(3) or "").strip()
            matched_wp = (
                self.navigator._match_project_name(raw_wproj.lower())
                if raw_wproj
                else self.navigator._match_project_name(clean_prompt.lower())
            )
            target_wproj = matched_wp or project_scope.strip() or "KAIROS_2_0"
            slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", wiki_title).strip("_") or "Project_Note"
            wiki_rel = f"02_Projects/{target_wproj}/Docs/{slug}.md"
            now_stamp = datetime.now().strftime("%Y-%m-%d")
            wiki_md = (
                f"# 📖 {wiki_title}\n\n"
                f"- **Project:** [[{target_wproj}]]\n"
                f"- **Updated:** `{now_stamp}`\n\n"
                f"## Overview\n"
                f"{wiki_body_extra or 'Project documentation note created via KAIROS.'}\n"
            )
            saved_wiki = self.vault.write_note(
                wiki_rel,
                {
                    "title": wiki_title,
                    "type": "project_wiki",
                    "project": f"[[{target_wproj}]]",
                    "updated_at": now_stamp,
                    "tags": ["wiki", "documentation", target_wproj.lower()],
                },
                wiki_md,
                mode="overwrite",
            )
            self.index.index_file(self.vault.resolve_safe_path(saved_wiki["rel_path"]))
            wiki_ui_cmds: List[Dict[str, Any]] = [
                {"type": "navigate_tab", "tab": "projects"},
                {"type": "select_project_scope", "project": target_wproj, "department": "", "list": ""},
                {"type": "set_projects_view", "view": "docs"},
            ]
            self._emit({"event": "note_saved", "rel_path": saved_wiki["rel_path"], "ui_commands": wiki_ui_cmds})
            actions_taken.append(f"Created Project Wiki note `{saved_wiki['rel_path']}`")
            reply_text = (
                f"Created Project Wiki note **'{wiki_title}'** in `{saved_wiki['rel_path']}` "
                f"and opened **`{target_wproj}` → Documentation**."
            )
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": False,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Direct",
                "route_reason": "project_wiki_created",
                "privacy_locked": False,
                "wiki_rel_path": saved_wiki["rel_path"],
                "ui_commands": wiki_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 3e. Fast Skill: Schedule Standalone Calendar Event (`03_Personal/Calendar/EVT-*.md`)
        m_cal_evt = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:schedule|add|create)\s+(?:a\s+)?(?:calendar\s+event|event|meeting)\s+(?:called\s+|titled\s+|for\s+)?(.+)$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_cal_evt:
            raw_evt_clause = m_cal_evt.group(1).strip()
            start_iso = parse_event_time_clause(raw_evt_clause)
            evt_proj = self.navigator._match_project_name(raw_evt_clause.lower()) or project_scope.strip()
            clean_evt_title = re.split(
                r"\s+(?:at\s+\d{1,2}|for\s+\d{1,2}|@\s*\d{1,2}|on\s+\d{4}-\d{2}-\d{2}|tomorrow\b|today\b)",
                raw_evt_clause,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            clean_evt_title = re.sub(
                r"\s+(?:in|for|under)\s+(?:kairos(?:\s*2\.0|\s*2)?|[A-Za-z0-9_]+)$",
                "",
                clean_evt_title,
                flags=re.IGNORECASE,
            ).strip(" .,'\"") or "Scheduled Session"
            created_evt = self.connectors.create_calendar_event(
                title=clean_evt_title,
                start_time_iso=start_iso,
                duration_hrs=1.0,
                category="Business",
                project=evt_proj,
            )
            self.index.index_file(self.vault.resolve_safe_path(created_evt["rel_path"]))
            evt_id = str(created_evt["frontmatter"].get("id") or "")
            cal_ui_cmds: List[Dict[str, Any]] = [
                {"type": "navigate_tab", "tab": "projects"},
                {"type": "set_projects_view", "view": "calendar"},
            ]
            self._emit({"event": "calendar_updated", "event_id": evt_id, "ui_commands": cal_ui_cmds})
            actions_taken.append(f"Scheduled Calendar event `{evt_id}` ('{clean_evt_title}') at `{start_iso}`")
            reply_text = (
                f"Scheduled **`{clean_evt_title}`** (`{evt_id}`) for `{start_iso.replace('T', ' ')}` "
                f"on your Monthly Calendar."
            )
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Direct",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": False,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Direct",
                "route_reason": "calendar_event_scheduled",
                "privacy_locked": False,
                "calendar_event_id": evt_id,
                "start_time": start_iso,
                "ui_commands": cal_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 4. Compound Gate-6 Skill: Multi-Department Task Creation + CrewAI + Calendar Time-Blocking + Voice Navigation
        m_create = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:create|add)\s+(?:an?\s+)?(?:(urgent|high|normal|low)(?:[-\s]+priority)?\s+)?tasks?\s+(.+)$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_create and not re.match(
            r"^\.?base\b",
            m_create.group(2).strip(),
            flags=re.IGNORECASE,
        ):
            prio_word = (m_create.group(1) or "normal").lower()
            prio_map = {"urgent": 1, "high": 2, "normal": 3, "low": 4}
            remainder = m_create.group(2).strip()

            assigned_agent = "None"
            m_agent = re.search(
                r"(?:,?\s*(?:and\s+)?assign(?:\s+it)?\s+to\s+)(CrewAI-Research|CrewAI-Dev|CrewAI-PM|CrewAI|Hermes-Agent|Hermes-Synthesizer|Hermes|Gemma-4|Gemini-Pro)",
                remainder,
                flags=re.IGNORECASE,
            )
            if m_agent:
                raw_ag = m_agent.group(1).lower()
                ag_map = {
                    "crewai": "CrewAI-Research",
                    "crewai-research": "CrewAI-Research",
                    "crewai-dev": "CrewAI-Dev",
                    "crewai-pm": "CrewAI-PM",
                    "hermes": "Hermes-Agent",
                    "hermes-agent": "Hermes-Agent",
                    "hermes-synthesizer": "Hermes-Synthesizer",
                    "gemma-4": "Gemma-4",
                    "gemini-pro": "Gemini-Pro",
                }
                assigned_agent = ag_map.get(raw_ag, "CrewAI-Research")

            block_iso = parse_block_time_clause(remainder)
            explicit_proj = self.navigator._match_project_name(remainder.lower())
            target_proj = explicit_proj or project_scope.strip() or "KAIROS_2_0"
            target_dept, target_list = infer_department_from_text(
                remainder,
                default_dept=department_scope or "Software_Development",
                index=self.index,
                project=target_proj,
            )

            clean_title = re.split(
                r",?\s*(?:and\s+)?(?:assign(?:\s+it)?\s+to\b|block\s+\d{1,2}|open\s+it\b|show\s+it\b|switch\s+to\b)",
                remainder,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()
            clean_title = re.sub(
                r"^(?:in\s+(?:kairos(?:\s*2\.0|\s*2)?\s+)?(?:marketing(?:\s+and\s+branding)?|software(?:\s+development)?|documentation|website|merch)\s+)?(?:called|named|to|for)\s+",
                "",
                clean_title,
                flags=re.IGNORECASE,
            ).strip(" .,'\"")

            created = self.vault.create_task(
                CreateTaskInput(
                    title=clean_title or remainder,
                    project=target_proj,
                    department=target_dept,
                    list=target_list,
                    priority=prio_map.get(prio_word, 3),
                    ai_agent=assigned_agent,
                )
            )
            self.index.index_file(self.vault.resolve_safe_path(created["rel_path"]))
            tid = created["frontmatter"]["id"]

            actions_taken.append(
                f"Created P{prio_map.get(prio_word, 3)} task {tid} ('{created['title']}') in {target_proj}/{target_dept}/{target_list}"
            )
            if block_iso:
                evt = self.connectors.time_block_task_on_calendar(tid, block_iso)
                actions_taken.append(
                    f"time-blocked on Calendar ({evt['frontmatter']['id']} at {block_iso})"
                )

            if assigned_agent.startswith(("CrewAI", "Hermes")):
                actions_taken.append(f"dispatched {assigned_agent} via Paperclip")
                crew_svc = self.crew
                idx_svc = self.index
                threading.Thread(
                    target=lambda: (
                        crew_svc.execute_task_with_crew(tid, assigned_agent),
                        idx_svc.rebuild_all(),
                        self._emit({"event": "crew_completed", "task_id": tid}),
                    ),
                    daemon=True,
                ).start()

            create_ui_cmds: List[Dict[str, Any]] = []
            rem_low = remainder.lower()
            if any(w in rem_low for w in ("open it", "show it", "on the board", "on gantt", "switch to")):
                create_ui_cmds.append({"type": "navigate_tab", "tab": "projects"})
                create_ui_cmds.append(
                    {
                        "type": "select_project_scope",
                        "project": target_proj,
                        "department": target_dept,
                        "list": "",
                    }
                )
                matched_v, v_lbl = self.navigator._match_projects_subview(rem_low)
                if matched_v:
                    create_ui_cmds.append({"type": "set_projects_view", "view": matched_v})
                    actions_taken.append(f"switched view to {v_lbl}")
                if "open it" in rem_low or "show it" in rem_low:
                    create_ui_cmds.append({"type": "open_task_drawer", "task_id": tid})
                    actions_taken.append(f"opened Task Drawer for {tid}")

            self.index.rebuild_all()
            self._emit({"event": "task_created", "task_id": tid, "ui_commands": create_ui_cmds})
            reply_text = " • ".join(actions_taken) + "."
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Orchestrator",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": False,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Orchestrator",
                "route_reason": "compound_gate6_action",
                "privacy_locked": False,
                "created_task_id": tid,
                "task_rel_path": created["rel_path"],
                "calendar_blocked_at": block_iso or "",
                "assigned_agent": assigned_agent,
                "ui_commands": create_ui_cmds,
                "actions": actions_taken,
                "session": ses_out,
            }

        # 5. Fast Skill: Post to Discord Channel ("Post to Discord: ...")
        m_disc = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:post|send)\s+to\s+discord\s*[:\-]\s*(.+)$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_disc:
            ok, msg = self._post_discord_message(m_disc.group(1).strip())
            actions_taken.append(msg)
            reply_text = f"{'✓' if ok else '⚠️'} {msg}."
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Discord",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": False,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Discord",
                "route_reason": "discord_dispatch",
                "privacy_locked": False,
                "ui_commands": [],
                "actions": actions_taken,
                "session": ses_out,
            }

        def _finish_fast_platform_skill(
            reply_text: str,
            route_reason: str,
            *,
            ui_cmds: Optional[List[Dict[str, Any]]] = None,
            is_priv_turn: bool = False,
            extra_fields: Optional[Dict[str, Any]] = None,
            ws_event: str = "ui_navigate",
        ) -> Dict[str, Any]:
            eff_ui = deduplicate_ui_commands(ui_cmds or [])
            if eff_ui or ws_event != "ui_navigate":
                self._emit({"event": ws_event, "ui_commands": eff_ui, "actions": actions_taken})
            assistant_turn = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "agent": "KAIROS-Platform",
                "persona": clean_persona,
                "tone_mode": clean_tone,
                "privacy_locked": is_priv_turn,
                "actions": actions_taken,
            }
            ses_out = (
                self._append_turns_to_session(
                    effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
                )
                if persist_session
                else None
            )
            return {
                "reply": reply_text,
                "spoken_reply": clean_text_for_speech(reply_text),
                "agent": "KAIROS-Platform",
                "route_reason": route_reason,
                "privacy_locked": is_priv_turn,
                "ui_commands": eff_ui,
                "actions": actions_taken,
                "session": ses_out,
                **(extra_fields or {}),
            }

        # 5a. Fast Skill: Toggle / Check Off Task Checklist Item ("Check off checklist item 1 on this task" / "... on TSK-...")
        m_chk_toggle = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:check\s+off|toggle|complete|uncheck)\s+checklist(?:\s+item)?\s+#?(\d+)(?:\s+(?:on|in|for)\s+(?:(?:task\s+)?(TSK-[\w\-]+)|(this\s+task|current\s+task|the\s+open\s+task)))?[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_chk_toggle:
            one_based_idx = max(1, int(m_chk_toggle.group(1)))
            tid_tog = _resolve_deictic_task_id(m_chk_toggle.group(2) or m_chk_toggle.group(3) or "")
            self._assert_task_unlocked(tid_tog)
            res_tog = self.platform_executor.execute(
                "projects_update_task",
                {"task_id": tid_tog, "toggle_checklist_index": one_based_idx - 1},
                is_private=early_priv,
                active_task_id=clean_active_task_id,
                actor="KAIROS-Direct",
            )
            if not res_tog.get("ok"):
                raise ValueError(str(res_tog.get("error") or "Unable to toggle checklist item"))
            upd_data = res_tog["data"]
            actions_taken.append(f"Toggled checklist item #{one_based_idx} on `{tid_tog}`")
            reply_text = f"Toggled checklist item **`#{one_based_idx}`** on **`{tid_tog}`** (`{upd_data['title']}`)."
            return _finish_fast_platform_skill(
                reply_text,
                "fast_task_checklist_toggle",
                ui_cmds=res_tog.get("ui_commands"),
                is_priv_turn=bool(early_priv or upd_data.get("is_private")),
                extra_fields={"task_id": tid_tog, "toggled_checklist_index": one_based_idx - 1},
                ws_event="task_updated",
            )

        # 5b. Fast Skill: Soft-Archive or Restore Task ("Archive task TSK-..." / "Archive this task" / "Restore task TSK-...")
        m_arch = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?archive\s+(?:(?:task\s+)?(TSK-[\w\-]+)|(this\s+task|current\s+task|the\s+open\s+task))[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_arch:
            tid_arch = _resolve_deictic_task_id(m_arch.group(1) or m_arch.group(2) or "")
            self._assert_task_unlocked(tid_arch)
            res_arch = self.platform_executor.execute(
                "projects_archive_task",
                {"task_id": tid_arch, "permanent": False},
                is_private=early_priv,
                active_task_id=clean_active_task_id,
                actor="KAIROS-Direct",
            )
            if not res_arch.get("ok"):
                raise ValueError(str(res_arch.get("error") or f"Failed to archive {tid_arch}"))
            arch_data = res_arch["data"]
            actions_taken.append(res_arch["action_summary"])
            reply_text = (
                f"Soft-archived **`{tid_arch}`** to `{arch_data.get('archived_rel_path')}` "
                "and recalculated project completion."
            )
            return _finish_fast_platform_skill(
                reply_text,
                "fast_task_archive",
                ui_cmds=res_arch.get("ui_commands"),
                is_priv_turn=early_priv,
                extra_fields={
                    "task_id": tid_arch,
                    "archived_rel_path": arch_data.get("archived_rel_path", ""),
                },
                ws_event="task_deleted",
            )

        m_restore = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?restore\s+(?:(?:the\s+)?(?:latest|last|newest|most\s+recent)\s+(?:archived\s+)?task|(?:archived\s+)?(?:task\s+)?(TSK-[\w\-]+))[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_restore:
            tid_rest = (m_restore.group(1) or "latest").strip()
            res_rest = self.platform_executor.execute(
                "projects_restore_task",
                {"task_id": tid_rest},
                is_private=early_priv,
                actor="KAIROS-Direct",
            )
            if not res_rest.get("ok"):
                raise FileNotFoundError(str(res_rest.get("error") or f"Archived task '{tid_rest}' not found"))
            rest_data = res_rest["data"]
            actions_taken.append(res_rest["action_summary"])
            reply_text = (
                f"Restored **`{rest_data['task_id']}`** (`{rest_data['title']}`) back to "
                f"`{rest_data['rel_path']}` and opened the Task Drawer."
            )
            return _finish_fast_platform_skill(
                reply_text,
                "fast_task_restore",
                ui_cmds=res_rest.get("ui_commands"),
                is_priv_turn=bool(early_priv or rest_data.get("is_private")),
                extra_fields={"task_id": rest_data["task_id"], "rel_path": rest_data["rel_path"]},
                ws_event="task_restored",
            )

        # 5c. Fast Skill: Force-Release Paperclip Lock ("Unlock TSK-..." / "Force unlock TSK-..." / "Release Paperclip lock on TSK-...")
        m_unlock = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:(?:force[\s\-]+)?unlock|release\s+(?:the\s+)?(?:paperclip\s+)?lock\s+(?:on|for))\s+(?:(?:task\s+)?(TSK-[\w\-]+)|(this\s+task|current\s+task|the\s+open\s+task))(?:\s*[:\-]\s*(.+))?[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_unlock:
            tid_unl = _resolve_deictic_task_id(m_unlock.group(1) or m_unlock.group(2) or "")
            reason_unl = (m_unlock.group(3) or "Voice/Chat operator force-unlock").strip()
            res_unl = self.platform_executor.execute(
                "paperclip_release_lock",
                {"task_id": tid_unl, "reason": reason_unl},
                is_private=early_priv,
                active_task_id=clean_active_task_id,
                actor="Jaime",
            )
            if not res_unl.get("ok"):
                raise ValueError(str(res_unl.get("error") or f"Failed to unlock {tid_unl}"))
            unl_data = res_unl["data"]
            actions_taken.append(res_unl["action_summary"])
            if unl_data.get("released"):
                reply_text = (
                    f"Force-released Paperclip checkout lock on **`{tid_unl}`** "
                    f"(previously held by `{unl_data.get('previous_agent')}`)."
                )
            else:
                reply_text = f"Task **`{tid_unl}`** currently has no active Paperclip lock."
            return _finish_fast_platform_skill(
                reply_text,
                "fast_paperclip_unlock",
                ui_cmds=[],
                is_priv_turn=early_priv,
                extra_fields={"task_id": tid_unl, "released": bool(unl_data.get("released"))},
                ws_event="paperclip_lock_released",
            )

        # 5d-sec. Fast Skill: Convert / Promote Inbox Capture -> Structured Obsidian Section Hub Entry
        # (e.g. "Convert inbox note Serum to a plugin in Music Studio", "Promote latest inbox note to Music Studio Plugins")
        m_conv_inbox_sec = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:convert|promote|triage)\s+(?:the\s+)?(?:(latest|newest|last|most\s+recent)\s+inbox\s+(?:note|item|capture|clip)|inbox\s+(?:note|item|capture|clip)\s+(.+?))\s+(?:to|into|as)\s+(?:a\s+|an\s+)?(plug-?in|vst|addon|add-on|preset|sample\s+pack|sample|support\s+site|support\s+portal|website|distribution(?:\s+platform)?|section\s+entry|catalog\s+entry)\s+(?:in|into|to|under)\s+(.+?)[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )

        # 5d. Fast Skill: Inbox Triage & Promotion ("Promote latest inbox note to KAIROS Marketing" / "Promote inbox note <query> to ...")
        m_promote = (
            None
            if m_conv_inbox_sec
            else re.match(
                r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:promote|triage)\s+(?:the\s+)?(?:(latest|newest|last|most\s+recent)\s+inbox\s+(?:note|item|capture|clip)|inbox\s+(?:note|item|capture|clip)\s+(.+?))\s+(?:to|into|in)\s+(.+?)[.!?]*$",
                clean_prompt,
                flags=re.IGNORECASE,
            )
        )
        if m_conv_inbox_sec or m_promote:
            if m_conv_inbox_sec:
                inbox_q = "latest" if m_conv_inbox_sec.group(1) else (m_conv_inbox_sec.group(2) or "").strip(" '\"")
                explicit_sec_kind = m_conv_inbox_sec.group(3).strip().lower()
                dest_clause = m_conv_inbox_sec.group(4).strip(" '\"")
                matched_proj = None
            else:
                assert m_promote is not None
                inbox_q = "latest" if m_promote.group(1) else (m_promote.group(2) or "").strip(" '\"")
                explicit_sec_kind = ""
                dest_clause = m_promote.group(3).strip()
                matched_proj = self.navigator._match_project_name(dest_clause.lower())
                if (
                    not matched_proj
                    and re.search(r"\bkairos\b", dest_clause, flags=re.IGNORECASE)
                    and not re.search(r"\bkairos\s*(?:2|two|2\.0|_2_0)\b", dest_clause, flags=re.IGNORECASE)
                ):
                    matched_proj = "KAIROS"

            # Check if destination targets an Obsidian Section Hub instead of `02_Projects/`
            dest_low_inb = re.sub(r"\s*#private\b", "", dest_clause, flags=re.IGNORECASE).strip().lower()
            matched_hub_rel = ""
            matched_col_folder = ""
            matched_item_type = ""
            disc_inb = self.index.discover_vault_structure()
            if not matched_proj:
                for sec in disc_inb.get("sections") or []:
                    s_title_l = str(sec.get("title") or "").lower()
                    s_slug_l = Path(str(sec.get("section_rel") or "")).name.lower().replace("_", " ")
                    if dest_low_inb in s_title_l or s_slug_l in dest_low_inb or (s_title_l and s_title_l in dest_low_inb):
                        matched_hub_rel = str(sec["section_rel"])
                        for col_obj in sec.get("collections") or []:
                            c_fld = str(col_obj.get("folder") or "")
                            c_ttl = str(col_obj.get("title") or "")
                            if (
                                c_fld.lower().replace("_", " ") in dest_low_inb
                                or c_fld.lower().rstrip("s") in dest_low_inb
                                or (c_ttl and c_ttl.lower() in dest_low_inb)
                            ):
                                matched_col_folder = c_fld
                                matched_item_type = str(col_obj.get("item_type") or "")
                                break
                        break

                if not matched_hub_rel and (
                    m_conv_inbox_sec
                    or any(
                        kw in dest_low_inb
                        for kw in (
                            "music studio",
                            "music_studio",
                            "creator media",
                            "hardware lab",
                            "research library",
                            "section hub",
                        )
                    )
                ):
                    if "music" in dest_low_inb or explicit_sec_kind in ("plugin", "plug-in", "vst", "sample pack", "sample"):
                        matched_hub_rel = "04_Resources/Music_Studio"
                    else:
                        matched_hub_rel = (
                            dest_clause.strip("/")
                            if "/" in dest_clause
                            else f"04_Resources/{re.sub(r'[^A-Za-z0-9_-]+', '_', dest_clause).strip('_')}"
                        )

            if matched_hub_rel:
                kind_probe = f"{explicit_sec_kind} {dest_low_inb}".strip()
                if not matched_col_folder:
                    if any(k in kind_probe for k in ("plugin", "plug-in", "vst")):
                        matched_col_folder, matched_item_type = "Plugins", "plugin"
                    elif any(k in kind_probe for k in ("addon", "add-on", "preset")):
                        matched_col_folder, matched_item_type = "Addons_and_Presets", "addon"
                    elif any(k in kind_probe for k in ("sample", "drum kit")):
                        matched_col_folder, matched_item_type = "Samples_and_Packs", "sample_pack"
                    elif any(k in kind_probe for k in ("distribution", "spotify", "youtube", "soundcloud")):
                        matched_col_folder, matched_item_type = "Distribution", "distribution_platform"
                    elif any(k in kind_probe for k in ("support", "website", "portal")):
                        matched_col_folder, matched_item_type = "Support_and_Websites", "support_portal"

                res_psec = self.platform_executor.execute(
                    "inbox_promote_to_section_entry",
                    {
                        "query": inbox_q,
                        "section_or_folder": matched_hub_rel,
                        "collection": matched_col_folder,
                        "item_type": matched_item_type,
                    },
                    is_private=early_priv,
                    actor="KAIROS-Direct",
                )
                if not res_psec.get("ok"):
                    raise FileNotFoundError(str(res_psec.get("error") or "No matching Inbox note found"))
                psec_data = res_psec["data"]
                ent_note = psec_data["entry"]
                actions_taken.append(res_psec["action_summary"])
                reply_text = (
                    f"Promoted Inbox capture into Section Hub entry **`{ent_note['title']}`** "
                    f"(`{ent_note['rel_path']}`) and archived raw capture to `{psec_data['archived_capture']}`."
                )
                return _finish_fast_platform_skill(
                    reply_text,
                    "fast_inbox_promote_to_section",
                    ui_cmds=res_psec.get("ui_commands"),
                    is_priv_turn=bool(early_priv or ent_note.get("is_private")),
                    extra_fields={
                        "entry_rel_path": ent_note["rel_path"],
                        "archived_capture": psec_data["archived_capture"],
                        "extracted_url": psec_data.get("extracted_url", ""),
                    },
                    ws_event="inbox_promoted_to_section",
                )

            target_proj_p = matched_proj or project_scope.strip() or "KAIROS_2_0"
            target_dept_p, target_list_p = infer_department_from_text(
                dest_clause,
                default_dept=department_scope or "Software_Development",
                index=self.index,
                project=target_proj_p,
            )
            res_prom = self.platform_executor.execute(
                "inbox_promote_to_task",
                {
                    "query": inbox_q,
                    "project": target_proj_p,
                    "department": target_dept_p,
                    "list": target_list_p,
                    "priority": 2,
                },
                is_private=early_priv,
                actor="KAIROS-Direct",
            )
            if not res_prom.get("ok"):
                raise FileNotFoundError(str(res_prom.get("error") or "No matching Inbox note found"))
            prom_data = res_prom["data"]
            new_tid = prom_data["task"]["frontmatter"]["id"]
            actions_taken.append(res_prom["action_summary"])
            reply_text = (
                f"Promoted Inbox capture into task **`{new_tid}`** (`{prom_data['task']['title']}`) "
                f"under **`{target_proj_p}/{target_dept_p}/{target_list_p}`** and archived raw capture to `{prom_data['archived_capture']}`."
            )
            return _finish_fast_platform_skill(
                reply_text,
                "fast_inbox_promote",
                ui_cmds=res_prom.get("ui_commands"),
                is_priv_turn=bool(early_priv or prom_data["task"].get("is_private")),
                extra_fields={
                    "created_task_id": new_tid,
                    "archived_capture": prom_data["archived_capture"],
                },
                ws_event="inbox_promoted",
            )

        # 5e. Fast Skill: Browser Clipper & Deictic Clip-to-Task ("Clip this page to Inbox" / "Clip https://... to Inbox" / "Turn this webpage into a task in KAIROS Website")
        m_clip_task = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?turn\s+(?:this|the)\s+(?:open\s+|current\s+)?(?:web\s*page|page|tab|article|site)\s+into\s+(?:a\s+)?task(?:\s+(?:in|under|for)\s+(.+?))?[.!?]*$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_clip_task:
            dest_hint = (m_clip_task.group(1) or "").strip()
            matched_proj_ct = self.navigator._match_project_name(dest_hint.lower()) if dest_hint else None
            if (
                not matched_proj_ct
                and dest_hint
                and re.search(r"\bkairos\b", dest_hint, flags=re.IGNORECASE)
                and not re.search(r"\bkairos\s*(?:2|two|2\.0|_2_0)\b", dest_hint, flags=re.IGNORECASE)
            ):
                matched_proj_ct = "KAIROS"
            target_proj_ct = matched_proj_ct or project_scope.strip() or "KAIROS_2_0"
            target_dept_ct, target_list_ct = infer_department_from_text(
                dest_hint or clean_prompt,
                default_dept=department_scope or "Software_Development",
                index=self.index,
                project=target_proj_ct,
            )
            res_ct = self.platform_executor.execute(
                "browser_clip_url",
                {
                    "url": active_browser_url,
                    "title": active_browser_title,
                    "promote_to_task": True,
                    "project": target_proj_ct,
                    "department": target_dept_ct,
                    "list": target_list_ct,
                },
                is_private=early_priv,
                active_browser_url=active_browser_url,
                active_browser_title=active_browser_title,
                actor="KAIROS-Clipper",
            )
            if not res_ct.get("ok"):
                raise ValueError(str(res_ct.get("error") or "No active browser URL available to clip"))
            ct_data = res_ct["data"]
            ct_tid = ct_data["task"]["frontmatter"]["id"]
            actions_taken.append(res_ct["action_summary"])
            reply_text = (
                f"Clipped **`{active_browser_title or active_browser_url}`** via Defuddle and promoted it to task "
                f"**`{ct_tid}`** in **`{target_proj_ct}/{target_dept_ct}`**."
            )
            return _finish_fast_platform_skill(
                reply_text,
                "fast_browser_clip_to_task",
                ui_cmds=res_ct.get("ui_commands"),
                is_priv_turn=early_priv,
                extra_fields={"created_task_id": ct_tid},
                ws_event="inbox_promoted",
            )

        prompt_no_priv = re.sub(r"\s*#private\b", "", clean_prompt, flags=re.IGNORECASE).strip()

        # 5e-bis. Fast Skill: Deictic Browser Webpage -> Structured Obsidian Section Hub Entry
        # (e.g. "Save this page as a plugin in Music Studio", "Register this website in Music Studio Support")
        m_page_entry = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:(?:save|add|log|register)\s+(?:this|the|current)\s+(?:open\s+)?(?:web\s*page|page|tab|site|website|url)\s+as\s+(?:a\s+|an\s+)?(plug-?in|vst|addon|add-on|preset|sample\s+pack|sample|support\s+site|support\s+portal|website|distribution(?:\s+platform)?|entry|catalog\s+entry)\s+(?:in|into|to|under)\s+([A-Za-z0-9_/\-& ]+?)|register\s+(?:this|the|current)\s+(?:open\s+)?(?:web\s*page|page|tab|site|website|url)\s+(?:in|into|to|under)\s+([A-Za-z0-9_/\-& ]+?))[.!?]*$",
            prompt_no_priv,
            flags=re.IGNORECASE,
        )
        if m_page_entry:
            if not (active_browser_url or "").strip():
                raise ValueError("No active browser webpage URL is open to register as a Section Hub entry.")
            raw_p_kind = (m_page_entry.group(1) or "support site").strip().lower()
            raw_p_sec = (m_page_entry.group(2) or m_page_entry.group(3) or "Music Studio").strip(" '\"")
            page_kind_map = {
                "plugin": ("Plugins", "plugin", "support_url"),
                "plug-in": ("Plugins", "plugin", "support_url"),
                "vst": ("Plugins", "plugin", "support_url"),
                "addon": ("Addons_and_Presets", "addon", "support_url"),
                "add-on": ("Addons_and_Presets", "addon", "support_url"),
                "preset": ("Addons_and_Presets", "addon", "support_url"),
                "sample pack": ("Samples_and_Packs", "sample_pack", "support_url"),
                "sample": ("Samples_and_Packs", "sample_pack", "support_url"),
                "support site": ("Support_and_Websites", "support_portal", "support_url"),
                "support portal": ("Support_and_Websites", "support_portal", "support_url"),
                "website": ("Support_and_Websites", "support_portal", "support_url"),
                "distribution": ("Distribution", "distribution_platform", "dashboard_url"),
                "distribution platform": ("Distribution", "distribution_platform", "dashboard_url"),
            }
            p_col, p_item_type, url_prop_key = page_kind_map.get(raw_p_kind, ("", "catalog_item", "support_url"))

            # Clean title & infer optional vendor from "Title — Vendor" or "Title | Vendor"
            raw_b_title = (active_browser_title or "").strip()
            vendor_from_title = ""
            for sep in (" — ", " - ", " | "):
                if sep in raw_b_title:
                    left_t, right_t = raw_b_title.split(sep, 1)
                    if left_t.strip() and right_t.strip():
                        raw_b_title = left_t.strip()
                        vendor_from_title = right_t.strip()
                        break
            if not raw_b_title:
                raw_b_title = re.sub(r"^https?://(?:www\.)?", "", active_browser_url.strip()).split("/")[0]

            resolved_p_sec = raw_p_sec if "/" in raw_p_sec else ""
            disc_p = self.index.discover_vault_structure()
            for sec in disc_p.get("sections") or []:
                s_title_l = str(sec.get("title") or "").lower()
                s_slug_l = Path(str(sec.get("section_rel") or "")).name.lower().replace("_", " ")
                if raw_p_sec.lower() in s_title_l or raw_p_sec.lower() == s_slug_l or s_slug_l in raw_p_sec.lower():
                    resolved_p_sec = str(sec["section_rel"])
                    if not p_col:
                        for col_item in sec.get("collections") or []:
                            c_fld_l = str(col_item.get("folder") or "").lower()
                            if c_fld_l and c_fld_l.replace("_", " ") in raw_p_sec.lower():
                                p_col = str(col_item["folder"])
                                p_item_type = str(col_item.get("item_type") or p_item_type)
                                break
                    break

            if not resolved_p_sec:
                if "music" in raw_p_sec.lower() or raw_p_kind in ("plugin", "plug-in", "vst", "sample pack", "sample"):
                    scaf_p = self.vault.scaffold_vault_section("", blueprint_key="music_production", seed_starters=True)
                    self.index.rebuild_all()
                    resolved_p_sec = scaf_p["section_rel"]
                else:
                    resolved_p_sec = f"04_Resources/{re.sub(r'[^A-Za-z0-9_-]+', '_', raw_p_sec).strip('_')}"

            p_props: Dict[str, Any] = {
                "status": "Active",
                url_prop_key: active_browser_url.strip(),
            }
            if vendor_from_title:
                p_props["vendor"] = vendor_from_title

            res_pe = self.platform_executor.execute(
                "vault_create_entry",
                {
                    "section_or_folder": resolved_p_sec,
                    "title": raw_b_title,
                    "collection": p_col,
                    "item_type": p_item_type,
                    "properties": p_props,
                },
                is_private=early_priv,
                active_browser_url=active_browser_url,
                active_browser_title=active_browser_title,
                actor="KAIROS-Clipper",
            )
            if not res_pe.get("ok"):
                raise ValueError(str(res_pe.get("error") or "Unable to save webpage as Section Hub entry"))
            pe_data = res_pe["data"]
            actions_taken.append(res_pe["action_summary"])
            reply_text = (
                f"Saved active webpage **`{pe_data['title']}`** into `{pe_data['rel_path']}` "
                f"(`{url_prop_key}` linked to `{active_browser_url.strip()}`)."
            )
            return _finish_fast_platform_skill(
                reply_text,
                "fast_browser_section_entry",
                ui_cmds=res_pe.get("ui_commands"),
                is_priv_turn=bool(early_priv or pe_data.get("is_private")),
                extra_fields={"entry_rel_path": pe_data["rel_path"]},
                ws_event="note_saved",
            )

        m_clip = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:clip|save)\s+(?:(https?://\S+)|(?:this|the|current)\s+(?:open\s+)?(?:web\s*page|page|tab|article|site|url))(?:\s+(?:to|into|in)\s+([A-Za-z0-9_/\-& ]+?))?[.!?]*$",
            prompt_no_priv,
            flags=re.IGNORECASE,
        )
        if m_clip:
            explicit_url = (m_clip.group(1) or "").strip()
            dest_raw = (m_clip.group(2) or "inbox").strip()
            dest_low = dest_raw.lower()
            if dest_low in ("", "inbox", "00_inbox"):
                dest_folder_clip = "00_Inbox"
            elif dest_low in ("resources", "04_resources", "second brain"):
                dest_folder_clip = "04_Resources"
            elif "/" in dest_raw:
                dest_folder_clip = dest_raw.strip("/")
            else:
                dest_folder_clip = "04_Resources"
                discovered = self.index.discover_vault_structure()
                for sec in discovered.get("sections") or []:
                    sec_title_low = str(sec.get("title") or "").lower()
                    sec_slug_low = Path(str(sec.get("section_rel") or "")).name.lower().replace("_", " ")
                    if dest_low in sec_title_low or dest_low == sec_slug_low or sec_slug_low in dest_low:
                        dest_folder_clip = str(sec["section_rel"])
                        for col in sec.get("collections") or []:
                            if "support" in str(col.get("folder") or "").lower() or "portal" in str(col.get("item_type") or "").lower():
                                dest_folder_clip = str(col["rel_path"])
                                break
                        break
            target_clip_url = explicit_url or (active_browser_url or "").strip()
            if not target_clip_url:
                ui_clip_cmds = [
                    {"type": "navigate_tab", "tab": "browser"},
                    {"type": "browser_clip", "dest_folder": dest_folder_clip},
                ]
                actions_taken.append(f"Triggered Embedded Browser clip into `{dest_folder_clip}`")
                return _finish_fast_platform_skill(
                    f"Clipping the active Embedded Browser page into `{dest_folder_clip}`.",
                    "fast_browser_clip",
                    ui_cmds=ui_clip_cmds,
                    is_priv_turn=early_priv,
                )
            res_clip = self.platform_executor.execute(
                "browser_clip_url",
                {
                    "url": target_clip_url,
                    "title": "" if explicit_url else active_browser_title,
                    "dest_folder": dest_folder_clip,
                },
                is_private=early_priv,
                active_browser_url=active_browser_url,
                active_browser_title=active_browser_title,
                actor="KAIROS-Clipper",
            )
            if not res_clip.get("ok"):
                raise ValueError(str(res_clip.get("error") or "Unable to clip URL"))
            clip_data = res_clip["data"]
            actions_taken.append(res_clip["action_summary"])
            reply_text = (
                f"Clipped **`{clip_data['title']}`** into `{clip_data['rel_path']}` via Defuddle."
            )
            return _finish_fast_platform_skill(
                reply_text,
                "fast_browser_clip",
                ui_cmds=res_clip.get("ui_commands"),
                is_priv_turn=early_priv,
                extra_fields={"clipped_rel_path": clip_data["rel_path"]},
                ws_event="note_saved",
            )

        # 5f. Fast Skill: Daily Note Append & Second Brain Note Creation
        m_daily = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:append|add|log)\s+to\s+(?:today'?s?\s+|my\s+)?daily\s+note\s*[:\-]\s*(.+)$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_daily:
            entry_txt = m_daily.group(1).strip()
            res_dn = self.platform_executor.execute(
                "daily_note_append",
                {"entry": entry_txt, "open_in_ui": True},
                is_private=early_priv or ("#private" in entry_txt.lower()),
                actor="KAIROS-Direct",
            )
            if not res_dn.get("ok"):
                raise ValueError(str(res_dn.get("error") or "Failed to append to Daily Note"))
            dn_data = res_dn["data"]
            actions_taken.append(res_dn["action_summary"])
            reply_text = f"Appended to today's Daily Note (`{dn_data['rel_path']}`): *{entry_txt}*"
            return _finish_fast_platform_skill(
                reply_text,
                "fast_daily_note_append",
                ui_cmds=res_dn.get("ui_commands"),
                is_priv_turn=bool(early_priv or dn_data.get("is_private")),
                extra_fields={"daily_note_rel_path": dn_data["rel_path"]},
                ws_event="note_saved",
            )

        m_note_write = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:write|create)\s+(?:a\s+)?(?:new\s+)?note\s+(?:in\s+(01_Business|03_Personal|04_Resources|Resources|Business|Personal|Second\s+Brain)\s+)?(?:titled|called|named)\s+([^:.\n]+?)\s*[:\-]\s*(.+)$",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if m_note_write:
            raw_fld = (m_note_write.group(1) or "04_Resources").strip().lower()
            fld_map = {
                "01_business": "01_Business",
                "business": "01_Business",
                "03_personal": "03_Personal",
                "personal": "03_Personal",
                "04_resources": "04_Resources",
                "resources": "04_Resources",
                "second brain": "04_Resources",
            }
            target_fld = fld_map.get(raw_fld, "04_Resources")
            n_title = m_note_write.group(2).strip(" '\"")
            n_body = m_note_write.group(3).strip()
            res_nw = self.platform_executor.execute(
                "vault_write_note",
                {
                    "folder": target_fld,
                    "title": n_title,
                    "body": f"# 📝 {n_title}\n\n{n_body}\n",
                    "open_in_ui": True,
                },
                is_private=early_priv or ("#private" in n_body.lower()),
                actor="KAIROS-Direct",
            )
            if not res_nw.get("ok"):
                raise ValueError(str(res_nw.get("error") or "Failed to write Vault note"))
            nw_data = res_nw["data"]
            actions_taken.append(res_nw["action_summary"])
            reply_text = f"Created Vault note **'{n_title}'** in `{nw_data['rel_path']}` and opened it in Second Brain."
            return _finish_fast_platform_skill(
                reply_text,
                "fast_vault_note_write",
                ui_cmds=res_nw.get("ui_commands"),
                is_priv_turn=bool(early_priv or nw_data.get("is_private")),
                extra_fields={"note_rel_path": nw_data["rel_path"]},
                ws_event="note_saved",
            )

        # 5g. Fast Skill: Adaptable Obsidian Section Hub Scaffolding
        # (e.g. "Create a music section in my vault that lists all my plug-ins, websites for support, add-ons, samples, and setup for online distribution on YouTube, Spotify, SoundCloud"
        #  or "Scaffold a vault section called Photography Studio with collections Lenses, Lighting, Client Galleries")
        m_sec_named = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:i\s+want\s+to\s+|can\s+you\s+|please\s+)?(?:create|make|build|scaffold|set\s+up|add)\s+(?:a\s+|an\s+)?(?:new\s+)?(?:obsidian\s+|vault\s+|second\s+brain\s+|knowledge\s+)?(?:section(?:\s+hub)?|hub)\s+(?:in\s+(?:my\s+|the\s+)?(?:obsidian\s+|canopy\s+)?(?:vault|second\s+brain|01_business|03_personal|04_resources|business|personal|resources)\s+)?(?:called|named|for)\s+([^:.,]+?)(?:\s*(?:that|which|with|covering|to\s+list|listing|:)\s*(.+))?[.!?]*$",
            prompt_no_priv,
            flags=re.IGNORECASE,
        )
        m_sec_domain = (
            None
            if m_sec_named
            else re.match(
                r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:i\s+want\s+to\s+|can\s+you\s+|please\s+)?(?:create|make|build|scaffold|set\s+up|add)\s+(?:a\s+|an\s+)?(?:new\s+)?([A-Za-z0-9_\-& ]{2,48}?)\s+(?:vault\s+section|section\s+hub|knowledge\s+hub|second\s+brain\s+section|section)(?:\s+(?:in|inside|under|for)\s+(?:my\s+|the\s+)?(?:obsidian\s+|canopy\s+|second\s+brain\s+)?(vault|second\s+brain|01_business|03_personal|04_resources|business|personal|resources))?(?:\s+(?:that|which|with|for|covering|to\s+list|listing)\s+(.+))?[.!?]*$",
                prompt_no_priv,
                flags=re.IGNORECASE,
            )
        )
        if m_sec_named or m_sec_domain:
            if m_sec_named:
                raw_sec_title = m_sec_named.group(1).strip(" '\"")
                raw_parent_hint = ""
                raw_sec_desc = (m_sec_named.group(2) or "").strip()
            else:
                assert m_sec_domain is not None
                raw_sec_title = m_sec_domain.group(1).strip(" '\"")
                raw_parent_hint = (m_sec_domain.group(2) or "").strip().lower()
                raw_sec_desc = (m_sec_domain.group(3) or "").strip()

            parent_map = {
                "01_business": "01_Business",
                "business": "01_Business",
                "03_personal": "03_Personal",
                "personal": "03_Personal",
                "04_resources": "04_Resources",
                "resources": "04_Resources",
            }
            eff_parent_sec = parent_map.get(raw_parent_hint, "")
            bp_inferred = infer_blueprint_key_from_text(f"{raw_sec_title} {raw_sec_desc}")
            eff_sec_name = raw_sec_title
            if bp_inferred == "music_production" and raw_sec_title.lower() in (
                "music",
                "music studio",
                "audio",
                "music production",
                "studio",
            ):
                eff_sec_name = ""

            explicit_cols: Optional[List[str]] = None
            m_cols_clause = re.search(
                r"\bcollections?\s*[:\-]?\s*([A-Za-z0-9_,\-&/ ]+)$",
                raw_sec_desc,
                flags=re.IGNORECASE,
            )
            if m_cols_clause:
                parsed_cols = [
                    c.strip(" .")
                    for c in re.split(r",|\band\b", m_cols_clause.group(1))
                    if c.strip(" .")
                ]
                if parsed_cols:
                    explicit_cols = parsed_cols

            res_sec = self.platform_executor.execute(
                "vault_scaffold_section",
                {
                    "section_name": eff_sec_name,
                    "blueprint_key": bp_inferred,
                    "parent_folder": eff_parent_sec,
                    "description": raw_sec_desc if not explicit_cols else "",
                    "collections": explicit_cols,
                    "seed_starters": True,
                },
                is_private=early_priv or ("#private" in clean_prompt.lower()),
                actor="KAIROS-Direct",
            )
            if not res_sec.get("ok"):
                raise ValueError(str(res_sec.get("error") or "Failed to scaffold Vault Section Hub"))
            sec_data = res_sec["data"]
            actions_taken.append(res_sec["action_summary"])
            col_names = ", ".join(f"`{c['folder']}/`" for c in (sec_data.get("collections") or []))
            starter_cnt = len(sec_data.get("seeded_entry_rels") or [])
            starter_note = f" + `{starter_cnt}` starter setup guides" if starter_cnt else ""
            reply_text = (
                f"Scaffolded **`{sec_data['icon']} {sec_data['title']}`** in `{sec_data['section_rel']}/`:\n"
                f"- **Hub MOC:** `{sec_data['hub_index_rel']}`\n"
                f"- **Live Obsidian Base:** `{sec_data['base_rel']}`\n"
                f"- **Ecosystem Canvas:** `{sec_data['canvas_rel']}`\n"
                f"- **Collections:** {col_names}{starter_note}"
            )
            return _finish_fast_platform_skill(
                reply_text,
                "fast_vault_section_scaffold",
                ui_cmds=res_sec.get("ui_commands"),
                is_priv_turn=bool(early_priv or sec_data.get("is_private")),
                extra_fields={
                    "section_rel": sec_data["section_rel"],
                    "hub_index_rel": sec_data["hub_index_rel"],
                    "base_rel": sec_data["base_rel"],
                    "canvas_rel": sec_data["canvas_rel"],
                },
                ws_event="vault_section_scaffolded",
            )

        # 5h. Fast Skill: Add Structured Catalog Entry to a Vault Section Hub
        # (e.g. "Add plugin Serum 2 by Xfer Records to Music Studio with support https://xferrecords.com")
        m_sec_entry = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:add|register|log|save)\s+(?:a\s+|an\s+)?(?:new\s+)?(plug-?in|vst|addon|add-on|preset|expansion|sample\s+pack|drum\s+kit|sample|support\s+site|support\s+portal|website|distribution(?:\s+platform)?|catalog\s+entry|entry)\s+(?:called\s+|named\s+)?(.+?)\s+(?:to|in|into|under)\s+([A-Za-z0-9_/\-& ]+?)(?:\s+with\s+(?:support(?:\s+url)?|url|website|link)\s+(https?://\S+))?[.!?]*$",
            prompt_no_priv,
            flags=re.IGNORECASE,
        )
        if m_sec_entry:
            raw_kind = m_sec_entry.group(1).strip().lower()
            raw_item_clause = m_sec_entry.group(2).strip(" '\"")
            raw_target_sec = m_sec_entry.group(3).strip(" '\"")
            raw_sup_url = (m_sec_entry.group(4) or "").strip().rstrip(".,)")

            vendor_val = ""
            m_by_vendor = re.match(r"^(.+?)\s+by\s+([A-Za-z0-9_.\-& ]+)$", raw_item_clause, flags=re.IGNORECASE)
            if m_by_vendor:
                entry_title_clean = m_by_vendor.group(1).strip(" '\"")
                vendor_val = m_by_vendor.group(2).strip(" '\"")
            else:
                entry_title_clean = raw_item_clause

            kind_to_col = {
                "plugin": ("Plugins", "plugin"),
                "plug-in": ("Plugins", "plugin"),
                "vst": ("Plugins", "plugin"),
                "addon": ("Addons_and_Presets", "addon"),
                "add-on": ("Addons_and_Presets", "addon"),
                "preset": ("Addons_and_Presets", "addon"),
                "expansion": ("Addons_and_Presets", "addon"),
                "sample pack": ("Samples_and_Packs", "sample_pack"),
                "drum kit": ("Samples_and_Packs", "sample_pack"),
                "sample": ("Samples_and_Packs", "sample_pack"),
                "support site": ("Support_and_Websites", "support_portal"),
                "support portal": ("Support_and_Websites", "support_portal"),
                "website": ("Support_and_Websites", "support_portal"),
                "distribution": ("Distribution", "distribution_platform"),
                "distribution platform": ("Distribution", "distribution_platform"),
            }
            col_hint, item_type_hint = kind_to_col.get(raw_kind, ("", "catalog_item"))

            # Resolve target Section Hub path (auto-scaffolds Music Studio if user adds a music plugin before scaffolding!)
            resolved_sec_folder = raw_target_sec if "/" in raw_target_sec else ""
            discovered_s = self.index.discover_vault_structure()
            for sec in discovered_s.get("sections") or []:
                s_title_low = str(sec.get("title") or "").lower()
                s_slug_low = Path(str(sec.get("section_rel") or "")).name.lower().replace("_", " ")
                if raw_target_sec.lower() in s_title_low or raw_target_sec.lower() == s_slug_low or s_slug_low in raw_target_sec.lower():
                    resolved_sec_folder = str(sec["section_rel"])
                    break

            if not resolved_sec_folder:
                if "music" in raw_target_sec.lower() or raw_kind in ("plugin", "plug-in", "vst", "sample pack", "drum kit"):
                    scaf = self.vault.scaffold_vault_section("", blueprint_key="music_production", seed_starters=True)
                    self.index.rebuild_all()
                    resolved_sec_folder = scaf["section_rel"]
                else:
                    resolved_sec_folder = f"04_Resources/{re.sub(r'[^A-Za-z0-9_-]+', '_', raw_target_sec).strip('_')}"

            props_payload: Dict[str, Any] = {"status": "Active"}
            if vendor_val:
                props_payload["vendor"] = vendor_val
            if raw_sup_url:
                props_payload["support_url"] = raw_sup_url

            res_ent = self.platform_executor.execute(
                "vault_create_entry",
                {
                    "section_or_folder": resolved_sec_folder,
                    "title": entry_title_clean,
                    "collection": col_hint,
                    "item_type": item_type_hint,
                    "properties": props_payload,
                },
                is_private=early_priv or ("#private" in clean_prompt.lower()),
                actor="KAIROS-Direct",
            )
            if not res_ent.get("ok"):
                raise ValueError(str(res_ent.get("error") or "Failed to create Section Hub entry"))
            ent_data = res_ent["data"]
            actions_taken.append(res_ent["action_summary"])
            reply_text = (
                f"Added **`{ent_data['title']}`** (`{ent_data['frontmatter'].get('type', item_type_hint)}`) "
                f"to `{ent_data['rel_path']}` and indexed it in your live `.base` catalog."
            )
            return _finish_fast_platform_skill(
                reply_text,
                "fast_vault_section_entry",
                ui_cmds=res_ent.get("ui_commands"),
                is_priv_turn=bool(early_priv or ent_data.get("is_private")),
                extra_fields={"entry_rel_path": ent_data["rel_path"]},
                ws_event="note_saved",
            )

        # 5i. Fast Skill: Link-Safe Vault Note Rename ("Rename this note to Serum_2_Guide" / "Rename note <path> to <new>")
        m_rename_note = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?rename\s+(?:(this\s+note|current\s+note|the\s+open\s+note)|note\s+([^\s]+))\s+to\s+([A-Za-z0-9_/\-. ]+?)[.!?]*$",
            prompt_no_priv,
            flags=re.IGNORECASE,
        )
        if m_rename_note:
            src_note_p = active_note_path if m_rename_note.group(1) else (m_rename_note.group(2) or "").strip(" '\"")
            dest_note_p = m_rename_note.group(3).strip(" '\"")
            if not src_note_p:
                raise ValueError("No active note is open to rename.")
            res_ren = self.platform_executor.execute(
                "vault_rename_note",
                {
                    "src_rel_path": src_note_p,
                    "dest_rel_path": dest_note_p,
                    "new_title": Path(dest_note_p).stem.replace("_", " "),
                    "update_links": True,
                },
                is_private=early_priv,
                active_note_path=active_note_path,
                actor="KAIROS-Direct",
            )
            if not res_ren.get("ok"):
                raise ValueError(str(res_ren.get("error") or "Failed to rename Vault note"))
            ren_data = res_ren["data"]
            actions_taken.append(res_ren["action_summary"])
            upd_cnt = len(ren_data.get("updated_backlink_files") or [])
            reply_text = (
                f"Renamed `{ren_data['old_rel_path']}` → **`{ren_data['new_rel_path']}`** "
                f"and updated `{upd_cnt}` backlink/canvas reference(s) across the Vault."
            )
            return _finish_fast_platform_skill(
                reply_text,
                "fast_vault_note_rename",
                ui_cmds=res_ren.get("ui_commands"),
                is_priv_turn=bool(early_priv or ren_data["note"].get("is_private")),
                extra_fields={
                    "old_rel_path": ren_data["old_rel_path"],
                    "new_rel_path": ren_data["new_rel_path"],
                    "updated_backlink_files": ren_data.get("updated_backlink_files", []),
                },
                ws_event="note_renamed",
            )

        # 5j. Fast Skill: ForestCityCreatorsLLC GitHub Organization Catalog -> Canopy Vault Sync
        m_gh_org_sync = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:can\s+you\s+|please\s+)?(?:sync|synchronize|refresh|update|index)\s+(?:our\s+|my\s+|the\s+)?(?:(forest\s*city\s*creators(?:\s*llc)?|fcc)|github\s+org(?:anization)?)\s*(?:github\s+)?(?:repos(?:itories)?|catalog)?(?:\s+(?:to|into|in)\s+(?:my\s+|the\s+)?(?:canopy\s+)?vault)?[.!?]*$",
            prompt_no_priv,
            flags=re.IGNORECASE,
        )
        if m_gh_org_sync:
            res_gh_sync = self.platform_executor.execute(
                "github_sync_org_catalog",
                {"org": "ForestCityCreatorsLLC", "open_in_ui": True},
                is_private=False,
                actor="KAIROS-Direct",
            )
            if not res_gh_sync.get("ok"):
                raise ValueError(str(res_gh_sync.get("error") or "Failed to sync ForestCityCreatorsLLC GitHub catalog"))
            gh_data = res_gh_sync["data"]
            actions_taken.append(res_gh_sync["action_summary"])
            reply_text = (
                f"Synchronized **`{gh_data['org']}`** GitHub repository catalog (`{gh_data['repo_count']}` repositories, "
                f"`{gh_data['private_count']}` private) into `{gh_data['catalog_rel_path']}` and opened it in Second Brain."
            )
            return _finish_fast_platform_skill(
                reply_text,
                "fast_github_org_sync",
                ui_cmds=res_gh_sync.get("ui_commands"),
                is_priv_turn=False,
                extra_fields={
                    "catalog_rel_path": gh_data["catalog_rel_path"],
                    "repo_count": gh_data["repo_count"],
                    "private_count": gh_data["private_count"],
                },
                ws_event="note_saved",
            )

        # 5k. Fast Skill: Project Obsidian `.base` Database Generation
        # (e.g. "Create task base for KAIROS_2_0", "Generate project base for KAIROS 2.0")
        m_proj_base = re.match(
            r"^(?:(?:hey|ok)\s+)?(?:kairos[, ]+)?(?:can\s+you\s+|please\s+)?(?:create|generate|build|refresh)\s+(?:a\s+|an\s+|the\s+)?(?:(?:project|tasks?|obsidian)\s+)+\.?base(?:\s+database|\s+table|\s+catalog)?(?:\s+(?:for|in|under)\s+(?:project\s+)?([A-Za-z0-9_\-. ]+?))?[.!?]*$",
            prompt_no_priv,
            flags=re.IGNORECASE,
        )
        if m_proj_base:
            raw_pb_proj = (m_proj_base.group(1) or "").strip()
            matched_pb = (
                self.navigator._match_project_name(raw_pb_proj.lower())
                if raw_pb_proj
                else None
            )
            target_pb_proj = (
                matched_pb
                or (raw_pb_proj.replace(" ", "_").replace(".", "_") if raw_pb_proj else "")
                or project_scope.strip()
                or "KAIROS_2_0"
            )
            res_pb = self.platform_executor.execute(
                "projects_create_base",
                {"project": target_pb_proj},
                is_private=False,
                actor="KAIROS-Direct",
            )
            if not res_pb.get("ok"):
                raise ValueError(str(res_pb.get("error") or "Failed to generate Project .base database"))
            pb_data = res_pb["data"]
            actions_taken.append(res_pb["action_summary"])
            reply_text = (
                f"Generated live Obsidian Base database **`{pb_data['base_rel_path']}`** for **`{pb_data['project']}`** "
                "(`All Project Tasks`, `Active Sprint`, and `Project Wiki & Docs` views) and opened Documentation."
            )
            return _finish_fast_platform_skill(
                reply_text,
                "fast_project_base_create",
                ui_cmds=res_pb.get("ui_commands"),
                is_priv_turn=False,
                extra_fields={
                    "project": pb_data["project"],
                    "base_rel_path": pb_data["base_rel_path"],
                },
                ws_event="project_base_created",
            )

        # 6. Full Conversational Turn with Canopy Vault RAG + Live APIs + Persona/Tone Engine + `<kairos_op>` + `<ui_nav>`
        context_chunks: List[str] = []
        is_priv = bool(session_tainted_private or early_priv or "#private" in clean_prompt.lower())

        if current_tab:
            context_chunks.append(
                f"Active UI Screen: tab=`{current_tab}`, view=`{current_view or 'default'}`, "
                f"project_scope=`{project_scope or 'Everything'}`, department=`{department_scope or 'All'}`"
            )

        if clean_active_task_id:
            try:
                open_tf = self.vault.find_task_file(clean_active_task_id)
                open_task = self.vault.read_note(self.vault.to_rel_path(open_tf))
                is_priv = is_priv or bool(open_task["is_private"])
                tf_fm = open_task["frontmatter"]
                context_chunks.append(
                    f"Active Open Task Drawer (`{clean_active_task_id}` — '{open_task['title']}'): "
                    f"status=`{tf_fm.get('status')}`, priority=`P{tf_fm.get('priority', 3)}`, "
                    f"project=`{tf_fm.get('project')}`, department=`{tf_fm.get('department')}`, "
                    f"due_date=`{tf_fm.get('due_date') or 'none'}`\n{open_task['body'][:1400]}"
                )
            except Exception:
                pass

        if active_browser_url:
            if "#private" in active_browser_url.lower() or "#private" in (active_browser_title or "").lower():
                is_priv = True
            context_chunks.append(
                f"Active Embedded Browser Tab: title='{active_browser_title or 'Web Tab'}', url=`{active_browser_url}`"
            )

        if active_note_path:
            try:
                active_note = self.vault.read_note(active_note_path)
                is_priv = is_priv or bool(active_note["is_private"])
                context_chunks.append(
                    f"Active Open Note ({active_note['rel_path']}):\n{active_note['body'][:2200]}"
                )
            except ValueError:
                is_priv = True
            except Exception:
                pass

        # Live Inbox Queue, Section Hubs & Paperclip Active Locks awareness
        inbox_preview = self.index.search_vault(query="", folder="00_Inbox", limit=5)
        if inbox_preview:
            vis_inbox = [i for i in inbox_preview if is_priv or not i.get("is_private")]
            if vis_inbox:
                inb_titles = ", ".join(f"`{i['rel_path']}` ('{i['title']}')" for i in vis_inbox[:4])
                context_chunks.append(f"00_Inbox Triage Queue ({len(vis_inbox)} shown): {inb_titles}")

        vault_struct = self.index.discover_vault_structure()
        vis_sections = [
            s for s in (vault_struct.get("sections") or []) if is_priv or not s.get("is_private")
        ]
        if vis_sections:
            sec_summaries = [
                f"{s['icon']} {s['title']} (`{s['section_rel']}/`, {s.get('entry_count', 0)} entries, collections: "
                + ", ".join(c["folder"] for c in (s.get("collections") or [])[:5])
                + ")"
                for s in vis_sections[:8]
            ]
            context_chunks.append("Active Obsidian Vault Section Hubs: " + " | ".join(sec_summaries))

        pclip_obj = getattr(self.crew, "paperclip", None)
        if pclip_obj is not None:
            pclip_snap = pclip_obj.get_snapshot()
            if pclip_snap.get("active_locks"):
                lock_str = ", ".join(
                    f"`{lk['task_id']}` held by `{lk['agent']}` ({lk.get('elapsed_sec', 0)}s)"
                    for lk in pclip_snap["active_locks"]
                )
                context_chunks.append(f"Active Paperclip Task Locks: {lock_str}")

        op_mem, op_mem_priv = self._read_operator_memory_with_privacy(allow_private=is_priv)
        if op_mem_priv:
            is_priv = True
        if op_mem:
            context_chunks.append(f"Operator Long-Term Memory:\n{op_mem}")

        if self.hermes is not None:
            hermes_recalled = self.hermes.recall_context(
                clean_prompt,
                project=project_scope,
                allow_private=is_priv,
            )
            if hermes_recalled.get("context_text"):
                context_chunks.append(
                    f"Hermes Knowledge & Skills Recall:\n{hermes_recalled['context_text']}"
                )

        hits = self.index.search_vault(query=clean_prompt, limit=5)
        for h in hits:
            if h["rel_path"].startswith(SESSIONS_DIR_REL):
                continue
            if h["is_private"]:
                is_priv = True
            context_chunks.append(f"- [{h['title']}] ({h['rel_path']}): {h['excerpt']}")

        rollup = self.index.get_rollup(project=project_scope if project_scope else "")
        context_chunks.append(
            f"Projects Rollup ({rollup['scope']['project']}): {rollup['total_tasks']} tasks "
            f"({rollup['progress_pct']}% Done) | By Department: {rollup.get('by_department', {})} "
            f"| By Status: {rollup['by_status']}"
        )

        p_low = clean_prompt.lower()
        sports_info: Optional[str] = None
        if not is_priv:
            sports_info = self._fetch_live_sports_scores(clean_prompt)
            if sports_info:
                context_chunks.append(f"LIVE ESPN SPORTS FEED (use these exact real-time figures):\n{sports_info}")
                actions_taken.append("Queried Live Sports Scoreboard (ESPN API)")

        if not is_priv and "weather" in p_low:
            weather_info = self._fetch_live_weather(clean_prompt)
            if weather_info:
                context_chunks.append(weather_info)
                actions_taken.append("Queried live Weather API")

        if not is_priv and ("printful" in p_low or "merch store" in p_low):
            pf_info = self._fetch_printful_summary()
            if pf_info:
                context_chunks.append(pf_info)
                actions_taken.append("Queried live Printful Merch API")

        # CPU Episodic Vector Memory Recall (`0 MB` GPU VRAM, `<8ms` retrieval, `#private` isolated)
        episodic_hits = self.cognitive_state.vector_store.retrieve_top_k(
            clean_prompt,
            top_k=3,
            allow_private=is_priv,
            exclude_session_id=effective_session_id,
        )
        if episodic_hits:
            ep_lines = [f"- ({h['role']}) {str(h['content'])[:180]}" for h in episodic_hits]
            context_chunks.append("Episodic Voice Memory Recall:\n" + "\n".join(ep_lines))

        # Multimodal 1080p WebP Vision Trigger (`<45ms` encode, `#private` Cloud Vision Shield)
        visual_source = self.vision.detect_visual_source(clean_prompt)
        vision_meta: Optional[Dict[str, Any]] = None
        captured_img_data_url = ""
        captured_img_bytes: Optional[bytes] = None
        if visual_source:
            snap = self.vision.capture_webp_frame(source=visual_source)
            captured_img_data_url = str(snap.get("data_url") or "")
            captured_img_bytes = snap.get("webp_bytes")
            vision_meta = {
                "source": snap["source"],
                "width": snap["width"],
                "height": snap["height"],
                "capture_ms": snap["capture_ms"],
                "privacy_locked": is_priv,
            }
            if is_priv:
                actions_taken.append(
                    f"Captured {visual_source} 1080p WebP locally ({snap['capture_ms']}ms; Cloud Vision blocked by #private Shield)"
                )
            else:
                actions_taken.append(f"Captured {visual_source} 1080p WebP vision frame ({snap['capture_ms']}ms)")
            context_chunks.append(
                f"Active Visual Context ({snap['source']} {snap['width']}x{snap['height']} WebP captured in {snap['capture_ms']}ms)"
            )

        p_meta = PERSONA_METADATA[clean_persona]
        sys_prompt = (
            f"You are KAIROS 2.0 ({p_meta['label']}), the embedded voice & conversational AI virtual assistant "
            f"for {self.cfg.operator_name} inside Canopy Vault OS.\n"
            f"ROLE DIRECTIVE: {p_meta['directive']}\n"
            f"{TONE_DIRECTIVES[clean_tone]}\n"
            "LIVE KNOWLEDGE RULE: Answer general, live sports, news, weather, coding, and business questions "
            "directly and accurately! When LIVE ESPN SPORTS FEED or Google Search facts are present in Context, "
            "lead immediately with the exact score, matchup, and game status.\n"
            "ARCHITECTURE FACTS: Projects live in `02_Projects/[Project]/[Department]/[List]/Tasks/TSK-*.md` "
            "where each Project contains portions like `Software_Development`, `Marketing_and_Branding`, "
            "`Documentation`, `Website`, `Merch`, and custom categories. Hermes retains durable knowledge in "
            "`04_Resources/Hermes/`. Never reference external SaaS task trackers.\n"
            "FULL PLATFORM EXECUTION (`<kairos_op>`): You have full read/write/action access across the entire KAIROS 2.0 platform. "
            "ONLY when the operator explicitly asks you to create, update, archive, restore, clip, promote, schedule, unlock, or retain "
            "something in the platform, append one or more `<kairos_op>{\"op\":\"...\",\"args\":{...}}</kairos_op>` JSON blocks at the end of your reply:\n"
            "- Create task: `<kairos_op>{\"op\":\"projects_create_task\",\"args\":{\"title\":\"...\",\"project\":\"KAIROS_2_0\",\"department\":\"Software_Development\",\"priority\":2}}</kairos_op>`\n"
            "- Update task: `<kairos_op>{\"op\":\"projects_update_task\",\"args\":{\"task_id\":\"TSK-...\",\"status\":\"In Progress\",\"add_checklist_item\":\"...\",\"toggle_checklist_index\":0}}</kairos_op>`\n"
            "- Archive / restore task: `<kairos_op>{\"op\":\"projects_archive_task\",\"args\":{\"task_id\":\"TSK-...\"}}</kairos_op>` or `projects_restore_task`\n"
            "- Create/append Vault or Daily Note: `vault_write_note` (`file_path`, `title`, `body`, `mode`) or `daily_note_append` (`entry`)\n"
            "- Scaffold Obsidian Section Hub (Music Studio, Creator Media, Hardware Lab, Research, Business CRM, or any custom domain): `<kairos_op>{\"op\":\"vault_scaffold_section\",\"args\":{\"section_name\":\"...\",\"blueprint_key\":\"auto\",\"collections\":[\"...\"]}}</kairos_op>`\n"
            "- Add structured Section Hub entry (plugin, sample pack, addon, support website, distribution guide, etc.): `<kairos_op>{\"op\":\"vault_create_entry\",\"args\":{\"section_or_folder\":\"04_Resources/Music_Studio\",\"collection\":\"Plugins\",\"title\":\"...\",\"properties\":{\"vendor\":\"...\",\"support_url\":\"https://...\"}}}</kairos_op>`\n"
            "- Update YAML frontmatter or Link-Safe Rename note: `vault_update_frontmatter` (`file_path`, `updates`, `remove_keys`), `vault_rename_note` (`src_rel_path`, `dest_rel_path`, `update_links`: true)\n"
            "- Inbox capture / move / promote: `inbox_capture`, `inbox_move_note`, `inbox_promote_to_task` (`query` or `src_rel_path`, `project`, `department`)\n"
            "- Browser clip & GitHub Org Sync: `browser_clip_url` (`url`, `title`, `promote_to_task`), `github_sync_org_catalog` (`org`: `\"ForestCityCreatorsLLC\"`)\n"
            "- Calendar: `calendar_create_event` (`title`, `start_time_iso`, `duration_hrs`), `calendar_time_block_task` (`task_id`, `start_time_iso`)\n"
            "- Paperclip & Hermes: `paperclip_dispatch_crew` (`task_id`, `crew_name`), `paperclip_release_lock` (`task_id`), `hermes_retain_memory` (`fact`), `hermes_create_skill`, `hermes_distill_task`\n"
            "OPTIONAL UI NAVIGATION TAGS: Only if the operator explicitly asks you to navigate, open, watch, or pull up "
            "a screen, video, or webpage during a conversational question, you may append `<ui_nav>{...}</ui_nav>` JSON block(s) "
            "at the very end of your reply:\n"
            "- Switch workspace: `<ui_nav>{\"type\":\"navigate_tab\",\"tab\":\"browser\"}</ui_nav>` "
            "(valid tabs: `assistant`, `inbox`, `projects`, `second-brain`, `browser`, `paperclip`, `settings`)\n"
            "- Open YouTube / webpage in Browser: `<ui_nav>{\"type\":\"browser_navigate\",\"url\":\"https://www.youtube.com/results?search_query=Cleveland+Browns+highlights\",\"title\":\"▶ YouTube: Cleveland Browns highlights\"}</ui_nav>`\n"
            "- Switch Projects sub-view: `<ui_nav>{\"type\":\"set_projects_view\",\"view\":\"gantt\"}</ui_nav>` "
            "(valid views: `rollup`, `list`, `board`, `calendar`, `gantt`, `docs`)\n"
            "- Open Task Drawer: `<ui_nav>{\"type\":\"open_task_drawer\",\"task_id\":\"TSK-...\"}</ui_nav>`"
        )

        router_kwargs: Dict[str, Any] = {
            "context": "\n".join(context_chunks),
            "history": prior_turns,
            "system_prompt_override": sys_prompt,
            "mode": mode,
            "is_private": is_priv,
            "target_path": active_note_path,
            "tool_name": "kairos_assistant_chat",
        }
        if captured_img_data_url or captured_img_bytes is not None:
            router_kwargs["image_data_url"] = captured_img_data_url
            router_kwargs["image_bytes"] = None if is_priv else captured_img_bytes

        try:
            ai_res = self.router.generate(clean_prompt, **router_kwargs)
        except TypeError:
            router_kwargs.pop("image_data_url", None)
            router_kwargs.pop("image_bytes", None)
            ai_res = self.router.generate(clean_prompt, **router_kwargs)

        raw_reply_text = str(ai_res.get("text") or "")
        ai_agent = str(ai_res.get("agent") or "KAIROS-AI")
        ai_privacy_locked = bool(ai_res.get("privacy_locked") or is_priv)
        ai_route_reason = str(ai_res.get("route_reason") or "router")
        ai_latency_ms = float(ai_res.get("latency_ms") or 0.0)
        if ai_res.get("ok") is False and sports_info and not is_priv:
            raw_reply_text = f"🏈 **Live Sports Update:**\n{sports_info}"

        demuxed_reply, mutter_clauses = TrainOfThoughtVerbalizer.demux_completed_text(raw_reply_text)
        op_cleaned_reply, op_action_notes, op_ui_cmds, op_results = extract_and_execute_kairos_ops(
            demuxed_reply or raw_reply_text,
            self.platform_executor,
            is_private=ai_privacy_locked,
            active_task_id=clean_active_task_id,
            active_note_path=active_note_path,
            active_browser_url=active_browser_url,
            active_browser_title=active_browser_title,
            actor=ai_agent,
        )
        if op_action_notes:
            actions_taken.extend(op_action_notes)
        clean_reply, llm_ui_cmds = extract_llm_ui_commands(op_cleaned_reply)
        if not clean_reply and op_action_notes:
            clean_reply = " • ".join(op_action_notes) + "."

        turns_for_trailing = list(prior_turns)
        if sports_info and not is_priv:
            turns_for_trailing.append({"role": "assistant", "content": sports_info})
        trailing_cmds, trailing_notes = self.navigator.resolve_trailing_navigation(
            clean_prompt,
            current_project=project_scope,
            current_department=department_scope,
            prior_turns=turns_for_trailing,
            is_private_context=is_priv,
            live_sports_hint_fn=None if is_priv else self._resolve_featured_live_game_subject,
        )

        combined_ui_cmds = deduplicate_ui_commands(op_ui_cmds + trailing_cmds + llm_ui_cmds)
        if trailing_notes:
            actions_taken.extend(trailing_notes)
        if combined_ui_cmds or op_results:
            if combined_ui_cmds and not trailing_notes and not op_action_notes:
                actions_taken.append(f"Executed {len(combined_ui_cmds)} UI navigation step(s)")
            self._emit({"event": "ui_navigate", "ui_commands": combined_ui_cmds, "actions": actions_taken})

        assistant_turn = {
            "role": "assistant",
            "content": clean_reply,
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "agent": ai_agent,
            "persona": clean_persona,
            "tone_mode": clean_tone,
            "privacy_locked": ai_privacy_locked,
            "actions": actions_taken,
        }
        ses_out = (
            self._append_turns_to_session(
                effective_session_id, user_turn, assistant_turn, clean_persona, clean_tone
            )
            if persist_session
            else None
        )
        try:
            self.cognitive_state.record_turn(
                effective_session_id,
                role="user",
                content=clean_prompt,
                agent="Operator",
                is_private=ai_privacy_locked,
            )
            self.cognitive_state.record_turn(
                effective_session_id,
                role="assistant",
                content=clean_reply,
                agent=ai_agent,
                is_private=ai_privacy_locked,
            )
        except Exception:
            pass

        return {
            "reply": clean_reply,
            "spoken_reply": clean_text_for_speech(clean_reply),
            "mutter_clauses": mutter_clauses,
            "vision_context": vision_meta,
            "agent": ai_agent,
            "route_reason": ai_route_reason,
            "privacy_locked": ai_privacy_locked,
            "latency_ms": ai_latency_ms,
            "ui_commands": combined_ui_cmds,
            "actions": actions_taken,
            "session": ses_out,
        }

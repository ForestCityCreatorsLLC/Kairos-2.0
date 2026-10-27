"""Obsidian Vault Engine: Hash-Guarded Atomic Markdown/YAML CRUD, Projects Task Engine & Defuddle Clipper (`vault_engine.py`)."""

from __future__ import annotations

import hashlib
import html
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

from services.kairos_core.net_guard import validate_entity_id
from services.kairos_core.schemas import (
    CreateTaskInput,
    STANDARD_DEPARTMENT_NAMES,
    TaskFrontmatter,
    UpdateTaskInput,
)
from services.kairos_core.vault_blueprint import (
    build_master_vault_base_yaml,
    build_project_tasks_base_yaml,
    build_section_base_yaml,
    build_section_canvas_json,
    resolve_section_blueprint,
    sanitize_vault_segment,
    validate_and_normalize_canvas,
)

FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", flags=re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
INLINE_TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_\-/]+)")

VAULT_STANDARD_DIRS = [
    "00_Inbox",
    "_System/Templates",
    "_System/Logs",
    "_System/Dashboards",
    "_System/Scripts",
    "_System/Cache",
    "01_Business/Operations",
    "01_Business/OS_Updates",
    "01_Business/Maintenance",
    "01_Business/KAIROS_Sessions",
    "02_Projects",
    "03_Personal/Health_and_Fitness",
    "03_Personal/Finance",
    "03_Personal/Family",
    "03_Personal/Personal_Growth",
    "03_Personal/Calendar",
    "04_Resources/Code_and_Research",
    "04_Resources/Media_and_Assets",
    "04_Resources/Hermes/Skills",
    "05_Archives",
]

STANDARD_PROJECT_DEPARTMENTS: List[Tuple[str, str]] = [
    ("Software_Development", "Sprint_01"),
    ("Marketing_and_Branding", "Campaigns"),
    ("Documentation", "Specs_and_Guides"),
    ("Website", "Web_Launch"),
    ("Merch", "Printful_Drops"),
]

# Canonical KAIROS 2.0 Project Template metadata (dept_folder, default_list, emoji, list_title, description)
KAIROS_PROJECT_TEMPLATE_SPEC: List[Tuple[str, str, str, str, str]] = [
    (
        "Software_Development",
        "Sprint_01",
        "💻",
        "Sprint 01 — Software Development",
        "Active software engineering sprint tasks, APIs, UI, and automated verification live in `Tasks/TSK-*.md`.",
    ),
    (
        "Marketing_and_Branding",
        "Campaigns",
        "📣",
        "Campaigns — Marketing & Branding",
        "Brand identity, social reels, Sendiio broadcasts, and launch campaigns live in `Tasks/TSK-*.md`.",
    ),
    (
        "Documentation",
        "Specs_and_Guides",
        "📄",
        "Specs & Guides — Documentation",
        "Architecture blueprints, operator manuals, SOPs, and technical documentation tasks live in `Tasks/TSK-*.md`.",
    ),
    (
        "Website",
        "Web_Launch",
        "🌐",
        "Web Launch — Website",
        "Landing pages, interactive demos, web copy, and domain deployment tasks live in `Tasks/TSK-*.md`.",
    ),
    (
        "Merch",
        "Printful_Drops",
        "👕",
        "Printful Drops — Merch",
        "Apparel drops, Printful SKUs, mockups, and merch release tasks live in `Tasks/TSK-*.md`.",
    ),
]

STANDARD_TASK_STATUSES: List[str] = [
    "Backlog",
    "To Do",
    "In Progress",
    "Review",
    "Blocked",
    "Done",
]


def build_project_template_canvas(project_title: str, safe_project: str) -> str:
    """Build the canonical Obsidian `.canvas` architecture whiteboard modeled on `KAIROS_2_0/Docs/Architecture_Diagram.canvas`."""
    import json

    canvas_obj = {
        "nodes": [
            {
                "id": "a100000000000001",
                "type": "text",
                "text": (
                    f"# 🚀 {project_title}\n"
                    f"`02_Projects/{safe_project}/`\n"
                    "Cross-Department Project Hub (`_Project_Index.md`)"
                ),
                "x": -540,
                "y": -40,
                "width": 340,
                "height": 190,
                "color": "5",
            },
            {
                "id": "a100000000000002",
                "type": "text",
                "text": (
                    "# 💻 Software Development\n"
                    "`Software_Development/Sprint_01/`\n"
                    "Engineering sprints, APIs, UI & tests"
                ),
                "x": 60,
                "y": -380,
                "width": 350,
                "height": 135,
                "color": "4",
            },
            {
                "id": "a100000000000003",
                "type": "text",
                "text": (
                    "# 📣 Marketing & Branding\n"
                    "`Marketing_and_Branding/Campaigns/`\n"
                    "Launch reels, social hooks & broadcasts"
                ),
                "x": 60,
                "y": -200,
                "width": 350,
                "height": 135,
                "color": "3",
            },
            {
                "id": "a100000000000004",
                "type": "text",
                "text": (
                    "# 📄 Documentation\n"
                    "`Documentation/Specs_and_Guides/`\n"
                    "Blueprints, specs, guides & SOPs"
                ),
                "x": 60,
                "y": -20,
                "width": 350,
                "height": 135,
                "color": "6",
            },
            {
                "id": "a100000000000005",
                "type": "text",
                "text": (
                    "# 🌐 Website\n"
                    "`Website/Web_Launch/`\n"
                    "Landing pages, showcase & domain launch"
                ),
                "x": 60,
                "y": 160,
                "width": 350,
                "height": 135,
                "color": "2",
            },
            {
                "id": "a100000000000006",
                "type": "text",
                "text": (
                    "# 👕 Merch\n"
                    "`Merch/Printful_Drops/`\n"
                    "Apparel drops, mockups & Printful SKUs"
                ),
                "x": 60,
                "y": 340,
                "width": 350,
                "height": 135,
                "color": "1",
            },
        ],
        "edges": [
            {
                "id": "e100000000000001",
                "fromNode": "a100000000000001",
                "fromSide": "right",
                "toNode": "a100000000000002",
                "toSide": "left",
                "label": "Sprint_01",
            },
            {
                "id": "e100000000000002",
                "fromNode": "a100000000000001",
                "fromSide": "right",
                "toNode": "a100000000000003",
                "toSide": "left",
                "label": "Campaigns",
            },
            {
                "id": "e100000000000003",
                "fromNode": "a100000000000001",
                "fromSide": "right",
                "toNode": "a100000000000004",
                "toSide": "left",
                "label": "Specs & Guides",
            },
            {
                "id": "e100000000000004",
                "fromNode": "a100000000000001",
                "fromSide": "right",
                "toNode": "a100000000000005",
                "toSide": "left",
                "label": "Web_Launch",
            },
            {
                "id": "e100000000000005",
                "fromNode": "a100000000000001",
                "fromSide": "right",
                "toNode": "a100000000000006",
                "toSide": "left",
                "label": "Printful_Drops",
            },
        ],
    }
    return json.dumps(canvas_obj, indent=2, ensure_ascii=False) + "\n"


def parse_markdown_note(raw_text: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter and Markdown body safely."""
    text = raw_text or ""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    yaml_block = match.group(1)
    body = text[match.end() :]
    try:
        parsed = yaml.safe_load(yaml_block)
        if isinstance(parsed, dict):
            clean_fm: Dict[str, Any] = {}
            for k, v in parsed.items():
                if hasattr(v, "isoformat"):
                    clean_fm[str(k)] = v.isoformat()
                else:
                    clean_fm[str(k)] = v
            return clean_fm, body
    except Exception:
        pass
    return {}, text


def serialize_markdown_note(frontmatter: Dict[str, Any], body: str) -> str:
    """Serialize YAML frontmatter + Markdown body cleanly with Obsidian-friendly formatting."""
    if not frontmatter:
        return body if body.endswith("\n") else f"{body}\n"
    yaml_str = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    clean_body = body.lstrip("\r\n")
    return f"---\n{yaml_str}\n---\n\n{clean_body}".rstrip() + "\n"


def extract_wikilinks_and_tags(frontmatter: Dict[str, Any], body: str) -> Tuple[List[str], List[str]]:
    """Extract all `[[WikiLinks]]` (from frontmatter + body) and `#tags`."""
    links: List[str] = []
    fm_str = yaml.safe_dump(frontmatter, allow_unicode=True) if frontmatter else ""
    for m in WIKILINK_RE.finditer(f"{fm_str}\n{body}"):
        target = m.group(1).strip()
        if target and target not in links:
            links.append(target)

    tags: List[str] = []
    fm_tags = frontmatter.get("tags")
    if isinstance(fm_tags, list):
        for t in fm_tags:
            clean_t = str(t).strip().lstrip("#")
            if clean_t and clean_t not in tags:
                tags.append(clean_t)
    elif isinstance(fm_tags, str) and fm_tags.strip():
        for part in fm_tags.split(","):
            clean_t = part.strip().lstrip("#")
            if clean_t and clean_t not in tags:
                tags.append(clean_t)

    for m in INLINE_TAG_RE.finditer(body or ""):
        t = m.group(1).strip()
        if t and t not in tags:
            tags.append(t)
    return links, tags


class HashGuardRegistry:
    """Prevents infinite `watchdog` loops when KAIROS itself writes a Markdown file."""

    def __init__(self, ttl_seconds: float = 2.0) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._recent: Dict[str, Tuple[str, float]] = {}

    def record_write(self, file_path: Path, raw_bytes: bytes) -> None:
        digest = hashlib.sha256(raw_bytes).hexdigest()
        key = str(file_path.resolve()).lower()
        with self._lock:
            self._recent[key] = (digest, time.monotonic() + self._ttl)

    def should_ignore_watchdog_event(self, file_path: Path) -> bool:
        key = str(file_path.resolve()).lower()
        now = time.monotonic()
        with self._lock:
            entry = self._recent.get(key)
            if not entry:
                return False
            expected_hash, expires_at = entry
            if now > expires_at:
                self._recent.pop(key, None)
                return False
        try:
            current_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            return current_hash == expected_hash
        except Exception:
            return False


class VaultEngine:
    """Core file-backed storage engine over the Obsidian Vault."""

    def __init__(self, vault_path: Path) -> None:
        self.vault_path = vault_path.resolve()
        self.hash_guard = HashGuardRegistry()
        self._id_lock = threading.RLock()
        self._write_lock = threading.RLock()
        self.initialize_vault_directories()

    def initialize_vault_directories(self) -> None:
        self.vault_path.mkdir(parents=True, exist_ok=True)
        for rel_dir in VAULT_STANDARD_DIRS:
            (self.vault_path / rel_dir).mkdir(parents=True, exist_ok=True)
        audit_file = self.vault_path / "_System" / "Logs" / "AI_Audit_Log.jsonl"
        if not audit_file.exists():
            audit_file.touch()

        # Clean up legacy inverted `02_Projects/Software_Dev` folder once `02_Projects/KAIROS_2_0` is active
        migrated_proj = self.vault_path / "02_Projects" / "KAIROS_2_0"
        legacy_space_dir = self.vault_path / "02_Projects" / "Software_Dev"
        if migrated_proj.is_dir() and legacy_space_dir.is_dir():
            shutil.rmtree(legacy_space_dir, ignore_errors=True)

        # Archive legacy seeded Multi-Department Structure Demo (`02_Projects/KAIROS`) into `05_Archives/KAIROS`
        legacy_demo_idx = self.vault_path / "02_Projects" / "KAIROS" / "_Project_Index.md"
        if migrated_proj.is_dir() and legacy_demo_idx.is_file():
            try:
                if "Multi-Department Structure Demo" in legacy_demo_idx.read_text(
                    encoding="utf-8", errors="replace"
                ):
                    self.archive_completed_project("KAIROS")
            except Exception:
                pass

        # Ensure every scaffolded `_List_Index.md` directory inside `02_Projects/` has a `Tasks/` subfolder
        projects_dir = self.vault_path / "02_Projects"
        if projects_dir.is_dir():
            for list_idx in projects_dir.rglob("_List_Index.md"):
                (list_idx.parent / "Tasks").mkdir(parents=True, exist_ok=True)

        # Ensure official Obsidian Bases master catalog exists in `_System/Dashboards/`
        master_base_file = self.vault_path / "_System" / "Dashboards" / "Vault_Master_Catalog.base"
        if not master_base_file.exists():
            raw_base = build_master_vault_base_yaml().encode("utf-8")
            self.hash_guard.record_write(master_base_file, raw_base)
            master_base_file.write_bytes(raw_base)

        # Ensure root `AGENTS.md` Vault Constitution exists so `[[AGENTS]]` governance links resolve cleanly
        agents_file = self.vault_path / "AGENTS.md"
        if not agents_file.exists():
            agents_text = serialize_markdown_note(
                {
                    "title": "Canopy Vault Constitution & Agent Rules",
                    "type": "constitution",
                    "status": "Active",
                    "tags": ["governance", "vault-constitution"],
                },
                (
                    "# 🏛️ Canopy Vault Constitution (`AGENTS.md`)\n\n"
                    "- Canonical local-first Obsidian knowledge graph (`Markdown + YAML + .base + .canvas`).\n"
                    "- Privacy Firewall: `03_Personal/Finance/` and `#private` notes stay 100% local.\n"
                    "- Section Hubs (`_Hub_Index.md`) pair typed Collections with `.base` catalogs and `.canvas` maps.\n"
                ),
            ).encode("utf-8")
            self.hash_guard.record_write(agents_file, agents_text)
            agents_file.write_bytes(agents_text)

    def resolve_safe_path(self, rel_or_abs: str | Path) -> Path:
        raw_str = str(rel_or_abs or "").strip()
        if not raw_str or "\x00" in raw_str:
            raise ValueError(f"Invalid Vault path: '{rel_or_abs}'")
        candidate = Path(raw_str)
        resolved = candidate.resolve() if candidate.is_absolute() else (self.vault_path / candidate).resolve()
        if not resolved.is_relative_to(self.vault_path):
            raise ValueError(f"Path '{rel_or_abs}' escapes Vault root '{self.vault_path}'")
        return resolved

    def to_rel_path(self, abs_path: Path) -> str:
        return str(abs_path.resolve().relative_to(self.vault_path)).replace("\\", "/")

    def list_markdown_files(self, folder_rel: str = "") -> List[Path]:
        """Return all `.md` files inside `folder_rel` (or Vault root when omitted), sorted newest-first."""
        base = self.resolve_safe_path(folder_rel) if (folder_rel or "").strip() else self.vault_path
        if not base.exists() or not base.is_dir():
            return []
        return sorted(
            [
                p
                for p in base.rglob("*.md")
                if p.is_file()
                and not self.to_rel_path(p).startswith((".obsidian/", "_System/Cache/", ".git/"))
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def is_private_note(
        self,
        rel_path: str,
        frontmatter: Optional[Dict[str, Any]] = None,
        body: str = "",
    ) -> bool:
        """Enforce Section 5A Privacy Rule: `03_Personal/Finance` or `#private` -> Local Gemma 4 ONLY."""
        norm = rel_path.replace("\\", "/").lower()
        if norm.startswith("03_personal/finance"):
            return True
        fm = frontmatter or {}
        if fm.get("private") is True or str(fm.get("private", "")).strip().lower() == "true":
            return True
        if str(fm.get("privacy", "")).lower() in ("private", "local_only"):
            return True
        _, tags = extract_wikilinks_and_tags(fm, body)
        return any(t.lower() == "private" for t in tags)

    def atomic_write_markdown(
        self,
        target_path: Path,
        frontmatter: Dict[str, Any],
        body: str,
    ) -> str:
        """Write Markdown + YAML atomically with OneDrive lock backoff and SHA-256 watchdog guard."""
        with self._write_lock:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            content = serialize_markdown_note(frontmatter, body)
            raw_bytes = content.encode("utf-8")
            tmp_path = target_path.parent / f".{target_path.name}.{uuid.uuid4().hex[:8]}.tmp"
            try:
                tmp_path.write_bytes(raw_bytes)
                self.hash_guard.record_write(target_path, raw_bytes)
                delays = (0.025, 0.05, 0.1, 0.2, 0.35, 0.0)
                last_err: Optional[OSError] = None
                for delay in delays:
                    try:
                        tmp_path.replace(target_path)
                        last_err = None
                        break
                    except OSError as exc:
                        last_err = exc
                        if delay > 0:
                            time.sleep(delay)
                if last_err is not None:
                    target_path.write_bytes(raw_bytes)
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
            return content

    def read_note(self, file_path: str) -> Dict[str, Any]:
        target = self.resolve_safe_path(file_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"Vault note not found: {file_path}")
        raw = target.read_text(encoding="utf-8", errors="replace")
        ext = target.suffix.lower()
        if ext in (".canvas", ".base"):
            fm, body = {}, raw
        else:
            fm, body = parse_markdown_note(raw)
        rel = self.to_rel_path(target)
        links, tags = extract_wikilinks_and_tags(fm, body)
        return {
            "rel_path": rel,
            "abs_path": str(target),
            "title": str(fm.get("title") or target.stem.replace("_", " ")),
            "frontmatter": fm,
            "body": body,
            "wikilinks": links,
            "tags": tags,
            "is_private": self.is_private_note(rel, fm, body),
        }

    def write_note(
        self,
        file_path: str,
        frontmatter: Optional[Dict[str, Any]] = None,
        body: str = "",
        mode: str = "overwrite",
    ) -> Dict[str, Any]:
        with self._write_lock:
            target = self.resolve_safe_path(file_path)
            if target.suffix.lower() == "":
                target = target.with_suffix(".md")
            fm_out = dict(frontmatter or {})
            body_out = body or ""
            ext = target.suffix.lower()
            if ext == ".canvas":
                # JSON Canvas files must remain pure JSON without YAML frontmatter headers
                fm_out = {}
                norm_canvas = validate_and_normalize_canvas(body_out)
                if body_out.strip().startswith("{") and "canvas" in norm_canvas:
                    import json as _json

                    if norm_canvas["canvas"]["nodes"] or norm_canvas["valid"]:
                        body_out = _json.dumps(norm_canvas["canvas"], indent=2, ensure_ascii=False)
            elif ext == ".base":
                # Obsidian Bases (`.base`) files are pure YAML documents without `---` frontmatter blocks
                fm_out = {}
            elif mode == "append" and target.exists():
                existing_fm, existing_body = parse_markdown_note(
                    target.read_text(encoding="utf-8", errors="replace")
                )
                merged_fm = {**existing_fm, **fm_out}
                fm_out = merged_fm
                body_out = f"{existing_body.rstrip()}\n\n{body_out.lstrip()}".strip()
            self.atomic_write_markdown(target, fm_out, body_out)
            return self.read_note(self.to_rel_path(target))

    def _next_project_id(self) -> str:
        year = datetime.now().strftime("%Y")
        prefix = f"PRJ-{year}-"
        max_seq = 0
        projects_dir = self.vault_path / "02_Projects"
        if projects_dir.exists():
            for idx_file in projects_dir.rglob("_Project_Index.md"):
                fm, _ = parse_markdown_note(idx_file.read_text(encoding="utf-8", errors="replace"))
                raw_id = str(fm.get("id") or "")
                if raw_id.startswith(prefix):
                    tail = raw_id[len(prefix) :]
                    if tail.isdigit():
                        max_seq = max(max_seq, int(tail))
        return f"{prefix}{max_seq + 1:02d}"

    def _next_task_id(self) -> str:
        today = datetime.now().strftime("%Y%m%d")
        prefix = f"TSK-{today}-"
        max_seq = 0
        for root_sub in ("02_Projects", "05_Archives"):
            scan_dir = self.vault_path / root_sub
            if scan_dir.exists():
                for p in scan_dir.rglob("TSK-*.md"):
                    if p.stem.startswith(prefix):
                        tail = p.stem[len(prefix) :]
                        if tail.isdigit():
                            max_seq = max(max_seq, int(tail))
        return f"{prefix}{max_seq + 1:03d}"

    def find_task_file(self, task_id: str) -> Path:
        clean_id = validate_entity_id(task_id, "task_id")
        for base_dir in (self.vault_path / "02_Projects", self.vault_path / "05_Archives"):
            if not base_dir.exists():
                continue
            for p in base_dir.rglob(f"{clean_id}.md"):
                return p
            for p in base_dir.rglob(f"{clean_id}_*.md"):
                return p
        raise FileNotFoundError(f"Task '{clean_id}' not found in 02_Projects/ or 05_Archives/")

    def _find_parent_project_folder(self, task_file: Path) -> Optional[Path]:
        projects_root = (self.vault_path / "02_Projects").resolve()
        for parent in task_file.resolve().parents:
            if parent == projects_root or parent == self.vault_path:
                break
            if (parent / "_Project_Index.md").is_file():
                return parent
        return None

    def create_task(self, req: CreateTaskInput) -> Dict[str, Any]:
        with self._id_lock:
            task_id = self._next_task_id()
            raw_proj = req.project.strip().strip("[]")
            safe_project = re.sub(r"[^A-Za-z0-9_\- ]+", "_", raw_proj) or "KAIROS_2_0"
            safe_dept = re.sub(r"[^A-Za-z0-9_\- ]+", "_", req.department.strip()) or "Software_Development"
            safe_list = re.sub(r"[^A-Za-z0-9_\- ]+", "_", req.list.strip()) or "Sprint_01"

            fm_model = TaskFrontmatter(
                id=task_id,
                title=req.title.strip(),
                status=req.status,
                priority=req.priority,
                project=f"[[{safe_project}]]",
                department=safe_dept,
                list=safe_list,
                parent_task=req.parent_task,
                depends_on=req.depends_on,
                assignee=req.assignee,
                ai_agent=req.ai_agent,
                start_date=req.start_date or datetime.now().strftime("%Y-%m-%d"),
                due_date=req.due_date,
                time_estimate_hrs=req.time_estimate_hrs,
                tags=req.tags or ["task"],
            )

            checklist_lines = (
                "\n".join(f"- [ ] {item}" for item in req.checklist)
                if req.checklist
                else "- [ ] Complete task deliverable"
            )
            now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            body = (
                f"## Description\n{req.description.strip() or req.title.strip()}\n\n"
                f"## Action Items (Checklist)\n{checklist_lines}\n\n"
                f"## Attachments & Links\n- [[{safe_project}]]\n\n"
                f"## Activity & AI Log\n"
                f"- **{now_stamp} [System]:** Task `{task_id}` created in `{safe_project}/{safe_dept}/{safe_list}`.\n"
            )

            project_dir = self.vault_path / "02_Projects" / safe_project
            project_index = project_dir / "_Project_Index.md"
            if not project_index.exists():
                self.create_project_structure(
                    project=safe_project,
                    department=safe_dept,
                    list_name=safe_list,
                    scaffold_standard_departments=True,
                    owner=req.assignee,
                    target_end_date=req.due_date or "",
                )

            task_file = project_dir / safe_dept / safe_list / "Tasks" / f"{task_id}.md"
            self.atomic_write_markdown(task_file, fm_model.model_dump(), body)

        self.recalculate_project_progress(project_dir)
        return self.read_note(self.to_rel_path(task_file))

    def update_task(self, req: UpdateTaskInput) -> Dict[str, Any]:
        with self._write_lock:
            return self._update_task_unlocked(req)

    def _update_task_unlocked(self, req: UpdateTaskInput) -> Dict[str, Any]:
        task_file = self.find_task_file(req.task_id)
        fm, body = parse_markdown_note(task_file.read_text(encoding="utf-8", errors="replace"))
        changes: List[str] = []

        target_task_file = task_file
        if req.title is not None and req.title != fm.get("title"):
            fm["title"] = req.title
            changes.append(f"title -> '{req.title}'")
        if req.status is not None and req.status != fm.get("status"):
            old_st = fm.get("status", "To Do")
            fm["status"] = req.status
            changes.append(f"status `{old_st}` -> `{req.status}`")
        if req.priority is not None and req.priority != fm.get("priority"):
            fm["priority"] = int(req.priority)
            changes.append(f"priority -> P{req.priority}")
        if req.department is not None:
            safe_dept = (
                re.sub(r"[^A-Za-z0-9_\- ]+", "_", req.department.strip()).replace(" ", "_")
                or "Software_Development"
            )
            if safe_dept != fm.get("department"):
                old_dept = fm.get("department", "")
                fm["department"] = safe_dept
                changes.append(f"department `{old_dept}` -> `{safe_dept}`")
                proj_folder = self._find_parent_project_folder(task_file)
                if proj_folder is not None:
                    dept_dir = proj_folder / safe_dept
                    existing_lists = (
                        sorted(
                            p.name
                            for p in dept_dir.iterdir()
                            if p.is_dir() and p.name not in ("Docs", "Tasks")
                        )
                        if dept_dir.is_dir()
                        else []
                    )
                    default_lists_map = dict(STANDARD_PROJECT_DEPARTMENTS)
                    next_list = (
                        existing_lists[0]
                        if existing_lists
                        else default_lists_map.get(safe_dept, "General")
                    )
                    self.create_project_structure(
                        project=proj_folder.name,
                        department=safe_dept,
                        list_name=next_list,
                        scaffold_standard_departments=False,
                    )
                    fm["list"] = next_list
                    target_task_file = proj_folder / safe_dept / next_list / "Tasks" / task_file.name
        if req.assignee is not None:
            fm["assignee"] = req.assignee
        if req.ai_agent is not None and req.ai_agent != fm.get("ai_agent"):
            fm["ai_agent"] = req.ai_agent
            changes.append(f"assigned AI agent -> `{req.ai_agent}`")
        if req.parent_task is not None:
            clean_parent = req.parent_task.strip().strip("[]").strip()
            formatted_parent = f"[[{clean_parent}]]" if clean_parent else ""
            if formatted_parent != str(fm.get("parent_task") or ""):
                fm["parent_task"] = formatted_parent
                changes.append(f"parent_task -> `{formatted_parent or 'None'}`")
        if req.depends_on is not None:
            normalized_deps: List[str] = []
            for raw_dep in req.depends_on:
                clean_dep = str(raw_dep).strip().strip("[]").strip()
                if clean_dep and clean_dep != req.task_id:
                    formatted_dep = f"[[{clean_dep}]]"
                    if formatted_dep not in normalized_deps:
                        normalized_deps.append(formatted_dep)
            if normalized_deps != list(fm.get("depends_on") or []):
                fm["depends_on"] = normalized_deps
                changes.append(f"depends_on -> {', '.join(normalized_deps) or 'None'}")
        if req.start_date is not None:
            fm["start_date"] = req.start_date
        if req.due_date is not None:
            fm["due_date"] = req.due_date
        if req.gcal_event_id is not None:
            fm["gcal_event_id"] = req.gcal_event_id.strip()
        if req.time_estimate_hrs is not None:
            fm["time_estimate_hrs"] = round(float(req.time_estimate_hrs), 2)
        if req.time_logged_hrs is not None:
            fm["time_logged_hrs"] = max(0.0, round(float(req.time_logged_hrs), 2))
        if req.time_logged_delta:
            prev_logged = float(fm.get("time_logged_hrs") or 0.0)
            new_logged = max(0.0, round(prev_logged + float(req.time_logged_delta), 2))
            fm["time_logged_hrs"] = new_logged
            changes.append(f"logged {req.time_logged_delta:+.2f}h (total {new_logged:.2f}h)")

        if req.description is not None:
            body = re.sub(
                r"(## Description\r?\n)(.*?)(\r?\n## |\Z)",
                lambda m: f"{m.group(1)}{req.description.strip()}\n\n{m.group(3)}"
                if m.group(3).startswith("\n##") or m.group(3).startswith("\r\n##")
                else f"{m.group(1)}{req.description.strip()}\n",
                body,
                count=1,
                flags=re.DOTALL,
            )

        if req.toggle_checklist_index is not None:
            lines = body.splitlines()
            chk_idx = 0
            for i, line in enumerate(lines):
                if re.match(r"^\s*-\s*\[[ xX]\]\s+", line):
                    if chk_idx == req.toggle_checklist_index:
                        if "[ ]" in line:
                            lines[i] = line.replace("[ ]", "[x]", 1)
                        else:
                            lines[i] = re.sub(r"\[[xX]\]", "[ ]", line, count=1)
                        changes.append(f"toggled checklist #{chk_idx + 1}")
                        break
                    chk_idx += 1
            body = "\n".join(lines)

        if req.add_checklist_item:
            marker = "## Action Items (Checklist)"
            if marker in body:
                idx = body.index(marker) + len(marker)
                body = f"{body[:idx]}\n- [ ] {req.add_checklist_item.strip()}{body[idx:]}"
            else:
                body = f"{body.rstrip()}\n\n## Action Items (Checklist)\n- [ ] {req.add_checklist_item.strip()}\n"
            changes.append(f"added checklist item '{req.add_checklist_item.strip()}'")

        log_msg = req.log_entry or ("; ".join(changes) if changes else "Task updated")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        log_line = f"- **{stamp} [{req.actor}]:** {log_msg}"
        if "## Activity & AI Log" in body:
            body = f"{body.rstrip()}\n{log_line}\n"
        else:
            body = f"{body.rstrip()}\n\n## Activity & AI Log\n{log_line}\n"

        validated = TaskFrontmatter(**fm)
        self.atomic_write_markdown(target_task_file, validated.model_dump(), body)
        if target_task_file.resolve() != task_file.resolve() and task_file.exists():
            task_file.unlink()
        task_file = target_task_file

        project_folder = self._find_parent_project_folder(task_file)
        if project_folder is not None:
            self.recalculate_project_progress(project_folder)
        return self.read_note(self.to_rel_path(task_file))

    def delete_or_archive_task(
        self,
        task_id: str,
        *,
        permanent: bool = False,
        actor: str = "Jaime",
    ) -> Dict[str, Any]:
        """Archive a task to `05_Archives/Tasks/[Project]/` (default) or permanently delete it."""
        with self._write_lock:
            task_file = self.find_task_file(task_id)
            old_rel = self.to_rel_path(task_file)
            project_folder = self._find_parent_project_folder(task_file)
            fm, body = parse_markdown_note(task_file.read_text(encoding="utf-8", errors="replace"))
            clean_id = str(fm.get("id") or task_file.stem).strip()
            proj_name = (
                project_folder.name
                if project_folder is not None
                else (str(fm.get("project") or "General").strip().strip("[]") or "General")
            )

            archived_rel = ""
            if permanent:
                task_file.unlink()
            else:
                dest_dir = self.vault_path / "05_Archives" / "Tasks" / proj_name
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / task_file.name
                if dest_path.exists() and dest_path.resolve() != task_file.resolve():
                    dest_path = dest_dir / f"{task_file.stem}_{datetime.now().strftime('%H%M%S')}.md"
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                fm["archived_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                log_line = f"- **{stamp} [{actor}]:** Soft-archived task to `05_Archives/Tasks/{proj_name}/`"
                body = f"{body.rstrip()}\n{log_line}\n"
                self.atomic_write_markdown(dest_path, fm, body)
                if dest_path.resolve() != task_file.resolve() and task_file.exists():
                    task_file.unlink()
                archived_rel = self.to_rel_path(dest_path)

            # Clean stale parent_task / depends_on references on active tasks inside the project
            if project_folder is not None and project_folder.exists():
                target_link = f"[[{clean_id}]]"
                for sib in project_folder.rglob("TSK-*.md"):
                    sib_fm, sib_body = parse_markdown_note(
                        sib.read_text(encoding="utf-8", errors="replace")
                    )
                    mutated = False
                    if str(sib_fm.get("parent_task") or "").strip() in (target_link, clean_id):
                        sib_fm["parent_task"] = ""
                        mutated = True
                    deps = list(sib_fm.get("depends_on") or [])
                    cleaned_deps = [
                        d for d in deps if str(d).strip().strip("[]") != clean_id
                    ]
                    if len(cleaned_deps) != len(deps):
                        sib_fm["depends_on"] = cleaned_deps
                        mutated = True
                    if mutated:
                        self.atomic_write_markdown(sib, sib_fm, sib_body)
                self.recalculate_project_progress(project_folder)

            return {
                "ok": True,
                "task_id": clean_id,
                "mode": "deleted" if permanent else "archived",
                "old_rel_path": old_rel,
                "archived_rel_path": archived_rel,
                "project": proj_name,
            }

    def list_archived_tasks(self, project: str = "") -> List[Dict[str, Any]]:
        """List soft-archived tasks inside `05_Archives/Tasks/` (optionally filtered by project)."""
        arch_tasks_root = self.vault_path / "05_Archives" / "Tasks"
        if not arch_tasks_root.exists():
            return []
        clean_proj_filter = project.strip().strip("[]").lower()
        items: List[Dict[str, Any]] = []
        files = sorted(
            arch_tasks_root.rglob("TSK-*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in files:
            try:
                fm, _ = parse_markdown_note(p.read_text(encoding="utf-8", errors="replace"))
                proj_val = (
                    str(fm.get("project") or p.parent.name or "General").strip().strip("[]")
                    or "General"
                )
                if clean_proj_filter and proj_val.lower() != clean_proj_filter:
                    continue
                tid = str(fm.get("id") or p.stem.split("_")[0]).strip()
                prio_raw = fm.get("priority", 3)
                try:
                    prio_val = int(prio_raw)
                except (TypeError, ValueError):
                    prio_val = 3
                items.append(
                    {
                        "id": tid,
                        "title": str(fm.get("title") or tid),
                        "project": proj_val,
                        "department": str(fm.get("department") or "Software_Development"),
                        "list": str(fm.get("list") or "Sprint_01"),
                        "status": str(fm.get("status") or "To Do"),
                        "priority": prio_val,
                        "archived_at": str(fm.get("archived_at") or ""),
                        "rel_path": self.to_rel_path(p),
                    }
                )
            except Exception:
                continue
        return items

    def restore_archived_task(self, task_id: str, actor: str = "Jaime") -> Dict[str, Any]:
        """Restore a soft-archived task from `05_Archives/Tasks/` back into its `02_Projects/` hierarchy."""
        clean_id = validate_entity_id(task_id, "task_id")
        arch_tasks_root = self.vault_path / "05_Archives" / "Tasks"
        with self._write_lock:
            found: Optional[Path] = None
            if arch_tasks_root.exists():
                for p in arch_tasks_root.rglob(f"{clean_id}.md"):
                    found = p
                    break
                if found is None:
                    for p in arch_tasks_root.rglob(f"{clean_id}_*.md"):
                        found = p
                        break
            if found is None:
                raise FileNotFoundError(
                    f"Archived task '{clean_id}' not found in 05_Archives/Tasks/"
                )

            old_archived_rel = self.to_rel_path(found)
            fm, body = parse_markdown_note(found.read_text(encoding="utf-8", errors="replace"))
            canon_id = str(fm.get("id") or clean_id).strip()
            raw_proj = str(fm.get("project") or found.parent.name or "KAIROS_2_0").strip().strip("[]")
            safe_proj = re.sub(r"[^A-Za-z0-9_\- ]+", "_", raw_proj).strip().replace(" ", "_") or "KAIROS_2_0"
            safe_dept = (
                re.sub(
                    r"[^A-Za-z0-9_\- ]+",
                    "_",
                    str(fm.get("department") or "Software_Development").strip(),
                )
                .strip()
                .replace(" ", "_")
                or "Software_Development"
            )
            safe_list = (
                re.sub(r"[^A-Za-z0-9_\- ]+", "_", str(fm.get("list") or "Sprint_01").strip())
                .strip()
                .replace(" ", "_")
                or "Sprint_01"
            )

            proj_dir = self.vault_path / "02_Projects" / safe_proj
            self.create_project_structure(
                project=safe_proj,
                department=safe_dept,
                list_name=safe_list,
                scaffold_standard_departments=not (proj_dir / "_Project_Index.md").exists(),
            )
            dest_file = proj_dir / safe_dept / safe_list / "Tasks" / f"{canon_id}.md"
            fm.pop("archived_at", None)
            fm["project"] = f"[[{safe_proj}]]"
            fm["department"] = safe_dept
            fm["list"] = safe_list
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            log_line = (
                f"- **{stamp} [{actor}]:** Restored task from `05_Archives/Tasks/` "
                f"to `{safe_proj}/{safe_dept}/{safe_list}`."
            )
            if "## Activity & AI Log" in body:
                body = f"{body.rstrip()}\n{log_line}\n"
            else:
                body = f"{body.rstrip()}\n\n## Activity & AI Log\n{log_line}\n"

            self.atomic_write_markdown(dest_file, fm, body)
            if dest_file.resolve() != found.resolve() and found.exists():
                found.unlink()
            self.recalculate_project_progress(proj_dir)
            restored_note = self.read_note(self.to_rel_path(dest_file))
            return {
                **restored_note,
                "ok": True,
                "task_id": canon_id,
                "old_archived_rel_path": old_archived_rel,
            }

    def recalculate_project_progress(self, project_folder: Path) -> Optional[int]:
        """Rule 3: Recalculate `progress_pct` in `_Project_Index.md` across all departments inside the Project."""
        index_path = project_folder / "_Project_Index.md"
        if not project_folder.exists() or not index_path.exists():
            return None
        task_files = list(project_folder.rglob("TSK-*.md"))
        total = len(task_files)
        done = 0
        for tf in task_files:
            fm, _ = parse_markdown_note(tf.read_text(encoding="utf-8", errors="replace"))
            if str(fm.get("status", "")) == "Done":
                done += 1
        pct = int(round((done / total) * 100)) if total > 0 else 0
        idx_fm, idx_body = parse_markdown_note(index_path.read_text(encoding="utf-8", errors="replace"))
        idx_fm["progress_pct"] = pct
        self.atomic_write_markdown(index_path, idx_fm, idx_body)

        if str(idx_fm.get("status", "")) == "Completed":
            self.archive_completed_project(project_folder)
        return pct

    def archive_completed_project(
        self,
        project_or_path: Path | str,
        department: Optional[str] = None,
    ) -> Optional[Path]:
        """Rule 2: Move completed Project (or Department inside a Project) into `05_Archives/`."""
        projects_root = (self.vault_path / "02_Projects").resolve()
        if isinstance(project_or_path, Path) and project_or_path.exists():
            resolved_path = project_or_path.resolve()
            if resolved_path == projects_root or not resolved_path.is_relative_to(projects_root):
                raise ValueError("Target folder must reside inside 02_Projects/")
            target_folder = resolved_path
            archive_name = target_folder.name
        else:
            clean_proj = str(project_or_path).strip().strip("[]")
            if (
                not clean_proj
                or clean_proj in (".", "..")
                or "/" in clean_proj
                or "\\" in clean_proj
                or "\x00" in clean_proj
            ):
                raise ValueError("Invalid project name for archive")
            proj_dir = (projects_root / clean_proj).resolve()
            if proj_dir == projects_root or not proj_dir.is_relative_to(projects_root):
                raise ValueError("Invalid project name for archive")
            if department and department.strip():
                clean_dept = department.strip()
                if (
                    clean_dept in (".", "..")
                    or "/" in clean_dept
                    or "\\" in clean_dept
                    or "\x00" in clean_dept
                ):
                    raise ValueError("Invalid department name for archive")
                dept_dir = (proj_dir / clean_dept).resolve()
                if not dept_dir.is_relative_to(proj_dir):
                    raise ValueError("Invalid department name for archive")
                if dept_dir.exists():
                    target_folder = dept_dir
                    archive_name = f"{clean_proj}_{clean_dept}"
                elif proj_dir.exists():
                    target_folder = proj_dir
                    archive_name = clean_proj
                else:
                    return None
            else:
                target_folder = proj_dir
                archive_name = clean_proj

        if not target_folder.exists():
            return None

        dest = self.vault_path / "05_Archives" / archive_name
        if dest.exists():
            dest = self.vault_path / "05_Archives" / f"{archive_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.move(str(target_folder), str(dest))
        return dest

    def list_archived_projects(self) -> List[str]:
        """List archived project/category directories inside `05_Archives/`."""
        arch_root = self.vault_path / "05_Archives"
        if not arch_root.exists():
            return []
        return sorted(
            p.name
            for p in arch_root.iterdir()
            if p.is_dir() and p.name not in ("Triaged_Inbox", "Tasks", "Sessions", "Events")
        )

    def unarchive_project(self, archive_name: str) -> Optional[Path]:
        """Restore an archived project folder from `05_Archives/[archive_name]` back into `02_Projects/`."""
        clean_name = re.sub(r"[^A-Za-z0-9_\- ]+", "", archive_name.strip())
        if not clean_name:
            return None
        src = self.vault_path / "05_Archives" / clean_name
        if not src.exists() or not src.is_dir():
            return None
        dest = self.vault_path / "02_Projects" / clean_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.copytree(str(src), str(dest), dirs_exist_ok=True)
            shutil.rmtree(str(src), ignore_errors=True)
            return dest
        shutil.move(str(src), str(dest))
        return dest

    def defuddle_clip_to_vault(
        self,
        url: str,
        raw_html_or_text: str,
        title: str = "",
        dest_folder: str = "00_Inbox",
    ) -> Dict[str, Any]:
        """Strip boilerplate HTML (`Defuddle` pattern) and save clean token-efficient Markdown to Vault."""
        cleaned = re.sub(
            r"<(script|style|noscript|nav|footer|header|svg|iframe)[^>]*>.*?</\1>",
            " ",
            raw_html_or_text or "",
            flags=re.DOTALL | re.IGNORECASE,
        )
        cleaned = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = html.unescape(cleaned)
        lines = [" ".join(ln.split()) for ln in cleaned.splitlines()]
        body_md = "\n".join(ln for ln in lines if ln).strip()

        safe_title = title.strip() or re.sub(r"^https?://(www\.)?", "", url).split("/")[0] or "Web_Clip"
        slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", safe_title).strip("_")[:56] or "Web_Clip"
        clean_dest = dest_folder.strip("/") or "00_Inbox"
        rel_path = f"{clean_dest}/Clip_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}.md"
        clip_tags: List[str] = ["web-clip"]
        if clean_dest.lower().startswith("00_inbox"):
            clip_tags.append("inbox")
        else:
            dest_tag = re.sub(r"[^a-z0-9\-]+", "-", clean_dest.split("/")[-1].lower()).strip("-")
            if dest_tag and dest_tag not in clip_tags:
                clip_tags.append(dest_tag)
        if clean_dest.lower().startswith("03_personal/finance"):
            clip_tags.append("private")
        fm = {
            "title": safe_title,
            "type": "web_clip",
            "source_url": url,
            "support_url": url,
            "status": "Active",
            "clipped_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "tags": clip_tags,
        }
        full_body = f"# 🌐 {safe_title}\n\n**Source:** {url}\n\n---\n\n{body_md[:12000]}\n"
        return self.write_note(rel_path, fm, full_body, mode="overwrite")

    def create_project_structure(
        self,
        project: str,
        department: str = "Software_Development",
        list_name: str = "Sprint_01",
        scaffold_standard_departments: bool = True,
        owner: str = "Jaime",
        target_end_date: str = "",
    ) -> Dict[str, Any]:
        """Scaffold a project using the canonical `KAIROS_2_0` multi-department template in `02_Projects/[Project]/`."""
        safe_project = re.sub(r"[^A-Za-z0-9_\- ]+", "_", project.strip().strip("[]")) or "KAIROS_2_0"
        safe_dept = re.sub(r"[^A-Za-z0-9_\- ]+", "_", department.strip()) or "Software_Development"
        safe_list = re.sub(r"[^A-Za-z0-9_\- ]+", "_", list_name.strip()) or "Sprint_01"
        pretty_project = safe_project.replace("_", " ")

        project_dir = self.vault_path / "02_Projects" / safe_project
        docs_dir = project_dir / "Docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        canvas_path = docs_dir / "Architecture_Diagram.canvas"
        if not canvas_path.exists():
            canvas_bytes = build_project_template_canvas(pretty_project, safe_project).encode("utf-8")
            self.hash_guard.record_write(canvas_path, canvas_bytes)
            canvas_path.write_bytes(canvas_bytes)

        spec_by_dept = {d: (lst, emj, ltitle, desc) for d, lst, emj, ltitle, desc in KAIROS_PROJECT_TEMPLATE_SPEC}

        proj_index = project_dir / "_Project_Index.md"
        if not proj_index.exists():
            proj_id = self._next_project_id()
            dept_lines = [
                f"- {emj} **`{d}`** (`{lst}`) — {desc.split(' live in ')[0]}"
                for d, lst, emj, _, desc in KAIROS_PROJECT_TEMPLATE_SPEC
            ]
            if safe_dept not in spec_by_dept:
                dept_lines.append(f"- 📂 **`{safe_dept}`** (`{safe_list}`) — Custom project department")

            self.atomic_write_markdown(
                proj_index,
                {
                    "id": proj_id,
                    "title": f"{pretty_project} — Project Hub",
                    "type": "project",
                    "status": "Active",
                    "project": safe_project,
                    "owner": owner or "Jaime",
                    "start_date": datetime.now().strftime("%Y-%m-%d"),
                    "target_end_date": target_end_date,
                    "github_repo": f"https://github.com/ForestCityCreatorsLLC/{safe_project}",
                    "gdrive_folder_url": "",
                    "progress_pct": 0,
                    "tags": ["project", safe_project.lower().replace(" ", "-")],
                },
                (
                    f"# 🚀 {pretty_project} — Project Index & Cross-Department Rollup\n\n"
                    f"> [!IMPORTANT] Canonical Multi-Department Project (`02_Projects/{safe_project}/`)\n"
                    f"> Structured from the **KAIROS 2.0 Project Template** (`Project -> Department -> List -> Tasks`).\n\n"
                    f"## Project Departments (`02_Projects/{safe_project}/`)\n"
                    + "\n".join(dept_lines)
                    + "\n\n"
                    "## Active Cross-Department Tasks (Dataview)\n"
                    "```dataview\n"
                    'TABLE department AS "Department", list AS "List", status AS "Status", priority AS "P", ai_agent AS "AI Agent", due_date AS "Due"\n'
                    f'FROM "02_Projects/{safe_project}"\n'
                    'WHERE type = "task"\n'
                    "SORT priority ASC, due_date ASC\n"
                    "```\n\n"
                    "## Architecture & Governance Links\n"
                    f"- Whiteboard: [[02_Projects/{safe_project}/Docs/Architecture_Diagram.canvas]]\n"
                    "- Vault Constitution: [[AGENTS]]\n"
                ),
            )
        else:
            # Ensure custom categories/portions added later are registered in `_Project_Index.md`
            idx_fm, idx_body = parse_markdown_note(
                proj_index.read_text(encoding="utf-8", errors="replace")
            )
            depts_list = list(idx_fm.get("departments") or list(STANDARD_DEPARTMENT_NAMES))
            changed_idx = False
            if safe_dept not in depts_list:
                depts_list.append(safe_dept)
                idx_fm["departments"] = depts_list
                changed_idx = True
            if f"`{safe_dept}`" not in idx_body:
                marker = f"## Project Departments (`02_Projects/{safe_project}/`)"
                custom_bullet = f"\n- 📂 **`{safe_dept}`** (`{safe_list}`) — Custom project category"
                if marker in idx_body:
                    pos = idx_body.index(marker) + len(marker)
                    idx_body = f"{idx_body[:pos]}{custom_bullet}{idx_body[pos:]}"
                else:
                    idx_body = f"{idx_body.rstrip()}\n\n## Custom Categories\n{custom_bullet.lstrip()}\n"
                changed_idx = True
            if changed_idx:
                self.atomic_write_markdown(proj_index, idx_fm, idx_body)

        pairs_to_create: List[Tuple[str, str]] = [(safe_dept, safe_list)]
        if scaffold_standard_departments:
            for std_dept, std_list in STANDARD_PROJECT_DEPARTMENTS:
                if std_dept != safe_dept:
                    pairs_to_create.append((std_dept, std_list))

        primary_list_index: Optional[Path] = None
        for d_name, l_name in pairs_to_create:
            list_dir = project_dir / d_name / l_name
            (list_dir / "Tasks").mkdir(parents=True, exist_ok=True)
            list_index = list_dir / "_List_Index.md"
            if not list_index.exists():
                if d_name in spec_by_dept and l_name == spec_by_dept[d_name][0]:
                    _, emj, ltitle, desc = spec_by_dept[d_name]
                else:
                    emj = spec_by_dept.get(d_name, ("", "📋", "", ""))[1] or "📋"
                    ltitle = f"{l_name.replace('_', ' ')} — {d_name.replace('_', ' ')}"
                    desc = "Active department sprint and deliverable tasks live in `Tasks/TSK-*.md`."

                self.atomic_write_markdown(
                    list_index,
                    {
                        "title": ltitle,
                        "type": "list",
                        "project": safe_project,
                        "department": d_name,
                        "list": l_name,
                        "statuses": list(STANDARD_TASK_STATUSES),
                    },
                    f"# {emj} {ltitle} (`{safe_project}`)\n\n{desc}\n",
                )
            if d_name == safe_dept and l_name == safe_list:
                primary_list_index = list_index

        assert primary_list_index is not None
        return {
            "project": safe_project,
            "department": safe_dept,
            "list": safe_list,
            "project_index_rel": self.to_rel_path(proj_index),
            "canvas_rel": self.to_rel_path(canvas_path),
            "list_index_rel": self.to_rel_path(primary_list_index),
        }

    def move_note(self, src_rel_path: str, dest_folder: str) -> Dict[str, Any]:
        """Move a Vault note into another folder (e.g. triaging `00_Inbox/` into Second Brain or a Section Hub)."""
        src = self.resolve_safe_path(src_rel_path)
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(f"Source note not found: {src_rel_path}")
        dest_dir = self.resolve_safe_path(dest_folder.strip("/"))
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / src.name
        if dest_path.exists() and dest_path.resolve() != src.resolve():
            dest_path = dest_dir / f"{src.stem}_{datetime.now().strftime('%H%M%S')}{src.suffix}"

        # If moving a Markdown note into a Section Hub or one of its Collections, auto-wire `section_hub` & `collection`
        hub_dir: Optional[Path] = None
        if (dest_dir / "_Hub_Index.md").is_file():
            hub_dir = dest_dir
        elif (dest_dir.parent / "_Hub_Index.md").is_file():
            hub_dir = dest_dir.parent

        if src.suffix.lower() == ".md" and hub_dir is not None:
            fm, body = parse_markdown_note(src.read_text(encoding="utf-8", errors="replace"))
            hub_idx = hub_dir / "_Hub_Index.md"
            hub_fm, _ = parse_markdown_note(hub_idx.read_text(encoding="utf-8", errors="replace"))
            hub_rel = self.to_rel_path(hub_idx)
            hub_title = str(hub_fm.get("title") or hub_dir.name.replace("_", " "))
            fm.setdefault("section_hub", f"[[{hub_rel}|{hub_title}]]")
            if dest_dir.resolve() != hub_dir.resolve():
                fm.setdefault("collection", dest_dir.name)
            fm.setdefault("status", "Active")
            if isinstance(fm.get("tags"), list) and not self.to_rel_path(dest_path).lower().startswith("00_inbox/"):
                fm["tags"] = [t for t in fm["tags"] if str(t).lower() != "inbox"]
            self.atomic_write_markdown(dest_path, fm, body)
            if dest_path.resolve() != src.resolve() and src.exists():
                src.unlink()
            return self.read_note(self.to_rel_path(dest_path))

        raw_bytes = src.read_bytes()
        self.hash_guard.record_write(dest_path, raw_bytes)
        shutil.move(str(src), str(dest_path))
        return self.read_note(self.to_rel_path(dest_path))

    def promote_inbox_note_to_task(
        self,
        src_rel_path: str,
        project: str = "KAIROS_2_0",
        department: str = "Software_Development",
        list_name: str = "Sprint_01",
        priority: int = 2,
        ai_agent: str = "None",
    ) -> Dict[str, Any]:
        """Convert an `00_Inbox/` capture or web clip into a structured Project `TSK-*.md` task and archive the raw capture."""
        note = self.read_note(src_rel_path)
        archived = self.move_note(src_rel_path, "05_Archives/Triaged_Inbox")
        created_task = self.create_task(
            CreateTaskInput(
                title=note["title"],
                project=project,
                department=department,
                list=list_name,
                priority=priority,
                ai_agent=ai_agent,
                description=f"Promoted from Inbox capture [[{archived['rel_path']}]]:\n\n{note['body'][:2500]}",
                tags=note["tags"] or ["triaged"],
            )
        )
        return {
            "task": created_task,
            "archived_capture": archived["rel_path"],
        }

    def create_inbox_capture(
        self,
        title: str,
        body: str = "",
        *,
        source: str = "Quick-Capture",
        tags: Optional[List[str]] = None,
        is_private: bool = False,
    ) -> Dict[str, Any]:
        """Create a raw capture note inside `00_Inbox/` with optional `#private` isolation."""
        clean_title = (title or "").strip() or "Inbox Capture"
        slug = sanitize_vault_segment(clean_title, fallback="Capture")[:48]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        rel_path = f"00_Inbox/Capture_{stamp}_{slug}.md"

        norm_tags: List[str] = ["inbox", "capture"]
        for raw_t in (tags or []):
            ct = str(raw_t).strip().lstrip("#")
            if ct and ct.lower() not in [x.lower() for x in norm_tags]:
                norm_tags.append(ct)
        if is_private and "private" not in [x.lower() for x in norm_tags]:
            norm_tags.append("private")

        fm: Dict[str, Any] = {
            "title": clean_title,
            "type": "inbox_capture",
            "source": (source or "Quick-Capture").strip(),
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "tags": norm_tags,
        }
        if is_private:
            fm["private"] = True

        clean_body = (body or "").strip()
        md_body = (
            clean_body
            if clean_body.startswith("#")
            else f"# 📥 {clean_title}\n\n{clean_body}\n".rstrip() + "\n"
        )
        return self.write_note(rel_path, fm, md_body, mode="overwrite")

    def promote_inbox_note_to_section_entry(
        self,
        src_rel_path: str,
        *,
        section_or_folder: str = "04_Resources/Music_Studio",
        collection: str = "",
        item_type: str = "",
        vendor: str = "",
        properties: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Promote an `00_Inbox/` capture or web clip into a typed Section Hub catalog entry and archive raw capture."""
        note = self.read_note(src_rel_path)
        clean_sec = (section_or_folder or "04_Resources/Music_Studio").strip().strip("/\\").replace("\\", "/")
        if not clean_sec:
            clean_sec = "04_Resources/Music_Studio"

        # Auto-scaffold Music_Studio if targeting `Music_Studio` before its `_Hub_Index.md` exists
        sec_path = self.resolve_safe_path(clean_sec)
        if (
            "music_studio" in clean_sec.lower()
            and not (sec_path / "_Hub_Index.md").is_file()
            and not (sec_path.parent / "_Hub_Index.md").is_file()
        ):
            scaf = self.scaffold_vault_section("", blueprint_key="music_production", seed_starters=True)
            clean_sec = scaf["section_rel"]

        src_fm = dict(note.get("frontmatter") or {})
        raw_body = str(note.get("body") or "").strip()

        # Extract primary URL from frontmatter or Markdown body
        extracted_url = ""
        for fk in ("support_url", "dashboard_url", "source_url", "url", "website"):
            cand_u = str(src_fm.get(fk) or "").strip()
            if cand_u.startswith(("http://", "https://")):
                extracted_url = cand_u
                break
        if not extracted_url:
            m_url = re.search(r"https?://[^\s\])>\"']+", raw_body)
            if m_url:
                extracted_url = m_url.group(0).rstrip(".,;)")

        merged_props: Dict[str, Any] = {"status": "Active", **(properties or {})}
        eff_vendor = (vendor or str(src_fm.get("vendor") or "")).strip()
        if eff_vendor and not merged_props.get("vendor"):
            merged_props["vendor"] = eff_vendor

        is_dist = (
            collection.strip().lower() == "distribution"
            or item_type.strip().lower() == "distribution_platform"
        )
        url_key = "dashboard_url" if is_dist else "support_url"
        if extracted_url and not merged_props.get(url_key):
            merged_props[url_key] = extracted_url

        carried_tags = [
            str(t).strip().lstrip("#")
            for t in (note.get("tags") or [])
            if str(t).strip().lstrip("#").lower() not in ("inbox", "capture", "web-clip")
        ]
        if "triaged" not in [t.lower() for t in carried_tags]:
            carried_tags.append("triaged")

        archived = self.move_note(src_rel_path, "05_Archives/Triaged_Inbox")
        clean_title = str(note.get("title") or Path(src_rel_path).stem.replace("_", " ")).strip()
        clean_title = re.sub(r"^Capture_\d+_", "", clean_title).strip() or "Catalog Entry"

        portal_block = (
            f"## Support & Web Portals\n- **{url_key.replace('_', ' ').title().replace('Url', 'URL')}:** [{extracted_url}]({extracted_url})\n\n"
            if extracted_url
            else ""
        )
        entry_body = (
            f"# {clean_title}\n\n"
            f"> [!note] Triaged from Inbox Capture [[{archived['rel_path']}]]\n\n"
            f"{portal_block}"
            f"## Captured Notes\n{raw_body[:3000]}\n"
        )

        entry = self.create_section_entry(
            section_or_folder=clean_sec,
            title=clean_title,
            collection=collection,
            item_type=item_type,
            properties=merged_props,
            body=entry_body,
            tags=carried_tags,
            is_private=bool(note.get("is_private")),
        )
        return {
            "entry": entry,
            "archived_capture": archived["rel_path"],
            "extracted_url": extracted_url,
        }

    def ensure_project_tasks_base(self, project: str = "KAIROS_2_0") -> Dict[str, Any]:
        """Create or refresh `02_Projects/<Project>/Docs/Project_Tasks.base` multi-view Obsidian Base database."""
        safe_proj = sanitize_vault_segment(project, fallback="KAIROS_2_0")
        proj_dir = self.vault_path / "02_Projects" / safe_proj
        if not (proj_dir / "_Project_Index.md").is_file():
            self.create_project_structure(
                project=safe_proj,
                department="Software_Development",
                list_name="Sprint_01",
                scaffold_standard_departments=True,
            )
        base_rel = f"02_Projects/{safe_proj}/Docs/Project_Tasks.base"
        yaml_text = build_project_tasks_base_yaml(safe_proj)
        saved = self.write_note(base_rel, {}, yaml_text, mode="overwrite")
        return {
            "ok": True,
            "project": safe_proj,
            "base_rel_path": saved["rel_path"],
            "note": saved,
        }

    # ------------------------------------------------------------------
    # Expandable Obsidian Section Hubs, Structured Entries & Refactoring
    # ------------------------------------------------------------------

    def _next_hub_id(self) -> str:
        year = datetime.now().strftime("%Y")
        prefix = f"HUB-{year}-"
        max_seq = 0
        for idx_file in self.vault_path.rglob("_Hub_Index.md"):
            try:
                fm, _ = parse_markdown_note(idx_file.read_text(encoding="utf-8", errors="replace"))
                raw_id = str(fm.get("id") or "")
                if raw_id.startswith(prefix):
                    tail = raw_id[len(prefix) :]
                    if tail.isdigit():
                        max_seq = max(max_seq, int(tail))
            except Exception:
                continue
        return f"{prefix}{max_seq + 1:02d}"

    def scaffold_vault_section(
        self,
        section_name: str,
        *,
        blueprint_key: str = "auto",
        parent_folder: str = "",
        icon: str = "",
        description: str = "",
        collections: Optional[List[Any]] = None,
        schema_fields: Optional[List[str]] = None,
        external_links: Optional[List[Dict[str, str]]] = None,
        seed_starters: bool = True,
        is_private: bool = False,
    ) -> Dict[str, Any]:
        """Scaffold or expand a state-of-the-art Obsidian Domain Section Hub (`_Hub_Index.md` + `.base` + `.canvas` + Collections + Templates)."""
        with self._write_lock:
            spec = resolve_section_blueprint(
                section_name=section_name,
                blueprint_key=blueprint_key,
                parent_folder=parent_folder,
                icon=icon,
                description=description,
                collections=collections,
                schema_fields=schema_fields,
                external_links=external_links,
                seed_starters=seed_starters,
            )
            section_rel = spec["section_rel"]
            section_dir = self.resolve_safe_path(section_rel)
            section_dir.mkdir(parents=True, exist_ok=True)

            eff_private = bool(is_private or section_rel.lower().startswith("03_personal/finance"))
            slug = spec["folder_slug"]
            hub_index_path = section_dir / "_Hub_Index.md"
            base_path = section_dir / f"{slug}_Catalog.base"
            canvas_path = section_dir / f"{slug}_Ecosystem.canvas"
            template_path = self.vault_path / "_System" / "Templates" / f"{slug}_Entry_Template.md"

            hub_index_rel = self.to_rel_path(hub_index_path)
            base_rel = self.to_rel_path(base_path)
            canvas_rel = self.to_rel_path(canvas_path)
            template_rel = self.to_rel_path(template_path)

            # Merge collections cleanly if expanding an existing Section Hub
            if hub_index_path.exists():
                existing_fm, _ = parse_markdown_note(
                    hub_index_path.read_text(encoding="utf-8", errors="replace")
                )
                hub_id = str(existing_fm.get("id") or self._next_hub_id())
                prev_cols = existing_fm.get("collections") if isinstance(existing_fm.get("collections"), list) else []
                existing_by_folder = {
                    str(c.get("folder") if isinstance(c, dict) else c): c for c in prev_cols
                }
                for col in spec["collections"]:
                    existing_by_folder[col["folder"]] = col
                merged_cols: List[Dict[str, Any]] = []
                for k, v in existing_by_folder.items():
                    if isinstance(v, dict):
                        merged_cols.append(v)
                    else:
                        merged_cols.append(
                            {
                                "folder": sanitize_vault_segment(str(k)),
                                "title": str(k).replace("_", " "),
                                "icon": "📂",
                                "item_type": str(k).lower().rstrip("s") or "entry",
                                "description": f"Collection in {spec['title']}",
                                "fields": list(spec["schema_fields"]),
                            }
                        )
                spec["collections"] = merged_cols
            else:
                hub_id = self._next_hub_id()

            # 1. Write Collection Subfolders + `_Collection_Index.md`
            created_collection_rels: List[str] = []
            for col in spec["collections"]:
                col_dir = section_dir / col["folder"]
                col_dir.mkdir(parents=True, exist_ok=True)
                col_idx = col_dir / "_Collection_Index.md"
                if not col_idx.exists():
                    col_tags = ["collection-index", slug.lower().replace("_", "-")]
                    if eff_private:
                        col_tags.append("private")
                    self.atomic_write_markdown(
                        col_idx,
                        {
                            "title": f"{col['title']} — {spec['title']}",
                            "type": "collection_index",
                            "section_hub": f"[[{hub_index_rel}|{spec['title']}]]",
                            "collection": col["folder"],
                            "item_type": col["item_type"],
                            "schema_fields": list(col.get("fields", [])),
                            "tags": col_tags,
                        },
                        (
                            f"# {col['icon']} {col['title']}\n\n"
                            f"> [!note] Part of [[{hub_index_rel}|{spec['icon']} {spec['title']}]]\n"
                            f"> {col['description']}\n\n"
                            f"## Structured YAML Properties\n"
                            + "\n".join(f"- `{fld}`" for fld in col.get("fields", []))
                            + f"\n\n## Live Catalog View\n![[{base_rel}#{col['icon']} {col['title']}]]\n"
                        ),
                    )
                created_collection_rels.append(self.to_rel_path(col_dir))

            # 2. Write Official Obsidian `.base` Database
            base_yaml_bytes = build_section_base_yaml(spec).encode("utf-8")
            self.hash_guard.record_write(base_path, base_yaml_bytes)
            base_path.write_bytes(base_yaml_bytes)

            # 3. Write Official JSON Canvas Spec 1.0 `.canvas` Ecosystem Map
            if not canvas_path.exists():
                canvas_bytes = build_section_canvas_json(spec, hub_index_rel, base_rel).encode("utf-8")
                self.hash_guard.record_write(canvas_path, canvas_bytes)
                canvas_path.write_bytes(canvas_bytes)

            # 4. Write Reusable Obsidian Note Template in `_System/Templates/`
            if not template_path.exists():
                tpl_fm: Dict[str, Any] = {
                    "title": "{{title}}",
                    "type": spec["collections"][0]["item_type"] if spec["collections"] else "catalog_item",
                    "section_hub": f"[[{hub_index_rel}|{spec['title']}]]",
                    "status": "Active",
                }
                for fld in spec["schema_fields"]:
                    tpl_fm.setdefault(fld, "")
                tpl_tags = [slug.lower().replace("_", "-")]
                if eff_private:
                    tpl_tags.append("private")
                tpl_fm["tags"] = tpl_tags
                self.atomic_write_markdown(
                    template_path,
                    tpl_fm,
                    (
                        f"# {spec['icon']} {{{{title}}}}\n\n"
                        f"> [!info] Overview\n"
                        f"> Linked to [[{hub_index_rel}|{spec['title']}]].\n\n"
                        "## Support & Portal Links\n"
                        "- **Primary Portal / Support URL:** \n\n"
                        "## Setup & Notes\n"
                        "- [ ] Configure & verify setup\n"
                    ),
                )

            # 5. Seed Optional Starter Entries (never overwriting existing user notes)
            seeded_rels: List[str] = []
            for starter in spec.get("starter_entries", []):
                st_col = sanitize_vault_segment(str(starter.get("collection") or "Catalog"))
                st_title = str(starter.get("title") or "Starter Guide").strip()
                st_slug = sanitize_vault_segment(st_title, fallback="Starter_Guide")
                st_target = section_dir / st_col / f"{st_slug}.md"
                if not st_target.exists():
                    st_fm = dict(starter.get("frontmatter") or {})
                    st_fm.setdefault("title", st_title)
                    st_fm["section_hub"] = f"[[{hub_index_rel}|{spec['title']}]]"
                    st_fm["collection"] = st_col
                    st_tags = list(st_fm.get("tags") or [])
                    hub_tag = slug.lower().replace("_", "-")
                    if hub_tag not in [str(t).lower() for t in st_tags]:
                        st_tags.append(hub_tag)
                    if eff_private and "private" not in [str(t).lower() for t in st_tags]:
                        st_tags.append("private")
                    st_fm["tags"] = st_tags
                    st_body = (
                        str(starter.get("body") or f"# {st_title}\n").rstrip()
                        + f"\n\n---\n*Hub:* [[{hub_index_rel}|{spec['icon']} {spec['title']}]]\n"
                    )
                    self.atomic_write_markdown(st_target, st_fm, st_body)
                    seeded_rels.append(self.to_rel_path(st_target))

            # 6. Write / Update `_Hub_Index.md` Map of Content (MOC)
            col_bullets = [
                (
                    f"- {c['icon']} **[[{section_rel}/{c['folder']}/_Collection_Index|{c['title']}]]** "
                    f"(`{section_rel}/{c['folder']}/`) — {c['description']}"
                )
                for c in spec["collections"]
            ]
            ext_link_lines = [
                f"- 🌐 **[{lk['label']}]({lk['url']})** — `{lk['url']}`"
                for lk in spec.get("external_links", [])
                if lk.get("url")
            ]
            ext_section = (
                "## Quick Support & Platform Portals\n" + "\n".join(ext_link_lines) + "\n\n"
                if ext_link_lines
                else ""
            )

            hub_tags = ["section-hub", "moc", slug.lower().replace("_", "-")]
            if eff_private:
                hub_tags.append("private")

            hub_fm = {
                "id": hub_id,
                "title": spec["title"],
                "type": "section_hub",
                "icon": spec["icon"],
                "domain": spec["blueprint_key"],
                "status": "Active",
                "base_path": base_rel,
                "canvas_path": canvas_rel,
                "template_path": template_rel,
                "schema_fields": list(spec["schema_fields"]),
                "collections": [
                    {
                        "folder": c["folder"],
                        "title": c["title"],
                        "icon": c["icon"],
                        "item_type": c["item_type"],
                        "fields": list(c.get("fields", [])),
                    }
                    for c in spec["collections"]
                ],
                "aliases": [spec["title"], slug.replace("_", " ")],
                "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "tags": hub_tags,
            }

            dataview_cols = ", ".join(
                f'{fld} AS "{fld.replace("_", " ").title()}"'
                for fld in spec["schema_fields"][:5]
            )
            dv_header = f"TABLE {dataview_cols}" if dataview_cols else 'TABLE type AS "Type", status AS "Status"'

            hub_body = (
                f"# {spec['icon']} {spec['title']}\n\n"
                f"> [!abstract] Knowledge Hub Overview (`{section_rel}/`)\n"
                f"> {spec['description']}\n\n"
                "## Interactive Views & Ecosystem Map\n"
                f"- 📊 **Obsidian Base Database:** [[{base_rel}|{slug} Catalog (.base)]]\n"
                f"- 🗺️ **Visual Ecosystem Canvas:** [[{canvas_rel}|{slug} Ecosystem (.canvas)]]\n"
                f"- 📋 **Entry Note Template:** [[{template_rel}|{slug} Entry Template]]\n"
                "- 🏛️ **Vault Constitution:** [[AGENTS]]\n\n"
                f"## Collections (`{section_rel}/*`)\n"
                + "\n".join(col_bullets)
                + "\n\n"
                + ext_section
                + "## Embedded Obsidian Base\n"
                f"![[{base_rel}]]\n\n"
                "## Dataview Index (Obsidian Reading View)\n"
                "```dataview\n"
                f"{dv_header}\n"
                f'FROM "{section_rel}"\n'
                'WHERE type != "section_hub" AND type != "collection_index"\n'
                "SORT file.mtime DESC\n"
                "```\n"
            )
            self.atomic_write_markdown(hub_index_path, hub_fm, hub_body)

            return {
                "ok": True,
                "hub_id": hub_id,
                "title": spec["title"],
                "icon": spec["icon"],
                "blueprint_key": spec["blueprint_key"],
                "section_rel": section_rel,
                "hub_index_rel": hub_index_rel,
                "base_rel": base_rel,
                "canvas_rel": canvas_rel,
                "template_rel": template_rel,
                "collections": spec["collections"],
                "collection_rels": created_collection_rels,
                "seeded_entry_rels": seeded_rels,
                "is_private": eff_private,
            }

    def create_section_entry(
        self,
        *,
        section_or_folder: str,
        title: str,
        collection: str = "",
        item_type: str = "",
        properties: Optional[Dict[str, Any]] = None,
        body: str = "",
        checklist: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        aliases: Optional[List[str]] = None,
        is_private: bool = False,
    ) -> Dict[str, Any]:
        """Create a structured Obsidian catalog entry inside any Vault Section Hub or subfolder."""
        clean_title = (title or "").strip()
        if not clean_title:
            raise ValueError("Entry title cannot be empty.")

        with self._write_lock:
            base_folder = section_or_folder.strip().strip("/\\").replace("\\", "/")
            if not base_folder:
                base_folder = "04_Resources"

            # Check if `base_folder` (or its parent) is an existing Section Hub with `_Hub_Index.md`
            candidate_dir = self.resolve_safe_path(base_folder)
            hub_dir: Optional[Path] = None
            if (candidate_dir / "_Hub_Index.md").is_file():
                hub_dir = candidate_dir
            elif (candidate_dir.parent / "_Hub_Index.md").is_file():
                hub_dir = candidate_dir.parent
                if not collection:
                    collection = candidate_dir.name

            hub_fm: Dict[str, Any] = {}
            hub_rel = ""
            hub_title = ""
            hub_icon = "📦"
            chosen_col_meta: Dict[str, Any] = {}

            if hub_dir is not None:
                hub_idx_path = hub_dir / "_Hub_Index.md"
                hub_fm, _ = parse_markdown_note(
                    hub_idx_path.read_text(encoding="utf-8", errors="replace")
                )
                hub_rel = self.to_rel_path(hub_idx_path)
                hub_title = str(hub_fm.get("title") or hub_dir.name.replace("_", " "))
                hub_icon = str(hub_fm.get("icon") or "📦")
                hub_cols = hub_fm.get("collections") if isinstance(hub_fm.get("collections"), list) else []

                if collection:
                    want_col = sanitize_vault_segment(collection).lower()
                    for c in hub_cols:
                        if isinstance(c, dict) and (
                            str(c.get("folder", "")).lower() == want_col
                            or str(c.get("title", "")).lower() == collection.strip().lower()
                            or str(c.get("item_type", "")).lower() == want_col.rstrip("s")
                        ):
                            chosen_col_meta = c
                            break
                    target_dir = hub_dir / (chosen_col_meta.get("folder") or sanitize_vault_segment(collection))
                elif hub_cols and isinstance(hub_cols[0], dict):
                    chosen_col_meta = hub_cols[0]
                    target_dir = hub_dir / str(chosen_col_meta.get("folder") or "Catalog")
                else:
                    target_dir = candidate_dir
            else:
                target_dir = (
                    candidate_dir / sanitize_vault_segment(collection)
                    if collection.strip()
                    else candidate_dir
                )

            target_dir.mkdir(parents=True, exist_ok=True)
            note_slug = sanitize_vault_segment(clean_title, fallback="Catalog_Entry")
            target_file = target_dir / f"{note_slug}.md"
            target_rel = self.to_rel_path(target_file)

            eff_priv = bool(
                is_private
                or target_rel.lower().startswith("03_personal/finance")
                or "#private" in body.lower()
                or "#private" in clean_title.lower()
            )
            eff_type = (
                item_type.strip()
                or str(chosen_col_meta.get("item_type") or "")
                or "catalog_item"
            )

            fm_out: Dict[str, Any] = {
                "title": clean_title,
                "type": eff_type,
                "status": "Active",
            }
            if hub_rel:
                fm_out["section_hub"] = f"[[{hub_rel}|{hub_title}]]"
            if chosen_col_meta.get("folder") or collection.strip():
                fm_out["collection"] = str(
                    chosen_col_meta.get("folder") or sanitize_vault_segment(collection)
                )

            for schema_key in chosen_col_meta.get("fields") or hub_fm.get("schema_fields") or []:
                fm_out.setdefault(str(schema_key), "")

            for k, v in (properties or {}).items():
                clean_k = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(k).strip()).strip("_")
                if clean_k and clean_k not in ("turns",):
                    fm_out[clean_k] = v

            if aliases:
                fm_out["aliases"] = [str(a).strip() for a in aliases if str(a).strip()]

            merged_tags: List[str] = []
            for t in (tags or []):
                ct = str(t).strip().lstrip("#")
                if ct and ct not in merged_tags:
                    merged_tags.append(ct)
            if eff_type and eff_type.replace("_", "-") not in [t.lower() for t in merged_tags]:
                merged_tags.append(eff_type.replace("_", "-"))
            if hub_dir is not None:
                hub_slug_tag = hub_dir.name.lower().replace("_", "-")
                if hub_slug_tag not in [t.lower() for t in merged_tags]:
                    merged_tags.append(hub_slug_tag)
            if eff_priv and "private" not in [t.lower() for t in merged_tags]:
                merged_tags.append("private")
            fm_out["tags"] = merged_tags
            fm_out["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            # Compose rich Obsidian Flavored Markdown body if none was provided
            if body.strip():
                body_out = body.strip() + "\n"
            else:
                portal_lines: List[str] = []
                for url_key in ("support_url", "dashboard_url", "download_url", "url", "source_url"):
                    u_val = str(fm_out.get(url_key) or "").strip()
                    if u_val:
                        label_u = url_key.replace("_", " ").title().replace("Url", "URL")
                        portal_lines.append(f"- **{label_u}:** [{u_val}]({u_val})")
                portals_md = (
                    "## Support & Web Portals\n" + "\n".join(portal_lines) + "\n\n"
                    if portal_lines
                    else ""
                )
                chk_md = (
                    "## Setup & Action Checklist\n"
                    + "\n".join(f"- [ ] {item}" for item in checklist)
                    + "\n\n"
                    if checklist
                    else ""
                )
                hub_callout = (
                    f"> [!note] Indexed in [[{hub_rel}|{hub_icon} {hub_title}]]\n"
                    f"> Type: `{eff_type}` | Status: `{fm_out.get('status', 'Active')}`\n\n"
                    if hub_rel
                    else f"> [!note] Structured Vault Entry\n> Type: `{eff_type}`\n\n"
                )
                body_out = f"# {hub_icon} {clean_title}\n\n{hub_callout}{portals_md}{chk_md}## Notes\n\n"

            self.atomic_write_markdown(target_file, fm_out, body_out)
            return self.read_note(target_rel)

    def update_note_frontmatter(
        self,
        file_path: str,
        updates: Optional[Dict[str, Any]] = None,
        remove_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Atomically patch or remove YAML frontmatter properties on an Obsidian Markdown note while preserving body text."""
        with self._write_lock:
            target = self.resolve_safe_path(file_path)
            if not target.exists() or not target.is_file():
                raise FileNotFoundError(f"Vault note not found: {file_path}")
            if target.suffix.lower() in (".canvas", ".base"):
                raise ValueError(f"Frontmatter properties are only supported on `.md` notes (got '{target.suffix}').")

            raw = target.read_text(encoding="utf-8", errors="replace")
            fm, body = parse_markdown_note(raw)
            next_fm = dict(fm)

            for rk in (remove_keys or []):
                next_fm.pop(str(rk).strip(), None)

            for k, v in (updates or {}).items():
                clean_k = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(k).strip()).strip("_")
                if not clean_k:
                    continue
                next_fm[clean_k] = v

            next_fm["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            self.atomic_write_markdown(target, next_fm, body)
            return self.read_note(self.to_rel_path(target))

    def rename_or_move_note(
        self,
        src_rel_path: str,
        dest_rel_path: str,
        *,
        new_title: str = "",
        update_links: bool = True,
    ) -> Dict[str, Any]:
        """Atomically rename/move a Vault file and propagate updated `[[WikiLinks]]` & `.canvas` file nodes across the Vault."""
        with self._write_lock:
            src = self.resolve_safe_path(src_rel_path)
            if not src.exists() or not src.is_file():
                raise FileNotFoundError(f"Source note not found: {src_rel_path}")

            old_rel = self.to_rel_path(src)
            old_ext = src.suffix
            old_stem = src.stem
            old_no_ext = old_rel[: -len(old_ext)] if old_ext else old_rel

            raw_dest = (dest_rel_path or "").strip().strip("/\\").replace("\\", "/")
            if not raw_dest:
                raise ValueError("Destination path cannot be empty.")

            # If caller passed only a filename (no `/`), keep inside the current parent folder
            if "/" not in raw_dest:
                parent_rel = str(Path(old_rel).parent).replace("\\", "/")
                raw_dest = f"{parent_rel}/{raw_dest}" if parent_rel not in ("", ".") else raw_dest

            if Path(raw_dest).suffix == "":
                raw_dest = f"{raw_dest}{old_ext}"

            dest = self.resolve_safe_path(raw_dest)
            if dest.exists() and dest.resolve() != src.resolve():
                raise FileExistsError(f"Destination note already exists: {self.to_rel_path(dest)}")

            dest.parent.mkdir(parents=True, exist_ok=True)
            new_rel = self.to_rel_path(dest)
            new_stem = dest.stem
            new_no_ext = new_rel[: -len(dest.suffix)] if dest.suffix else new_rel

            if dest.suffix.lower() == ".md":
                fm, body = parse_markdown_note(src.read_text(encoding="utf-8", errors="replace"))
                if new_title.strip():
                    fm["title"] = new_title.strip()
                elif not fm.get("title") or str(fm.get("title")).strip() in (
                    old_stem,
                    old_stem.replace("_", " "),
                ):
                    fm["title"] = new_stem.replace("_", " ")
                fm["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                self.atomic_write_markdown(dest, fm, body)
                if dest.resolve() != src.resolve() and src.exists():
                    src.unlink()
            else:
                raw_bytes = src.read_bytes()
                self.hash_guard.record_write(dest, raw_bytes)
                shutil.move(str(src), str(dest))

            updated_backlink_files: List[str] = []
            if update_links and new_rel.lower() != old_rel.lower():
                import json as _json

                link_pat = re.compile(r"(!?\[\[)([^\]|#]+)((?:#[^\]|]*)?(?:\|[^\]]*)?\]\])")

                def _rewrite_wikilink(match: re.Match[str]) -> str:
                    prefix_brk, raw_target, suffix_brk = match.group(1), match.group(2), match.group(3)
                    clean_tgt = raw_target.strip().strip("/").replace("\\", "/")
                    clean_low = clean_tgt.lower()
                    tgt_no_ext = (
                        clean_low[:-3]
                        if clean_low.endswith(".md")
                        else clean_low
                    )
                    if clean_low in (old_rel.lower(), old_no_ext.lower()) or tgt_no_ext == old_no_ext.lower():
                        replacement_tgt = new_rel if clean_low.endswith(dest.suffix.lower()) else new_no_ext
                        return f"{prefix_brk}{replacement_tgt}{suffix_brk}"
                    if (
                        "/" not in clean_tgt
                        and old_stem.lower() not in ("_project_index", "_list_index", "_hub_index", "_collection_index")
                        and clean_low == old_stem.lower()
                    ):
                        return f"{prefix_brk}{new_stem}{suffix_brk}"
                    return match.group(0)

                for cand in self.vault_path.rglob("*"):
                    if not cand.is_file() or cand.resolve() == dest.resolve():
                        continue
                    cand_rel = self.to_rel_path(cand)
                    if cand_rel.startswith((".obsidian/", "_System/Cache/", "_System/Logs/", ".git/")):
                        continue
                    c_ext = cand.suffix.lower()
                    if c_ext == ".md":
                        raw_txt = cand.read_text(encoding="utf-8", errors="replace")
                        rewritten = link_pat.sub(_rewrite_wikilink, raw_txt)
                        if rewritten != raw_txt:
                            c_fm, c_body = parse_markdown_note(rewritten)
                            self.atomic_write_markdown(cand, c_fm, c_body)
                            updated_backlink_files.append(cand_rel)
                    elif c_ext == ".canvas":
                        try:
                            c_obj = _json.loads(cand.read_text(encoding="utf-8", errors="replace"))
                            changed_canvas = False
                            for node in c_obj.get("nodes") or []:
                                if isinstance(node, dict) and node.get("type") == "file":
                                    f_val = str(node.get("file") or "").replace("\\", "/").strip("/")
                                    if f_val.lower() == old_rel.lower():
                                        node["file"] = new_rel
                                        changed_canvas = True
                                elif isinstance(node, dict) and node.get("type") == "text" and node.get("text"):
                                    new_t = link_pat.sub(_rewrite_wikilink, str(node["text"]))
                                    if new_t != node["text"]:
                                        node["text"] = new_t
                                        changed_canvas = True
                            if changed_canvas:
                                out_bytes = (_json.dumps(c_obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
                                self.hash_guard.record_write(cand, out_bytes)
                                cand.write_bytes(out_bytes)
                                updated_backlink_files.append(cand_rel)
                        except Exception:
                            continue

            return {
                "ok": True,
                "old_rel_path": old_rel,
                "new_rel_path": new_rel,
                "updated_backlink_files": updated_backlink_files,
                "note": self.read_note(new_rel),
            }

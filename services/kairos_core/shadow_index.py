"""Disposable SQLite WAL + FTS5 Shadow Index (`_System/Cache/vault_index.sqlite` — `shadow_index.py`).

Provides `< 5ms` Projects Kanban, Gantt, Rollup, Full-Text Search, and Second Brain Graph queries
while keeping Obsidian Markdown + YAML files on disk as the 100% canonical source of truth.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import yaml

from services.kairos_core.schemas import STANDARD_DEPARTMENT_NAMES
from services.kairos_core.vault_blueprint import (
    evaluate_obsidian_base,
    extract_canvas_file_links,
    list_blueprint_catalog,
    validate_and_normalize_canvas,
)
from services.kairos_core.vault_engine import (
    VaultEngine,
    extract_wikilinks_and_tags,
    parse_markdown_note,
)

_DEPT_SORT_ORDER = {name: idx for idx, name in enumerate(STANDARD_DEPARTMENT_NAMES)}
_FTS5_RESERVED = frozenset({"and", "or", "not", "near"})


class IndexRebuildResult(dict):
    """Dict result (`{"indexed_notes": N, "indexed_tasks": M}`) that also supports integer comparisons (`>=`, `>`, `int()`)."""

    def _note_count(self) -> int:
        return int(self.get("indexed_notes", 0))

    def __int__(self) -> int:
        return self._note_count()

    def __ge__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self._note_count() >= other
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self._note_count() > other
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self._note_count() <= other
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self._note_count() < other
        return NotImplemented


def _safe_int(val: Any, default: int = 3) -> int:
    if val is None or val == "":
        return default
    try:
        return int(float(str(val).strip()))
    except (TypeError, ValueError):
        low = str(val).strip().lower()
        if low in ("urgent", "p1", "critical"):
            return 1
        if low in ("high", "p2"):
            return 2
        if low in ("normal", "medium", "p3"):
            return 3
        if low in ("low", "p4"):
            return 4
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "" or isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).strip())
    except (TypeError, ValueError):
        return default


class ShadowIndex:
    """Thread-safe SQLite WAL + FTS5 derived index over `Vault_Root/`."""

    def __init__(self, vault: VaultEngine, db_path: Optional[Path] = None) -> None:
        self.vault = vault
        self.db_path = db_path or (vault.vault_path / "_System" / "Cache" / "vault_index.sqlite")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    @contextmanager
    def _db_session(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._db_session() as conn:
            # Automatically upgrade disposable `tasks` cache table if migrating from legacy `space/folder` columns
            existing_cols = {
                str(r["name"])
                for r in conn.execute("PRAGMA table_info(tasks);").fetchall()
            }
            if existing_cols and ("project" not in existing_cols or "department" not in existing_cols):
                conn.execute("DROP TABLE IF EXISTS tasks;")

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    rel_path TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    note_type TEXT NOT NULL,
                    folder_top TEXT NOT NULL,
                    is_private INTEGER NOT NULL DEFAULT 0,
                    frontmatter_json TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    wikilinks_json TEXT NOT NULL,
                    excerpt TEXT NOT NULL,
                    mtime REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    rel_path TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    project TEXT NOT NULL,
                    department TEXT NOT NULL,
                    list_name TEXT NOT NULL,
                    parent_task TEXT NOT NULL,
                    depends_on_json TEXT NOT NULL,
                    assignee TEXT NOT NULL,
                    ai_agent TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    time_estimate_hrs REAL NOT NULL,
                    time_logged_hrs REAL NOT NULL,
                    tags_json TEXT NOT NULL,
                    checklist_total INTEGER NOT NULL DEFAULT 0,
                    checklist_done INTEGER NOT NULL DEFAULT 0,
                    updated_mtime REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS edges (
                    source_path TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    edge_kind TEXT NOT NULL,
                    PRIMARY KEY (source_path, target_name, edge_kind)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS fts_notes USING fts5(
                    rel_path UNINDEXED,
                    title,
                    body,
                    tags
                );
                """
            )

    def _should_skip_rel(self, rel: str) -> bool:
        if rel.startswith((".obsidian/", "_System/Cache/", ".git/")):
            return True
        if (
            rel.startswith("02_Projects/Software_Dev/")
            and (self.vault.vault_path / "02_Projects" / "KAIROS_2_0").is_dir()
        ):
            return True
        return False

    def rebuild_all(self) -> Dict[str, int]:
        """Scan all `.md`, `.base`, and `.canvas` files in `Vault_Root/` and rebuild the shadow index."""
        self.vault.initialize_vault_directories()
        note_count = 0
        task_count = 0
        with self._lock, self._db_session() as conn:
            conn.execute("DELETE FROM notes;")
            conn.execute("DELETE FROM tasks;")
            conn.execute("DELETE FROM edges;")
            conn.execute("DELETE FROM fts_notes;")

            for path in self.vault.vault_path.rglob("*"):
                if not path.is_file():
                    continue
                rel = self.vault.to_rel_path(path)
                if self._should_skip_rel(rel):
                    continue
                if path.suffix.lower() not in (".md", ".canvas", ".base"):
                    continue
                try:
                    is_task = self._index_path_in_tx(conn, path, rel)
                except Exception:
                    continue
                note_count += 1
                if is_task:
                    task_count += 1
        return IndexRebuildResult({"indexed_notes": note_count, "indexed_tasks": task_count})

    def index_file(self, abs_path: Path) -> None:
        if not abs_path.exists() or not abs_path.is_file():
            self.remove_file(abs_path)
            return
        if abs_path.suffix.lower() not in (".md", ".canvas", ".base"):
            return
        rel = self.vault.to_rel_path(abs_path)
        if self._should_skip_rel(rel):
            return
        with self._lock, self._db_session() as conn:
            self._index_path_in_tx(conn, abs_path, rel)

    def remove_file(self, abs_path: Path) -> None:
        try:
            rel = self.vault.to_rel_path(abs_path)
        except ValueError:
            return
        with self._lock, self._db_session() as conn:
            conn.execute("DELETE FROM notes WHERE rel_path = ?;", (rel,))
            conn.execute("DELETE FROM tasks WHERE rel_path = ?;", (rel,))
            conn.execute("DELETE FROM edges WHERE source_path = ?;", (rel,))
            conn.execute("DELETE FROM fts_notes WHERE rel_path = ?;", (rel,))

    def remove_path(self, abs_path: Path) -> None:
        """Alias for `remove_file` used when relocating task or note paths on disk."""
        self.remove_file(abs_path)

    def _index_path_in_tx(self, conn: sqlite3.Connection, path: Path, rel: str) -> bool:
        raw = path.read_text(encoding="utf-8", errors="replace")
        mtime = path.stat().st_mtime
        ext = path.suffix.lower()
        if ext == ".md":
            fm, body = parse_markdown_note(raw)
        else:
            fm, body = {"type": ext.lstrip(".")}, raw

        links, tags = extract_wikilinks_and_tags(fm, body)
        title = str(fm.get("title") or path.stem.replace("_", " "))
        note_type = str(
            fm.get("type")
            or ("canvas" if ext == ".canvas" else ("base" if ext == ".base" else "note"))
        )
        folder_top = rel.split("/")[0] if "/" in rel else "Root"
        is_priv = 1 if self.vault.is_private_note(rel, fm, body) else 0
        excerpt = " ".join(body.split())[:280]

        conn.execute("DELETE FROM edges WHERE source_path = ?;", (rel,))
        conn.execute("DELETE FROM fts_notes WHERE rel_path = ?;", (rel,))
        conn.execute("DELETE FROM tasks WHERE rel_path = ?;", (rel,))

        conn.execute(
            """
            INSERT OR REPLACE INTO notes
            (rel_path, title, note_type, folder_top, is_private, frontmatter_json, tags_json, wikilinks_json, excerpt, mtime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                rel,
                title,
                note_type,
                folder_top,
                is_priv,
                json.dumps(fm),
                json.dumps(tags),
                json.dumps(links),
                excerpt,
                mtime,
            ),
        )
        fts_tags_blob = " ".join(
            part for part in [*tags, path.stem, str(fm.get("id") or "")] if part
        )
        conn.execute(
            "INSERT INTO fts_notes (rel_path, title, body, tags) VALUES (?, ?, ?, ?);",
            (rel, title, body, fts_tags_blob),
        )

        for target in links:
            conn.execute(
                "INSERT OR IGNORE INTO edges (source_path, target_name, edge_kind) VALUES (?, ?, 'wikilink');",
                (rel, target),
            )

        if ext == ".canvas":
            for canvas_file_ref in extract_canvas_file_links(raw):
                conn.execute(
                    "INSERT OR IGNORE INTO edges (source_path, target_name, edge_kind) VALUES (?, ?, 'canvas_file');",
                    (rel, canvas_file_ref),
                )

        is_task = (
            rel.startswith("02_Projects/")
            and "/Templates/" not in rel
            and (note_type in ("task", "subtask", "bug", "milestone", "epic") or path.stem.startswith("TSK-"))
            and "{{" not in str(fm.get("id") or "")
            and "{{" not in str(fm.get("project") or "")
        )
        if is_task and ext == ".md":
            task_id = str(fm.get("id") or path.stem)
            parts = rel.split("/")
            # Canonical path: 02_Projects/[Project]/[Department]/[List]/Tasks/TSK-*.md
            inferred_project = (
                parts[1]
                if len(parts) > 2 and parts[0] == "02_Projects"
                else str(fm.get("project") or fm.get("folder") or "KAIROS_2_0").strip("[]")
            )
            inferred_dept = (
                parts[2]
                if len(parts) > 3 and parts[0] == "02_Projects"
                else str(fm.get("department") or fm.get("space") or "Software_Development")
            )
            inferred_list = (
                parts[3]
                if len(parts) > 4 and parts[0] == "02_Projects"
                else str(fm.get("list") or "Sprint_01")
            )

            proj_val = (
                inferred_project
                if len(parts) > 2 and parts[0] == "02_Projects"
                else (str(fm.get("project") or inferred_project).strip("[]") or inferred_project)
            )
            dept_val = str(fm.get("department") or inferred_dept) or inferred_dept
            list_val = str(fm.get("list") or inferred_list) or inferred_list

            chk_total = 0
            chk_done = 0
            for ln in body.splitlines():
                ls = ln.strip()
                if ls.startswith("- [ ]"):
                    chk_total += 1
                elif ls.startswith(("- [x]", "- [X]")):
                    chk_total += 1
                    chk_done += 1

            deps = fm.get("depends_on") if isinstance(fm.get("depends_on"), list) else []
            for dep in deps:
                clean_dep = str(dep).strip("[]")
                if clean_dep:
                    conn.execute(
                        "INSERT OR IGNORE INTO edges (source_path, target_name, edge_kind) VALUES (?, ?, 'depends_on');",
                        (rel, clean_dep),
                    )

            conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    task_id, rel_path, title, task_type, status, priority,
                    project, department, list_name, parent_task, depends_on_json,
                    assignee, ai_agent, start_date, due_date,
                    time_estimate_hrs, time_logged_hrs, tags_json,
                    checklist_total, checklist_done, updated_mtime
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    task_id,
                    rel,
                    title,
                    note_type if note_type in ("task", "subtask", "bug", "milestone", "epic") else "task",
                    str(fm.get("status") or "To Do"),
                    _safe_int(fm.get("priority"), 3),
                    proj_val,
                    dept_val,
                    list_val,
                    str(fm.get("parent_task") or ""),
                    json.dumps(deps),
                    str(fm.get("assignee") or "Jaime"),
                    str(fm.get("ai_agent") or "None"),
                    str(fm.get("start_date") or ""),
                    str(fm.get("due_date") or ""),
                    _safe_float(fm.get("time_estimate_hrs"), 0.0),
                    _safe_float(fm.get("time_logged_hrs"), 0.0),
                    json.dumps(tags),
                    chk_total,
                    chk_done,
                    mtime,
                ),
            )
            return True
        return False

    def search_vault(
        self,
        query: str = "",
        folder: str = "",
        tags: Optional[List[str]] = None,
        frontmatter_filter: Optional[Dict[str, Any]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        norm_folder = folder.strip().strip("/").lower()
        raw_query = (query or "").strip()
        tokens = [
            tok
            for tok in re.findall(r"[A-Za-z0-9_]+", raw_query)
            if tok.strip("_") and tok.lower() not in _FTS5_RESERVED
        ]
        if not tokens and raw_query:
            tokens = [tok for tok in re.findall(r"[A-Za-z0-9]+", raw_query) if tok]
        if raw_query and not tokens:
            return []

        with self._lock, self._db_session() as conn:
            if tokens:
                safe_q = " ".join(f'"{tok}"*' for tok in tokens)
                if norm_folder:
                    rows = conn.execute(
                        """
                        SELECT n.* FROM fts_notes f
                        JOIN notes n ON n.rel_path = f.rel_path
                        WHERE fts_notes MATCH ?
                          AND (LOWER(n.rel_path) = ? OR LOWER(n.rel_path) LIKE ?)
                        ORDER BY rank LIMIT ?;
                        """,
                        (safe_q, norm_folder, f"{norm_folder}/%", limit * 3),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT n.* FROM fts_notes f
                        JOIN notes n ON n.rel_path = f.rel_path
                        WHERE fts_notes MATCH ?
                        ORDER BY rank LIMIT ?;
                        """,
                        (safe_q, limit * 3),
                    ).fetchall()
            else:
                if norm_folder:
                    rows = conn.execute(
                        """
                        SELECT * FROM notes
                        WHERE LOWER(rel_path) = ? OR LOWER(rel_path) LIKE ?
                        ORDER BY mtime DESC LIMIT ?;
                        """,
                        (norm_folder, f"{norm_folder}/%", limit * 3),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM notes ORDER BY mtime DESC LIMIT ?;", (limit * 3,)
                    ).fetchall()

        results: List[Dict[str, Any]] = []
        req_tags = {t.strip().lstrip("#").lower() for t in (tags or []) if t.strip()}
        fm_filter = frontmatter_filter or {}

        for r in rows:
            rel = r["rel_path"]
            rel_low = rel.lower()
            if norm_folder and not (rel_low == norm_folder or rel_low.startswith(f"{norm_folder}/")):
                continue
            note_tags = [str(t) for t in json.loads(r["tags_json"])]
            if req_tags and not req_tags.issubset({t.lower() for t in note_tags}):
                continue
            fm = json.loads(r["frontmatter_json"])
            if any(str(fm.get(k)) != str(v) for k, v in fm_filter.items()):
                continue
            results.append(
                {
                    "rel_path": rel,
                    "title": r["title"],
                    "type": r["note_type"],
                    "folder_top": r["folder_top"],
                    "is_private": bool(r["is_private"]),
                    "tags": note_tags,
                    "wikilinks": json.loads(r["wikilinks_json"]),
                    "frontmatter": fm,
                    "excerpt": r["excerpt"],
                    "mtime": r["mtime"],
                }
            )
            if len(results) >= limit:
                break
        return results

    def list_tasks(
        self,
        project: str = "",
        department: str = "",
        list_name: str = "",
        status: str = "",
        ai_agent: str = "",
    ) -> List[Dict[str, Any]]:
        clauses = ["1=1"]
        params: List[Any] = []
        if project:
            clauses.append("LOWER(project) = LOWER(?)")
            params.append(project.strip("[]"))
        if department:
            clauses.append("LOWER(department) = LOWER(?)")
            params.append(department)
        if list_name:
            clauses.append("LOWER(list_name) = LOWER(?)")
            params.append(list_name)
        if status:
            clauses.append("LOWER(status) = LOWER(?)")
            params.append(status)
        if ai_agent:
            clauses.append("LOWER(ai_agent) = LOWER(?)")
            params.append(ai_agent)

        sql = f"""
            SELECT * FROM tasks
            WHERE {' AND '.join(clauses)}
            ORDER BY priority ASC, CASE WHEN due_date = '' THEN 1 ELSE 0 END, due_date ASC, task_id ASC;
        """
        with self._lock, self._db_session() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "id": r["task_id"],
                "rel_path": r["rel_path"],
                "title": r["title"],
                "type": r["task_type"],
                "status": r["status"],
                "priority": r["priority"],
                "project": r["project"],
                "department": r["department"],
                "list": r["list_name"],
                "parent_task": r["parent_task"],
                "depends_on": json.loads(r["depends_on_json"]),
                "assignee": r["assignee"],
                "ai_agent": r["ai_agent"],
                "start_date": r["start_date"],
                "due_date": r["due_date"],
                "time_estimate_hrs": r["time_estimate_hrs"],
                "time_logged_hrs": r["time_logged_hrs"],
                "tags": json.loads(r["tags_json"]),
                "checklist_total": r["checklist_total"],
                "checklist_done": r["checklist_done"],
            }
            for r in rows
        ]

    def get_projects_hierarchy(self) -> List[Dict[str, Any]]:
        """Build the Projects Sidebar Tree: `Everything -> Project -> Department / Portion -> List / Sprint`."""
        tasks = self.list_tasks()
        tree: Dict[str, Dict[str, Dict[str, int]]] = {}
        done_by_project: Dict[str, int] = {}

        proj_root = self.vault.vault_path / "02_Projects"
        has_migrated_kairos = (proj_root / "KAIROS_2_0").is_dir()
        existing_project_dirs: set[str] = set()

        if proj_root.exists():
            for proj_dir in sorted(
                p for p in proj_root.iterdir() if p.is_dir() and not p.name.startswith(".")
            ):
                if proj_dir.name == "Software_Dev" and has_migrated_kairos:
                    continue
                existing_project_dirs.add(proj_dir.name)
                tree.setdefault(proj_dir.name, {})
                for dept_dir in sorted(
                    p for p in proj_dir.iterdir() if p.is_dir() and p.name != "Docs"
                ):
                    tree[proj_dir.name].setdefault(dept_dir.name, {})
                    for lst_dir in sorted(
                        p for p in dept_dir.iterdir() if p.is_dir() and p.name not in ("Docs", "Tasks")
                    ):
                        tree[proj_dir.name][dept_dir.name].setdefault(lst_dir.name, 0)

        for t in tasks:
            pr = t["project"]
            if proj_root.exists() and pr not in existing_project_dirs:
                continue
            dp = t["department"]
            ls = t["list"]
            tree.setdefault(pr, {}).setdefault(dp, {})
            tree[pr][dp][ls] = tree[pr][dp].get(ls, 0) + 1
            if t["status"] == "Done":
                done_by_project[pr] = done_by_project.get(pr, 0) + 1

        def _proj_sort_key(name: str) -> Any:
            if name == "KAIROS":
                return (0, name.lower())
            if name == "KAIROS_2_0":
                return (1, name.lower())
            return (2, name.lower())

        def _dept_sort_key(name: str) -> Any:
            return (_DEPT_SORT_ORDER.get(name, 99), name.lower())

        out: List[Dict[str, Any]] = []
        for proj_name in sorted(tree.keys(), key=_proj_sort_key):
            departments_map = tree[proj_name]
            dept_items: List[Dict[str, Any]] = []
            proj_count = 0
            for dept_name in sorted(departments_map.keys(), key=_dept_sort_key):
                lists_map = departments_map[dept_name]
                l_items = [{"name": ln, "task_count": cnt} for ln, cnt in sorted(lists_map.items())]
                dept_count = sum(x["task_count"] for x in l_items)
                proj_count += dept_count
                dept_items.append(
                    {
                        "name": dept_name,
                        "task_count": dept_count,
                        "lists": l_items,
                    }
                )
            done_cnt = done_by_project.get(proj_name, 0)
            pct = int(round((done_cnt / proj_count) * 100)) if proj_count > 0 else 0
            out.append(
                {
                    "name": proj_name,
                    "task_count": proj_count,
                    "progress_pct": pct,
                    "departments": dept_items,
                }
            )
        return out

    def get_rollup(
        self,
        project: str = "",
        department: str = "",
        list_name: str = "",
    ) -> Dict[str, Any]:
        tasks = self.list_tasks(project=project, department=department, list_name=list_name)
        by_status: Dict[str, int] = {
            "Backlog": 0,
            "To Do": 0,
            "In Progress": 0,
            "Review": 0,
            "Blocked": 0,
            "Done": 0,
        }
        by_department: Dict[str, int] = {}
        today_iso = datetime.now().strftime("%Y-%m-%d")
        overdue: List[str] = []
        blocked: List[str] = []
        est_total = 0.0
        logged_total = 0.0

        for t in tasks:
            st = t["status"]
            dp = t["department"]
            by_status[st] = by_status.get(st, 0) + 1
            by_department[dp] = by_department.get(dp, 0) + 1
            est_total += float(t["time_estimate_hrs"] or 0.0)
            logged_total += float(t["time_logged_hrs"] or 0.0)
            if st == "Blocked":
                blocked.append(t["id"])
            if st != "Done" and t["due_date"] and t["due_date"] < today_iso:
                overdue.append(t["id"])

        total = len(tasks)
        done = by_status.get("Done", 0)
        progress_pct = int(round((done / total) * 100)) if total > 0 else 0
        return {
            "scope": {
                "project": project.strip("[]") or "All",
                "department": department or "All",
                "list": list_name or "All",
            },
            "total_tasks": total,
            "progress_pct": progress_pct,
            "by_status": by_status,
            "by_department": by_department,
            "time_estimate_hrs": round(est_total, 2),
            "time_logged_hrs": round(logged_total, 2),
            "overdue_task_ids": overdue,
            "blocked_task_ids": blocked,
        }

    def get_graph_data(self) -> Dict[str, Any]:
        """Return Second Brain Knowledge Graph nodes & `[[WikiLink]]` / `.canvas` / dependency edges."""
        with self._lock, self._db_session() as conn:
            note_rows = conn.execute(
                "SELECT rel_path, title, note_type, folder_top, is_private, frontmatter_json FROM notes;"
            ).fetchall()
            edge_rows = conn.execute(
                "SELECT source_path, target_name, edge_kind FROM edges;"
            ).fetchall()

        nodes: List[Dict[str, Any]] = []
        path_to_id: Dict[str, str] = {}
        stem_to_id: Dict[str, str] = {}
        title_to_id: Dict[str, str] = {}
        generic_index_stems = {"_project_index", "_list_index", "_hub_index", "_collection_index"}

        for r in note_rows:
            nid = str(r["rel_path"])
            nid_low = nid.lower()
            path_to_id[nid_low] = nid
            for ext in (".md", ".canvas", ".base"):
                if nid_low.endswith(ext):
                    path_to_id[nid_low[: -len(ext)]] = nid
                    break

            p_obj = Path(nid)
            stem = p_obj.stem.lower()
            if stem not in generic_index_stems:
                stem_to_id[stem] = nid
            elif stem in ("_project_index", "_hub_index") and p_obj.parent.name:
                stem_to_id[p_obj.parent.name.lower()] = nid
            try:
                fm_obj = json.loads(r["frontmatter_json"] or "{}")
                fm_id = str(fm_obj.get("id") or "").strip().lower()
                if fm_id:
                    stem_to_id[fm_id] = nid
                aliases = fm_obj.get("aliases")
                if isinstance(aliases, list):
                    for al in aliases:
                        al_s = str(al or "").strip().lower()
                        if al_s:
                            title_to_id[al_s] = nid
            except Exception:
                pass
            title_to_id[str(r["title"]).lower()] = nid
            nodes.append(
                {
                    "id": nid,
                    "label": r["title"],
                    "type": r["note_type"],
                    "group": r["folder_top"],
                    "is_private": bool(r["is_private"]),
                }
            )

        resolved_edges: List[Dict[str, str]] = []
        existing_ids = {n["id"] for n in nodes}
        seen_pairs: set[tuple[str, str, str]] = set()
        for e in edge_rows:
            src = e["source_path"]
            tgt_raw = str(e["target_name"]).split("|")[0].split("#")[0].strip().strip("/").replace("\\", "/")
            if not tgt_raw:
                continue
            tgt_low = tgt_raw.lower()
            tgt_no_ext = tgt_low
            for ext in (".md", ".canvas", ".base"):
                if tgt_no_ext.endswith(ext):
                    tgt_no_ext = tgt_no_ext[: -len(ext)]
                    break
            tgt_key = Path(tgt_raw).stem.lower()
            tgt_id = (
                path_to_id.get(tgt_low)
                or path_to_id.get(tgt_no_ext)
                or (stem_to_id.get(tgt_key) if tgt_key not in generic_index_stems else None)
                or title_to_id.get(tgt_low)
            )
            if tgt_id and tgt_id in existing_ids and src in existing_ids and src != tgt_id:
                pair = (src, tgt_id, str(e["edge_kind"]))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    resolved_edges.append(
                        {"source": src, "target": tgt_id, "kind": e["edge_kind"]}
                    )

        return {"nodes": nodes, "edges": resolved_edges}

    def get_backlinks(self, rel_path: str) -> List[Dict[str, Any]]:
        """Return all Vault notes, Project Wikis, Hermes skills, `.canvas` maps, and Tasks linking to `rel_path`."""
        norm_rel = rel_path.strip().strip("/").replace("\\", "/")
        if not norm_rel:
            return []

        p_obj = Path(norm_rel)
        no_ext = norm_rel
        for ext in (".md", ".canvas", ".base"):
            if no_ext.lower().endswith(ext):
                no_ext = no_ext[: -len(ext)]
                break

        generic_index_stems = {"_project_index", "_list_index", "_hub_index", "_collection_index"}
        candidate_keys = {norm_rel.lower(), no_ext.lower()}
        stem_low = p_obj.stem.lower()
        if stem_low not in generic_index_stems:
            candidate_keys.add(stem_low)
        elif stem_low in ("_project_index", "_hub_index") and p_obj.parent.name:
            candidate_keys.add(p_obj.parent.name.lower())

        with self._lock, self._db_session() as conn:
            target_row = conn.execute(
                "SELECT title, frontmatter_json FROM notes WHERE LOWER(rel_path) = ?;",
                (norm_rel.lower(),),
            ).fetchone()
            if target_row is not None:
                t_title = str(target_row["title"] or "").strip().lower()
                if t_title:
                    candidate_keys.add(t_title)
                try:
                    fm_obj = json.loads(target_row["frontmatter_json"] or "{}")
                    fm_id = str(fm_obj.get("id") or "").strip().lower()
                    if fm_id:
                        candidate_keys.add(fm_id)
                    aliases = fm_obj.get("aliases")
                    if isinstance(aliases, list):
                        for al in aliases:
                            al_s = str(al or "").strip().lower()
                            if al_s:
                                candidate_keys.add(al_s)
                except Exception:
                    pass

            rows = conn.execute(
                """
                SELECT e.source_path, e.target_name, e.edge_kind,
                       n.title, n.note_type, n.folder_top, n.is_private, n.excerpt, n.mtime
                FROM edges e
                JOIN notes n ON n.rel_path = e.source_path
                WHERE LOWER(e.source_path) != ?
                ORDER BY CASE WHEN e.edge_kind = 'depends_on' THEN 0 ELSE 1 END, n.mtime DESC;
                """,
                (norm_rel.lower(),),
            ).fetchall()

        seen_sources: set[str] = set()
        backlinks: List[Dict[str, Any]] = []
        for r in rows:
            src = str(r["source_path"])
            if src in seen_sources:
                continue
            raw_tgt = str(r["target_name"] or "").split("|")[0].split("#")[0].strip().strip("/").replace("\\", "/")
            if not raw_tgt:
                continue
            raw_low = raw_tgt.lower()
            raw_no_ext = raw_low
            for ext in (".md", ".canvas", ".base"):
                if raw_no_ext.endswith(ext):
                    raw_no_ext = raw_no_ext[: -len(ext)]
                    break
            tgt_stem = Path(raw_tgt).stem.lower()

            if (
                raw_low in candidate_keys
                or raw_no_ext in candidate_keys
                or (tgt_stem not in generic_index_stems and tgt_stem in candidate_keys)
            ):
                seen_sources.add(src)
                src_stem = Path(src).stem
                backlinks.append(
                    {
                        "rel_path": src,
                        "title": str(r["title"]),
                        "type": str(r["note_type"]),
                        "folder_top": str(r["folder_top"]),
                        "edge_kind": str(r["edge_kind"]),
                        "is_private": bool(r["is_private"]),
                        "excerpt": str(r["excerpt"]),
                        "task_id": src_stem if src_stem.startswith("TSK-") else "",
                    }
                )
        return backlinks

    def discover_vault_structure(self) -> Dict[str, Any]:
        """Auto-discover all Vault Section Hubs, Collections, Folders, `.base` Catalogs, `.canvas` Maps, Templates & Blueprints."""
        self.vault.initialize_vault_directories()
        with self._lock, self._db_session() as conn:
            note_rows = conn.execute(
                "SELECT rel_path, title, note_type, is_private FROM notes ORDER BY rel_path ASC;"
            ).fetchall()

        md_rels: List[str] = []
        bases_list: List[Dict[str, str]] = []
        canvases_list: List[Dict[str, str]] = []
        templates_list: List[Dict[str, str]] = []

        for r in note_rows:
            rel = str(r["rel_path"])
            low = rel.lower()
            folder_str = str(Path(rel).parent).replace("\\", "/")
            if folder_str == ".":
                folder_str = ""
            if low.endswith(".base"):
                bases_list.append({"rel_path": rel, "title": str(r["title"]), "folder": folder_str})
            elif low.endswith(".canvas"):
                canvases_list.append({"rel_path": rel, "title": str(r["title"]), "folder": folder_str})
            elif low.endswith(".md"):
                md_rels.append(rel)
                if low.startswith("_system/templates/"):
                    templates_list.append({"rel_path": rel, "title": str(r["title"])})

        sections: List[Dict[str, Any]] = []
        for hub_idx in sorted(self.vault.vault_path.rglob("_Hub_Index.md")):
            try:
                hub_index_rel = self.vault.to_rel_path(hub_idx)
            except ValueError:
                continue
            if hub_index_rel.startswith((".obsidian/", ".git/", "_System/", "05_Archives/")):
                continue

            hub_dir = hub_idx.parent
            section_rel = self.vault.to_rel_path(hub_dir)
            raw_hub = hub_idx.read_text(encoding="utf-8", errors="replace")
            fm, body = parse_markdown_note(raw_hub)

            base_rel = str(fm.get("base_path") or "").strip()
            if not base_rel or not (self.vault.vault_path / base_rel).is_file():
                found_bases = sorted(hub_dir.glob("*.base"))
                base_rel = self.vault.to_rel_path(found_bases[0]) if found_bases else ""

            canvas_rel = str(fm.get("canvas_path") or "").strip()
            if not canvas_rel or not (self.vault.vault_path / canvas_rel).is_file():
                found_canvases = sorted(hub_dir.glob("*.canvas"))
                canvas_rel = self.vault.to_rel_path(found_canvases[0]) if found_canvases else ""

            template_rel = str(fm.get("template_path") or "").strip()
            schema_fields = [str(f) for f in (fm.get("schema_fields") or []) if str(f).strip()]

            raw_cols = fm.get("collections") if isinstance(fm.get("collections"), list) else []
            col_map: Dict[str, Dict[str, Any]] = {}
            for rc in raw_cols:
                if isinstance(rc, dict) and rc.get("folder"):
                    fld = str(rc["folder"])
                    col_map[fld] = {
                        "folder": fld,
                        "title": str(rc.get("title") or fld.replace("_", " ")),
                        "icon": str(rc.get("icon") or "📂"),
                        "item_type": str(rc.get("item_type") or "catalog_item"),
                        "fields": [str(x) for x in (rc.get("fields") or schema_fields)],
                    }

            # Also pick up any subdirectories created directly in Obsidian Desktop inside this Section Hub
            for sub in sorted(p for p in hub_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
                if sub.name not in col_map:
                    col_map[sub.name] = {
                        "folder": sub.name,
                        "title": sub.name.replace("_", " "),
                        "icon": "📂",
                        "item_type": sub.name.lower().rstrip("s") or "catalog_item",
                        "fields": list(schema_fields),
                    }

            collections_out: List[Dict[str, Any]] = []
            for fld_name, c_meta in col_map.items():
                col_rel = f"{section_rel}/{fld_name}"
                col_prefix = f"{col_rel.lower()}/"
                col_cnt = sum(
                    1
                    for mr in md_rels
                    if mr.lower().startswith(col_prefix)
                    and not Path(mr).stem.startswith("_")
                )
                collections_out.append(
                    {
                        **c_meta,
                        "rel_path": col_rel,
                        "entry_count": col_cnt,
                    }
                )

            sec_prefix = f"{section_rel.lower()}/"
            sec_entry_count = sum(
                1
                for mr in md_rels
                if mr.lower().startswith(sec_prefix)
                and not Path(mr).stem.startswith("_")
            )

            sections.append(
                {
                    "hub_id": str(fm.get("id") or ""),
                    "title": str(fm.get("title") or hub_dir.name.replace("_", " ")),
                    "icon": str(fm.get("icon") or "🧩"),
                    "domain": str(fm.get("domain") or "custom"),
                    "section_rel": section_rel,
                    "hub_index_rel": hub_index_rel,
                    "base_rel": base_rel,
                    "canvas_rel": canvas_rel,
                    "template_rel": template_rel,
                    "schema_fields": schema_fields,
                    "collections": collections_out,
                    "entry_count": sec_entry_count,
                    "is_private": self.vault.is_private_note(hub_index_rel, fm, body),
                }
            )

        # Build clean dynamic list of Vault folders for Explorer, Browser Clipper & Inbox Triage
        folder_set: set[str] = {
            "00_Inbox",
            "01_Business",
            "02_Projects",
            "03_Personal",
            "03_Personal/Calendar",
            "03_Personal/Finance",
            "04_Resources",
            "_System/Dashboards",
            "_System/Templates",
        }
        for sec in sections:
            folder_set.add(sec["section_rel"])
            for col in sec["collections"]:
                folder_set.add(col["rel_path"])

        for d_path in self.vault.vault_path.rglob("*"):
            if not d_path.is_dir():
                continue
            try:
                d_rel = self.vault.to_rel_path(d_path)
            except ValueError:
                continue
            if not d_rel or d_rel == ".":
                continue
            parts = d_rel.split("/")
            if any(p.startswith(".") for p in parts):
                continue
            if d_rel.startswith(("_System/Cache", "_System/Logs", "05_Archives", "01_Business/KAIROS_Sessions")):
                continue
            # Keep `02_Projects` top-level project folders without flooding with deep Sprint/Tasks subfolders
            if parts[0] == "02_Projects" and len(parts) > 2:
                continue
            if parts[0] == "_System" and d_rel not in ("_System/Dashboards", "_System/Templates"):
                continue
            if len(parts) <= 3:
                folder_set.add(d_rel)

        return {
            "ok": True,
            "sections": sections,
            "folders": sorted(folder_set, key=lambda s: (0 if not s.startswith("_") else 1, s.lower())),
            "bases": bases_list,
            "canvases": canvases_list,
            "templates": templates_list,
            "blueprints": list_blueprint_catalog(),
        }

    def evaluate_base(self, base_rel_path: str, view_name: str = "") -> Dict[str, Any]:
        """Evaluate an Obsidian `.base` database YAML file against the live ShadowIndex."""
        target = self.vault.resolve_safe_path(base_rel_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"Obsidian Base file not found: {base_rel_path}")
        if target.suffix.lower() != ".base":
            raise ValueError(f"Expected a `.base` file, got '{target.name}'.")

        raw_yaml = target.read_text(encoding="utf-8", errors="replace")
        norm_base_rel = self.vault.to_rel_path(target)

        with self._lock, self._db_session() as conn:
            rows = conn.execute("SELECT * FROM notes;").fetchall()

        records: List[Dict[str, Any]] = []
        for r in rows:
            rel = str(r["rel_path"])
            p_obj = Path(rel)
            fld = str(p_obj.parent).replace("\\", "/")
            if fld == ".":
                fld = ""
            abs_p = self.vault.vault_path / rel
            try:
                f_size = abs_p.stat().st_size if abs_p.is_file() else len(str(r["excerpt"] or ""))
            except OSError:
                f_size = len(str(r["excerpt"] or ""))

            records.append(
                {
                    "rel_path": rel,
                    "title": str(r["title"]),
                    "type": str(r["note_type"]),
                    "is_private": bool(r["is_private"]),
                    "frontmatter": json.loads(r["frontmatter_json"] or "{}"),
                    "tags": json.loads(r["tags_json"] or "[]"),
                    "wikilinks": json.loads(r["wikilinks_json"] or "[]"),
                    "mtime": float(r["mtime"] or 0.0),
                    "file_name": p_obj.name,
                    "file_basename": p_obj.stem,
                    "file_folder": fld,
                    "file_ext": p_obj.suffix.lstrip(".").lower(),
                    "file_size": f_size,
                }
            )

        return evaluate_obsidian_base(
            raw_yaml=raw_yaml,
            base_rel_path=norm_base_rel,
            note_records=records,
            selected_view=view_name,
        )

    def audit_vault_health(self) -> Dict[str, Any]:
        """Run a comprehensive Obsidian Vault health diagnostic (broken links, orphans, `.base`/`.canvas` validation)."""
        with self._lock, self._db_session() as conn:
            note_rows = conn.execute(
                "SELECT rel_path, title, note_type, is_private, frontmatter_json FROM notes;"
            ).fetchall()
            edge_rows = conn.execute(
                "SELECT source_path, target_name, edge_kind FROM edges;"
            ).fetchall()
            task_cnt_row = conn.execute("SELECT COUNT(*) AS cnt FROM tasks;").fetchone()
            tasks_count = int(task_cnt_row["cnt"]) if task_cnt_row else 0

        generic_index_stems = {"_project_index", "_list_index", "_hub_index", "_collection_index"}
        path_keys: set[str] = set()
        stem_keys: set[str] = set()
        title_keys: set[str] = set()
        path_to_id: Dict[str, str] = {}
        stem_to_id: Dict[str, str] = {}
        title_to_id: Dict[str, str] = {}

        md_count = 0
        bases_count = 0
        canvases_count = 0
        hubs_count = 0
        syntax_issues: List[Dict[str, Any]] = []

        for r in note_rows:
            rel = str(r["rel_path"])
            rel_low = rel.lower()
            path_keys.add(rel_low)
            path_to_id[rel_low] = rel
            for ext in (".md", ".canvas", ".base"):
                if rel_low.endswith(ext):
                    no_e = rel_low[: -len(ext)]
                    path_keys.add(no_e)
                    path_to_id[no_e] = rel
                    break

            p_obj = Path(rel)
            ext_low = p_obj.suffix.lower()
            if ext_low == ".md":
                md_count += 1
            elif ext_low == ".base":
                bases_count += 1
                abs_b = self.vault.vault_path / rel
                if abs_b.is_file():
                    try:
                        parsed_b = yaml.safe_load(abs_b.read_text(encoding="utf-8", errors="replace"))
                        if parsed_b is not None and not isinstance(parsed_b, dict):
                            syntax_issues.append(
                                {"rel_path": rel, "kind": "base", "errors": ["Root of `.base` file must be a YAML mapping."]}
                            )
                    except Exception as exc:
                        syntax_issues.append({"rel_path": rel, "kind": "base", "errors": [str(exc)]})
            elif ext_low == ".canvas":
                canvases_count += 1
                abs_c = self.vault.vault_path / rel
                if abs_c.is_file():
                    res_c = validate_and_normalize_canvas(abs_c.read_text(encoding="utf-8", errors="replace"))
                    if not res_c["valid"]:
                        syntax_issues.append({"rel_path": rel, "kind": "canvas", "errors": res_c["errors"]})

            if str(r["note_type"]) == "section_hub" or p_obj.name == "_Hub_Index.md":
                hubs_count += 1

            st = p_obj.stem.lower()
            if st not in generic_index_stems:
                stem_keys.add(st)
                stem_to_id[st] = rel
            elif st in ("_project_index", "_hub_index") and p_obj.parent.name:
                parent_k = p_obj.parent.name.lower()
                stem_keys.add(parent_k)
                stem_to_id[parent_k] = rel

            t_low = str(r["title"] or "").strip().lower()
            if t_low:
                title_keys.add(t_low)
                title_to_id[t_low] = rel

            try:
                fm_obj = json.loads(r["frontmatter_json"] or "{}")
                fm_id = str(fm_obj.get("id") or "").strip().lower()
                if fm_id:
                    stem_keys.add(fm_id)
                    stem_to_id[fm_id] = rel
                aliases = fm_obj.get("aliases")
                if isinstance(aliases, list):
                    for al in aliases:
                        al_s = str(al or "").strip().lower()
                        if al_s:
                            title_keys.add(al_s)
                            title_to_id[al_s] = rel
            except Exception:
                pass

        broken_links: List[Dict[str, str]] = []
        seen_broken: set[tuple[str, str]] = set()
        connected_paths: set[str] = set()

        for e in edge_rows:
            src = str(e["source_path"])
            if src.lower().startswith("_system/templates/"):
                continue
            raw_tgt = str(e["target_name"] or "").split("|")[0].split("#")[0].strip().strip("/").replace("\\", "/")
            if not raw_tgt:
                continue
            if raw_tgt.lower().startswith(("http://", "https://", "mailto:")) or "{{" in raw_tgt:
                continue

            tgt_low = raw_tgt.lower()
            tgt_no_ext = tgt_low
            for ext in (".md", ".canvas", ".base"):
                if tgt_no_ext.endswith(ext):
                    tgt_no_ext = tgt_no_ext[: -len(ext)]
                    break
            tgt_stem = Path(raw_tgt).stem.lower()

            resolved_id = (
                path_to_id.get(tgt_low)
                or path_to_id.get(tgt_no_ext)
                or (stem_to_id.get(tgt_stem) if tgt_stem not in generic_index_stems else None)
                or title_to_id.get(tgt_low)
            )
            if resolved_id:
                connected_paths.add(src)
                connected_paths.add(resolved_id)
            else:
                if (src, raw_tgt) not in seen_broken and len(broken_links) < 100:
                    seen_broken.add((src, raw_tgt))
                    src_parent = str(Path(src).parent).replace("\\", "/")
                    if src_parent == ".":
                        src_parent = "04_Resources"
                    broken_links.append(
                        {
                            "source_path": src,
                            "target": raw_tgt,
                            "edge_kind": str(e["edge_kind"]),
                            "suggested_folder": src_parent,
                        }
                    )

        orphan_notes: List[Dict[str, str]] = []
        for r in note_rows:
            rel = str(r["rel_path"])
            p_obj = Path(rel)
            if p_obj.suffix.lower() != ".md":
                continue
            if rel in connected_paths:
                continue
            if rel == "AGENTS.md" or p_obj.stem.startswith("_"):
                continue
            if rel.startswith(
                (
                    "00_Inbox/",
                    "03_Personal/Calendar/",
                    "01_Business/KAIROS_Sessions/",
                    "_System/",
                    "05_Archives/",
                )
            ):
                continue
            if len(orphan_notes) < 100:
                orphan_notes.append({"rel_path": rel, "title": str(r["title"])})

        penalty = len(broken_links) * 4 + len(syntax_issues) * 10 + min(15, len(orphan_notes))
        health_score = max(0, 100 - penalty)
        status = "healthy" if health_score >= 90 else ("attention" if health_score >= 70 else "issues")

        return {
            "ok": True,
            "status": status,
            "health_score": health_score,
            "counts": {
                "total_files": len(note_rows),
                "markdown_notes": md_count,
                "bases": bases_count,
                "canvases": canvases_count,
                "tasks": tasks_count,
                "section_hubs": hubs_count,
            },
            "broken_links": broken_links,
            "orphan_notes": orphan_notes,
            "syntax_issues": syntax_issues,
        }

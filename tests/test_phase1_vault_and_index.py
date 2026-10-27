"""Phase 1 Verification Suite: Vault Engine, Hash-Guard, Projects Hierarchy YAML CRUD & SQLite WAL Shadow Index."""

from __future__ import annotations

from pathlib import Path
from services.kairos_core.schemas import CreateTaskInput, UpdateTaskInput
from services.kairos_core.shadow_index import ShadowIndex
from services.kairos_core.vault_engine import VaultEngine


def test_vault_initialization_and_hash_guard(tmp_path: Path) -> None:
    vault = VaultEngine(tmp_path / "Test_Canopy_Vault")
    assert (vault.vault_path / "00_Inbox").is_dir()
    assert (vault.vault_path / "01_Business" / "KAIROS_Sessions").is_dir()
    assert (vault.vault_path / "02_Projects").is_dir()
    assert (vault.vault_path / "03_Personal" / "Finance").is_dir()
    assert (vault.vault_path / "_System" / "Logs" / "AI_Audit_Log.jsonl").is_file()

    saved = vault.write_note(
        "00_Inbox/Quick_Idea.md",
        frontmatter={"title": "Quick Idea", "tags": ["capture"]},
        body="Testing [[Project_Alpha]] link and #roadmap tag.",
    )
    target = vault.resolve_safe_path(saved["rel_path"])

    # Self-write should be ignored by watchdog hash-guard
    assert vault.hash_guard.should_ignore_watchdog_event(target) is True

    # External edit in Obsidian changes SHA-256 -> watchdog should process it
    target.write_text(
        target.read_text(encoding="utf-8") + "\nExternal Obsidian edit\n",
        encoding="utf-8",
    )
    assert vault.hash_guard.should_ignore_watchdog_event(target) is False


def test_projects_task_lifecycle_rollup_and_archive(tmp_path: Path) -> None:
    vault = VaultEngine(tmp_path / "Projects_Vault")
    index = ShadowIndex(vault)

    t1 = vault.create_task(
        CreateTaskInput(
            title="Build FastMCP Server",
            project="KAIROS_2_0",
            department="Software_Development",
            list="Sprint_01",
            priority=1,
            time_estimate_hrs=3.0,
            checklist=["Write schemas", "Register tools"],
        )
    )
    t2 = vault.create_task(
        CreateTaskInput(
            title="Launch Teaser Campaign",
            project="KAIROS_2_0",
            department="Marketing_and_Branding",
            list="Campaigns",
            priority=2,
            depends_on=[f"[[{t1['frontmatter']['id']}]]"],
            time_estimate_hrs=2.0,
        )
    )

    assert t1["rel_path"].startswith("02_Projects/KAIROS_2_0/Software_Development/Sprint_01/Tasks/")
    assert t2["rel_path"].startswith("02_Projects/KAIROS_2_0/Marketing_and_Branding/Campaigns/Tasks/")

    id1 = t1["frontmatter"]["id"]
    id2 = t2["frontmatter"]["id"]
    assert id1 != id2

    # Toggle checklist item 0, add subtask, log 1.5h, and mark t1 Done
    updated_t1 = vault.update_task(
        UpdateTaskInput(
            task_id=id1,
            status="Done",
            time_logged_delta=1.5,
            toggle_checklist_index=0,
            add_checklist_item="Run pytest verification",
            log_entry="Completed initial implementation",
        )
    )
    assert updated_t1["frontmatter"]["status"] == "Done"
    assert updated_t1["frontmatter"]["time_logged_hrs"] == 1.5
    assert "- [x] Write schemas" in updated_t1["body"]
    assert "- [ ] Run pytest verification" in updated_t1["body"]

    # Project `02_Projects/KAIROS_2_0/_Project_Index.md` progress_pct should now be 50% (1 of 2 Done across departments)
    proj_note = vault.read_note("02_Projects/KAIROS_2_0/_Project_Index.md")
    assert proj_note["frontmatter"]["progress_pct"] == 50

    # Rebuild SQLite WAL + FTS5 Shadow Index & verify queries
    stats = index.rebuild_all()
    assert stats["indexed_tasks"] == 2

    with index._connect() as conn:
        wal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert wal_mode.lower() == "wal"

    rollup = index.get_rollup(project="KAIROS_2_0")
    assert rollup["total_tasks"] == 2
    assert rollup["progress_pct"] == 50
    assert rollup["by_department"]["Software_Development"] == 1
    assert rollup["by_department"]["Marketing_and_Branding"] == 1
    assert rollup["time_logged_hrs"] == 1.5
    assert rollup["time_estimate_hrs"] == 5.0

    fts_hits = index.search_vault(query="FastMCP")
    assert any(h["rel_path"] == updated_t1["rel_path"] for h in fts_hits)

    graph = index.get_graph_data()
    assert any(e["kind"] == "depends_on" for e in graph["edges"])

    # Mark second task Done and archive whole project into `05_Archives/`
    vault.update_task(UpdateTaskInput(task_id=id2, status="Done"))
    archived_dest = vault.archive_completed_project("KAIROS_2_0")
    assert archived_dest is not None
    assert vault.to_rel_path(archived_dest).startswith("05_Archives/KAIROS_2_0")
    assert (archived_dest / "_Project_Index.md").exists()


def test_defuddle_html_clipper(tmp_path: Path) -> None:
    vault = VaultEngine(tmp_path / "Clipper_Vault")
    raw_html = """
    <html>
      <head><title>Obsidian Local Architecture</title><script>evil()</script></head>
      <body>
        <nav>Noise Menu</nav>
        <h1>Local-First Knowledge OS</h1>
        <p>Markdown files outlive proprietary databases.</p>
      </body>
    </html>
    """
    clipped = vault.defuddle_clip_to_vault(
        url="https://example.com/local-first",
        raw_html_or_text=raw_html,
        dest_folder="00_Inbox",
    )
    assert clipped["rel_path"].startswith("00_Inbox/Clip_")
    assert "Local-First Knowledge OS" in clipped["body"]
    assert "evil()" not in clipped["body"]

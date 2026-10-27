"""Phase 4 Checkpoint Hardening & Resilience Verification Suite (`v2.0-checkpoint-1`):
1. `resolve_safe_path` sibling-prefix traversal & null-byte guard + `is_private_note` multi-form YAML checks
2. Voice Sidecar (`:8421`) multi-line YAML `tags: [private]` & `private: true` detection + fail-closed traversal shield
3. Hermes `#private` memory isolation (`03_Personal/Finance/Hermes_Private_Memory.md`), shared `MEMORY.md` auto-sanitization & 80-bullet archive rotation
4. OneDrive `PermissionError` exponential retry in `atomic_write_markdown` + 8-thread concurrent `VaultEngine.update_task` safety
5. Watchdog 4-level `_Project_Index.md` rollup, `on_moved` index sync, and external `Hermes-Agent` auto-dispatch
6. Paperclip `HTTP 409` active-lock conflict guards across `PATCH /api/tasks/{id}`, `DELETE /api/tasks/{id}`, and `POST /api/paperclip/dispatch-crew`
7. Task soft-archive (`05_Archives/Tasks/[Project]/`) + sibling `parent_task`/`depends_on` cleanup + permanent delete via 18th MCP tool (`projects_archive_task`)
8. Assistant session rename (`PATCH /api/assistant/sessions/{id}`), soft-archive (`05_Archives/Sessions/`), and collision-safe `_next_session_id`
"""

from __future__ import annotations

import base64
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient
from watchdog.events import FileSystemMovedEvent

import services.kairos_core.api as api_mod
import services.kairos_core.vault_engine as vault_mod
import services.kairos_voice.voice_service as voice_mod
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.schemas import CreateTaskInput, UpdateTaskInput
from services.kairos_core.vault_engine import VaultEngine, parse_markdown_note, serialize_markdown_note
from services.kairos_core.watcher import _VaultWatchdogHandler


def test_resolve_safe_path_blocks_sibling_prefix_and_null_byte(tmp_path: Path) -> None:
    vault_dir = tmp_path / "Canopy_Vault"
    evil_sibling = tmp_path / "Canopy_Vault_Evil"
    evil_sibling.mkdir(parents=True, exist_ok=True)
    (evil_sibling / "secret.md").write_text("leaked", encoding="utf-8")

    vault = VaultEngine(vault_dir)

    valid = vault.resolve_safe_path("01_Business/Strategy_2026.md")
    assert valid.is_relative_to(vault.vault_path)

    # Sibling folder sharing the string prefix `Canopy_Vault` MUST be rejected by `is_relative_to`
    with pytest.raises(ValueError, match="escapes Vault root"):
        vault.resolve_safe_path("../Canopy_Vault_Evil/secret.md")

    with pytest.raises(ValueError, match="escapes Vault root"):
        vault.resolve_safe_path("../../outside.md")

    with pytest.raises(ValueError, match="Invalid Vault path"):
        vault.resolve_safe_path("01_Business/bad\x00note.md")

    # Canonical `is_private_note` checks across path, YAML list, YAML boolean, privacy field, and inline `#private`
    assert vault.is_private_note("03_Personal/Finance/Taxes.md", {}, "Plain body") is True
    assert vault.is_private_note("01_Business/Board.md", {"tags": ["ops", "private"]}, "Plain body") is True
    assert vault.is_private_note("01_Business/Flagged.md", {"private": True}, "Plain body") is True
    assert vault.is_private_note("01_Business/Local.md", {"privacy": "local_only"}, "Plain body") is True
    assert vault.is_private_note("01_Business/Inline.md", {}, " Confidential #private note") is True
    assert vault.is_private_note("01_Business/Public.md", {"tags": ["roadmap"]}, "Public body") is False


def test_voice_sidecar_privacy_lock_yaml_tags_and_traversal_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v_root = tmp_path / "Voice_Priv_Vault"
    vault = VaultEngine(v_root)
    monkeypatch.setattr(voice_mod.settings, "vault_path", v_root)

    # Multi-line YAML list `tags:\n- board\n- private` with NO `#private` in body
    vault.write_note(
        "01_Business/YAML_List_Private.md",
        {"title": "Board Confidential", "tags": ["board", "private"]},
        "Quarterly margin targets without inline hashtag.",
    )
    vault.write_note(
        "01_Business/Flag_Private.md",
        {"title": "Flag Private", "private": True},
        "Internal compensation review.",
    )
    vault.write_note(
        "01_Business/Public_Update.md",
        {"title": "Public Update", "tags": ["public"]},
        "Weekly product launch checklist.",
    )

    assert voice_mod.is_voice_context_private("01_Business/YAML_List_Private.md") is True
    assert voice_mod.is_voice_context_private("01_Business/Flag_Private.md") is True
    # Path traversal outside Vault root fails closed (`True`) to block cloud transmission
    assert voice_mod.is_voice_context_private("../Outside_Sibling/secret.md") is True
    assert voice_mod.is_voice_context_private("01_Business/Public_Update.md") is False

    v_client = TestClient(voice_mod.app)

    tts_res = v_client.post(
        "/api/voice/tts",
        json={
            "text": "Read confidential summary",
            "active_note_path": "01_Business/YAML_List_Private.md",
        },
    )
    assert tts_res.status_code == 200
    assert tts_res.json()["privacy_locked"] is True

    def _offline_local_stt(*_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("Local Whisper offline in unit test")

    monkeypatch.setattr(voice_mod.requests, "post", _offline_local_stt)
    audio_b64 = base64.b64encode(b"RIFF0000WAVEfmt ").decode("ascii")
    stt_res = v_client.post(
        "/api/voice/audio-command",
        json={
            "audio_base64": audio_b64,
            "mime_type": "audio/webm",
            "active_note_path": "01_Business/YAML_List_Private.md",
        },
    )
    assert stt_res.status_code == 200
    stt_data = stt_res.json()
    assert stt_data["stt"]["privacy_locked"] is True
    assert stt_data["stt"]["provider"] == "local-privacy-shield"


def test_hermes_private_memory_isolation_and_80_bullet_archive_rotation(tmp_path: Path) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Hermes_Hardened_Vault"))
    hermes = bundle["hermes"]
    vault = bundle["vault"]

    # 1. Retaining a private fact writes strictly to `03_Personal/Finance/Hermes_Private_Memory.md`
    priv_res = hermes.retain_memory(
        "Confidential Q4 treasury reserve threshold is $125k",
        is_private=True,
    )
    assert priv_res["privacy_locked"] is True
    assert priv_res["rel_path"] == "03_Personal/Finance/Hermes_Private_Memory.md"

    shared_mem = vault.read_note("04_Resources/Hermes/MEMORY.md")
    assert shared_mem["is_private"] is False
    assert "treasury reserve" not in shared_mem["body"].lower()

    recalled_public = hermes.recall_context("treasury reserve", allow_private=False)
    assert "treasury reserve" not in recalled_public["context_text"].lower()
    assert recalled_public["has_private"] is False

    recalled_private = hermes.recall_context("treasury reserve", allow_private=True)
    assert "treasury reserve" in recalled_private["context_text"].lower()
    assert recalled_private["has_private"] is True

    # 2. Legacy taint auto-sanitization on `initialize_hermes_files()`
    tainted_fm = dict(shared_mem["frontmatter"])
    tainted_fm["tags"] = ["hermes", "memory", "private"]
    tainted_body = shared_mem["body"] + "\n- **[2026-10-25]** Legacy leaked line #private\n"
    vault.write_note("04_Resources/Hermes/MEMORY.md", tainted_fm, tainted_body, mode="overwrite")

    hermes.initialize_hermes_files()
    cleaned_mem = vault.read_note("04_Resources/Hermes/MEMORY.md")
    assert cleaned_mem["is_private"] is False
    assert "legacy leaked line" not in cleaned_mem["body"].lower()
    priv_mem_after = vault.read_note("03_Personal/Finance/Hermes_Private_Memory.md")
    assert "legacy leaked line" in priv_mem_after["body"].lower()

    # 3. Retaining >80 shared bullets enforces the 80-bullet cap and rotates overflow to `MEMORY_Archive.md`
    for idx in range(85):
        hermes.retain_memory(f"Hardened sprint architectural lesson #{idx:03d} verified")

    capped_mem = vault.read_note("04_Resources/Hermes/MEMORY.md")
    bullet_lines = [ln for ln in capped_mem["body"].splitlines() if ln.strip().startswith("- ")]
    assert len(bullet_lines) == 80

    archive_note = vault.read_note("04_Resources/Hermes/MEMORY_Archive.md")
    archived_bullets = [ln for ln in archive_note["body"].splitlines() if ln.strip().startswith("- ")]
    assert len(archived_bullets) >= 5


def test_atomic_write_onedrive_permission_error_retry_and_concurrent_task_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = VaultEngine(tmp_path / "Concurrent_Vault")

    # 1. Simulate transient Windows/OneDrive `PermissionError` on `Path.replace` twice before succeeding
    orig_replace = Path.replace
    attempts = {"count": 0}

    def _flaky_onedrive_replace(self_path: Path, target: Path) -> Path:
        if ".tmp" in self_path.name and target.name == "Retry_Note.md":
            attempts["count"] += 1
            if attempts["count"] <= 2:
                raise PermissionError(13, "The process cannot access the file because OneDrive has it open")
        return orig_replace(self_path, target)

    monkeypatch.setattr(vault_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(Path, "replace", _flaky_onedrive_replace)
    try:
        saved = vault.write_note(
            "01_Business/Retry_Note.md",
            {"title": "OneDrive Resilient Write"},
            "Atomic retry succeeded without data loss.",
        )
    finally:
        monkeypatch.setattr(Path, "replace", orig_replace)

    assert attempts["count"] == 3
    assert vault.read_note(saved["rel_path"])["body"].strip() == "Atomic retry succeeded without data loss."
    leftover_tmps = list((vault.vault_path / "01_Business").glob("*.tmp"))
    assert leftover_tmps == []

    # 2. 8 concurrent threads updating `time_logged_delta` + `log_entry` on the same `TSK-*.md`
    created = vault.create_task(
        CreateTaskInput(
            title="Concurrent Multi-Agent Task",
            project="KAIROS_2_0",
            department="Software_Development",
            list="Sprint_01",
        )
    )
    tid = created["frontmatter"]["id"]
    barrier = threading.Barrier(8)
    errors: List[Exception] = []

    def _worker(worker_idx: int) -> None:
        try:
            barrier.wait(timeout=5.0)
            vault.update_task(
                UpdateTaskInput(
                    task_id=tid,
                    time_logged_delta=0.25,
                    log_entry=f"concurrent-worker-{worker_idx}",
                    actor=f"Agent-{worker_idx}",
                )
            )
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert errors == []
    final_task = vault.read_note(created["rel_path"])
    assert float(final_task["frontmatter"]["time_logged_hrs"]) == pytest.approx(2.0)
    for i in range(8):
        assert f"concurrent-worker-{i}" in final_task["body"]


def test_watchdog_4_level_rollup_on_moved_and_hermes_auto_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Watchdog_Vault"))
    vault = bundle["vault"]
    index = bundle["index"]
    crew = bundle["crew"]
    router = bundle["router"]

    monkeypatch.setattr(
        router,
        "generate",
        lambda prompt, **kwargs: {
            "ok": True,
            "agent": "Gemma-4",
            "text": "Autonomous Hermes watchdog deliverable verified.",
            "tokens_used": 32,
            "latency_ms": 4,
            "route_reason": "watchdog_test_mock",
            "privacy_locked": False,
        },
    )

    events: List[Dict[str, Any]] = []
    handler = _VaultWatchdogHandler(vault, index, crew, on_change_broadcast=events.append)

    # Part A: External Obsidian edit on a 4-level task updates `_Project_Index.md` `progress_pct`
    t1 = vault.create_task(
        CreateTaskInput(
            title="Watchdog Task One",
            project="KAIROS_2_0",
            department="Software_Development",
            list="Sprint_01",
            status="To Do",
        )
    )
    vault.create_task(
        CreateTaskInput(
            title="Watchdog Task Two",
            project="KAIROS_2_0",
            department="Software_Development",
            list="Sprint_01",
            status="To Do",
        )
    )
    index.rebuild_all()

    t1_abs = vault.resolve_safe_path(t1["rel_path"])
    fm1, body1 = parse_markdown_note(t1_abs.read_text(encoding="utf-8"))
    fm1["status"] = "Done"
    # Direct write simulates an external Obsidian user edit (bypassing KAIROS `hash_guard`)
    t1_abs.write_text(serialize_markdown_note(fm1, body1), encoding="utf-8")

    handler._handle_fs_change(str(t1_abs))
    proj_idx = vault.read_note("02_Projects/KAIROS_2_0/_Project_Index.md")
    assert proj_idx["frontmatter"]["progress_pct"] == 50

    # Part B: `on_moved` removes old path from SQLite and indexes new path with zero stale duplicates
    src_note = vault.vault_path / "00_Inbox" / "Obsidian_Draft.md"
    src_note.write_text(
        serialize_markdown_note({"title": "Moved Note"}, "UniqueTokenWatchdogMove99"),
        encoding="utf-8",
    )
    handler._handle_fs_change(str(src_note))
    hits_before = index.search_vault(query="UniqueTokenWatchdogMove99")
    assert [h["rel_path"] for h in hits_before] == ["00_Inbox/Obsidian_Draft.md"]

    dst_note = vault.vault_path / "01_Business" / "Obsidian_Final.md"
    shutil.move(str(src_note), str(dst_note))
    handler.on_moved(FileSystemMovedEvent(str(src_note), str(dst_note)))

    hits_after = index.search_vault(query="UniqueTokenWatchdogMove99")
    assert [h["rel_path"] for h in hits_after] == ["01_Business/Obsidian_Final.md"]

    # Part C: External `To Do` task assigned to `Hermes-Agent` auto-dispatches in background
    ext_tid = "TSK-20991231-001"
    ext_path = (
        vault.vault_path
        / "02_Projects"
        / "KAIROS_2_0"
        / "Software_Development"
        / "Sprint_01"
        / "Tasks"
        / f"{ext_tid}_External_Hermes.md"
    )
    ext_fm = {
        "id": ext_tid,
        "title": "External Hermes Synthesis",
        "type": "task",
        "status": "To Do",
        "priority": 2,
        "project": "[[KAIROS_2_0]]",
        "department": "Software_Development",
        "list": "Sprint_01",
        "ai_agent": "Hermes-Agent",
        "tags": ["task"],
    }
    ext_path.write_text(serialize_markdown_note(ext_fm, "# External Hermes Synthesis\n"), encoding="utf-8")
    handler._handle_fs_change(str(ext_path))

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if any(e.get("event") == "crew_completed" and e.get("task_id") == ext_tid for e in events):
            break
        time.sleep(0.02)

    assert any(e.get("event") == "crew_completed" and e.get("task_id") == ext_tid for e in events)
    done_fm, _ = parse_markdown_note(ext_path.read_text(encoding="utf-8"))
    assert done_fm["status"] == "Review"


def test_paperclip_http_409_conflict_guard_on_locked_task_patch_delete_and_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "Lock409_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    created = client.post(
        "/api/tasks",
        json={
            "title": "Checked-Out Engine Refactor",
            "project": "KAIROS_2_0",
            "department": "Software_Development",
            "list": "Sprint_01",
        },
    ).json()
    tid = created["frontmatter"]["id"]

    # Acquire Paperclip lock as `CrewAI-Dev`
    isolated_bundle["paperclip"].checkout_task(tid, agent_name="CrewAI-Dev", crew_type="crew")

    # Operator (`actor="Jaime"` default) PATCH, DELETE, and duplicate dispatch must all return HTTP 409
    r_patch_blocked = client.patch(f"/api/tasks/{tid}", json={"status": "Done"})
    assert r_patch_blocked.status_code == 409
    assert "Paperclip Lock Conflict" in r_patch_blocked.json()["detail"]

    r_del_blocked = client.delete(f"/api/tasks/{tid}")
    assert r_del_blocked.status_code == 409

    r_disp_blocked = client.post(
        "/api/paperclip/dispatch-crew",
        json={"task_id": tid, "crew_name": "CrewAI-Research"},
    )
    assert r_disp_blocked.status_code == 409

    # Lock holder (`actor="CrewAI-Dev"`) is allowed to PATCH its own checked-out task
    r_owner_ok = client.patch(
        f"/api/tasks/{tid}",
        json={"status": "In Progress", "actor": "CrewAI-Dev"},
    )
    assert r_owner_ok.status_code == 200
    assert r_owner_ok.json()["frontmatter"]["status"] == "In Progress"

    # Once released, operator PATCH succeeds cleanly
    isolated_bundle["paperclip"].release_task(tid, status="completed", summary="Finished")
    r_after_release = client.patch(f"/api/tasks/{tid}", json={"status": "Done"})
    assert r_after_release.status_code == 200
    assert r_after_release.json()["frontmatter"]["status"] == "Done"


def test_task_soft_archive_permanent_delete_and_mcp_18th_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "TaskLifecycle_Vault"))
    mcp_tools = isolated_bundle["mcp_tools"]
    assert len(mcp_tools) == 18
    assert "projects_archive_task" in mcp_tools

    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    t1 = client.post(
        "/api/tasks",
        json={
            "title": "Upstream Foundation Spec",
            "project": "KAIROS_2_0",
            "department": "Software_Development",
            "list": "Sprint_01",
            "status": "Done",
        },
    ).json()
    tid1 = t1["frontmatter"]["id"]

    t2 = client.post(
        "/api/tasks",
        json={
            "title": "Downstream Dependent Feature",
            "project": "KAIROS_2_0",
            "department": "Software_Development",
            "list": "Sprint_01",
            "status": "To Do",
            "parent_task": f"[[{tid1}]]",
            "depends_on": [f"[[{tid1}]]"],
        },
    ).json()
    tid2 = t2["frontmatter"]["id"]

    t3 = client.post(
        "/api/tasks",
        json={
            "title": "Ephemeral Scratch Task",
            "project": "KAIROS_2_0",
            "department": "Software_Development",
            "list": "Sprint_01",
            "status": "Backlog",
        },
    ).json()
    tid3 = t3["frontmatter"]["id"]

    # 1. Soft-archive `tid1` via REST `DELETE /api/tasks/{tid1}?permanent=false`
    arch_res = client.delete(f"/api/tasks/{tid1}?permanent=false")
    assert arch_res.status_code == 200
    arch_json = arch_res.json()
    assert arch_json["mode"] == "archived"
    assert arch_json["archived_rel_path"].startswith("05_Archives/Tasks/KAIROS_2_0/")

    # Excluded from active Kanban/List `tasks` table and excluded from `archived_projects` system buckets
    active_ids = {t["id"] for t in client.get("/api/tasks").json()["tasks"]}
    assert tid1 not in active_ids
    assert tid2 in active_ids
    assert "Tasks" not in isolated_bundle["vault"].list_archived_projects()

    # Archived task remains FTS-searchable as a Second Brain note inside `05_Archives/Tasks/KAIROS_2_0/`
    note_hits = client.get("/api/vault/notes?query=Upstream").json()["notes"]
    assert any(n["rel_path"] == arch_json["archived_rel_path"] for n in note_hits)

    # Sibling `tid2` had dangling `parent_task` and `depends_on` references to `tid1` cleaned automatically
    t2_row = next(t for t in client.get("/api/tasks").json()["tasks"] if t["id"] == tid2)
    assert t2_row["parent_task"] == ""
    assert t2_row["depends_on"] == []

    # 2. Permanently delete `tid3` via the 18th MCP tool `projects_archive_task(..., permanent=True)`
    del_res = mcp_tools["projects_archive_task"](task_id=tid3, permanent=True)
    assert del_res["mode"] == "deleted"
    active_ids_after = {t["id"] for t in client.get("/api/tasks").json()["tasks"]}
    assert tid3 not in active_ids_after
    scratch_hits = client.get("/api/vault/notes?query=Ephemeral").json()["notes"]
    assert scratch_hits == []


def test_assistant_session_rename_and_archive_lifecycle_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "SessionLifecycle_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    s1 = client.post(
        "/api/assistant/sessions",
        json={"title": "Initial Triage Thread", "persona": "dev", "tone_mode": "DEFAULT"},
    ).json()
    sid1 = s1["session_id"]

    # Rename session via `PATCH /api/assistant/sessions/{sid1}`
    renamed = client.patch(
        f"/api/assistant/sessions/{sid1}",
        json={"title": "Checkpoint v2.0 Architecture Sign-Off"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Checkpoint v2.0 Architecture Sign-Off"

    listed = client.get("/api/assistant/sessions").json()["sessions"]
    assert len(listed) == 1
    assert listed[0]["title"] == "Checkpoint v2.0 Architecture Sign-Off"

    # Soft-archive session via `DELETE /api/assistant/sessions/{sid1}?permanent=false`
    archived = client.delete(f"/api/assistant/sessions/{sid1}?permanent=false")
    assert archived.status_code == 200
    arch_data = archived.json()
    assert arch_data["mode"] == "archived"
    assert arch_data["archived_rel_path"] == f"05_Archives/Sessions/{sid1}.md"

    assert client.get("/api/assistant/sessions").json()["sessions"] == []
    assert (isolated_bundle["vault"].vault_path / f"05_Archives/Sessions/{sid1}.md").is_file()
    assert "Sessions" not in isolated_bundle["vault"].list_archived_projects()

    # Creating a new session scans `05_Archives/Sessions/` so `sid1` is never reused
    s2 = client.post(
        "/api/assistant/sessions",
        json={"title": "Post-Archive Follow-Up", "persona": "companion", "tone_mode": "DEFAULT"},
    ).json()
    assert s2["session_id"] != sid1

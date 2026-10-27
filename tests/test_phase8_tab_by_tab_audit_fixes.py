"""Phase 8 Verification Suite: Tab-by-Tab Workspace Audit, Privacy Isolation, Canvas JSON & Paperclip Locks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import services.kairos_core.api as api_mod
from services.kairos_core.assistant import MEMORY_NOTE_REL, PRIVATE_MEMORY_NOTE_REL
from services.kairos_core.config import KairosSettings
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.vault_engine import parse_markdown_note

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_SRC_ROOT = REPO_ROOT / "apps" / "desktop" / "src"


def test_operator_private_memory_isolation_and_early_priv_fast_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `#private` & `03_Personal/Finance/` operator memories isolate to `PRIVATE_MEMORY_NOTE_REL` and never leak."""
    cfg = KairosSettings(vault_path=tmp_path / "Tab_Audit_Privacy_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)
    assistant = bundle["assistant"]
    vault = bundle["vault"]

    # 1. Public memory goes to public `KAIROS_Operator_Memory.md`
    r_pub = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Remember that sprint demos happen Fridays at 2pm",
            "mode": "gemma-4",
        },
    )
    assert r_pub.status_code == 200
    assert r_pub.json()["privacy_locked"] is False
    assert MEMORY_NOTE_REL in r_pub.json()["reply"]

    # 2. Explicit `#private` operator memory routes ONLY to `03_Personal/Finance/KAIROS_Operator_Private_Memory.md`
    r_priv_tag = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Remember that hardware wallet recovery rule stays offline #private",
            "mode": "auto",
        },
    )
    assert r_priv_tag.status_code == 200
    assert r_priv_tag.json()["privacy_locked"] is True
    assert PRIVATE_MEMORY_NOTE_REL in r_priv_tag.json()["reply"]

    pub_raw = vault.resolve_safe_path(MEMORY_NOTE_REL).read_text(encoding="utf-8")
    priv_raw = vault.resolve_safe_path(PRIVATE_MEMORY_NOTE_REL).read_text(encoding="utf-8")
    assert "hardware wallet recovery rule" not in pub_raw
    assert "hardware wallet recovery rule" in priv_raw

    # Verify cloud-safe memory read (`allow_private=False`) omits private facts
    cloud_safe_mem, cloud_priv = assistant._read_operator_memory_with_privacy(allow_private=False)
    local_full_mem, local_priv = assistant._read_operator_memory_with_privacy(allow_private=True)
    assert cloud_priv is False
    assert local_priv is True
    assert "sprint demos happen Fridays" in cloud_safe_mem
    assert "hardware wallet recovery rule" not in cloud_safe_mem
    assert "hardware wallet recovery rule" in local_full_mem

    # 3. `early_priv` via active `03_Personal/Finance/` note enforces privacy across Fast Skills 1, 1b & 2
    vault.write_note(
        "03_Personal/Finance/Taxes_2026.md",
        {"title": "Taxes 2026", "tags": ["finance", "private"]},
        "# Taxes 2026\n",
    )

    r_mem_ctx = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Remember that quarterly estimated tax payment is due April 15",
            "mode": "auto",
            "active_note_path": "03_Personal/Finance/Taxes_2026.md",
        },
    )
    assert r_mem_ctx.status_code == 200
    assert r_mem_ctx.json()["privacy_locked"] is True
    assert PRIVATE_MEMORY_NOTE_REL in r_mem_ctx.json()["reply"]

    r_hermes_ctx = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Retain in Hermes: Personal tax ledger stays local",
            "mode": "auto",
            "active_note_path": "03_Personal/Finance/Taxes_2026.md",
        },
    )
    assert r_hermes_ctx.status_code == 200
    assert r_hermes_ctx.json()["privacy_locked"] is True
    assert "03_Personal/Finance/Hermes_Private_Memory.md" in r_hermes_ctx.json()["reply"]

    r_inbox_ctx = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Capture to inbox: Review private brokerage statement",
            "mode": "auto",
            "active_note_path": "03_Personal/Finance/Taxes_2026.md",
        },
    )
    assert r_inbox_ctx.status_code == 200
    assert r_inbox_ctx.json()["privacy_locked"] is True
    inbox_files = list((vault.vault_path / "00_Inbox").glob("Voice_Capture_*.md"))
    assert len(inbox_files) == 1
    fm_inbox, _ = parse_markdown_note(inbox_files[0].read_text(encoding="utf-8"))
    assert "private" in fm_inbox["tags"]


def test_vault_canvas_json_integrity_without_yaml_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `.canvas` writes never prepend `---` YAML frontmatter even if caller supplies frontmatter metadata."""
    cfg = KairosSettings(vault_path=tmp_path / "Canvas_Integrity_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    canvas_payload = {
        "nodes": [
            {
                "id": "node_arch_1",
                "type": "text",
                "x": 0,
                "y": 0,
                "width": 260,
                "height": 140,
                "text": "KAIROS 2.0 Architecture Node",
            }
        ],
        "edges": [],
    }
    res = client.post(
        "/api/vault/note",
        json={
            "file_path": "02_Projects/KAIROS_2_0/Docs/System_Map.canvas",
            "frontmatter": {"title": "Should Be Stripped For JSON Canvas", "tags": ["canvas"]},
            "body": json.dumps(canvas_payload, indent=2),
            "mode": "overwrite",
        },
    )
    assert res.status_code == 200

    raw_disk = (
        bundle["vault"]
        .resolve_safe_path("02_Projects/KAIROS_2_0/Docs/System_Map.canvas")
        .read_text(encoding="utf-8")
    )
    assert not raw_disk.lstrip().startswith("---")
    parsed = json.loads(raw_disk)
    assert parsed["nodes"][0]["id"] == "node_arch_1"


def test_raw_vault_note_and_calendar_timeblock_enforce_paperclip_lock_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `POST /api/vault/note` and `POST /api/calendar/time-block` return `HTTP 409` on Paperclip-locked tasks."""
    cfg = KairosSettings(vault_path=tmp_path / "Paperclip_Raw_Lock_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    created = client.post(
        "/api/tasks",
        json={
            "title": "Audit Raw Note Lock Enforcement",
            "project": "KAIROS_2_0",
            "department": "Software_Development",
            "list": "Sprint_01",
            "priority": 1,
        },
    ).json()
    tid = created["frontmatter"]["id"]
    rel_task = created["rel_path"]

    bundle["paperclip"].acquire_lock(tid, "CrewAI-Dev")

    # 1. Raw note overwrite on locked TSK-*.md must be blocked with HTTP 409
    r_note_locked = client.post(
        "/api/vault/note",
        json={
            "file_path": rel_task,
            "frontmatter": created["frontmatter"],
            "body": "# Attempted raw bypass while CrewAI holds checkout\n",
            "mode": "overwrite",
        },
    )
    assert r_note_locked.status_code == 409
    assert "Paperclip Lock Conflict" in r_note_locked.json()["detail"]

    # 2. Calendar time-block on locked task must also be blocked with HTTP 409
    r_tb_locked = client.post(
        "/api/calendar/time-block",
        json={
            "task_id": tid,
            "start_time_iso": "2026-10-28T10:00:00",
            "duration_hrs": 1.5,
        },
    )
    assert r_tb_locked.status_code == 409
    assert "Paperclip Lock Conflict" in r_tb_locked.json()["detail"]

    # 3. Once unlocked, both operations succeed cleanly
    bundle["paperclip"].release_lock(tid, "CrewAI-Dev")

    r_tb_ok = client.post(
        "/api/calendar/time-block",
        json={
            "task_id": tid,
            "start_time_iso": "2026-10-28T10:00:00",
            "duration_hrs": 1.5,
        },
    )
    assert r_tb_ok.status_code == 200

    latest_task_note = bundle["vault"].read_note(rel_task)
    r_note_ok = client.post(
        "/api/vault/note",
        json={
            "file_path": rel_task,
            "frontmatter": latest_task_note["frontmatter"],
            "body": latest_task_note["body"] + "\nVerified after lock release.\n",
            "mode": "overwrite",
        },
    )
    assert r_note_ok.status_code == 200


def test_calendar_standalone_event_invalid_iso_returns_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `POST /api/calendar/events` returns `HTTP 400` instead of `500` on invalid ISO timestamps."""
    cfg = KairosSettings(vault_path=tmp_path / "Calendar_Validation_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    r_bad = client.post(
        "/api/calendar/events",
        json={
            "title": "Malformed Date Event",
            "start_time_iso": "not-a-valid-iso-timestamp",
            "duration_hrs": 1.0,
        },
    )
    assert r_bad.status_code == 400


def test_all_seven_workspace_tabs_ui_audit_contracts() -> None:
    """Verify source-level UI resilience, privacy propagation & state-sync fixes across all 7 KAIROS tabs."""
    # Global Shell + Client
    app_src = (UI_SRC_ROOT / "App.tsx").read_text(encoding="utf-8")
    sidebar_src = (UI_SRC_ROOT / "components" / "LeftSidebar.tsx").read_text(encoding="utf-8")
    palette_src = (UI_SRC_ROOT / "components" / "CommandPalette.tsx").read_text(encoding="utf-8")
    client_src = (UI_SRC_ROOT / "api" / "client.ts").read_text(encoding="utf-8")
    assert "isOpenTaskPrivate" in app_src
    assert "creatingStructure" in sidebar_src
    assert "Second Brain 3D Galaxy Graph" in palette_src
    assert "getCognitiveVoiceTelemetry" in client_src
    assert "verifyLmStudioKvCache" in client_src

    # Tab 1: Assistant + Chat Drawer
    assistant_src = (UI_SRC_ROOT / "features" / "assistant" / "AssistantWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    drawer_chat_src = (UI_SRC_ROOT / "components" / "KairosChatDrawer.tsx").read_text(
        encoding="utf-8"
    )
    assert "Grounded Context:" in assistant_src
    assert "setRenamingSession(false)" in assistant_src
    assert "Hermes Retain Failed" in drawer_chat_src

    # Tab 2: Inbox
    inbox_src = (UI_SRC_ROOT / "features" / "inbox" / "InboxWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "targetPriority" in inbox_src
    assert "expandedPath" in inbox_src
    assert "Save Capture" in inbox_src

    # Tab 3: Projects + TaskDrawer
    projects_src = (UI_SRC_ROOT / "features" / "projects" / "ProjectsWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    task_drawer_src = (UI_SRC_ROOT / "features" / "projects" / "TaskDrawer.tsx").read_text(
        encoding="utf-8"
    )
    assert "useCustomTaskCategory" in projects_src
    assert "notifyMutationError" in projects_src
    assert "key={`${taskId}-title-${detail.title}`}" in task_drawer_src
    assert "Task Unavailable" in task_drawer_src

    # Tab 4: Second Brain
    brain_src = (
        UI_SRC_ROOT / "features" / "second-brain" / "SecondBrainWorkspace.tsx"
    ).read_text(encoding="utf-8")
    assert "onSelectNote(" in brain_src  # used inside safeSelectNote / readNote sync
    assert "safeSelectNote(n.id, n.is_private)" in brain_src
    assert "safeSelectNote(bl.rel_path, bl.is_private)" in brain_src
    assert "safeSelectNote(matchTask.rel_path, isTaskPrivate(matchTask))" in brain_src
    assert "Select a Canopy Vault Note or Build a New Domain Hub" in brain_src

    # Tab 5: Browser
    browser_src = (UI_SRC_ROOT / "features" / "browser" / "BrowserWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "isFrameRestrictedInWebPreview(effectiveCurrentUrl)" in browser_src
    assert "clipStatusKind" in browser_src
    assert "03_Personal/Finance" in browser_src

    # Tab 6: Paperclip
    paperclip_src = (UI_SRC_ROOT / "features" / "paperclip" / "PaperclipWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "dispatching" in paperclip_src
    assert "applyingSkillId" in paperclip_src
    assert "Cancel" in paperclip_src

    # Tab 7: Settings
    settings_src = (UI_SRC_ROOT / "features" / "settings" / "SettingsWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "Verify LM Studio KV Cache" in settings_src
    assert "Refresh Diagnostics" in settings_src
    assert "Copy JSON" in settings_src


def test_four_box_ui_and_vault_hierarchy_regressions(tmp_path: Path) -> None:
    """Verify Purple (icon rail), Green (Canopy Vault projects only), Blue (FCC GitHub home), and Yellow (hook-safe chat collapse)."""
    import re
    from services.kairos_core.schemas import CreateTaskInput
    from services.kairos_core.shadow_index import ShadowIndex
    from services.kairos_core.vault_engine import VaultEngine

    # 1. Green Box: `_System/Templates/Task_Template.md` (`{{VALUE:project}}`) and legacy demo `02_Projects/KAIROS`
    v_dir = tmp_path / "Four_Box_Canopy_Vault"
    vault = VaultEngine(v_dir)
    vault.create_task(
        CreateTaskInput(
            title="Active KAIROS 2.0 Core Deliverable",
            project="KAIROS_2_0",
            department="Software_Development",
            list="Sprint_01",
            priority=1,
        )
    )
    vault.write_note(
        "_System/Templates/Task_Template.md",
        {
            "id": "{{VALUE:id}}",
            "title": "{{VALUE:title}}",
            "type": "task",
            "project": "[[{{VALUE:project}}]]",
            "department": "{{VALUE:department}}",
            "list": "{{VALUE:list}}",
        },
        "## Description\nTemplate placeholder that must never index as a real project/task.\n",
    )
    # Seed legacy Multi-Department Structure Demo (`02_Projects/KAIROS`) and verify auto-archival to `05_Archives/KAIROS`
    vault.write_note(
        "02_Projects/KAIROS/_Project_Index.md",
        {"id": "PRJ-2026-02", "title": "KAIROS Demo", "type": "project", "project": "KAIROS"},
        "# KAIROS\n> [!IMPORTANT] Multi-Department Structure Demo\n",
    )
    vault.initialize_vault_directories()
    assert not (v_dir / "02_Projects" / "KAIROS").exists()
    assert (v_dir / "05_Archives" / "KAIROS" / "_Project_Index.md").is_file()

    index = ShadowIndex(vault)
    index.rebuild_all()
    hierarchy = index.get_projects_hierarchy()
    assert [p["name"] for p in hierarchy] == ["KAIROS_2_0"]
    assert index.get_rollup()["total_tasks"] == 1

    # 2. Purple Box: Retractable icon-only LeftSidebar (`w-14`, `PanelLeftClose`, `PanelLeftOpen`, `formatProjectDisplayName`)
    app_src = (UI_SRC_ROOT / "App.tsx").read_text(encoding="utf-8")
    sidebar_src = (UI_SRC_ROOT / "components" / "LeftSidebar.tsx").read_text(encoding="utf-8")
    assert "sidebarCollapsed" in app_src
    assert "PanelLeftClose" in sidebar_src
    assert "PanelLeftOpen" in sidebar_src
    assert "formatProjectDisplayName" in sidebar_src
    assert "w-14 shrink-0" in sidebar_src

    # 3. Blue Box: Forest City Creators LLC Repositories home URL + `.env` GitHub_Username/GitHub_Password support
    browser_src = (UI_SRC_ROOT / "features" / "browser" / "BrowserWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    electron_main_src = (
        REPO_ROOT / "apps" / "desktop" / "electron" / "main.cjs"
    ).read_text(encoding="utf-8")
    assert "https://github.com/ForestCityCreatorsLLC?tab=repositories" in browser_src
    assert "https://github.com/ForestCityCreatorsLLC?tab=repositories" in electron_main_src
    assert "https://github.com/kepano/obsidian-skills" not in browser_src
    assert "handleGoHome" in browser_src
    assert "github_username" in electron_main_src
    assert "github_password" in electron_main_src
    assert "window.location.origin !== 'https://github.com'" in electron_main_src

    # Verify KairosSettings + verify_env_apis recognize `GitHub_Username` & `GitHub_Password` while masking secrets
    from services.kairos_core.env_verifier import verify_env_apis

    gh_cfg = KairosSettings(vault_path=v_dir, gemini_api_key="")
    gh_cfg.github_token = ""
    gh_cfg.github_username = "fcc-test-operator"
    gh_cfg.github_password = " TestSecret#Pass99! "
    env_report = verify_env_apis(gh_cfg, live=False)
    assert env_report["total_count"] == 11
    gh_check = next(c for c in env_report["checks"] if c["id"] == "github")
    assert gh_check["configured"] is True
    assert "••••" in gh_check["masked_key"]
    assert "TestSecret#Pass99!" not in gh_check["masked_key"]

    # 4. Yellow Box: Zero React hooks after `if (!open) return null;` in `KairosChatDrawer.tsx` + dynamic `<main>` layout
    drawer_src = (UI_SRC_ROOT / "components" / "KairosChatDrawer.tsx").read_text(encoding="utf-8")
    early_return_pos = drawer_src.index("if (!open) return null;")
    after_early_return = drawer_src[early_return_pos:]
    assert (
        re.search(r"\buse(State|Effect|Memo|Callback|Ref|LayoutEffect|Reducer|Context)\s*\(", after_early_return)
        is None
    ), "React hook found after `if (!open) return null;` in KairosChatDrawer.tsx!"
    assert '<main className="flex-1 flex min-w-0 min-h-0 w-full overflow-hidden">' in app_src
    assert "{chatDrawerOpen && activeTab !== 'assistant' && (" in app_src

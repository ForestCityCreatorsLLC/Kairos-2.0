"""Phase 3–6 & Gate 1–6 End-to-End Verification Suite:
- Gate 1: Bulk task creation across Projects & Departments + SQLite WAL/FTS5 rollup & search latency (<50ms)
- Gate 2–5: FastAPI Core E2E (`projects/structure` multi-department scaffold, `inbox/promote`, `inbox/move`, `gsuite-link`, `projects/archive`)
- Gate 6: Unified Top-Bar & KAIROS Virtual Assistant Multi-Action Engine (Sessions, Personas, Memory, Auto Cloud Failover, `.env` API Verifier)
"""

from __future__ import annotations

import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import services.kairos_core.api as api_mod
from services.kairos_core.config import KairosSettings
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.router import DualAIRouter
from services.kairos_core.schemas import CreateTaskInput
from services.kairos_core.shadow_index import ShadowIndex
from services.kairos_core.vault_engine import VaultEngine
from services.kairos_core.vault_sync_hook import sync_codebase_changes_to_vault


def test_gate1_bulk_indexing_subtasks_and_sub_50ms_latency(tmp_path: Path) -> None:
    vault = VaultEngine(tmp_path / "Gate1_Perf_Vault")
    index = ShadowIndex(vault)

    parent = vault.create_task(
        CreateTaskInput(
            title="Anchor Parent Epic",
            project="KAIROS_2_0",
            department="Software_Development",
            list="Sprint_01",
            priority=1,
            time_estimate_hrs=4.0,
        )
    )
    parent_id = parent["frontmatter"]["id"]

    departments = [
        ("Software_Development", "Sprint_01"),
        ("Marketing_and_Branding", "Campaigns"),
        ("Documentation", "Specs_and_Guides"),
        ("Website", "Web_Launch"),
        ("Merch", "Printful_Drops"),
    ]

    # Create 24 additional Project tasks across 2 Projects & 5 Departments
    for i in range(24):
        project = "KAIROS_2_0" if i % 2 == 0 else "Canopy_Studio"
        dept, lst = departments[i % len(departments)]
        vault.create_task(
            CreateTaskInput(
                title=f"Sprint Deliverable Module {i + 1}",
                project=project,
                department=dept,
                list=lst,
                status="Done" if i % 3 == 0 else "In Progress",
                priority=(i % 4) + 1,
                parent_task=f"[[{parent_id}]]" if i < 4 else "",
                depends_on=[f"[[{parent_id}]]"] if i < 6 else [],
                time_estimate_hrs=1.5,
                tags=["sprint", f"module-{i + 1}"],
            )
        )

    stats = index.rebuild_all()
    assert stats["indexed_tasks"] == 25

    t0 = time.perf_counter()
    rollup = index.get_rollup()
    rollup_ms = (time.perf_counter() - t0) * 1000.0
    assert rollup_ms < 50.0, f"Rollup query exceeded 50ms budget: {rollup_ms:.2f}ms"
    assert rollup["total_tasks"] == 25
    assert rollup["by_status"]["Done"] == 8

    t1 = time.perf_counter()
    hits = index.search_vault(query="Deliverable")
    search_ms = (time.perf_counter() - t1) * 1000.0
    assert search_ms < 50.0, f"FTS5 search exceeded 50ms budget: {search_ms:.2f}ms"
    assert len(hits) >= 24

    hierarchy = index.get_projects_hierarchy()
    project_names = {p["name"] for p in hierarchy}
    assert {"KAIROS_2_0", "Canopy_Studio"}.issubset(project_names)

    # Verify `02_Projects/KAIROS` and `02_Projects/KAIROS_2_0` coexist with zero folder-prefix bleed
    vault.create_project_structure(project="KAIROS", scaffold_standard_departments=True)
    vault.create_task(
        CreateTaskInput(
            title="Implement V2 Micro-Kernel Event Bus",
            project="KAIROS",
            department="Software_Development",
            list="Sprint_01",
            priority=1,
        )
    )
    index.rebuild_all()
    kairos_v1_docs = index.search_vault(query="", folder="02_Projects/KAIROS")
    assert len(kairos_v1_docs) >= 2
    assert all(d["rel_path"].startswith("02_Projects/KAIROS/") for d in kairos_v1_docs)

    graph = index.get_graph_data()
    assert any(
        e["target"] == "02_Projects/KAIROS/_Project_Index.md" for e in graph["edges"]
    )


def test_api_projects_structure_inbox_promote_and_archive_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "API_E2E_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)

    client = TestClient(api_mod.app)

    # 1. Create Project with all 5 standard departments scaffolded via REST API
    r_struct = client.post(
        "/api/projects/structure",
        json={
            "project": "Throttle_Run",
            "department": "Software_Development",
            "list_name": "Sprint_01",
            "scaffold_standard_departments": True,
        },
    )
    assert r_struct.status_code == 200
    struct_data = r_struct.json()
    assert struct_data["project_index_rel"] == "02_Projects/Throttle_Run/_Project_Index.md"
    assert struct_data["canvas_rel"] == "02_Projects/Throttle_Run/Docs/Architecture_Diagram.canvas"
    assert (
        struct_data["list_index_rel"]
        == "02_Projects/Throttle_Run/Software_Development/Sprint_01/_List_Index.md"
    )
    vault_root = isolated_bundle["vault"].vault_path
    assert (vault_root / "02_Projects" / "Throttle_Run" / "Docs" / "Architecture_Diagram.canvas").is_file()
    for std_dept, std_list in (
        ("Software_Development", "Sprint_01"),
        ("Marketing_and_Branding", "Campaigns"),
        ("Documentation", "Specs_and_Guides"),
        ("Website", "Web_Launch"),
        ("Merch", "Printful_Drops"),
    ):
        assert (vault_root / "02_Projects" / "Throttle_Run" / std_dept / std_list / "Tasks").is_dir()
        list_note = isolated_bundle["vault"].read_note(
            f"02_Projects/Throttle_Run/{std_dept}/{std_list}/_List_Index.md"
        )
        assert list_note["frontmatter"]["type"] == "list"
        assert len(list_note["frontmatter"]["statuses"]) == 6

    # 2. Capture 2 notes in `00_Inbox/`
    client.post(
        "/api/vault/note",
        json={
            "file_path": "00_Inbox/Idea_Landing_Page.md",
            "frontmatter": {"title": "Build New Hero Landing Page", "tags": ["inbox", "ui"]},
            "body": "Need responsive hero layout and CTA metrics.",
            "mode": "overwrite",
        },
    )
    client.post(
        "/api/vault/note",
        json={
            "file_path": "00_Inbox/Ops_SOP_Draft.md",
            "frontmatter": {"title": "Quarterly Operations SOP", "tags": ["inbox"]},
            "body": "Standard operating procedure notes.",
            "mode": "overwrite",
        },
    )

    # 3. Promote first Inbox note into `Website` department of `Throttle_Run`
    r_prom = client.post(
        "/api/inbox/promote",
        json={
            "src_rel_path": "00_Inbox/Idea_Landing_Page.md",
            "project": "Throttle_Run",
            "department": "Website",
            "list_name": "Web_Launch",
            "priority": 1,
            "ai_agent": "Gemma-4",
        },
    )
    assert r_prom.status_code == 200
    prom_data = r_prom.json()
    assert prom_data["task"]["frontmatter"]["title"] == "Build New Hero Landing Page"
    assert prom_data["task"]["rel_path"].startswith(
        "02_Projects/Throttle_Run/Website/Web_Launch/Tasks/"
    )
    assert prom_data["archived_capture"].startswith("05_Archives/Triaged_Inbox/")

    # 4. File second Inbox note into `01_Business/Operations`
    r_move = client.post(
        "/api/inbox/move",
        json={"src_rel_path": "00_Inbox/Ops_SOP_Draft.md", "dest_folder": "01_Business/Operations"},
    )
    assert r_move.status_code == 200
    assert r_move.json()["rel_path"] == "01_Business/Operations/Ops_SOP_Draft.md"

    # 5. Embed Google Doc iframe into `_Project_Index.md`
    r_gdoc = client.post(
        "/api/connectors/gsuite-link",
        json={
            "note_path": struct_data["project_index_rel"],
            "google_doc_url": "https://docs.google.com/document/d/example-spec/preview",
            "pull_summary": False,
        },
    )
    assert r_gdoc.status_code == 200
    assert "<iframe" in r_gdoc.json()["body"]

    # 6. Archive completed Project into `05_Archives/`
    r_arch = client.post(
        "/api/projects/archive",
        json={"project": "Throttle_Run"},
    )
    assert r_arch.status_code == 200
    assert r_arch.json()["archived_rel"].startswith("05_Archives/Throttle_Run")


def test_gate6_compound_voice_command_and_privacy_shield_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "Gate6_Vault"))
    router = isolated_bundle["router"]

    monkeypatch.setattr(
        router,
        "_call_lmstudio_gemma4",
        lambda sys_p, usr_p: {
            "ok": True,
            "agent": "Gemma-4",
            "text": "Local Gemma 4 response verified.",
            "tokens_used": 28,
            "latency_ms": 3,
        },
    )
    monkeypatch.setattr(
        router,
        "_call_gemini_cloud",
        lambda sys_p, usr_p: {
            "ok": True,
            "agent": "Gemini-Pro",
            "text": "Cloud Gemini response verified.",
            "tokens_used": 34,
            "latency_ms": 9,
        },
    )
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)

    client = TestClient(api_mod.app)

    # A. Quick Voice Inbox Capture
    r_cap = client.post(
        "/api/kairos/command",
        json={"prompt": "Kairos, capture in Inbox: Review Q4 Canopy OKRs", "mode": "auto"},
    )
    assert r_cap.status_code == 200
    assert r_cap.json()["route_reason"] == "fast_inbox_capture"
    inbox_notes = client.get("/api/vault/notes", params={"folder": "00_Inbox"}).json()["notes"]
    assert any("Review Q4 Canopy OKRs" in n["title"] for n in inbox_notes)

    # B. Gate 6 Compound Command: Create High-Priority Task + Assign CrewAI + Block 9 AM Tomorrow
    r_gate6 = client.post(
        "/api/kairos/command",
        json={
            "prompt": (
                "Kairos, create a high-priority task to test Calendar sync, "
                "assign it to CrewAI-Research, and block 9 AM tomorrow"
            ),
            "mode": "auto",
        },
    )
    assert r_gate6.status_code == 200
    g6 = r_gate6.json()
    assert g6["route_reason"] == "compound_gate6_action"
    assert g6["assigned_agent"] == "CrewAI-Research"
    assert g6["calendar_blocked_at"].endswith("T09:00:00")
    tid = g6["created_task_id"]
    assert tid.startswith("TSK-")

    deadline = time.monotonic() + 2.0
    task_detail = client.get(f"/api/tasks/{tid}").json()
    while time.monotonic() < deadline and task_detail["frontmatter"]["status"] != "Review":
        time.sleep(0.05)
        task_detail = client.get(f"/api/tasks/{tid}").json()

    assert task_detail["frontmatter"]["priority"] == 2
    assert task_detail["frontmatter"]["status"] == "Review"

    cal_events = client.get("/api/calendar/events").json()["events"]
    assert any(tid in ev["linked_task"] for ev in cal_events)

    # C. Fast Voice Status Transition ("Move TSK-... to Done")
    r_done = client.post(
        "/api/kairos/command",
        json={"prompt": f"Kairos, move {tid} to Done", "mode": "auto"},
    )
    assert r_done.status_code == 200
    assert r_done.json()["route_reason"] == "fast_status_update"
    assert client.get(f"/api/tasks/{tid}").json()["frontmatter"]["status"] == "Done"

    # D. Hard Privacy Shield: Asking with `mode="gemini"` while viewing `03_Personal/Finance/` MUST lock to Gemma-4
    client.post(
        "/api/vault/note",
        json={
            "file_path": "03_Personal/Finance/Confidential_Budget.md",
            "frontmatter": {"title": "Confidential Budget", "tags": ["private", "finance"]},
            "body": "Net reserve figures.",
            "mode": "overwrite",
        },
    )
    r_priv = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Summarize this budget document",
            "mode": "gemini",
            "active_note_path": "03_Personal/Finance/Confidential_Budget.md",
        },
    )
    assert r_priv.status_code == 200
    priv_json = r_priv.json()
    assert priv_json["privacy_locked"] is True
    assert priv_json["agent"] == "Gemma-4"
    assert priv_json["route_reason"] == "privacy_hard_lock_local"


def test_kairos_assistant_sessions_personas_failover_and_env_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "Assistant_Vault"))
    vault = isolated_bundle["vault"]

    # Test Smart Auto Failover when LM Studio is offline vs `#private` hard-lock
    failover_cfg = KairosSettings(vault_path=vault.vault_path, gemini_api_key="test-gemini-key")
    failover_router = DualAIRouter(
        cfg=failover_cfg,
        audit_path=vault.vault_path / "_System" / "Logs" / "AI_Audit_Log.jsonl",
    )
    monkeypatch.setattr(
        failover_router,
        "_call_lmstudio_gemma4",
        lambda sys_p, usr_p: {
            "ok": False,
            "agent": "Gemma-4",
            "text": "[Local Gemma 4 Offline Fallback]",
            "tokens_used": 0,
            "latency_ms": 2,
        },
    )
    monkeypatch.setattr(
        failover_router,
        "_call_gemini_cloud",
        lambda sys_p, usr_p: {
            "ok": True,
            "agent": "Gemini-Pro",
            "text": "Live Gemini failover response!",
            "tokens_used": 25,
            "latency_ms": 11,
        },
    )

    non_priv = failover_router.generate("Hello KAIROS, what should we focus on?", mode="auto")
    assert non_priv["agent"] == "Gemini-Pro"
    assert non_priv["route_reason"] == "auto_cloud_failover_lmstudio_offline"

    strict_priv = failover_router.generate(
        "Summarize my private reserve #private",
        mode="auto",
        is_private=True,
    )
    assert strict_priv["agent"] == "Gemma-4"
    assert strict_priv["privacy_locked"] is True
    assert strict_priv["route_reason"] == "privacy_hard_lock_local"

    # Wire failover_router into bundle & test `/api/assistant/*` + `/api/settings/verify-apis`
    isolated_bundle["router"] = failover_router
    isolated_bundle["assistant"].router = failover_router
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    # 1. Multi-turn conversational session persistence in `01_Business/KAIROS_Sessions/SES-*.md`
    r_chat1 = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Give me an executive sprint check-in.",
            "mode": "auto",
            "persona": "pm",
            "tone_mode": "CODE_RED",
            "project_scope": "KAIROS_2_0",
        },
    )
    assert r_chat1.status_code == 200
    c1 = r_chat1.json()
    assert c1["reply"] == "Live Gemini failover response!"
    sid = c1["session"]["session_id"]
    assert sid.startswith("SES-")
    assert len(c1["session"]["turns"]) == 2

    # 2. Long-term Operator Memory command writes `03_Personal/Personal_Growth/KAIROS_Operator_Memory.md`
    r_mem = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Kairos, remember that Printful hoodies drop next Friday",
            "session_id": sid,
            "mode": "auto",
            "persona": "creative",
        },
    )
    assert r_mem.status_code == 200
    assert r_mem.json()["route_reason"] == "operator_memory_write"
    mem_note = vault.read_note("03_Personal/Personal_Growth/KAIROS_Operator_Memory.md")
    assert "Printful hoodies drop next Friday" in mem_note["body"]

    # 2b. Natural-language Canonical Project Template creation ("create a new project called ...")
    r_new_proj = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Kairos, create a new project called Canopy Studio",
            "session_id": sid,
            "mode": "auto",
            "persona": "pm",
        },
    )
    assert r_new_proj.status_code == 200
    np_data = r_new_proj.json()
    assert np_data["route_reason"] == "project_template_scaffolded"
    assert np_data["created_project"] == "Canopy_Studio"
    assert (
        vault.vault_path / "02_Projects" / "Canopy_Studio" / "Docs" / "Architecture_Diagram.canvas"
    ).is_file()
    assert (
        vault.vault_path
        / "02_Projects"
        / "Canopy_Studio"
        / "Merch"
        / "Printful_Drops"
        / "Tasks"
    ).is_dir()

    # 3. Natural-language department task creation -> lands in `Marketing_and_Branding/Campaigns/Tasks/`
    r_mkt = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Kairos, create a high-priority task in Marketing and Branding to film launch reel",
            "session_id": sid,
            "mode": "auto",
            "persona": "creative",
            "project_scope": "KAIROS_2_0",
        },
    )
    assert r_mkt.status_code == 200
    mkt_tid = r_mkt.json()["created_task_id"]
    mkt_task = client.get(f"/api/tasks/{mkt_tid}").json()
    assert mkt_task["rel_path"].startswith(
        "02_Projects/KAIROS_2_0/Marketing_and_Branding/Campaigns/Tasks/"
    )
    assert len(client.get(f"/api/assistant/sessions/{sid}").json()["turns"]) == 8

    # 4. Verify `.env` API verifier masks secrets & never leaks raw keys
    r_env = client.get("/api/settings/verify-apis", params={"live": "false"})
    assert r_env.status_code == 200
    env_data = r_env.json()
    assert env_data["total_count"] == 11
    for chk in env_data["checks"]:
        if chk["id"] != "canopy_vault" and chk["id"] != "google_oauth" and chk["configured"]:
            assert "••••" in chk["masked_key"] or chk["masked_key"].startswith("http")


def test_auto_codebase_to_vault_change_sync(tmp_path: Path) -> None:
    fake_codebase = tmp_path / "Fake_KAIROS_Repo"
    (fake_codebase / "services").mkdir(parents=True)
    mod_file = fake_codebase / "services" / "demo_module.py"
    mod_file.write_text("VERSION = '2.0.0'\n", encoding="utf-8")

    bundle = create_mcp_bundle(str(tmp_path / "Sync_Vault"))
    vault = bundle["vault"]
    index = bundle["index"]
    router = bundle["router"]

    r1 = sync_codebase_changes_to_vault(vault, index, router, codebase_root=fake_codebase)
    assert r1["ledger_updated"] is True
    assert "services/demo_module.py" in r1["added"]

    r2 = sync_codebase_changes_to_vault(vault, index, router, codebase_root=fake_codebase)
    assert r2["ledger_updated"] is False

    mod_file.write_text("VERSION = '2.1.0'\n", encoding="utf-8")
    r3 = sync_codebase_changes_to_vault(vault, index, router, codebase_root=fake_codebase)
    assert r3["ledger_updated"] is True
    assert r3["modified"] == ["services/demo_module.py"]

    ledger_note = vault.read_note("01_Business/OS_Updates/KAIROS_2_0_Change_Ledger.md")
    assert "[MODIFIED]` `services/demo_module.py`" in ledger_note["body"]


def test_full_voice_assistant_platform_navigation_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "Voice_Nav_Vault"))
    vault = isolated_bundle["vault"]
    index = isolated_bundle["index"]
    router = isolated_bundle["router"]

    # Seed both flagship projects (`KAIROS` and `KAIROS_2_0`) to verify exact voice disambiguation
    vault.create_project_structure(project="KAIROS_2_0", scaffold_standard_departments=True)
    vault.create_project_structure(project="KAIROS", scaffold_standard_departments=True)
    t_kairos = vault.create_task(
        CreateTaskInput(
            title="Stabilize Moonraker Klipper Telemetry Bridge",
            project="KAIROS",
            department="Software_Development",
            list="Sprint_01",
            priority=1,
        )
    )
    tid_kairos = t_kairos["frontmatter"]["id"]
    index.rebuild_all()

    monkeypatch.setattr(
        router,
        "_call_lmstudio_gemma4",
        lambda sys_p, usr_p: {
            "ok": True,
            "agent": "Gemma-4",
            "text": 'Here is your summary. <ui_nav>{"type":"navigate_tab","tab":"paperclip"}</ui_nav>',
            "tokens_used": 20,
            "latency_ms": 4,
        },
    )
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    # 1. Chained Voice Command: Navigate to `KAIROS` (NOT `KAIROS_2_0`) + switch to `Gantt`
    r1 = client.post(
        "/api/kairos/command",
        json={"prompt": "Hey Kairos, open KAIROS and switch to Gantt", "mode": "auto"},
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["route_reason"] == "platform_voice_navigation"
    assert d1["ui_commands"] == [
        {"type": "navigate_tab", "tab": "projects"},
        {"type": "select_project_scope", "project": "KAIROS", "department": "", "list": ""},
        {"type": "set_projects_view", "view": "gantt"},
    ]
    assert "[[" not in d1["spoken_reply"]

    # 2. Department + Kanban Board Voice Navigation on `KAIROS_2_0`
    r2 = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Open KAIROS 2.0 Marketing and Branding and show Kanban board",
            "mode": "auto",
        },
    )
    d2 = r2.json()
    assert d2["ui_commands"] == [
        {"type": "navigate_tab", "tab": "projects"},
        {
            "type": "select_project_scope",
            "project": "KAIROS_2_0",
            "department": "Marketing_and_Branding",
            "list": "",
        },
        {"type": "set_projects_view", "view": "board"},
    ]

    # 3. Inspect Task Drawer by spoken Task ID
    r3 = client.post(
        "/api/kairos/command",
        json={"prompt": f"Pull up task {tid_kairos}", "mode": "auto"},
    )
    d3 = r3.json()
    assert {"type": "open_task_drawer", "task_id": tid_kairos} in d3["ui_commands"]

    # 4. Second Brain 3D Galaxy + Daily Note + Private Finance Folder
    r4 = client.post(
        "/api/kairos/command",
        json={"prompt": "Show the 3D Galaxy graph in Second Brain", "mode": "auto"},
    )
    assert {"type": "set_second_brain_graph", "show": True, "mode": "3d"} in r4.json()["ui_commands"]

    r_daily = client.post(
        "/api/kairos/command",
        json={"prompt": "Open today's daily note", "mode": "auto"},
    )
    assert r_daily.json()["ui_commands"][0] == {"type": "navigate_tab", "tab": "second-brain"}
    assert r_daily.json()["ui_commands"][1]["type"] == "open_note"

    r_fin = client.post(
        "/api/kairos/command",
        json={"prompt": "Open Finance folder", "mode": "auto"},
    )
    assert r_fin.json()["privacy_locked"] is True

    # 5. Browser Search + Clip Webpage
    r_br = client.post(
        "/api/kairos/command",
        json={"prompt": "Search in the browser for Klipper Moonraker API", "mode": "auto"},
    )
    assert r_br.json()["ui_commands"][0] == {"type": "navigate_tab", "tab": "browser"}
    assert r_br.json()["ui_commands"][1]["type"] == "browser_navigate"

    r_clip = client.post(
        "/api/kairos/command",
        json={"prompt": "Clip current page", "mode": "auto"},
    )
    assert {"type": "browser_clip", "dest_folder": "00_Inbox"} in r_clip.json()["ui_commands"]

    # 6. Persona + CODE RED Switching
    r_red = client.post(
        "/api/kairos/command",
        json={"prompt": "Activate CODE RED", "mode": "auto"},
    )
    assert r_red.json()["ui_commands"] == [{"type": "set_tone_mode", "tone_mode": "CODE_RED"}]

    r_pers = client.post(
        "/api/kairos/command",
        json={"prompt": "Switch persona to Project Director", "mode": "auto"},
    )
    assert r_pers.json()["ui_commands"] == [{"type": "set_persona", "persona": "pm"}]

    # 7. Compound Voice Task Creation + Immediate Task Drawer Navigation
    r_create_nav = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Create an urgent task in KAIROS Website for interactive 3D hero demo and open it on the board",
            "mode": "auto",
            "project_scope": "KAIROS_2_0",
        },
    )
    cn = r_create_nav.json()
    assert cn["route_reason"] == "compound_gate6_action"
    new_tid = cn["created_task_id"]
    created_file = client.get(f"/api/tasks/{new_tid}").json()
    assert created_file["rel_path"].startswith("02_Projects/KAIROS/Website/Web_Launch/Tasks/")
    assert {"type": "open_task_drawer", "task_id": new_tid} in cn["ui_commands"]
    assert {"type": "set_projects_view", "view": "board"} in cn["ui_commands"]

    # 8. Conversational LLM `<ui_nav>` tag extraction
    r_llm_nav = client.post(
        "/api/kairos/command",
        json={"prompt": "Why would two agents collide and can you pull up the lock monitor?", "mode": "gemma-4"},
    )
    ln = r_llm_nav.json()
    assert "<ui_nav>" not in ln["reply"]
    assert ln["ui_commands"] == [{"type": "navigate_tab", "tab": "paperclip"}]


def test_live_sports_custom_categories_unarchive_calendar_and_hermes_api_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify live sports answers, custom categories, unarchive/resync, standalone calendar events, Wiki & Hermes REST APIs."""
    import services.kairos_core.assistant as assistant_mod

    isolated_bundle = create_mcp_bundle(str(tmp_path / "Live_Upgrade_Vault"))
    vault = isolated_bundle["vault"]
    index = isolated_bundle["index"]
    router = isolated_bundle["router"]

    vault.create_project_structure(project="KAIROS_2_0", scaffold_standard_departments=True)
    vault.create_project_structure(project="KAIROS", scaffold_standard_departments=True)
    index.rebuild_all()

    monkeypatch.setattr(
        router,
        "_call_lmstudio_gemma4",
        lambda sys_p, usr_p: {
            "ok": True,
            "agent": "Gemma-4",
            "text": (
                "Cleveland Browns 24, Baltimore Ravens 17 (Final)!"
                if "Cleveland Browns" in usr_p
                else "TAKEAWAY: Always scaffold custom category lists inside 02_Projects.\nSTEPS:\n- Register category in _Project_Index.md.\n- Rebuild ShadowIndex."
            ),
            "tokens_used": 28,
            "latency_ms": 5,
        },
    )

    class _FakeResp:
        ok = True

        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    def _fake_requests_get(url: str, *args, **kwargs):
        if "football/nfl/scoreboard" in url:
            return _FakeResp(
                {
                    "events": [
                        {
                            "name": "Baltimore Ravens at Cleveland Browns",
                            "competitions": [
                                {
                                    "status": {"type": {"shortDetail": "Final"}},
                                    "competitors": [
                                        {
                                            "team": {"displayName": "Cleveland Browns", "shortDisplayName": "Browns"},
                                            "score": "24",
                                        },
                                        {
                                            "team": {"displayName": "Baltimore Ravens", "shortDisplayName": "Ravens"},
                                            "score": "17",
                                        },
                                    ],
                                }
                            ],
                        }
                    ]
                }
            )
        return _FakeResp({"events": []})

    monkeypatch.setattr(assistant_mod.requests, "get", _fake_requests_get)
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    # 1. Live Sports Question ("What's the score of the Browns game?") must answer with live scoreboard & spoken_reply (not hijacked by navigator)
    r_browns = client.post(
        "/api/assistant/chat",
        json={"prompt": "What's the score of the Browns game?", "mode": "gemma-4"},
    )
    assert r_browns.status_code == 200
    browns_data = r_browns.json()
    assert "Cleveland Browns 24" in browns_data["reply"]
    assert "Cleveland Browns 24" in browns_data["spoken_reply"]
    assert any("Live Sports Scoreboard" in a for a in browns_data["actions"])

    # 2. Add Custom Category ("Hardware_and_Firmware") inside KAIROS_2_0 without re-scaffolding unrelated departments
    r_cat = client.post(
        "/api/projects/structure",
        json={
            "project": "KAIROS_2_0",
            "department": "Hardware_and_Firmware",
            "list_name": "Board_Bringup",
            "scaffold_standard_departments": False,
        },
    )
    assert r_cat.status_code == 200
    tree = client.get("/api/projects/tree").json()
    k2_proj = next(p for p in tree["projects"] if p["name"] == "KAIROS_2_0")
    dept_names = [d["name"] for d in k2_proj["departments"]]
    assert "Hardware_and_Firmware" in dept_names

    # Verify voice navigator dynamically recognizes the newly added custom category
    r_nav_custom = client.post(
        "/api/kairos/command",
        json={"prompt": "Open KAIROS 2.0 Hardware and Firmware and show rollup", "mode": "auto"},
    )
    assert {
        "type": "select_project_scope",
        "project": "KAIROS_2_0",
        "department": "Hardware_and_Firmware",
        "list": "",
    } in r_nav_custom.json()["ui_commands"]
    assert {"type": "set_projects_view", "view": "rollup"} in r_nav_custom.json()["ui_commands"]

    # 3. Archive & Restore (`unarchive`) Project + Resync Index
    r_arch = client.post("/api/projects/archive", json={"project": "KAIROS"})
    assert r_arch.status_code == 200
    archived_list = client.get("/api/projects/archived").json()["archived_projects"]
    assert "KAIROS" in archived_list

    r_unarch = client.post("/api/projects/unarchive", json={"archive_name": "KAIROS"})
    assert r_unarch.status_code == 200
    resynced = client.post("/api/projects/resync").json()
    assert any(p["name"] == "KAIROS" for p in resynced["projects"])

    # 4. Standalone Calendar Event (`POST /api/calendar/events`) with project linkage
    r_evt = client.post(
        "/api/calendar/events",
        json={
            "title": "KAIROS 2.0 Sprint Architecture Review",
            "start_time_iso": "2026-10-28T14:00:00",
            "duration_hrs": 1.5,
            "category": "Deep_Work",
            "project": "KAIROS_2_0",
            "notes": "Verify Rollup -> List -> Board -> Calendar -> Gantt -> Documentation flow.",
        },
    )
    assert r_evt.status_code == 200
    evts = client.get("/api/calendar/events").json()["events"]
    assert any(
        e["title"] == "KAIROS 2.0 Sprint Architecture Review" and e["linked_project"] == "KAIROS_2_0"
        for e in evts
    )

    # 5. Project Documentation Wiki page creation inside `02_Projects/KAIROS_2_0/Docs/`
    r_wiki = client.post(
        "/api/vault/note",
        json={
            "file_path": "02_Projects/KAIROS_2_0/Docs/Release_Runbook.md",
            "frontmatter": {
                "title": "Release Runbook",
                "type": "project_wiki",
                "project": "[[KAIROS_2_0]]",
                "tags": ["wiki", "documentation"],
            },
            "body": "# 📖 Release Runbook\n\nStep-by-step release checklist for KAIROS 2.0.",
            "mode": "overwrite",
        },
    )
    assert r_wiki.status_code == 200
    wiki_notes = client.get("/api/vault/notes", params={"folder": "02_Projects/KAIROS_2_0"}).json()["notes"]
    assert any(n["rel_path"] == "02_Projects/KAIROS_2_0/Docs/Release_Runbook.md" for n in wiki_notes)

    # 6. Hermes REST & Conversational Knowledge Retention + Skill Distillation
    r_h_chat = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Hermes, remember that Projects always opens on the Rollup sub-view first.",
            "mode": "gemma-4",
        },
    )
    assert r_h_chat.status_code == 200
    assert r_h_chat.json()["route_reason"] == "hermes_memory_retain"

    t_created = client.post(
        "/api/tasks",
        json={
            "title": "Standardize Custom Category Scaffolding",
            "project": "KAIROS_2_0",
            "department": "Hardware_and_Firmware",
            "list": "Board_Bringup",
        },
    ).json()
    tid = t_created["frontmatter"]["id"]

    r_distill = client.post("/api/hermes/distill-task", json={"task_id": tid})
    assert r_distill.status_code == 200
    assert r_distill.json()["skill_id"].startswith("SKL-")

    r_manual_skill = client.post(
        "/api/hermes/skills",
        json={
            "title": "Gantt Today Dateline Audit",
            "category": "UI Verification",
            "trigger": "When updating timeline or Gantt views",
            "steps_markdown": "1. Verify sticky date header.\n2. Confirm red TODAY marker position.",
            "project": "KAIROS_2_0",
        },
    )
    assert r_manual_skill.status_code == 200

    h_status = client.get("/api/hermes/status").json()
    assert h_status["skill_count"] >= 2
    assert "Rollup sub-view first" in h_status["memory_body"]

    # 7. Physical Category relocation via PATCH /api/tasks/{tid} (`TaskDrawer` Category Switcher)
    old_rel = t_created["rel_path"]
    r_move_cat = client.patch(
        f"/api/tasks/{tid}",
        json={"task_id": tid, "department": "Podcast_Studio"},
    )
    assert r_move_cat.status_code == 200
    moved_detail = r_move_cat.json()
    assert moved_detail["frontmatter"]["department"] == "Podcast_Studio"
    assert "02_Projects/KAIROS_2_0/Podcast_Studio/" in moved_detail["rel_path"]
    assert not (vault.vault_path / old_rel).exists()
    assert (vault.vault_path / moved_detail["rel_path"]).exists()
    podcast_tasks = client.get(
        "/api/tasks",
        params={"project": "KAIROS_2_0", "department": "Podcast_Studio"},
    ).json()["tasks"]
    assert any(t["id"] == tid for t in podcast_tasks)


def test_conversational_custom_category_wiki_calendar_and_task_relocation_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify spoken/conversational Custom Category creation, custom-category task routing, task relocation, Project Wiki creation, and Calendar event scheduling."""
    isolated_bundle = create_mcp_bundle(str(tmp_path / "Conv_Skills_Vault"))
    vault = isolated_bundle["vault"]
    index = isolated_bundle["index"]

    vault.create_project_structure(project="KAIROS_2_0", scaffold_standard_departments=True)
    index.rebuild_all()
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    # 1. Conversational Custom Category creation (`custom_category_created`)
    r_cat = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Kairos, add category called Hardware Lab to KAIROS 2.0 with list PCB_Bringup",
            "mode": "auto",
        },
    )
    assert r_cat.status_code == 200
    d_cat = r_cat.json()
    assert d_cat["route_reason"] == "custom_category_created"
    assert d_cat["created_category"] == "Hardware_Lab"
    assert {
        "type": "select_project_scope",
        "project": "KAIROS_2_0",
        "department": "Hardware_Lab",
        "list": "",
    } in d_cat["ui_commands"]

    # 2. Conversational Task Creation dynamically routes into the new Custom Category (`Hardware_Lab/PCB_Bringup`)
    r_tsk = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Kairos, create a high-priority task in KAIROS 2.0 Hardware Lab to solder sensor breakout",
            "mode": "auto",
            "project_scope": "KAIROS_2_0",
        },
    )
    assert r_tsk.status_code == 200
    d_tsk = r_tsk.json()
    assert d_tsk["route_reason"] == "compound_gate6_action"
    tid = d_tsk["created_task_id"]
    task_file = client.get(f"/api/tasks/{tid}").json()
    assert task_file["rel_path"].startswith("02_Projects/KAIROS_2_0/Hardware_Lab/PCB_Bringup/Tasks/")

    # 3. Conversational Task Category Relocation (`fast_category_relocate`) + Drawer Open
    r_reloc = client.post(
        "/api/assistant/chat",
        json={
            "prompt": f"Kairos, move task {tid} to category Podcast Studio and open it",
            "mode": "auto",
        },
    )
    assert r_reloc.status_code == 200
    d_reloc = r_reloc.json()
    assert d_reloc["route_reason"] == "fast_category_relocate"
    assert d_reloc["rel_path"].startswith("02_Projects/KAIROS_2_0/Podcast_Studio/")
    assert {"type": "open_task_drawer", "task_id": tid} in d_reloc["ui_commands"]
    assert not (vault.vault_path / task_file["rel_path"]).exists()
    assert (vault.vault_path / d_reloc["rel_path"]).exists()

    # 4. Conversational Project Wiki Note creation (`project_wiki_created`) + `docs` sub-view switch
    r_wiki = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Kairos, create wiki note in KAIROS 2.0 titled Hardware Bringup Guide: Check 5V rail before flashing MCU",
            "mode": "auto",
        },
    )
    assert r_wiki.status_code == 200
    d_wiki = r_wiki.json()
    assert d_wiki["route_reason"] == "project_wiki_created"
    assert d_wiki["wiki_rel_path"] == "02_Projects/KAIROS_2_0/Docs/Hardware_Bringup_Guide.md"
    assert {"type": "set_projects_view", "view": "docs"} in d_wiki["ui_commands"]
    wiki_read = vault.read_note("02_Projects/KAIROS_2_0/Docs/Hardware_Bringup_Guide.md")
    assert "Check 5V rail before flashing MCU" in wiki_read["body"]

    # 5. Conversational Standalone Calendar Event Scheduling (`calendar_event_scheduled`) + `calendar` sub-view switch
    r_cal = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Kairos, schedule calendar event Sprint Architecture Demo at 2:30 PM tomorrow in KAIROS 2.0",
            "mode": "auto",
        },
    )
    assert r_cal.status_code == 200
    d_cal = r_cal.json()
    assert d_cal["route_reason"] == "calendar_event_scheduled"
    assert d_cal["start_time"].endswith("T14:30:00")
    assert {"type": "set_projects_view", "view": "calendar"} in d_cal["ui_commands"]
    all_evts = client.get("/api/calendar/events").json()["events"]
    assert any(
        ev["title"] == "Sprint Architecture Demo" and ev["linked_project"] == "KAIROS_2_0"
        for ev in all_evts
    )

    # 6. Health endpoint reports live `hermes_skill_count`
    h_res = client.get("/api/health").json()
    assert isinstance(h_res.get("hermes_skill_count"), int)


def test_task_dependencies_relocation_dedup_and_17_mcp_tools_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify PATCH parent_task/depends_on, zero-duplicate ShadowIndex category relocation (`remove_path`), and all 18 `second_brain_mcp` tools."""
    isolated_bundle = create_mcp_bundle(str(tmp_path / "Mcp17_Vault"))
    vault = isolated_bundle["vault"]
    index = isolated_bundle["index"]
    mcp_tools = isolated_bundle["mcp_tools"]

    assert len(mcp_tools) == 18

    # 1. MCP `projects_create_structure` creates project + custom category
    created_struct = mcp_tools["projects_create_structure"](
        project="KAIROS_2_0",
        department="Podcast_Ops",
        list_name="Episode_Queue",
        scaffold_standard_departments=True,
    )
    assert created_struct["project"] == "KAIROS_2_0"
    assert created_struct["department"] == "Podcast_Ops"

    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    # 2. Create two tasks via MCP `projects_create_task` and link subtask + Gantt dependency via PATCH
    t1 = mcp_tools["projects_create_task"](
        title="Record Episode 01 Audio",
        project="KAIROS_2_0",
        department="Podcast_Ops",
        list_name="Episode_Queue",
        priority=1,
    )
    t2 = mcp_tools["projects_create_task"](
        title="Publish Episode 01 Show Notes",
        project="KAIROS_2_0",
        department="Podcast_Ops",
        list_name="Episode_Queue",
        priority=2,
    )
    tid1 = t1["frontmatter"]["id"]
    tid2 = t2["frontmatter"]["id"]

    r_patch = client.patch(
        f"/api/tasks/{tid2}",
        json={
            "task_id": tid2,
            "parent_task": tid1,
            "depends_on": [tid1],
            "department": "Marketing_and_Branding",
        },
    )
    assert r_patch.status_code == 200
    patched = r_patch.json()
    assert patched["frontmatter"]["parent_task"] == f"[[{tid1}]]"
    assert patched["frontmatter"]["depends_on"] == [f"[[{tid1}]]"]
    assert patched["frontmatter"]["department"] == "Marketing_and_Branding"

    # Verify ShadowIndex has ZERO duplicate rows for `tid2` after physical category move (`remove_path`)
    all_tasks = index.list_tasks(project="KAIROS_2_0")
    matching_tid2 = [t for t in all_tasks if t["id"] == tid2]
    assert len(matching_tid2) == 1
    assert matching_tid2[0]["department"] == "Marketing_and_Branding"
    assert matching_tid2[0]["parent_task"] == f"[[{tid1}]]"
    assert matching_tid2[0]["depends_on"] == [f"[[{tid1}]]"]
    assert client.get("/api/health").status_code == 200

    # 3. Exercise MCP `projects_create_wiki_note`, `calendar_create_event`, and `vault_clip_webpage`
    wiki_res = mcp_tools["projects_create_wiki_note"](
        project="KAIROS_2_0",
        title="Podcast Launch Playbook",
        body="# 📘 Podcast Launch Playbook\n\n1. Normalize LUFS to -16.\n2. Publish RSS.",
    )
    assert wiki_res["rel_path"] == "02_Projects/KAIROS_2_0/Docs/Podcast_Launch_Playbook.md"

    cal_res = mcp_tools["calendar_create_event"](
        title="Podcast Guest Recording",
        start_time_iso="2026-10-30T15:00:00",
        duration_hrs=1.0,
        project="KAIROS_2_0",
        linked_task=tid1,
    )
    assert cal_res["rel_path"].startswith("03_Personal/Calendar/EVT-20261030-")

    clip_res = mcp_tools["vault_clip_webpage"](
        url="https://example.com/audio-guide",
        raw_html_or_text="<html><body><h1>Audio Mastering</h1><p>Use -16 LUFS.</p></body></html>",
        title="Audio Mastering Guide",
    )
    assert clip_res["rel_path"].startswith("00_Inbox/Clip_")


def test_calendar_event_crud_task_gcal_link_briefing_and_voice_dependencies_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify Calendar EVT CRUD + gcal_event_id sync, Voice/Chat dependency & reschedule skills, Executive Daily Briefing, and #private Crew deliverable tag preservation."""
    isolated_bundle = create_mcp_bundle(str(tmp_path / "Round5_Feature_Vault"))
    vault = isolated_bundle["vault"]
    index = isolated_bundle["index"]
    router = isolated_bundle["router"]
    crew = isolated_bundle["crew"]
    paperclip = isolated_bundle["paperclip"]

    vault.create_project_structure(project="KAIROS_2_0", scaffold_standard_departments=True)
    t_a = vault.create_task(
        CreateTaskInput(
            title="Finalize Calendar Drag Rescheduler",
            project="KAIROS_2_0",
            department="Software_Development",
            list="Sprint_01",
            priority=1,
        )
    )
    t_b = vault.create_task(
        CreateTaskInput(
            title="Audit Local Finance Ledger Export",
            project="KAIROS_2_0",
            department="Software_Development",
            list="Sprint_01",
            priority=2,
            tags=["private", "finance"],
        )
    )
    tid_a = t_a["frontmatter"]["id"]
    tid_b = t_b["frontmatter"]["id"]
    index.rebuild_all()

    monkeypatch.setattr(
        router,
        "_call_lmstudio_gemma4",
        lambda sys_p, usr_p: {
            "ok": True,
            "agent": "Gemma-4",
            "text": "Private ledger verified locally.",
            "tokens_used": 18,
            "latency_ms": 5,
        },
    )
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    # 1. Time-block `tid_a` -> populates `gcal_event_id` on Task YAML + `linked_project` & `linked_task_id` on Event
    r_tb = client.post(
        "/api/calendar/time-block",
        json={
            "task_id": tid_a,
            "start_time_iso": "2026-10-28T13:30:00",
            "duration_hrs": 1.5,
            "category": "Business",
        },
    )
    assert r_tb.status_code == 200
    evt_id = r_tb.json()["frontmatter"]["id"]
    assert r_tb.json()["frontmatter"]["linked_project"] == "[[KAIROS_2_0]]"
    t_after_tb = client.get(f"/api/tasks/{tid_a}").json()
    assert t_after_tb["frontmatter"]["gcal_event_id"] == evt_id

    ev_list = client.get("/api/calendar/events").json()["events"]
    matched_ev = [e for e in ev_list if e["id"] == evt_id]
    assert len(matched_ev) == 1
    assert matched_ev[0]["linked_task_id"] == tid_a

    # 2. PATCH `/api/calendar/events/{evt_id}` reschedules day while preserving `13:30:00` & syncs Task `due_date`
    r_move_ev = client.patch(
        f"/api/calendar/events/{evt_id}",
        json={"new_date_iso": "2026-10-31"},
    )
    assert r_move_ev.status_code == 200
    assert r_move_ev.json()["frontmatter"]["start_time"] == "2026-10-31T13:30:00"
    assert r_move_ev.json()["frontmatter"]["end_time"] == "2026-10-31T15:00:00"
    assert client.get(f"/api/tasks/{tid_a}").json()["frontmatter"]["due_date"] == "2026-10-31"

    # 3. DELETE `/api/calendar/events/{evt_id}` removes `EVT-*.md` and clears `gcal_event_id` on `tid_a`
    r_del_ev = client.delete(f"/api/calendar/events/{evt_id}")
    assert r_del_ev.status_code == 200
    assert r_del_ev.json()["deleted_id"] == evt_id
    assert client.get(f"/api/tasks/{tid_a}").json()["frontmatter"]["gcal_event_id"] == ""

    # 4. Deterministic Voice/Chat Skills: Dependency Linking, Date Rescheduling, and Executive Daily Briefing
    r_dep = client.post(
        "/api/assistant/chat",
        json={"prompt": f"Kairos, make {tid_b} depend on {tid_a}", "mode": "auto"},
    )
    assert r_dep.status_code == 200
    assert r_dep.json()["route_reason"] == "fast_task_dependency_link"
    assert {"type": "set_projects_view", "view": "gantt"} in r_dep.json()["ui_commands"]
    assert client.get(f"/api/tasks/{tid_b}").json()["frontmatter"]["depends_on"] == [f"[[{tid_a}]]"]

    r_rs = client.post(
        "/api/assistant/chat",
        json={"prompt": f"Reschedule {tid_a} to 2026-11-04", "mode": "auto"},
    )
    assert r_rs.status_code == 200
    assert r_rs.json()["route_reason"] == "fast_task_reschedule"
    assert {"type": "set_projects_view", "view": "calendar"} in r_rs.json()["ui_commands"]
    assert client.get(f"/api/tasks/{tid_a}").json()["frontmatter"]["due_date"] == "2026-11-04"

    r_brief = client.post(
        "/api/assistant/chat",
        json={"prompt": "Give me my daily briefing", "mode": "auto"},
    )
    assert r_brief.status_code == 200
    d_brief = r_brief.json()
    assert d_brief["route_reason"] == "executive_daily_briefing"
    assert "Portfolio Rollup" in d_brief["reply"]
    assert {"type": "set_projects_view", "view": "rollup"} in d_brief["ui_commands"]

    # 5. `#private` task run through `Hermes-Agent` preserves `is_private == True` on report + records `artifact_rel_path` & `hermes_skill_rel_path` in Paperclip `recent_runs`
    crew_res = crew.execute_task_with_crew(tid_b, crew_name="Hermes-Agent")
    assert crew_res["ok"] is True
    rep_note = vault.read_note(crew_res["artifact_rel_path"])
    assert rep_note["is_private"] is True
    assert "private" in rep_note["frontmatter"]["tags"]
    snap = paperclip.get_snapshot()
    assert snap["recent_runs"][0]["artifact_rel_path"] == crew_res["artifact_rel_path"]
    assert snap["recent_runs"][0]["hermes_skill_rel_path"] == crew_res["hermes_skill_rel_path"]


def test_second_brain_backlinks_and_voice_crew_checklist_timelog_skills_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify Second Brain Backlinks (`/api/vault/backlinks`) + deterministic Voice/Chat Checklist, Time-Log, and Paperclip Crew/Hermes dispatch skills."""
    isolated_bundle = create_mcp_bundle(str(tmp_path / "Round6_Feature_Vault"))
    vault = isolated_bundle["vault"]
    index = isolated_bundle["index"]
    router = isolated_bundle["router"]

    vault.create_project_structure(project="KAIROS_2_0", scaffold_standard_departments=True)
    t_core = vault.create_task(
        CreateTaskInput(
            title="Build Second Brain Backlinks Engine",
            project="KAIROS_2_0",
            department="Software_Development",
            list="Sprint_01",
            priority=1,
        )
    )
    tid_core = t_core["frontmatter"]["id"]
    rel_core = t_core["rel_path"]

    t_dep = vault.create_task(
        CreateTaskInput(
            title="Wire Linked Mentions Panel in Second Brain UI",
            project="KAIROS_2_0",
            department="Software_Development",
            list="Sprint_01",
            priority=2,
            depends_on=[f"[[{tid_core}]]"],
            parent_task=tid_core,
        )
    )
    tid_dep = t_dep["frontmatter"]["id"]

    wiki_doc = vault.write_note(
        "02_Projects/KAIROS_2_0/Docs/Backlinks_Spec.md",
        {"title": "Backlinks Spec", "type": "wiki", "project": "[[KAIROS_2_0]]"},
        f"# Backlinks Spec\n\nTracks [[{tid_core}]] under [[02_Projects/KAIROS_2_0/_Project_Index|KAIROS 2.0]].\n",
        mode="overwrite",
    )
    index.rebuild_all()

    monkeypatch.setattr(
        router,
        "_call_lmstudio_gemma4",
        lambda sys_p, usr_p: {
            "ok": True,
            "agent": "Gemma-4",
            "text": "TAKEAWAY: Backlinks unify WikiLinks and task dependencies.\nSTEPS:\n- Query ShadowIndex.get_backlinks.\n- Render Linked Mentions chips.",
            "tokens_used": 24,
            "latency_ms": 4,
        },
    )
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    # 1. Backlinks API resolves both `depends_on` task edges (with `task_id`) and Wiki `wikilink` edges
    r_bl = client.get("/api/vault/backlinks", params={"path": rel_core})
    assert r_bl.status_code == 200
    bl_data = r_bl.json()
    assert bl_data["count"] >= 2
    by_src = {item["rel_path"]: item for item in bl_data["backlinks"]}
    assert t_dep["rel_path"] in by_src
    assert by_src[t_dep["rel_path"]]["edge_kind"] == "depends_on"
    assert by_src[t_dep["rel_path"]]["task_id"] == tid_dep
    assert wiki_doc["rel_path"] in by_src
    assert by_src[wiki_doc["rel_path"]]["edge_kind"] == "wikilink"

    # Project `_Project_Index.md` also receives incoming backlinks from tasks & wiki docs
    r_proj_bl = client.get(
        "/api/vault/backlinks",
        params={"path": "02_Projects/KAIROS_2_0/_Project_Index.md"},
    )
    assert r_proj_bl.status_code == 200
    assert r_proj_bl.json()["count"] >= 3

    # 2. Voice/Chat Fast Skill: `fast_task_checklist_add`
    r_chk = client.post(
        "/api/assistant/chat",
        json={
            "prompt": f"Kairos, add checklist item Verify Linked Mentions chip jump to {tid_core}",
            "mode": "auto",
        },
    )
    assert r_chk.status_code == 200
    d_chk = r_chk.json()
    assert d_chk["route_reason"] == "fast_task_checklist_add"
    assert {"type": "open_task_drawer", "task_id": tid_core} in d_chk["ui_commands"]
    t_after_chk = client.get(f"/api/tasks/{tid_core}").json()
    assert "- [ ] Verify Linked Mentions chip jump" in t_after_chk["body"]

    # 3. Voice/Chat Fast Skill: `fast_task_time_log` (minutes -> hours conversion + activity log)
    r_log = client.post(
        "/api/assistant/chat",
        json={
            "prompt": f"Log 45 minutes on task {tid_core}: Verified backlinks SQLite WAL query",
            "mode": "auto",
        },
    )
    assert r_log.status_code == 200
    d_log = r_log.json()
    assert d_log["route_reason"] == "fast_task_time_log"
    t_after_log = client.get(f"/api/tasks/{tid_core}").json()
    assert float(t_after_log["frontmatter"]["time_logged_hrs"]) == 0.75
    assert "Verified backlinks SQLite WAL query" in t_after_log["body"]

    # 4. Voice/Chat Fast Skill: `fast_crew_dispatch` (`Hermes-Agent` via Paperclip lock)
    r_crew = client.post(
        "/api/assistant/chat",
        json={
            "prompt": f"Dispatch Hermes-Agent on {tid_core}",
            "mode": "auto",
        },
    )
    assert r_crew.status_code == 200
    d_crew = r_crew.json()
    assert d_crew["route_reason"] == "fast_crew_dispatch"
    assert (
        d_crew["artifact_rel_path"]
        == f"04_Resources/Code_and_Research/{tid_core}_Hermes-Agent_Report.md"
    )
    assert d_crew["hermes_skill_rel_path"].startswith("04_Resources/Hermes/Skills/SKL-")
    assert {"type": "navigate_tab", "tab": "paperclip"} in d_crew["ui_commands"]
    assert client.get(f"/api/tasks/{tid_core}").json()["frontmatter"]["status"] == "Review"




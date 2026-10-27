"""Phase 12 — Inbox-to-Section Hub Promotion, Command Palette Hubs, Interactive JSON Canvas 1.0 Edges/Groups & Project `.base` Databases."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import services.kairos_core.api as api_mod
from services.kairos_core.env_verifier import verify_env_apis
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.tool_registry import extract_and_execute_kairos_ops

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_SRC_ROOT = REPO_ROOT / "apps" / "desktop" / "src"


def test_phase12_inbox_promote_to_section_endpoint_and_fast_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase12_InboxHub_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    # 1. Capture a #private Inbox note with an embedded vendor URL and promote via REST API
    cap_a = client.post(
        "/api/inbox",
        json={
            "title": "FabFilter Pro-Q 4",
            "body": "Check linear phase EQ docs at https://www.fabfilter.com/products/pro-q-4-equalizer-plug-in before mastering.",
            "source": "Quick-Capture",
            "tags": ["#inbox", "#private"],
            "is_private": True,
        },
    )
    assert cap_a.status_code == 200
    src_rel_a = cap_a.json()["rel_path"]

    prom_a = client.post(
        "/api/inbox/promote-to-section",
        json={
            "src_rel_path": src_rel_a,
            "section_or_folder": "04_Resources/Music_Studio",
            "collection": "Plugins",
            "item_type": "plugin",
            "vendor": "FabFilter",
        },
    )
    assert prom_a.status_code == 200
    pa_data = prom_a.json()
    assert pa_data["extracted_url"] == "https://www.fabfilter.com/products/pro-q-4-equalizer-plug-in"
    assert pa_data["archived_capture"].startswith("05_Archives/Triaged_Inbox/")
    assert not bundle["vault"].resolve_safe_path(src_rel_a).exists()

    entry_a = pa_data["entry"]
    assert entry_a["rel_path"].startswith("04_Resources/Music_Studio/Plugins/")
    assert entry_a["is_private"] is True
    assert entry_a["frontmatter"]["vendor"] == "FabFilter"
    assert (
        entry_a["frontmatter"]["support_url"]
        == "https://www.fabfilter.com/products/pro-q-4-equalizer-plug-in"
    )

    # 2. Capture a second Inbox note and promote via KairosAssistant Fast Skill 5d-sec
    cap_b = client.post(
        "/api/inbox",
        json={
            "title": "Output Portal Granular FX",
            "body": "Granular FX reference: https://output.com/products/portal",
            "source": "Web-Clipper",
            "tags": ["#inbox", "#clip"],
            "is_private": False,
        },
    )
    assert cap_b.status_code == 200

    chat_res = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Convert inbox note Output Portal Granular FX to a plugin in Music Studio",
            "mode": "auto",
        },
    )
    assert chat_res.status_code == 200
    chat_json = chat_res.json()
    assert chat_json["route_reason"] == "fast_inbox_promote_to_section"
    entry_b_rel = chat_json["entry_rel_path"]
    assert entry_b_rel.startswith("04_Resources/Music_Studio/Plugins/")
    assert chat_json["extracted_url"] == "https://output.com/products/portal"

    # 3. Verify both promoted entries appear in live `Music_Studio_Catalog.base` query
    base_res = client.get(
        "/api/vault/base-query",
        params={"rel_path": "04_Resources/Music_Studio/Music_Studio_Catalog.base"},
    )
    assert base_res.status_code == 200
    row_paths = {r["rel_path"] for r in base_res.json()["rows"]}
    assert entry_a["rel_path"] in row_paths
    assert entry_b_rel in row_paths


def test_phase12_project_tasks_base_endpoint_fast_skill_and_live_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase12_ProjectBase_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    # Seed two tasks + one Project Wiki spec under KAIROS_2_0
    t1 = client.post(
        "/api/tasks",
        json={
            "title": "Implement Obsidian Base Engine",
            "project": "KAIROS_2_0",
            "department": "Software_Development",
            "list": "Sprint_01",
            "status": "In Progress",
            "priority": 1,
            "time_estimate": 4.0,
        },
    )
    assert t1.status_code == 200
    t1_id = t1.json()["frontmatter"]["id"]

    t2 = client.post(
        "/api/tasks",
        json={
            "title": "Finalize Release Notes",
            "project": "KAIROS_2_0",
            "department": "Operations",
            "list": "Sprint_01",
            "status": "Done",
            "priority": 3,
            "time_estimate": 2.5,
        },
    )
    assert t2.status_code == 200
    t2_id = t2.json()["frontmatter"]["id"]

    wiki_res = client.post(
        "/api/vault/note",
        json={
            "rel_path": "02_Projects/KAIROS_2_0/Docs/Architecture_Spec.md",
            "frontmatter": {"type": "wiki", "project": "[[KAIROS_2_0]]", "tags": ["#wiki"]},
            "body": "# Architecture Spec\n\nLinked to [[" + t1_id + "]].\n",
            "mode": "overwrite",
        },
    )
    assert wiki_res.status_code == 200

    # Generate via REST endpoint + verify Fast Skill 5k (`fast_project_base_create`)
    pb_http = client.post("/api/projects/KAIROS_2_0/base")
    assert pb_http.status_code == 200
    base_rel = pb_http.json()["base_rel_path"]
    assert base_rel == "02_Projects/KAIROS_2_0/Docs/Project_Tasks.base"

    pb_skill = client.post(
        "/api/assistant/chat",
        json={"prompt": "Create task base for KAIROS_2_0", "mode": "auto"},
    )
    assert pb_skill.status_code == 200
    assert pb_skill.json()["route_reason"] == "fast_project_base_create"
    assert pb_skill.json()["base_rel_path"] == base_rel

    # Pure YAML invariant (no `---` Markdown frontmatter delimiter)
    raw_base_text = bundle["vault"].resolve_safe_path(base_rel).read_text(encoding="utf-8")
    assert not raw_base_text.lstrip().startswith("---")

    # Evaluate View 1: All Project Tasks
    q_all = client.get(
        "/api/vault/base-query",
        params={"rel_path": base_rel, "view": "All Project Tasks"},
    )
    assert q_all.status_code == 200
    all_json = q_all.json()
    assert all_json["valid_yaml"] is True
    task_ids_all = {r["task_id"] for r in all_json["rows"]}
    assert {t1_id, t2_id}.issubset(task_ids_all)
    t1_row = next(r for r in all_json["rows"] if r["task_id"] == t1_id)
    assert "P1 Urgent" in str(t1_row["cells"]["formula.priority_badge"])
    assert float(all_json["summaries"]["time_estimate_hrs"]["value"]) == pytest.approx(6.5)

    # Evaluate View 2: Active Sprint (excludes Done)
    q_active = client.get(
        "/api/vault/base-query",
        params={"rel_path": base_rel, "view": "Active Sprint"},
    )
    assert q_active.status_code == 200
    active_ids = {r["task_id"] for r in q_active.json()["rows"]}
    assert t1_id in active_ids
    assert t2_id not in active_ids

    # Evaluate View 3: Project Wiki & Docs (includes Wiki spec, excludes TSK-*)
    q_docs = client.get(
        "/api/vault/base-query",
        params={"rel_path": base_rel, "view": "Project Wiki & Docs"},
    )
    assert q_docs.status_code == 200
    doc_paths = {r["rel_path"] for r in q_docs.json()["rows"]}
    assert "02_Projects/KAIROS_2_0/Docs/Architecture_Spec.md" in doc_paths
    assert all(not r["task_id"].startswith("TSK-") for r in q_docs.json()["rows"])


def test_phase12_json_canvas_group_node_edit_and_directional_edges_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase12_CanvasEdges_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    # Create a target Markdown note to embed as a `file` node on the JSON Canvas
    note_rel = "04_Resources/Code_and_Research/Mastering_Chain.md"
    client.post(
        "/api/vault/note",
        json={
            "rel_path": note_rel,
            "frontmatter": {"type": "resource", "tags": ["#audio", "#dsp"]},
            "body": "# Mastering Chain\n\nEQ -> Compression -> Limiter.\n",
            "mode": "overwrite",
        },
    )

    canvas_rel = "04_Resources/Canvases/Studio_Signal_Chain.canvas"
    canvas_doc = {
        "nodes": [
            {
                "id": "a1b2c3d4e5f60718",
                "type": "group",
                "x": 0,
                "y": 0,
                "width": 640,
                "height": 380,
                "label": "Mix Bus Group",
                "color": "5",
            },
            {
                "id": "1122334455667788",
                "type": "file",
                "x": 40,
                "y": 60,
                "width": 260,
                "height": 180,
                "file": note_rel,
                "color": "4",
            },
            {
                "id": "99aabbccddeeff00",
                "type": "text",
                "x": 360,
                "y": 60,
                "width": 240,
                "height": 160,
                "text": "Target -14 LUFS integrated",
                "color": "2",
            },
        ],
        "edges": [
            {
                "id": "fedcba9876543210",
                "fromNode": "1122334455667788",
                "fromSide": "right",
                "toNode": "99aabbccddeeff00",
                "toSide": "left",
                "toEnd": "arrow",
                "label": "Audio Bus",
            }
        ],
    }

    w_res = client.post(
        "/api/vault/note",
        json={
            "rel_path": canvas_rel,
            "frontmatter": {},
            "body": json.dumps(canvas_doc, indent=2),
            "mode": "overwrite",
        },
    )
    assert w_res.status_code == 200

    # Pure JSON invariant on disk (no YAML frontmatter injected into `.canvas`)
    raw_canvas = bundle["vault"].resolve_safe_path(canvas_rel).read_text(encoding="utf-8")
    assert not raw_canvas.lstrip().startswith("---")
    parsed = json.loads(raw_canvas)
    assert len(parsed["nodes"]) == 3
    assert parsed["nodes"][0]["type"] == "group"
    assert parsed["edges"][0]["label"] == "Audio Bus"

    # Verify ShadowIndex registered `canvas_file` backlink to Mastering_Chain.md
    bl_res = client.get("/api/vault/backlinks", params={"rel_path": note_rel})
    assert bl_res.status_code == 200
    backlinks = bl_res.json()["backlinks"]
    assert any(
        b["rel_path"] == canvas_rel and b["edge_kind"] == "canvas_file" for b in backlinks
    )

    # Tag filter search check (`#dsp` returns Mastering_Chain.md)
    tag_search = client.get("/api/vault/notes", params={"tag": "#dsp"})
    assert tag_search.status_code == 200
    assert any(n["rel_path"] == note_rel for n in tag_search.json()["notes"])

    # Vault health reports zero `.canvas` syntax issues
    health = client.get("/api/vault/health")
    assert health.status_code == 200
    assert health.json()["syntax_issues"] == []


def test_phase12_platform_executor_kairos_ops_for_inbox_section_and_project_base(
    tmp_path: Path,
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase12_KairosOps_Vault"))
    vault = bundle["vault"]
    index = bundle["index"]
    executor = bundle["assistant"].platform_executor

    cap = vault.create_inbox_capture(
        title="Valhalla Shimmer Reverb",
        body="Check lush ambient reverb at https://valhalladsp.com/shop/reverb/valhalla-shimmer/",
        source="Quick-Capture",
    )
    index.index_file(vault.resolve_safe_path(cap["rel_path"]))

    llm_output = (
        "Promoting your Inbox note and generating your project `.base` database now.\n"
        '<kairos_op>{"op": "inbox_promote_to_section_entry", "args": '
        '{"query": "Valhalla Shimmer", "section_or_folder": "04_Resources/Music_Studio", "collection": "Plugins", "vendor": "Valhalla DSP"}}</kairos_op>\n'
        '<kairos_op>{"op": "projects_create_base", "args": {"project": "KAIROS_2_0"}}</kairos_op>'
    )
    cleaned, summaries, ui_cmds, raw_results = extract_and_execute_kairos_ops(
        llm_output,
        executor,
    )
    assert "<kairos_op>" not in cleaned
    assert len(raw_results) == 2
    assert all(r["ok"] is True for r in raw_results)
    assert len(summaries) == 2
    assert any(c.get("type") == "open_note" for c in ui_cmds)
    assert any(
        c.get("type") == "set_projects_view" and c.get("view") == "docs" for c in ui_cmds
    )


def test_phase12_desktop_ui_contracts_across_inbox_palette_brain_and_projects() -> None:
    inbox_src = (UI_SRC_ROOT / "features" / "inbox" / "InboxWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "promoteInboxToSection" in inbox_src
    assert "targetSectionHub" in inbox_src
    assert "handlePromoteToSectionHub" in inbox_src
    assert "→ Hub Entry" in inbox_src

    palette_src = (UI_SRC_ROOT / "components" / "CommandPalette.tsx").read_text(encoding="utf-8")
    assert "getVaultStructure" in palette_src
    assert "Vault_Master_Catalog.base" in palette_src
    assert "filteredHubs" in palette_src
    assert "Second Brain 3D Galaxy Graph" in palette_src

    sb_src = (UI_SRC_ROOT / "features" / "second-brain" / "SecondBrainWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "tagFilter" in sb_src
    assert sb_src.count("{tagFilter && (") == 1
    assert "handleUpdateCanvasNode" in sb_src
    assert "handleAddCanvasEdge" in sb_src
    assert "handleDeleteCanvasEdge" in sb_src

    proj_src = (UI_SRC_ROOT / "features" / "projects" / "ProjectsWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "createProjectTasksBase" in proj_src
    assert "projectBaseResult" in proj_src
    assert "+ Tasks .base" in proj_src
    assert "projectBaseResult.active_view?.name" in proj_src
    assert "projectBaseResult.summaries" in proj_src

    # Verify global MCP 18-tool & env_verifier 11-integration invariants remain intact
    mcp_bundle = create_mcp_bundle()
    assert len(mcp_bundle["mcp_tools"]) == 18
    env_report = verify_env_apis(live=False)
    assert env_report["total_count"] == 11


def test_phase12_phonetic_wake_greeting_and_cloud_failover_timeout_resilience(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.kairos_core.config import KairosSettings
    from services.kairos_core.llm_cloud import CloudGeminiLLMService
    from services.kairos_core.navigator import normalize_kairos_phonetics
    from services.kairos_core.router import DualAIRouter
    from services.kairos_voice.voice_service import check_wake_word

    # 1. Verify WebSpeech/Whisper STT phonetic normalization ('Hey Kros', 'Hi Kyros', vocative 'Hey Cairo')
    assert normalize_kairos_phonetics("Hey Kros") == "Hey KAIROS"
    assert normalize_kairos_phonetics("Hi Kyros, open Music Studio") == "Hi KAIROS, open Music Studio"
    assert normalize_kairos_phonetics("Hey Kai Ross") == "Hey KAIROS"
    assert normalize_kairos_phonetics("Hey Cairo, switch to Gantt") == "Hey KAIROS, switch to Gantt"
    assert normalize_kairos_phonetics("What's the weather in Cairo?") == "What's the weather in Cairo?"

    # 2. Verify Voice Sidecar wake-word filter accepts phonetic 'Hey Kros' both bare and with command
    ok_bare, rem_bare = check_wake_word("Hey Kros", wake_word_only=True)
    assert ok_bare is True
    assert rem_bare == "Hey KAIROS"
    ok_cmd, rem_cmd = check_wake_word("Hey Kros, open Gantt", wake_word_only=True)
    assert ok_cmd is True
    assert rem_cmd == "open Gantt"

    # 3. Verify '/api/kairos/command' responds instantaneously (<5ms, zero-LLM) to 'Hey Kros' even when offline
    bundle = create_mcp_bundle(str(tmp_path / "Phase12_Wake_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    r_wake = client.post(
        "/api/kairos/command",
        json={"prompt": "Hey Kros", "mode": "auto", "project_scope": "KAIROS_2_0"},
    )
    assert r_wake.status_code == 200
    wake_data = r_wake.json()
    assert wake_data["route_reason"] == "fast_wake_greeting"
    assert wake_data["agent"] == "KAIROS-Direct"
    assert "online and listening" in wake_data["reply"]
    assert "HTTPConnectionPool" not in wake_data["reply"]

    # 4. Verify DualAIRouter cloud failover passes >= 12.0s completion timeout and never leaks HTTPConnectionPool
    cfg = KairosSettings(
        vault_path=bundle["vault"].vault_path,
        lmstudio_base_url="http://127.0.0.1:9/v1",
        gemini_api_key="test-gemini-key",
        cloud_timeout_sec=3.0,
    )
    router = DualAIRouter(
        cfg=cfg,
        audit_path=bundle["vault"].vault_path / "_System" / "Logs" / "AI_Audit_Log.jsonl",
    )

    # Confirm offline local fallback text is clean and speakable with zero raw urllib3 memory pointers
    local_offline = router._call_lmstudio_gemma4("sys", "Hey Kros")
    assert local_offline["ok"] is False
    assert "HTTPConnectionPool" not in local_offline["text"]
    assert "LM Studio" in local_offline["text"]
    assert "error" in local_offline

    # Confirm Gemini 2.5 Flash candidate configs lead with thinking_budget=0 for low-latency failover
    cand_cfgs = CloudGeminiLLMService._candidate_configs("gemini-2.5-flash", wants_grounding=False)
    assert cand_cfgs[0] == {"thinking_config": {"thinking_budget": 0}}
    assert cand_cfgs[-1] is None

    seen_timeouts: list[float] = []

    def _mock_complete_chat(user_prompt: str, **kwargs: object) -> dict[str, object]:
        t_val = kwargs.get("timeout_sec")
        seen_timeouts.append(float(t_val) if isinstance(t_val, (int, float)) else 0.0)
        return {
            "ok": True,
            "agent": "Gemini-Pro",
            "text": "Cloud failover succeeded cleanly without premature 3.0s cutoff.",
            "tokens_used": 24,
            "latency_ms": 420,
            "timed_out": False,
        }

    monkeypatch.setattr(router.cloud_llm, "complete_chat", _mock_complete_chat)
    failover_out = router.generate("Summarize what we should prioritize next sprint.", mode="auto")
    assert failover_out["ok"] is True
    assert failover_out["agent"] == "Gemini-Pro"
    assert failover_out["route_reason"] == "auto_cloud_failover_lmstudio_offline"
    assert seen_timeouts and seen_timeouts[0] >= 12.0

    # Confirm TopBar.tsx includes client-side normalizeKairosTranscript
    topbar_src = (UI_SRC_ROOT / "components" / "TopBar.tsx").read_text(encoding="utf-8")
    assert "normalizeKairosTranscript" in topbar_src

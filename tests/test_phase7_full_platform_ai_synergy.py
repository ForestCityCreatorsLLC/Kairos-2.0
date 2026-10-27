"""Phase 7 Verification Suite: Full-Platform AI Synergy (`PlatformActionExecutor`, `<kairos_op>`, Deictic Context, Vision Privacy & MCP Lock Guard)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

import services.kairos_core.api as api_mod
from services.kairos_core.config import KairosSettings
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.paperclip_crew import PaperclipLockConflictError
import services.kairos_core.tool_registry as tool_reg_mod
from services.kairos_core.vault_engine import parse_markdown_note
from services.kairos_voice.vision_context import VisionContextProcessor
import services.kairos_voice.voice_service as voice_mod


def test_mcp_bundle_kwargs_18_tool_invariant_and_cognitive_telemetry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `create_mcp_bundle(vault_path=..., cfg=...)`, 18 MCP tools, MCP Paperclip lock guard & cognitive telemetry."""
    cfg = KairosSettings(vault_path=tmp_path / "Synergy_MCP_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    assert len(bundle["mcp_tools"]) == 18

    # Verify MCP `projects_update_task` enforces Paperclip checkout locks
    created = bundle["mcp_tools"]["projects_create_task"](
        title="Verify MCP Paperclip Lock Guard",
        project="KAIROS_2_0",
        department="Software_Development",
    )
    tid = created["frontmatter"]["id"]
    bundle["paperclip"].acquire_lock(tid, "CrewAI-Dev")

    with pytest.raises(PaperclipLockConflictError, match="Paperclip Lock Conflict"):
        bundle["mcp_tools"]["projects_update_task"](tid, status="Done", actor="Jaime")

    bundle["paperclip"].release_lock(tid, "CrewAI-Dev")
    updated = bundle["mcp_tools"]["projects_update_task"](tid, status="Done", actor="Jaime")
    assert updated["frontmatter"]["status"] == "Done"

    # Verify `GET /api/voice/cognitive-telemetry` returns `last_cache_hit_ratio` and `headroom_gb` cleanly
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)
    res = client.get("/api/voice/cognitive-telemetry")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "last_cache_hit_ratio" in body["local_kv_stats"]
    assert body["vram_envelope"]["headroom_gb"] >= 4.0
    assert body["vram_envelope"]["dwm_safety_headroom_gb"] == body["vram_envelope"]["headroom_gb"]
    assert body["voice_tools"] == [
        "get_system_telemetry",
        "search_local_notes",
        "execute_workspace_task",
        "delegate_to_gemini",
    ]


def test_deictic_open_task_and_checklist_voice_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify deictic commands ('this task') for checklist add, checklist toggle, time log, and status transition."""
    bundle = create_mcp_bundle(str(tmp_path / "Deictic_Task_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    created = client.post(
        "/api/tasks",
        json={
            "title": "Ship Full Platform AI Co-Pilot",
            "project": "KAIROS_2_0",
            "department": "Software_Development",
            "list": "Sprint_01",
            "priority": 1,
        },
    ).json()
    tid = created["frontmatter"]["id"]

    # 1. Add checklist item to "this task"
    r_add = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Add checklist item Verify full platform synergy to this task",
            "mode": "gemma-4",
            "active_task_id": tid,
        },
    )
    assert r_add.status_code == 200
    assert r_add.json()["route_reason"] == "fast_task_checklist_add"
    raw_after_add = bundle["vault"].find_task_file(tid).read_text(encoding="utf-8")
    assert "- [ ] Verify full platform synergy" in raw_after_add

    # 2. Check off checklist item 1 on "this task"
    r_tog = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Check off checklist item 1 on this task",
            "mode": "gemma-4",
            "active_task_id": tid,
        },
    )
    assert r_tog.status_code == 200
    assert r_tog.json()["route_reason"] == "fast_task_checklist_toggle"
    raw_after_tog = bundle["vault"].find_task_file(tid).read_text(encoding="utf-8")
    assert "- [x] Verify full platform synergy" in raw_after_tog

    # 3. Log hours on "this task"
    r_log = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Log 1.5 hours on this task: Completed end-to-end synergy audit",
            "mode": "gemma-4",
            "active_task_id": tid,
        },
    )
    assert r_log.status_code == 200
    assert r_log.json()["route_reason"] == "fast_task_time_log"
    assert r_log.json()["time_logged_hrs"] == 1.5

    # 4. Mark "this task" Done
    r_done = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Mark this task Done",
            "mode": "gemma-4",
            "active_task_id": tid,
        },
    )
    assert r_done.status_code == 200
    assert r_done.json()["route_reason"] == "fast_status_update"
    fm_done, _ = parse_markdown_note(bundle["vault"].find_task_file(tid).read_text(encoding="utf-8"))
    assert fm_done["status"] == "Done"


def test_task_archive_restore_and_paperclip_force_unlock_by_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify voice/chat Paperclip force-unlock, soft-archive ('Archive this task'), and restore ('Restore latest archived task')."""
    bundle = create_mcp_bundle(str(tmp_path / "Unlock_Archive_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    created = client.post(
        "/api/tasks",
        json={
            "title": "Audit Stale Checkout Recovery",
            "project": "KAIROS_2_0",
            "department": "Software_Development",
            "list": "Sprint_01",
        },
    ).json()
    tid = created["frontmatter"]["id"]

    # Lock task via Paperclip and verify archive is blocked with HTTP 409
    bundle["paperclip"].acquire_lock(tid, "CrewAI-Research")
    r_blocked = client.post(
        "/api/kairos/command",
        json={"prompt": "Archive this task", "mode": "gemma-4", "active_task_id": tid},
    )
    assert r_blocked.status_code == 409

    # Force-unlock "this task" by voice/chat
    r_unlock = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Force unlock this task: Stale agent run cleared by operator",
            "mode": "gemma-4",
            "active_task_id": tid,
        },
    )
    assert r_unlock.status_code == 200
    assert r_unlock.json()["route_reason"] == "fast_paperclip_unlock"
    assert r_unlock.json()["released"] is True
    assert bundle["paperclip"].get_active_lock(tid) is None

    # Soft-archive "this task"
    r_arch = client.post(
        "/api/kairos/command",
        json={"prompt": "Archive this task", "mode": "gemma-4", "active_task_id": tid},
    )
    assert r_arch.status_code == 200
    assert r_arch.json()["route_reason"] == "fast_task_archive"
    assert r_arch.json()["archived_rel_path"].startswith("05_Archives/Tasks/KAIROS_2_0/")
    assert all(t["id"] != tid for t in client.get("/api/tasks").json()["tasks"])

    # Restore latest archived task
    r_rest = client.post(
        "/api/kairos/command",
        json={"prompt": "Restore latest archived task", "mode": "gemma-4"},
    )
    assert r_rest.status_code == 200
    rest_json = r_rest.json()
    assert rest_json["route_reason"] == "fast_task_restore"
    assert rest_json["task_id"] == tid
    assert any(c.get("type") == "open_task_drawer" and c.get("task_id") == tid for c in rest_json["ui_commands"])
    assert any(t["id"] == tid for t in client.get("/api/tasks").json()["tasks"])


def test_deictic_browser_clip_inbox_promote_and_daily_note_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `:8421` -> `:8420` deictic browser clipping, Inbox promotion, and Daily Note append."""
    bundle = create_mcp_bundle(str(tmp_path / "Clip_Promote_Daily_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    core_client = TestClient(api_mod.app)
    voice_client = TestClient(voice_mod.app)

    monkeypatch.setattr(
        tool_reg_mod,
        "safe_fetch_public_text",
        lambda _url, **_kw: (
            "<html><head><title>Three.js WebGPU Spec</title></head>"
            "<body><article><h1>Three.js WebGPU Shaders</h1><p>Real-time node material pipeline.</p></article></body></html>"
        ),
    )

    class _LocalCoreBridgeResponse:
        def __init__(self, status_code: int, payload: Dict[str, Any]) -> None:
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
            self._payload = payload

        def json(self) -> Dict[str, Any]:
            return self._payload

    def _mock_voice_post(url: str, json: Dict[str, Any] | None = None, **_kw: Any) -> Any:
        assert url.endswith("/api/kairos/command")
        resp = core_client.post("/api/kairos/command", json=json or {})
        return _LocalCoreBridgeResponse(resp.status_code, resp.json())

    monkeypatch.setattr(voice_mod.requests, "post", _mock_voice_post)

    # 1. Deictic Browser Clip through `:8421` `/api/voice/utterance` -> `:8420` `/api/kairos/command`
    r_clip = voice_client.post(
        "/api/voice/utterance",
        json={
            "transcript": "Clip this page to Inbox",
            "mode": "gemma-4",
            "active_browser_url": "https://threejs.org/docs/webgpu",
            "active_browser_title": "Three.js WebGPU Guide",
            "synthesize_speech": False,
        },
    )
    assert r_clip.status_code == 200
    core_clip = r_clip.json()["core_response"]
    assert core_clip["route_reason"] == "fast_browser_clip"
    clipped_rel = core_clip["clipped_rel_path"]
    assert clipped_rel.startswith("00_Inbox/")
    assert (bundle["vault"].vault_path / clipped_rel).is_file()

    # 2. Promote latest Inbox note to `KAIROS` -> `Marketing_and_Branding`
    r_prom = core_client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Promote latest inbox note to KAIROS Marketing",
            "mode": "gemma-4",
        },
    )
    assert r_prom.status_code == 200
    prom_json = r_prom.json()
    assert prom_json["route_reason"] == "fast_inbox_promote"
    new_tid = prom_json["created_task_id"]
    task_file = bundle["vault"].find_task_file(new_tid)
    assert "02_Projects/KAIROS/Marketing_and_Branding/" in bundle["vault"].to_rel_path(task_file)
    assert not (bundle["vault"].vault_path / clipped_rel).exists()

    # 3. Append to today's Daily Note
    r_daily = core_client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Append to today's daily note: Phase 7 full platform synergy verified",
            "mode": "gemma-4",
        },
    )
    assert r_daily.status_code == 200
    daily_json = r_daily.json()
    assert daily_json["route_reason"] == "fast_daily_note_append"
    today_rel = f"03_Personal/Calendar/{datetime.now().strftime('%Y-%m-%d')}.md"
    assert daily_json["daily_note_rel_path"] == today_rel
    daily_text = (bundle["vault"].vault_path / today_rel).read_text(encoding="utf-8")
    assert "Phase 7 full platform synergy verified" in daily_text


def test_conversational_llm_kairos_op_execution_and_ui_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify conversational `<kairos_op>{...}</kairos_op>` executes real Vault/Projects/Hermes writes and strips tags."""
    cfg = KairosSettings(vault_path=tmp_path / "KairosOp_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    assistant = bundle["assistant"]

    monkeypatch.setattr(
        assistant.router,
        "generate",
        lambda *_a, **_kw: {
            "text": (
                "I've spun up the P1 Website launch task and stored our WebGPU hero architecture note in Hermes! "
                '<kairos_op>{"op":"projects_create_task","args":{"title":"Build WebGPU Hero Showcase","project":"KAIROS_2_0","department":"Website","list":"Web_Launch","priority":1}}</kairos_op>'
                '<kairos_op>{"op":"hermes_retain_memory","args":{"fact":"Website hero uses zero-copy WebGPU shaders."}}</kairos_op>'
            ),
            "agent": "Gemma-4-Local",
            "route_reason": "local_fast_voice",
            "privacy_locked": False,
            "latency_ms": 84.0,
        },
    )

    out = assistant.chat(
        "Based on our roadmap discussion, spin up the WebGPU hero showcase task and save that shader note in Hermes",
        mode="gemma-4",
        persist_session=False,
    )

    assert "<kairos_op>" not in out["reply"]
    assert "<kairos_op>" not in out["spoken_reply"]
    assert "WebGPU Hero Showcase" not in out["reply"] or "spun up" in out["reply"]

    # Verify real task `.md` created & indexed in SQLite WAL
    tasks = bundle["index"].list_tasks(project="KAIROS_2_0")
    matching = [t for t in tasks if t["title"] == "Build WebGPU Hero Showcase"]
    assert len(matching) == 1
    created_tid = matching[0]["id"]
    assert matching[0]["department"] == "Website"
    assert matching[0]["priority"] == 1
    assert any(c.get("type") == "open_task_drawer" and c.get("task_id") == created_tid for c in out["ui_commands"])

    # Verify Hermes `MEMORY.md` persisted the fact
    mem_text = (cfg.vault_path / "04_Resources" / "Hermes" / "MEMORY.md").read_text(encoding="utf-8")
    assert "Website hero uses zero-copy WebGPU shaders." in mem_text


def test_vision_frame_forwarded_to_router_and_blocked_from_cloud_when_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `1080p` WebP vision frames reach Local Gemma 4 while `image_bytes` is blocked from Cloud when `#private`."""
    cfg = KairosSettings(vault_path=tmp_path / "Vision_Privacy_Vault", gemini_api_key="test-key")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    assistant = bundle["assistant"]
    assistant.vision = VisionContextProcessor(frame_grabber=lambda _src: (None, 1920, 1080))

    bundle["vault"].write_note(
        "03_Personal/Finance/Q4_Tax_Reserve.md",
        {"title": "Q4 Tax Reserve", "tags": ["private"]},
        "Confidential reserve schedule.",
    )

    captured_calls: list[Dict[str, Any]] = []

    def _spy_generate(prompt: str, **kwargs: Any) -> Dict[str, Any]:
        captured_calls.append({"prompt": prompt, **kwargs})
        return {
            "text": "Screen summary ready.",
            "agent": "Gemma-4-Local" if kwargs.get("is_private") else "Gemini-Pro-Cloud",
            "route_reason": "privacy_hard_lock_local" if kwargs.get("is_private") else "cloud_escalation",
            "privacy_locked": bool(kwargs.get("is_private")),
            "latency_ms": 75.0,
        }

    monkeypatch.setattr(assistant.router, "generate", _spy_generate)

    # 1. Public turn: both `image_data_url` and `image_bytes` are passed to `router.generate`
    pub_out = assistant.chat(
        "Look at my screen and summarize the active Kanban board",
        mode="auto",
        persist_session=False,
    )
    assert pub_out["vision_context"]["privacy_locked"] is False
    assert captured_calls[-1]["image_data_url"].startswith("data:image/webp;base64,")
    assert isinstance(captured_calls[-1]["image_bytes"], bytes)
    assert captured_calls[-1]["image_bytes"][:4] == b"RIFF"

    # 2. Private turn (`03_Personal/Finance/`): `image_data_url` reaches local Gemma-4, `image_bytes` is strictly `None`
    priv_out = assistant.chat(
        "Look at my screen and check this balance sheet",
        mode="auto",
        active_note_path="03_Personal/Finance/Q4_Tax_Reserve.md",
        persist_session=False,
    )
    assert priv_out["privacy_locked"] is True
    assert priv_out["vision_context"]["privacy_locked"] is True
    assert captured_calls[-1]["image_data_url"].startswith("data:image/webp;base64,")
    assert captured_calls[-1]["image_bytes"] is None

"""Phase 2 Verification Suite: Dual-AI Privacy Hard-Lock, Paperclip Broker, CrewAI, Hermes Knowledge Retention, Calendar & Voice Sidecar."""

from __future__ import annotations

import array
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from services.kairos_core.config import KairosSettings
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.router import DualAIRouter
from services.kairos_voice.voice_service import (
    app as voice_app,
    apply_raised_cosine_envelope,
    check_wake_word,
    condition_or_wrap_wav,
)


def test_dual_ai_privacy_hard_lock_and_audit_log(tmp_path: Path) -> None:
    audit_file = tmp_path / "_System" / "Logs" / "AI_Audit_Log.jsonl"
    cfg = KairosSettings(vault_path=tmp_path, gemini_api_key="fake-test-key")
    router = DualAIRouter(cfg=cfg, audit_path=audit_file)

    # Even if caller explicitly requests Cloud `gemini`, `03_Personal/Finance/` MUST hard-lock to `gemma-4`
    route_fin = router.select_route(
        "Summarize my tax deductions",
        mode="gemini",
        target_path="03_Personal/Finance/Taxes_2026.md",
    )
    assert route_fin["provider"] == "gemma-4"
    assert route_fin["privacy_locked"] is True

    # `#private` tag also hard-locks to local `gemma-4`
    route_priv = router.select_route("Analyze note #private", mode="hybrid", is_private=True)
    assert route_priv["provider"] == "gemma-4"
    assert route_priv["privacy_locked"] is True

    # Non-private deep research routes to Gemini when key is present
    route_cloud = router.select_route("Deep analysis and research on competitor pricing", mode="auto")
    assert route_cloud["provider"] == "gemini"
    assert route_cloud["privacy_locked"] is False

    router.log_audit(
        agent="Gemma-4",
        route_reason="privacy_hard_lock_local",
        tool="unit_test",
        target="03_Personal/Finance/Taxes_2026.md",
    )
    logs = router.read_recent_audit_logs()
    assert len(logs) == 1
    assert logs[0]["route_reason"] == "privacy_hard_lock_local"


def test_paperclip_collision_guard_crewai_and_calendar_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "MCP_Vault"))
    assert len(bundle["mcp"]._tool_manager.list_tools()) == 18
    vault = bundle["vault"]
    paperclip = bundle["paperclip"]
    crew = bundle["crew"]
    connectors = bundle["connectors"]
    router = bundle["router"]

    # Deterministic mock for LLM generation during unit test
    monkeypatch.setattr(
        router,
        "generate",
        lambda prompt, **kwargs: {
            "ok": True,
            "agent": "Gemma-4",
            "text": "Actionable research deliverable verified.",
            "tokens_used": 42,
            "latency_ms": 5,
            "route_reason": "test_mock",
            "privacy_locked": bool(kwargs.get("is_private")),
        },
    )

    from services.kairos_core.schemas import CreateTaskInput

    created = vault.create_task(CreateTaskInput(title="Evaluate Obsidian Bases Schema"))
    task_id = created["frontmatter"]["id"]

    # Verify Paperclip prevents simultaneous double-checkout on the same task
    paperclip.checkout_task(task_id, agent_name="Agent-A")
    with pytest.raises(RuntimeError, match="Paperclip Lock Conflict"):
        paperclip.checkout_task(task_id, agent_name="Agent-B")
    paperclip.release_task(task_id, status="released")

    # Execute CrewAI workflow via Paperclip -> writes deliverable & transitions task to `Review`
    res = crew.execute_task_with_crew(task_id, crew_name="CrewAI-Research")
    assert res["ok"] is True
    assert (vault.vault_path / res["artifact_rel_path"]).exists()
    updated_task = vault.read_note(created["rel_path"])
    assert updated_task["frontmatter"]["status"] == "Review"

    # Time-block task onto Calendar -> creates `03_Personal/Calendar/EVT-*.md`
    evt = connectors.time_block_task_on_calendar(task_id, "2026-10-26T09:00:00", duration_hrs=1.5)
    assert evt["rel_path"].startswith("03_Personal/Calendar/EVT-20261026-")
    cal_sync = connectors.gcal_sync_events()
    assert cal_sync["event_count"] == 1


def test_voice_sidecar_envelope_and_controls() -> None:
    # Create loud constant PCM samples and verify raised-cosine fade zeroes endpoints cleanly
    raw_samples = array.array("h", [12000] * 2400)
    conditioned = apply_raised_cosine_envelope(raw_samples.tobytes(), sample_rate=24000)
    out_samples = array.array("h")
    out_samples.frombytes(conditioned)
    assert out_samples[0] == 0
    assert abs(out_samples[-1]) < 100
    assert out_samples[len(out_samples) // 2] == 12000

    client = TestClient(voice_app)
    r_play = client.post("/api/voice/play")
    assert r_play.status_code == 200
    assert r_play.json()["status"] == "LISTENING"

    r_hold = client.post("/api/voice/extend-hold")
    assert r_hold.json()["hold_seconds"] >= 2.5

    r_pause = client.post("/api/voice/pause")
    assert r_pause.status_code == 200
    assert r_pause.json()["status"] == "MUTED"


def test_voice_sidecar_dual_engine_wake_word_and_privacy_lock() -> None:
    import base64

    # 1. Verify raw 24kHz PCM wraps cleanly into RIFF WAVE with raised-cosine envelope
    pcm = array.array("h", [8000] * 1200).tobytes()
    wav_bytes = condition_or_wrap_wav(pcm, default_sample_rate=24000)
    assert wav_bytes[:4] == b"RIFF"
    assert b"WAVE" in wav_bytes[:16]

    # 2. Verify wake-word filter (`"Hey Kairos"`)
    ok_amb, _ = check_wake_word("pass me the coffee mug", wake_word_only=True)
    assert ok_amb is False
    ok_wake, stripped = check_wake_word("Hey Kairos, open KAIROS and switch to Gantt", wake_word_only=True)
    assert ok_wake is True
    assert stripped == "open KAIROS and switch to Gantt"

    client = TestClient(voice_app)
    r_cfg = client.post(
        "/api/voice/config",
        json={"hands_free": True, "wake_word_only": True, "neural_tts": True, "tts_voice": "Kore"},
    )
    assert r_cfg.status_code == 200
    assert r_cfg.json()["wake_word_only"] is True

    # Reset wake_word_only back to False for general operation
    client.post("/api/voice/config", json={"wake_word_only": False})

    # 3. Verify Privacy Hard-Lock blocks Cloud STT & Cloud TTS when viewing `03_Personal/Finance/`
    fake_audio_b64 = base64.b64encode(b"WEBM_TEST_AUDIO_BYTES").decode("ascii")
    r_priv_audio = client.post(
        "/api/voice/audio-command",
        json={
            "audio_base64": fake_audio_b64,
            "mime_type": "audio/webm",
            "mode": "gemini",
            "active_note_path": "03_Personal/Finance/Private_Ledger.md",
        },
    )
    assert r_priv_audio.status_code == 200
    pa = r_priv_audio.json()
    assert pa["stt"]["privacy_locked"] is True
    assert pa["stt"]["provider"] in ("local-privacy-shield", "local-whisper")

    r_priv_tts = client.post(
        "/api/voice/tts",
        json={
            "text": "Opened [[03_Personal/Finance/Private_Ledger.md]]",
            "active_note_path": "03_Personal/Finance/Private_Ledger.md",
        },
    )
    assert r_priv_tts.status_code == 200
    pt = r_priv_tts.json()
    assert pt["privacy_locked"] is True
    assert pt["fallback_browser_tts"] is True
    assert "[[" not in pt["clean_text"]


def test_hermes_memory_skill_distillation_and_crew_continuity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Hermes_Vault"))
    vault = bundle["vault"]
    router = bundle["router"]
    crew = bundle["crew"]
    hermes = bundle["hermes"]

    # 1. Verify bounded MEMORY.md and USER.md initialized on disk
    st0 = hermes.get_status()
    assert st0["ok"] is True
    assert (vault.vault_path / "04_Resources/Hermes/MEMORY.md").exists()
    assert (vault.vault_path / "04_Resources/Hermes/USER.md").exists()

    # 2. Verify `#private` local lock strips private bullets when recalling for cloud prompts
    hermes.retain_memory("Always open Projects on the Rollup sub-view first.", target="memory")
    hermes.retain_memory("Confidential private account routing threshold.", target="memory", is_private=True)

    cloud_recall = hermes.recall_context("Projects sub-view", allow_private=False)
    assert "Rollup sub-view first" in cloud_recall["context_text"]
    assert "Confidential private account" not in cloud_recall["context_text"]

    local_recall = hermes.recall_context("Projects sub-view", allow_private=True)
    assert "Confidential private account" in local_recall["context_text"]

    # 3. Execute task with `Hermes-Agent` via Paperclip -> auto-distills reusable `SKL-*.md` skill + updates `MEMORY.md`
    monkeypatch.setattr(
        router,
        "generate",
        lambda prompt, **kwargs: {
            "ok": True,
            "agent": "Gemma-4",
            "text": (
                "TAKEAWAY: Render a red TODAY dateline across Gantt task rows.\n"
                "STEPS:\n- Compute timeline min/max bounds.\n- Position red TODAY marker by elapsed day ratio."
            ),
            "tokens_used": 36,
            "latency_ms": 4,
            "route_reason": "test_mock",
            "privacy_locked": bool(kwargs.get("is_private")),
        },
    )

    from services.kairos_core.schemas import CreateTaskInput

    t_gantt = vault.create_task(
        CreateTaskInput(title="Add Date-Scaled Gantt Timeline & Today Marker", project="KAIROS_2_0")
    )
    tid = t_gantt["frontmatter"]["id"]

    res = crew.execute_task_with_crew(tid, crew_name="Hermes-Agent")
    assert res["ok"] is True
    assert res["hermes_skill_rel_path"].startswith("04_Resources/Hermes/Skills/SKL-")
    assert (vault.vault_path / res["hermes_skill_rel_path"]).exists()

    # 4. Verify distilled skill is automatically recalled on subsequent related queries
    matched = hermes.recall_context("Gantt Timeline Today Marker", project="KAIROS_2_0")
    assert len(matched["matched_skill_ids"]) >= 1
    assert "Hermes Reusable Skill" in matched["context_text"]

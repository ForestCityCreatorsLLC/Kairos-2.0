"""Batch 5 Verification Suite: 1080p WebP Vision, Shielded Voice Tools, Cross-Model Sanitizer & E2E HUD Telemetry."""

from __future__ import annotations

import asyncio
from pathlib import Path
import time
from typing import Any, Dict

from fastapi.testclient import TestClient

from services.kairos_core.config import STATIC_VOICE_SYSTEM_PROMPT, KairosSettings
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.tool_registry import (
    UnifiedVoiceToolRegistry,
    get_vram_envelope_telemetry,
    sanitize_tool_history_for_handoff,
)
from services.kairos_voice.vision_context import VisionContextProcessor
import services.kairos_voice.voice_service as voice_mod


def test_vision_1080p_webp_encode_sla_and_private_cloud_shield() -> None:
    """Verify `<45ms` `1920x1080` WebP screen encoding, index-0 KV preservation, and `#private` cloud vision block."""
    try:
        from PIL import Image  # type: ignore

        sample_img = Image.new("RGB", (1920, 1080), color=(14, 23, 41))
        processor = VisionContextProcessor(frame_grabber=lambda _src: (sample_img, 1920, 1080))
        # Warm up Pillow's WebP encoder once so import overhead isn't measured
        processor.capture_webp_frame("screen")
    except Exception:
        processor = VisionContextProcessor(frame_grabber=lambda _src: (None, 1920, 1080))

    snap = processor.capture_webp_frame("screen")
    assert snap["ok"] is True
    assert snap["width"] == 1920
    assert snap["height"] == 1080
    assert snap["webp_bytes"][:4] == b"RIFF"
    assert b"WEBP" in snap["webp_bytes"][:16]
    assert snap["capture_ms"] < 45.0, f"Expected <45ms WebP capture, got {snap['capture_ms']}ms"

    base_messages = [
        {"role": "system", "content": STATIC_VOICE_SYSTEM_PROMPT},
        {"role": "user", "content": "Hey Kairos, look at my screen and explain this traceback."},
    ]

    local_attached = processor.attach_vision_to_messages(
        base_messages,
        "Hey Kairos, look at my screen and explain this traceback.",
        is_private=True,
        target_provider="gemma-4",
    )
    assert local_attached["attached"] is True
    out_msgs = local_attached["messages"]
    # Static system prompt at index 0 MUST remain untouched for KV prefix cache
    assert out_msgs[0] == {"role": "system", "content": STATIC_VOICE_SYSTEM_PROMPT}
    assert isinstance(out_msgs[-1]["content"], list)
    assert out_msgs[-1]["content"][1]["type"] == "image_url"
    assert out_msgs[-1]["content"][1]["image_url"]["url"].startswith("data:image/webp;base64,")

    # HARD PRIVACY GATE: Cloud vision attachment MUST be blocked when `#private` is active
    cloud_blocked = processor.attach_vision_to_messages(
        base_messages,
        "Hey Kairos, look at my screen while viewing #private ledger.",
        is_private=True,
        target_provider="gemini",
    )
    assert cloud_blocked["attached"] is False
    assert cloud_blocked.get("blocked_cloud_vision") is True
    assert isinstance(cloud_blocked["messages"][-1]["content"], str)


def test_unified_voice_tools_shield_and_cross_model_sanitization(tmp_path: Path) -> None:
    """Verify `cancel_on_interruption=False` `asyncio.shield` execution & cross-model tool history sanitization."""
    cfg = KairosSettings(vault_path=tmp_path / "Canopy_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    registry = UnifiedVoiceToolRegistry(
        vault=bundle["vault"],
        index=bundle["index"],
        paperclip=bundle["paperclip"],
        cfg=cfg,
    )

    tool_names = [t.name for t in registry.schema.standard_tools]
    assert tool_names == [
        "get_system_telemetry",
        "search_local_notes",
        "execute_workspace_task",
        "delegate_to_gemini",
    ]
    assert all(t.cancel_on_interruption is False for t in registry.schema.standard_tools)

    # Simulate an outer voice turn task being cancelled mid-flight by user barge-in while a shielded tool writes
    completed_flag = {"done": False}

    def slow_shielded_handler(title: str = "Shielded Write") -> Dict[str, Any]:
        time.sleep(0.06)
        completed_flag["done"] = True
        return {"ok": True, "title": title}

    registry.register_handler("shielded_op", slow_shielded_handler)

    async def _run_shield_scenario() -> None:
        caller_task = asyncio.create_task(
            registry.execute_tool("shielded_op", {"title": "Atomic Vault Commit"})
        )
        await asyncio.sleep(0.015)
        caller_task.cancel()
        try:
            await caller_task
        except asyncio.CancelledError:
            pass
        # Give the shielded worker thread time to finish its atomic commit
        await asyncio.sleep(0.08)

    asyncio.run(_run_shield_scenario())
    assert completed_flag["done"] is True

    # Verify cross-model OpenAI `tool_calls` + `role="tool"` + Gemini `functionCall` sanitization
    mixed_history = [
        {"role": "system", "content": STATIC_VOICE_SYSTEM_PROMPT},
        {"role": "user", "content": "Search my notes for sprint goals"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {"name": "search_local_notes", "arguments": '{"query": "sprint goals"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_abc123",
            "name": "search_local_notes",
            "content": '{"count": 2}',
        },
        {
            "role": "model",
            "parts": [
                {"functionCall": {"name": "get_system_telemetry", "args": {}}},
                {"functionResponse": {"name": "get_system_telemetry", "response": {"within_vram_ceiling": True}}},
            ],
        },
    ]

    sanitized = sanitize_tool_history_for_handoff(mixed_history, target_provider="gemma-4")
    assert sanitized[0] == {"role": "system", "content": STATIC_VOICE_SYSTEM_PROMPT}
    assert all(m["role"] in ("system", "user", "assistant") for m in sanitized)
    assert all("tool_calls" not in m and "parts" not in m for m in sanitized)
    # Paired `call_abc123` output was folded into the assistant turn without duplicating a second tool message
    assert len(sanitized) == 4
    assert "search_local_notes" in sanitized[2]["content"]
    assert '{"count": 2}' in sanitized[2]["content"]


def test_end_to_end_voice_telemetry_barge_in_and_assistant_think_demux(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Verify `:8421` VRAM/barge-in telemetry (`<=11.86 GB`, `<80ms`) & `KairosAssistant` `<think>` demuxing."""
    vram = get_vram_envelope_telemetry()
    assert vram["active_resident_vram_gb"] <= 11.86
    assert vram["within_vram_ceiling"] is True

    voice_client = TestClient(voice_mod.app)
    tel_res = voice_client.get("/api/voice/telemetry")
    assert tel_res.status_code == 200
    tel_json = tel_res.json()
    assert tel_json["ok"] is True
    assert tel_json["vram_telemetry"]["within_vram_ceiling"] is True

    # Simulate thinking-aloud VAD sensitivity (`0.35`) followed by `<80ms` operator barge-in
    voice_mod.vad_controller.set_thinking_aloud_vad_sensitivity(True)
    assert voice_mod.vad_controller.current_threshold == 0.35

    barge_res = voice_client.post("/api/voice/barge-in")
    assert barge_res.status_code == 200
    barge_json = barge_res.json()
    assert barge_json["barge_in"]["interrupted"] is True
    assert barge_json["barge_in"]["flush_latency_ms"] < 80.0
    assert barge_json["vad_threshold"] == 0.50

    # Verify `KairosAssistant.chat()` strips `<think>...</think>` into `mutter_clauses` while preserving `<ui_nav>`
    cfg = KairosSettings(vault_path=tmp_path / "Assistant_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    assistant = bundle["assistant"]

    monkeypatch.setattr(
        assistant.router,
        "generate",
        lambda *_a, **_kw: {
            "text": (
                "<think>Checking the latest NFL highlights query and building browser navigation tag.</think>"
                "Pulling up Cleveland Browns highlights on YouTube right now! "
                '<ui_nav>{"type":"browser_navigate","url":"https://www.youtube.com/results?search_query=Cleveland+Browns+highlights","title":"▶ YouTube: Cleveland Browns highlights"}</ui_nav>'
            ),
            "agent": "Gemma-4-Local",
            "route_reason": "local_fast_voice",
            "privacy_locked": False,
            "latency_ms": 92.4,
        },
    )

    chat_out = assistant.chat(
        "Explain the Browns game breakdown",
        mode="gemma-4",
        persist_session=False,
    )
    assert "<think>" not in chat_out["reply"]
    assert "<think>" not in chat_out["spoken_reply"]
    assert len(chat_out["mutter_clauses"]) == 1
    assert "NFL highlights" in chat_out["mutter_clauses"][0]
    assert any(cmd.get("type") == "browser_navigate" for cmd in chat_out["ui_commands"])

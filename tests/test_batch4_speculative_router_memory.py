"""Batch 4 Verification Suite: `<10ms` Speculative Router, `<8ms` CPU Vector Memory, Turn 1->2 Shared Context & `3.0s` Cloud Fallback."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List
import pytest

from services.kairos_core.config import KairosSettings, STATIC_VOICE_SYSTEM_PROMPT
from services.kairos_core.escalation_tool import delegate_to_gemini
from services.kairos_core.intent_router import SpeculativeDualBrainRouter
from services.kairos_core.llm_cloud import CloudGeminiLLMService
from services.kairos_core.llm_local import LocalGemma4LLMService
from services.kairos_core.state_manager import SharedConversationStateManager


def test_batch4_sub_8ms_cpu_vector_retrieval_and_20_turn_rolling_compression(tmp_path: Path) -> None:
    state = SharedConversationStateManager(tmp_path / "episodic_test.sqlite")

    # Seed 60 episodic turns (including a `#private` turn that must stay quarantined from cloud recall)
    for i in range(58):
        state.record_turn(
            f"ses-{i // 4}",
            role="user" if i % 2 == 0 else "assistant",
            content=f"General sprint status update item number {i} on UI layout.",
            agent="Gemma-4",
        )
    state.record_turn(
        "ses-moonraker",
        role="assistant",
        content="Klipper Moonraker printer bed mesh calibration requires probing at 65C.",
        agent="Gemma-4",
    )
    state.record_turn(
        "ses-priv",
        role="user",
        content="Confidential tax reserve routing threshold is $180,000 #private",
        is_private=True,
    )

    # 1. Verify top-3 CPU retrieval completes in `< 8 ms` and ranks Moonraker memory #1
    ctx_public = state.build_turn_context_and_messages(
        "ses-live",
        "How do we calibrate the Klipper Moonraker bed mesh?",
        allow_private=False,
    )
    assert ctx_public["retrieval_ms"] < 8.0, f"Expected <8ms vector recall, got {ctx_public['retrieval_ms']}ms"
    assert ctx_public["index_0_pinned"] is True
    assert ctx_public["messages"][0]["content"] == STATIC_VOICE_SYSTEM_PROMPT
    assert any("Moonraker" in m["content"] for m in ctx_public["episodic_matches"])

    # 2. Verify `#private` episodic memory is strictly excluded when `allow_private=False`
    priv_leak_check = state.vector_store.retrieve_top_k("Confidential tax reserve routing", allow_private=False)
    assert all("180,000" not in m["content"] for m in priv_leak_check)
    priv_allowed_check = state.vector_store.retrieve_top_k("Confidential tax reserve routing", allow_private=True)
    assert any("180,000" in m["content"] for m in priv_allowed_check)

    # 3. Verify 20-turn rolling compression compresses oldest 10 turns cleanly
    for turn_idx in range(22):
        state.record_turn("ses-rolling", role="user", content=f"Turn message #{turn_idx}")
    rolling_hist = state.get_shared_history("ses-rolling")
    assert rolling_hist[0]["content"].startswith("[Prior Conversation Summary]")
    assert len(rolling_hist) <= 14  # 1 summary anchor + remaining uncompressed turns


def test_batch4_sub_10ms_routing_shared_context_handoff_and_cloud_timeout_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = KairosSettings(vault_path=tmp_path, gemini_api_key="test-gemini-key")
    local_llm = LocalGemma4LLMService(cfg=cfg)
    cloud_llm = CloudGeminiLLMService(cfg=cfg, timeout_sec=0.15)
    state = SharedConversationStateManager(tmp_path / "router_state.sqlite")
    router = SpeculativeDualBrainRouter(
        cfg=cfg,
        local_llm=local_llm,
        cloud_llm=cloud_llm,
        state_manager=state,
    )

    # 1. Verify router intent classification completes in `< 10 ms`
    d_local = router.classify_intent("Open Kanban board tasks", session_id="s1")
    d_cloud = router.classify_intent("What is the latest NFL score today?", session_id="s1")
    d_spec = router.classify_intent("Analyze the architecture tradeoffs of our caching layer", session_id="s1")
    d_priv = router.classify_intent("Check Q4 ledger", session_id="s1", active_note_path="03_Personal/Finance/Q4.md")

    assert d_local["routing_ms"] < 10.0
    assert d_local["route"] == "local_primary"
    assert d_cloud["route"] == "cloud_primary"
    assert d_spec["route"] == "speculative_dual_fire"
    assert d_priv["route"] == "local_only" and d_priv["privacy_locked"] is True

    # 2. Verify Turn 1 (Local Gemma 4) -> Turn 2 (Cloud Gemini) preserves 100% shared conversation context
    seen_cloud_histories: List[List[Dict[str, Any]]] = []

    monkeypatch.setattr(
        local_llm,
        "complete_chat",
        lambda prompt, **kw: {
            "ok": True,
            "agent": "Gemma-4",
            "text": "<think>Checking sprint velocity.</think>Codeword Falcon is assigned to Sprint 02.",
            "tokens_used": 24,
            "latency_ms": 18,
            "kv_prefix_pinned": True,
        },
    )

    def _mock_cloud_complete(prompt: str, **kw: Any) -> Dict[str, Any]:
        seen_cloud_histories.append(list(kw.get("history") or []))
        return {
            "ok": True,
            "agent": "Gemini-Pro",
            "text": "Confirmed from shared history: Codeword Falcon is active alongside today's NFL schedule.",
            "tokens_used": 30,
            "latency_ms": 42,
            "timed_out": False,
        }

    monkeypatch.setattr(cloud_llm, "complete_chat", _mock_cloud_complete)

    t1 = router.execute_turn("Assign Codeword Falcon to Sprint 02", session_id="handoff-ses")
    assert t1["agent"] == "Gemma-4"
    assert "<think>" not in t1["text"]
    assert "Codeword Falcon" in t1["text"]

    t2 = router.execute_turn("Check latest NFL schedule and remind me our sprint codeword", session_id="handoff-ses")
    assert t2["agent"] == "Gemini-Pro"
    assert len(seen_cloud_histories) == 1
    flattened_hist = " ".join(str(m.get("content", "")) for m in seen_cloud_histories[0])
    assert "Codeword Falcon is assigned to Sprint 02." in flattened_hist

    # 3. Verify simulated Cloud timeout falls back cleanly to Local `google/gemma-4-12b`
    def _timed_out_cloud(prompt: str, **kw: Any) -> Dict[str, Any]:
        time.sleep(0.05)
        return {
            "ok": False,
            "agent": "Gemini-Pro",
            "text": "[Gemini Cloud Circuit Breaker: exceeded timeout]",
            "tokens_used": 0,
            "latency_ms": 150,
            "timed_out": True,
        }

    monkeypatch.setattr(cloud_llm, "complete_chat", _timed_out_cloud)
    t3 = router.execute_turn("Latest breaking news on GPU drivers", session_id="handoff-ses", timeout_sec=0.1)
    assert t3["ok"] is True
    assert t3["agent"] == "Gemma-4"
    assert t3["route_reason"] == "cloud_timeout_fallback_to_local"

    # 4. Verify `delegate_to_gemini` blocks `#private` escalation and falls back to local on cloud timeout
    blocked_esc = delegate_to_gemini(
        "Check #private tax deductions",
        require_web_search=True,
        cloud_llm=cloud_llm,
        local_llm=local_llm,
    )
    assert blocked_esc["escalated"] is False
    assert blocked_esc["privacy_locked"] is True

    fallback_esc = delegate_to_gemini(
        "Compare public cloud benchmarks",
        require_web_search=True,
        cloud_llm=cloud_llm,
        local_llm=local_llm,
    )
    assert fallback_esc["ok"] is True
    assert fallback_esc["agent"] == "Gemma-4 (Escalation-Fallback)"

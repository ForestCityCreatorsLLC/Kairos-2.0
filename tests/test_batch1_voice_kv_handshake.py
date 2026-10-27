"""Batch 1 Verification Suite: Static KV Prefix Pinning, Warmed TTFT (<150ms), Streaming & Cloud Circuit Breaker."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List
import pytest

from services.kairos_core.config import KairosSettings, STATIC_VOICE_SYSTEM_PROMPT
from services.kairos_core.llm_cloud import CloudCircuitBreakerTimeout, CloudGeminiLLMService
from services.kairos_core.llm_local import LocalGemma4LLMService, build_kv_pinned_messages


def test_batch1_static_system_prompt_prefix_immutability_and_tail_injection() -> None:
    history = [
        {"role": "user", "content": "What tasks are in Sprint 01?"},
        {"role": "assistant", "content": "You have 3 active tasks in Sprint 01."},
    ]
    msgs_turn1 = build_kv_pinned_messages(
        "Summarize the blockers.",
        history=history,
        dynamic_tail_context="Episodic Recall #1: TSK-001 waiting on API schema.",
        persona_directive="Project Director (DEFAULT tone)",
    )
    msgs_turn2 = build_kv_pinned_messages(
        "Now switch focus to marketing.",
        history=history + [
            {"role": "user", "content": "Summarize the blockers."},
            {"role": "assistant", "content": "TSK-001 is waiting on API schema."},
        ],
        dynamic_tail_context="Episodic Recall #2: Hoodie campaign launches Friday.",
        persona_directive="Brand & Merch Director (CODE_RED tone)",
    )

    # Index 0 MUST be byte-for-byte identical across turns regardless of RAG or Persona changes
    assert msgs_turn1[0] == {"role": "system", "content": STATIC_VOICE_SYSTEM_PROMPT}
    assert msgs_turn2[0] == {"role": "system", "content": STATIC_VOICE_SYSTEM_PROMPT}
    assert msgs_turn1[0] == msgs_turn2[0]

    # Rolling prefix turns 1..2 remain untouched; dynamic context only appears in the final user message
    assert msgs_turn1[1:3] == msgs_turn2[1:3]
    assert "Episodic Recall #2" in msgs_turn2[-1]["content"]
    assert "Episodic Recall #2" not in msgs_turn2[0]["content"]


def test_batch1_lm_studio_kv_warmup_and_streaming_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = KairosSettings(
        vault_path=tmp_path,
        lmstudio_base_url="http://127.0.0.1:1234/v1",
        lmstudio_model="google/gemma-4-12b",
    )
    local_svc = LocalGemma4LLMService(cfg=cfg)
    captured_payloads: List[Dict[str, Any]] = []

    class _FakeResp:
        status_code = 200
        ok = True

        def __init__(self, streaming: bool = False) -> None:
            self._streaming = streaming

        def raise_for_status(self) -> None:
            return None

        def json(self) -> Dict[str, Any]:
            return {
                "choices": [{"message": {"content": "Ready."}}],
                "usage": {"total_tokens": 12},
            }

        def iter_lines(self, decode_unicode: bool = True) -> Iterator[str]:
            yield 'data: {"choices":[{"delta":{"content":"<think>Quick check.</think>"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"All systems nominal."}}]}'
            yield "data: [DONE]"

    def _fake_post(url: str, json: Dict[str, Any], **kwargs: Any) -> _FakeResp:
        captured_payloads.append(json)
        return _FakeResp(streaming=bool(kwargs.get("stream")))

    monkeypatch.setattr("services.kairos_core.llm_local.requests.post", _fake_post)

    warmup = local_svc.verify_lm_studio_kv_cache()
    assert warmup["ok"] is True
    assert warmup["index_0_pinned"] is True
    assert warmup["warmed_ttft_ms"] < 150.0
    assert warmup["meets_150ms_sla"] is True
    assert captured_payloads[0]["messages"][0]["content"] == STATIC_VOICE_SYSTEM_PROMPT

    async def _collect_stream() -> List[str]:
        out: List[str] = []
        async for chunk in local_svc.astream_chat("Status check"):
            out.append(chunk)
        return out

    streamed = asyncio.run(_collect_stream())
    assert streamed == ["<think>Quick check.</think>", "All systems nominal."]
    assert local_svc.last_ttft_ms < 150.0


def test_batch1_cloud_gemini_streaming_and_timeout_circuit_breaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = KairosSettings(vault_path=tmp_path, gemini_api_key="test-gemini-key")
    cloud_svc = CloudGeminiLLMService(cfg=cfg, timeout_sec=0.15)

    # 1. Verify streaming token emission
    monkeypatch.setattr(
        cloud_svc,
        "stream_chat",
        lambda prompt, **kw: iter(["Grounded ", "answer ", "ready."]),
    )

    async def _read_cloud_stream() -> str:
        parts: List[str] = []
        async for ch in cloud_svc.astream_chat("Latest NFL standings"):
            parts.append(ch)
        return "".join(parts)

    assert asyncio.run(_read_cloud_stream()) == "Grounded answer ready."

    # 2. Verify circuit breaker trips cleanly when cloud stalls past timeout_sec
    def _stalled_stream(prompt: str, **kw: Any) -> Iterator[str]:
        time.sleep(0.45)
        yield "Too late"

    monkeypatch.setattr(cloud_svc, "stream_chat", _stalled_stream)

    async def _expect_breaker() -> None:
        async for _ in cloud_svc.astream_chat("Stalled request", timeout_sec=0.12):
            pass

    with pytest.raises(CloudCircuitBreakerTimeout):
        asyncio.run(_expect_breaker())

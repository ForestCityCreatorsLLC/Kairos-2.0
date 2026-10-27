"""Batch 3 Verification Suite: `TrainOfThoughtVerbalizer` (`<500ms` suppression, `>500ms` mutter, `550ms` watchdog & split tags)."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator, List, Tuple

from services.kairos_voice.thought_verbalizer import (
    TrainOfThoughtVerbalizer,
    VerbalizerEvent,
    extract_trailing_partial_think_tag,
)


def test_batch3_partial_think_tag_carryover_prevents_delimiter_leakage() -> None:
    head1, carry1 = extract_trailing_partial_think_tag("Hello <thi")
    assert head1 == "Hello "
    assert carry1 == "<thi"

    head2, carry2 = extract_trailing_partial_think_tag("Checking schema</thin")
    assert head2 == "Checking schema"
    assert carry2 == "</thin"

    async def _split_tag_stream() -> AsyncGenerator[str, None]:
        # Split `<think>` and `</think>` across chunk boundaries in < 200ms
        yield "<thi"
        await asyncio.sleep(0.03)
        yield "nk>Checking how the Kanban board maps columns right now."
        await asyncio.sleep(0.03)
        yield "</th"
        await asyncio.sleep(0.03)
        yield "ink>Sprint 01 has four tasks Done."

    async def _run() -> List[VerbalizerEvent]:
        verb = TrainOfThoughtVerbalizer(lag_threshold_sec=0.50, prefill_watchdog_sec=0.55)
        out: List[VerbalizerEvent] = []
        async for ev in verb.process_token_stream(_split_tag_stream()):
            if ev.kind == "text":
                out.append(ev)
        return out

    events = asyncio.run(_run())
    # Fast ~90ms `<think>` stream (<500ms): MUST emit 0 `[mutter]` frames and 0 leaked `<think>` fragments!
    mutter_events = [e for e in events if e.prosody_mode == "mutter" or "[mutter]" in e.text]
    assert mutter_events == []
    combined_answer = "".join(e.text for e in events)
    assert "<think>" not in combined_answer and "</think>" not in combined_answer
    assert "Sprint 01 has four tasks Done." in combined_answer


def test_batch3_prolonged_think_block_emits_distilled_mutter_then_normal_answer() -> None:
    mutter_toggles: List[bool] = []

    async def _slow_deliberation_stream() -> AsyncGenerator[str, None]:
        # Immediately send `<think>` (<50ms so prefill watchdog cancels cleanly)
        yield "<think>"
        await asyncio.sleep(0.28)
        yield "Need to `inspect` ** vault_index.sqlite ** for blocked tasks. "
        await asyncio.sleep(0.32)  # Total elapsed ~600ms (>= 500ms lag_threshold_sec)
        yield "Tracing dependency chain across Sprint 01 tasks right now. "
        await asyncio.sleep(0.15)
        yield "</think>Task TSK-20261024-009 is ready for review."

    async def _run() -> List[VerbalizerEvent]:
        verb = TrainOfThoughtVerbalizer(
            lag_threshold_sec=0.50,
            prefill_watchdog_sec=0.55,
            thought_cadence_sec=3.20,
            on_mutter_state_change=mutter_toggles.append,
        )
        out: List[VerbalizerEvent] = []
        async for ev in verb.process_token_stream(_slow_deliberation_stream()):
            if ev.kind == "text":
                out.append(ev)
        return out

    events = asyncio.run(_run())
    mutter_frames = [e for e in events if e.prosody_mode == "mutter"]
    normal_frames = [e for e in events if e.prosody_mode == "normal"]

    assert len(mutter_frames) >= 1
    assert mutter_frames[0].text.startswith("[mutter] ")
    # Markdown symbols stripped from spoken thought clause
    assert "`" not in mutter_frames[0].text and "*" not in mutter_frames[0].text

    assert len(normal_frames) == 1
    assert normal_frames[0].text.startswith("[normal] ")
    assert "Task TSK-20261024-009 is ready for review." in normal_frames[0].text
    assert True in mutter_toggles and mutter_toggles[-1] is False


def test_batch3_prefill_stall_fires_watchdog_at_550ms() -> None:
    async def _stalled_prefill_stream() -> AsyncGenerator[str, None]:
        # Simulate 650ms GPU prompt prefill delay before Token #1 arrives
        await asyncio.sleep(0.65)
        yield "Context loaded; all metrics verified."

    async def _run() -> Tuple[float, List[VerbalizerEvent]]:
        verb = TrainOfThoughtVerbalizer(lag_threshold_sec=0.50, prefill_watchdog_sec=0.55)
        t0 = time.monotonic()
        watchdog_elapsed = 0.0
        collected: List[VerbalizerEvent] = []
        async for ev in verb.process_token_stream(_stalled_prefill_stream()):
            if ev.kind == "text":
                if ev.prosody_mode == "mutter" and watchdog_elapsed == 0.0:
                    watchdog_elapsed = time.monotonic() - t0
                collected.append(ev)
        return watchdog_elapsed, collected

    fired_at_sec, events = asyncio.run(_run())
    # Watchdog fires at 550ms (+/- 55ms OS scheduler tolerance on Windows)
    assert 0.50 <= fired_at_sec <= 0.62, f"Expected ~0.55s watchdog fire, got {fired_at_sec:.3f}s"
    assert events[0].prosody_mode == "mutter"
    assert "[mutter] Scanning through the context window..." in events[0].text
    # Subsequent non-think answer automatically restores `[normal]` prosody!
    assert events[1].prosody_mode == "normal"
    assert events[1].text.startswith("[normal] ")

"""Cognitive Stream Demuxer (`services/kairos_voice/thought_verbalizer.py`).

Demultiplexes `<think>...</think>` deliberation tokens from Local `Gemma 4 12B` and Cloud `Gemini`:
1. Reassembles split `<think>` / `</think>` delimiters across arbitrary streaming chunk boundaries (`_tag_carryover`).
2. Silently suppresses `<think>` tokens if deliberation completes under `lag_threshold_sec` (`0.50s`).
3. Fires an async `_prefill_lag_watchdog` at `prefill_watchdog_sec` (`0.55s`) if Token #1 stalls during heavy context prefill.
4. Distills conversational `[mutter]` status clauses (`15–95` chars) every `thought_cadence_sec` (`3.20s`) during prolonged `<think>`, then restores `[normal]` prosody for the final answer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
import time
from typing import AsyncGenerator, AsyncIterable, Callable, List, Optional, Tuple


@dataclass
class VerbalizerEvent:
    kind: str  # "text" | "turn_start" | "turn_end" | "interrupted"
    text: str = ""
    prosody_mode: str = "normal"  # "mutter" | "normal"


def extract_trailing_partial_think_tag(text: str) -> Tuple[str, str]:
    """Split off any trailing prefix of `<think>` or `</think>` at the end of a streaming chunk.

    Returns `(safe_head, carryover_suffix)` with zero risk of double-truncation.
    """
    if not text or "<" not in text[-8:]:
        return text, ""
    best_len = 0
    best_suffix = ""
    for tag in ("</think>", "<think>"):
        max_check = min(len(text), len(tag) - 1)
        for length in range(max_check, 0, -1):
            candidate = tag[:length]
            if text.endswith(candidate) and length > best_len:
                best_len = length
                best_suffix = candidate
                break
    if best_len > 0:
        return text[:-best_len], best_suffix
    return text, ""


class TrainOfThoughtVerbalizer:
    """Async cognitive stream demultiplexer for full-duplex `[mutter]` / `[normal]` voice synthesis."""

    def __init__(
        self,
        lag_threshold_sec: float = 0.50,
        prefill_watchdog_sec: float = 0.55,
        thought_cadence_sec: float = 3.20,
        on_mutter_state_change: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self.lag_threshold_sec = float(lag_threshold_sec)
        self.prefill_watchdog_sec = float(prefill_watchdog_sec)
        self.thought_cadence_sec = float(thought_cadence_sec)
        self._on_mutter_state_change = on_mutter_state_change

        self._in_think_block: bool = False
        self._turn_start_time: float = 0.0
        self._last_spoken_thought_time: Optional[float] = None
        self._thought_buffer: str = ""
        self._tag_carryover: str = ""
        self._first_token_received: bool = False
        self._emitted_mutter_in_turn: bool = False
        self._prefill_watchdog_task: Optional[asyncio.Task[None]] = None
        self._out_queue: Optional[asyncio.Queue[Optional[VerbalizerEvent]]] = None

    def _notify_mutter_state(self, is_mutter: bool) -> None:
        if self._on_mutter_state_change is not None:
            try:
                self._on_mutter_state_change(is_mutter)
            except Exception:
                pass

    def cancel_watchdog(self) -> None:
        if self._prefill_watchdog_task and not self._prefill_watchdog_task.done():
            self._prefill_watchdog_task.cancel()
        self._prefill_watchdog_task = None

    def reset_state(self) -> None:
        self.cancel_watchdog()
        self._in_think_block = False
        self._thought_buffer = ""
        self._tag_carryover = ""
        self._first_token_received = False
        self._last_spoken_thought_time = None
        if self._emitted_mutter_in_turn:
            self._emitted_mutter_in_turn = False
            self._notify_mutter_state(False)

    @staticmethod
    def _clean_thought_clause(raw_thought: str) -> Optional[str]:
        """Extract a clean, natural conversational status clause (`15..95` chars) from raw `<think>` tokens."""
        cleaned = re.sub(r"[`*_#\[\]{}()<>~|]", "", raw_thought or "")
        cleaned = re.sub(
            r"^(?:The user is asking|Need to|Checking|Let us see,?|Let's see,?|Okay,?|First,?)\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        match = re.search(r"([A-Z0-9][^.!?,\n]{15,95}[.!?])", cleaned)
        if match:
            clause = match.group(1).strip()
            return f"[mutter] {clause} "
        if len(cleaned) >= 24:
            fallback = cleaned[:80].rsplit(" ", 1)[0].strip(" ,;:-")
            if len(fallback) >= 15:
                return f"[mutter] {fallback}... "
        return None

    async def _prefill_lag_watchdog(self) -> None:
        """Emit a sub-vocal `[mutter]` bridge frame if GPU/Cloud prefill stalls past `550ms` before Token #1."""
        try:
            await asyncio.sleep(self.prefill_watchdog_sec)
            if not self._first_token_received and self._out_queue is not None:
                self._last_spoken_thought_time = time.monotonic()
                self._emitted_mutter_in_turn = True
                self._notify_mutter_state(True)
                await self._out_queue.put(
                    VerbalizerEvent(
                        kind="text",
                        text="[mutter] Scanning through the context window... ",
                        prosody_mode="mutter",
                    )
                )
        except asyncio.CancelledError:
            pass

    async def _emit_text(self, text: str, prosody_mode: str = "normal") -> None:
        if not text or self._out_queue is None:
            return
        if prosody_mode == "mutter":
            self._emitted_mutter_in_turn = True
            self._notify_mutter_state(True)
        else:
            if self._emitted_mutter_in_turn:
                self._emitted_mutter_in_turn = False
                self._notify_mutter_state(False)
                if not text.lstrip().startswith("[normal]"):
                    text = f"[normal] {text}"
        await self._out_queue.put(VerbalizerEvent(kind="text", text=text, prosody_mode=prosody_mode))

    async def _ingest_token_chunk(self, raw_chunk: str) -> None:
        self._first_token_received = True
        self.cancel_watchdog()

        combined = self._tag_carryover + (raw_chunk or "")
        self._tag_carryover = ""
        text, carryover = extract_trailing_partial_think_tag(combined)
        self._tag_carryover = carryover

        if not text:
            return

        # Process `<think>` / `</think>` transitions iteratively in case multiple tags appear in one chunk
        cursor = text
        while cursor:
            if not self._in_think_block:
                if "<think>" in cursor:
                    pre_think, post_open = cursor.split("<think>", 1)
                    if pre_think.strip():
                        await self._emit_text(pre_think, prosody_mode="normal")
                    self._in_think_block = True
                    cursor = post_open
                    continue
                # Regular answer text outside `<think>`
                await self._emit_text(cursor, prosody_mode="normal")
                break
            else:
                if "</think>" in cursor:
                    thought_part, post_close = cursor.split("</think>", 1)
                    self._thought_buffer += thought_part
                    self._in_think_block = False
                    self._thought_buffer = ""
                    if post_close.strip():
                        # Explicitly stamp `[normal] ` upon exiting `<think>`
                        self._emitted_mutter_in_turn = False
                        self._notify_mutter_state(False)
                        await self._out_queue.put(  # type: ignore[union-attr]
                            VerbalizerEvent(
                                kind="text",
                                text=f"[normal] {post_close}",
                                prosody_mode="normal",
                            )
                        )
                    cursor = ""
                    break

                # Still inside `<think>` block
                self._thought_buffer += cursor
                now = time.monotonic()
                elapsed_total = now - self._turn_start_time
                cadence_ready = (
                    self._last_spoken_thought_time is None
                    or (now - self._last_spoken_thought_time) >= self.thought_cadence_sec
                )
                if (
                    elapsed_total >= self.lag_threshold_sec
                    and cadence_ready
                    and len(self._thought_buffer) >= 40
                ):
                    spoken_clause = self._clean_thought_clause(self._thought_buffer)
                    if spoken_clause:
                        await self._emit_text(spoken_clause, prosody_mode="mutter")
                        self._last_spoken_thought_time = now
                        self._thought_buffer = ""
                break

    async def process_token_stream(
        self,
        token_stream: AsyncIterable[str],
        *,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncGenerator[VerbalizerEvent, None]:
        """Consume an async token stream and yield `[mutter]` / `[normal]` `VerbalizerEvent` frames."""
        self.reset_state()
        q: asyncio.Queue[Optional[VerbalizerEvent]] = asyncio.Queue()
        self._out_queue = q
        self._turn_start_time = time.monotonic()
        self._prefill_watchdog_task = asyncio.create_task(self._prefill_lag_watchdog())

        await q.put(VerbalizerEvent(kind="turn_start"))

        async def _driver() -> None:
            try:
                async for chunk in token_stream:
                    if cancel_event is not None and cancel_event.is_set():
                        self.reset_state()
                        await q.put(VerbalizerEvent(kind="interrupted"))
                        return
                    await self._ingest_token_chunk(chunk)

                # Flush any benign non-tag carryover outside `<think>` at end of stream
                if not self._in_think_block and self._tag_carryover:
                    leftover = self._tag_carryover
                    self._tag_carryover = ""
                    if leftover not in ("<think>", "</think>"):
                        await self._emit_text(leftover, prosody_mode="normal")
            finally:
                self.reset_state()
                await q.put(VerbalizerEvent(kind="turn_end"))
                await q.put(None)

        driver_task = asyncio.create_task(_driver())
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                yield item
        finally:
            self.cancel_watchdog()
            if not driver_task.done():
                driver_task.cancel()

    @classmethod
    def demux_completed_text(cls, raw_text: str) -> Tuple[str, List[str]]:
        """Synchronous helper stripping `<think>...</think>` blocks from completed LLM replies.

        Returns `(clean_answer_text, extracted_mutter_clauses)` so non-streaming callers never read
        raw `<think>` syntax aloud while still exposing distilled thought telemetry.
        """
        if not raw_text or "<think>" not in raw_text.lower():
            return (raw_text or "").strip(), []

        mutters: List[str] = []
        for match in re.finditer(r"<think>([\s\S]*?)</think>", raw_text, flags=re.IGNORECASE):
            clause = cls._clean_thought_clause(match.group(1))
            if clause:
                mutters.append(clause.strip())
        # Also strip any unclosed `<think>...` if generation truncated mid-thought
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw_text, flags=re.IGNORECASE)
        cleaned = re.sub(r"<think>[\s\S]*$", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned, mutters

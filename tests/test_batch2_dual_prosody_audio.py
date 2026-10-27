"""Batch 2 Verification Suite: Dual-Prosody (`[mutter]` vs `[normal]`), VAD Sensitivity & `<80ms` Barge-In."""

from __future__ import annotations

import asyncio
import math
from typing import List, Tuple

from services.kairos_voice.audio_io import AdaptiveVADController, LocalSmartTurnAnalyzer
from services.kairos_voice.tts_kokoro import (
    KokoroDualProsodyTTSService,
    TTSAudioRawEvent,
    TTSStoppedEvent,
    compute_pcm16_rms,
)


def _synthetic_speech_backend(text: str, voice: str, speed: float) -> Tuple[List[float], int]:
    """Generate a deterministic 260 Hz fundamental harmonic tone scaled by `speed` at 24 kHz."""
    sr = 24000
    base_duration_sec = max(0.32, min(1.6, len(text) * 0.025))
    actual_duration_sec = base_duration_sec / max(0.5, speed)
    n_samples = int(sr * actual_duration_sec)
    samples = [
        0.72 * math.sin(2.0 * math.pi * 260.0 * (i / sr))
        + 0.18 * math.sin(2.0 * math.pi * 520.0 * (i / sr))
        for i in range(n_samples)
    ]
    return samples, sr


def test_batch2_dual_prosody_rms_attenuation_speed_scaling_and_markdown_stripping() -> None:
    tts = KokoroDualProsodyTTSService(synth_backend=_synthetic_speech_backend)

    # 1. Markdown & WikiLink stripping verification
    is_mutter, stripped = tts.parse_prosody_directive(
        "[normal] ** Check ** [Obsidian Spec](https://obsidian.md) and `[[02_Projects/KAIROS/TSK-01]]`!"
    )
    assert is_mutter is False
    assert "*" not in stripped
    assert "`" not in stripped
    assert "[[" not in stripped
    assert "https://" not in stripped
    assert "Obsidian Spec" in stripped

    # 2. Compare `[normal]` (1.00x, 0.0 dB) vs `[mutter]` (1.12x, -3.3 dB = 0.68 gain, LP alpha=0.78)
    phrase = "Tracing how the Dual-AI router evaluates local prefix cache blocks right now."
    normal_res = tts.synthesize_wav_sync(f"[normal] {phrase}")
    mutter_res = tts.synthesize_wav_sync(f"[mutter] {phrase}")

    assert normal_res["ok"] is True and mutter_res["ok"] is True
    assert normal_res["prosody_mode"] == "normal"
    assert mutter_res["prosody_mode"] == "mutter"

    rms_normal = compute_pcm16_rms(normal_res["pcm_bytes"])
    rms_mutter = compute_pcm16_rms(mutter_res["pcm_bytes"])
    rms_ratio = rms_mutter / rms_normal

    # Acceptance gate: `[mutter]` RMS measures `0.68 +/- 0.05` relative to `[normal]`
    assert 0.63 <= rms_ratio <= 0.73, f"Expected ~0.68 RMS ratio, got {rms_ratio:.4f}"

    # Acceptance gate: `[normal]` byte length / `[mutter]` byte length scales by `1.12x`
    duration_scale = len(normal_res["pcm_bytes"]) / len(mutter_res["pcm_bytes"])
    assert 1.09 <= duration_scale <= 1.15, f"Expected ~1.12x speed ratio, got {duration_scale:.4f}"


def test_batch2_adaptive_vad_sensitivity_smart_turn_and_sub_80ms_barge_in() -> None:
    tts = KokoroDualProsodyTTSService(synth_backend=_synthetic_speech_backend)
    vad = AdaptiveVADController(tts_service=tts)

    # 1. Verify VAD threshold shifts from 0.50 -> 0.35 during thinking-aloud `[mutter]` mode
    assert vad.current_threshold == 0.50
    assert vad.should_interrupt(0.40) is False

    vad.set_thinking_aloud_vad_sensitivity(True)
    assert vad.current_threshold == 0.35
    assert vad.should_interrupt(0.40) is True

    # 2. Verify Smart Turn extends hold on trailing conjunctions
    smart_turn = LocalSmartTurnAnalyzer(base_silence_sec=0.85, incomplete_extension_sec=0.75)
    assert smart_turn.is_turn_complete(0.95, "Open KAIROS Gantt view") is True
    assert smart_turn.is_turn_complete(0.95, "Open KAIROS Gantt view and") is False
    assert smart_turn.is_turn_complete(1.70, "Open KAIROS Gantt view and") is True

    # 3. Verify simulated `UserStartedSpeaking` flushes queued 40ms TTS frames in `< 80 ms`
    async def _simulate_barge_in_mid_stream() -> Tuple[int, bool, float]:
        emitted_chunks = 0
        was_interrupted = False
        flush_ms = 0.0
        long_text = "[normal] " + ("Delivering comprehensive sprint progress metrics across departments. " * 6)
        async for frame in tts.run_tts(long_text):
            if isinstance(frame, TTSAudioRawEvent):
                emitted_chunks += 1
                if emitted_chunks == 2:
                    barge = vad.handle_user_started_speaking()
                    flush_ms = barge["flush_latency_ms"]
            elif isinstance(frame, TTSStoppedEvent):
                was_interrupted = frame.interrupted
        return emitted_chunks, was_interrupted, flush_ms

    chunks_before_stop, interrupted, latency_ms = asyncio.run(_simulate_barge_in_mid_stream())
    assert chunks_before_stop == 2
    assert interrupted is True
    assert latency_ms < 80.0
    assert vad.current_threshold == 0.50

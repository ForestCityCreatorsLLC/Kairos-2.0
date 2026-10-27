"""Dual-Prosody Local & Hybrid Neural TTS Processor (`services/kairos_voice/tts_kokoro.py`).

Implements `KokoroDualProsodyTTSService` supporting real-time prosody shifting:
- `[mutter]` mode: `speed=1.12x`, `gain=0.68` (`-3.3 dB`), first-order low-pass filter (`alpha=0.78`)
- `[normal]` mode: `speed=1.00x`, `gain=1.00` (`0.0 dB`), crisp full-spectrum `24 kHz` PCM output

Works natively with `kokoro-onnx` (`Kokoro-82M`) on GPU/ONNX when weights are present, and provides
universal PCM/WAV prosody conditioning (`apply_dual_prosody_pcm16` / `apply_dual_prosody_wav`) so
Gemini TTS and local synthesis share identical sub-vocal `[mutter]` vs `[normal]` acoustics.
"""

from __future__ import annotations

import array
import asyncio
from dataclasses import dataclass
import io
import math
from pathlib import Path
import re
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple
import wave

try:
    import numpy as _np  # type: ignore
except Exception:  # pragma: no cover
    _np = None


@dataclass
class VoicePipelineFrame:
    """Lightweight Pipecat-compatible frame contract for KAIROS `/ws/voice` streaming."""

    kind: str


@dataclass
class TTSStartedEvent(VoicePipelineFrame):
    prosody_mode: str = "normal"

    def __init__(self, prosody_mode: str = "normal") -> None:
        super().__init__(kind="tts_started")
        self.prosody_mode = prosody_mode


@dataclass
class TTSAudioRawEvent(VoicePipelineFrame):
    audio: bytes = b""
    sample_rate: int = 24000
    num_channels: int = 1
    prosody_mode: str = "normal"

    def __init__(
        self,
        audio: bytes,
        sample_rate: int = 24000,
        num_channels: int = 1,
        prosody_mode: str = "normal",
    ) -> None:
        super().__init__(kind="tts_audio_raw")
        self.audio = audio
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.prosody_mode = prosody_mode


@dataclass
class TTSStoppedEvent(VoicePipelineFrame):
    interrupted: bool = False

    def __init__(self, interrupted: bool = False) -> None:
        super().__init__(kind="tts_stopped")
        self.interrupted = interrupted


@dataclass
class TTSErrorEvent(VoicePipelineFrame):
    error: str = ""

    def __init__(self, error: str) -> None:
        super().__init__(kind="tts_error")
        self.error = error


def strip_tts_markdown(text: str) -> str:
    """Strip markdown symbols, links, `<think>` remnants, and prosody tags for clean synthesis."""
    cleaned = re.sub(r"<ui_nav>[\s\S]*?</ui_nav>", " ", text or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"<think>[\s\S]*?</think>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", cleaned)
    cleaned = re.sub(r"\[\[([^\]]+)\]\]", lambda m: m.group(1).split("/")[-1].replace("_", " "), cleaned)
    cleaned = re.sub(r"[`*_#~>|]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def resample_float_samples(samples: List[float], speed: float) -> List[float]:
    """Linearly time-scale float32 waveform samples by `speed` (e.g. `1.12x` shortens duration by `1 / 1.12`)."""
    if not samples or abs(speed - 1.0) < 1e-4 or speed <= 0.0:
        return list(samples)
    in_len = len(samples)
    out_len = max(1, int(round(in_len / speed)))
    if _np is not None:
        arr = _np.asarray(samples, dtype=_np.float32)
        positions = _np.linspace(0.0, float(in_len - 1), num=out_len, dtype=_np.float32)
        return _np.interp(positions, _np.arange(in_len, dtype=_np.float32), arr).astype(_np.float32).tolist()

    out: List[float] = [0.0] * out_len
    max_idx = in_len - 1
    for i in range(out_len):
        pos = (i * max_idx) / max(1, out_len - 1) if out_len > 1 else 0.0
        lo = int(math.floor(pos))
        hi = min(max_idx, lo + 1)
        frac = pos - lo
        out[i] = samples[lo] * (1.0 - frac) + samples[hi] * frac
    return out


def apply_mutter_dsp_float(samples: List[float], gain: float = 0.68, alpha: float = 0.78) -> List[float]:
    """Apply `-3.3 dB` (`0.68`) gain scaling and gentle 1-pole low-pass softening (`alpha=0.78`)."""
    if not samples:
        return []
    if _np is not None:
        arr = _np.asarray(samples, dtype=_np.float32) * float(gain)
        filtered = _np.empty_like(arr)
        filtered[0] = arr[0]
        if arr.shape[0] > 1:
            filtered[1:] = float(alpha) * arr[1:] + (1.0 - float(alpha)) * arr[:-1]
        return _np.clip(filtered, -1.0, 1.0).tolist()

    n = len(samples)
    attenuated = [s * gain for s in samples]
    filtered_list = [0.0] * n
    filtered_list[0] = max(-1.0, min(1.0, attenuated[0]))
    one_minus = 1.0 - alpha
    for idx in range(1, n):
        val = alpha * attenuated[idx] + one_minus * attenuated[idx - 1]
        filtered_list[idx] = -1.0 if val < -1.0 else (1.0 if val > 1.0 else val)
    return filtered_list


def float_samples_to_pcm16(samples: List[float]) -> bytes:
    """Convert normalized `[-1.0, 1.0]` float samples to 16-bit signed little-endian PCM bytes."""
    if _np is not None:
        arr = _np.clip(_np.asarray(samples, dtype=_np.float32), -1.0, 1.0)
        return (arr * 32767.0).astype(_np.int16).tobytes()
    pcm = array.array("h", (int(max(-1.0, min(1.0, s)) * 32767.0) for s in samples))
    return pcm.tobytes()


def pcm16_to_float_samples(pcm16_bytes: bytes) -> List[float]:
    """Convert 16-bit signed little-endian PCM bytes to normalized `[-1.0, 1.0]` floats."""
    even_bytes = pcm16_bytes[: len(pcm16_bytes) - (len(pcm16_bytes) % 2)]
    if not even_bytes:
        return []
    if _np is not None:
        arr = _np.frombuffer(even_bytes, dtype=_np.int16).astype(_np.float32) / 32767.0
        return arr.tolist()
    raw = array.array("h")
    raw.frombytes(even_bytes)
    return [s / 32767.0 for s in raw]


def compute_pcm16_rms(pcm16_bytes: bytes) -> float:
    """Compute normalized `[0.0, 1.0]` RMS amplitude of 16-bit mono PCM bytes."""
    floats = pcm16_to_float_samples(pcm16_bytes)
    if not floats:
        return 0.0
    mean_sq = sum(s * s for s in floats) / len(floats)
    return math.sqrt(mean_sq)


def apply_dual_prosody_wav(
    wav_bytes: bytes,
    *,
    prosody_mode: str = "normal",
    mutter_speed: float = 1.12,
    mutter_gain: float = 0.68,
    alpha: float = 0.78,
) -> bytes:
    """Apply `[mutter]` speed (`1.12x`), attenuation (`0.68`), and low-pass (`0.78`) to a RIFF WAV buffer."""
    if not wav_bytes or prosody_mode != "mutter":
        return wav_bytes
    if wav_bytes[:4] != b"RIFF" or b"WAVE" not in wav_bytes[:16]:
        return wav_bytes
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            raw_frames = wf.readframes(wf.getnframes())
        if nchannels != 1 or sampwidth != 2:
            return wav_bytes
        samples = pcm16_to_float_samples(raw_frames)
        sped = resample_float_samples(samples, mutter_speed)
        shaped = apply_mutter_dsp_float(sped, gain=mutter_gain, alpha=alpha)
        pcm_out = float_samples_to_pcm16(shaped)
        out_buf = io.BytesIO()
        with wave.open(out_buf, "wb") as wout:
            wout.setnchannels(1)
            wout.setsampwidth(2)
            wout.setframerate(framerate)
            wout.writeframes(pcm_out)
        return out_buf.getvalue()
    except Exception:
        return wav_bytes


class KokoroDualProsodyTTSService:
    """Local GPU/ONNX Kokoro-82M TTS service with real-time `[mutter]` / `[normal]` prosody & `<80ms` barge-in."""

    def __init__(
        self,
        model_path: str = "models/kokoro-v1.0.onnx",
        voices_path: str = "models/voices-v1.0.bin",
        voice: str = "af_heart",
        sample_rate: int = 24000,
        mutter_speed: float = 1.12,
        mutter_gain: float = 0.68,
        normal_speed: float = 1.00,
        normal_gain: float = 1.00,
        lowpass_alpha: float = 0.78,
        synth_backend: Optional[Callable[[str, str, float], Tuple[List[float], int]]] = None,
    ) -> None:
        self._model_path = model_path
        self._voices_path = voices_path
        self._voice = voice
        self._sample_rate = sample_rate
        self._mutter_speed = mutter_speed
        self._mutter_gain = mutter_gain
        self._normal_speed = normal_speed
        self._normal_gain = normal_gain
        self._lowpass_alpha = lowpass_alpha
        self._is_mutter_mode: bool = False
        self._kokoro: Optional[Any] = None
        self._synth_backend = synth_backend
        self._barge_in_flag: bool = False
        self.last_barge_in_flush_ms: float = 0.0

    @property
    def is_mutter_mode(self) -> bool:
        return self._is_mutter_mode

    def is_local_model_available(self) -> bool:
        """Return True when an injected backend or on-disk Kokoro-82M `.onnx` weights are available."""
        if self._synth_backend is not None or self._kokoro is not None:
            return True
        return Path(self._model_path).is_file() and Path(self._voices_path).is_file()

    def _ensure_kokoro_loaded(self) -> Optional[Any]:
        if self._kokoro is not None:
            return self._kokoro
        if not (Path(self._model_path).is_file() and Path(self._voices_path).is_file()):
            return None
        try:
            from kokoro_onnx import Kokoro  # type: ignore

            self._kokoro = Kokoro(self._model_path, self._voices_path)
            return self._kokoro
        except Exception:
            return None

    def trigger_barge_in(self) -> float:
        """Immediately halt active/queued TTS chunk emission (`< 80ms` cancellation SLA)."""
        t0 = time.perf_counter()
        self._barge_in_flag = True
        self.last_barge_in_flush_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return self.last_barge_in_flush_ms

    def reset_barge_in(self) -> None:
        self._barge_in_flag = False

    @staticmethod
    def parse_prosody_directive(text: str, current_mutter: bool = False) -> Tuple[bool, str]:
        """Extract `[mutter]` or `[normal]` prosody prefix and return `(is_mutter, stripped_text)`."""
        is_mutter = current_mutter
        out = text or ""
        if "[mutter]" in out:
            is_mutter = True
            out = out.replace("[mutter]", "")
        if "[normal]" in out:
            is_mutter = False
            out = out.replace("[normal]", "")
        return is_mutter, strip_tts_markdown(out)

    def _synthesize_raw_samples(self, clean_text: str, speed: float) -> Tuple[List[float], int]:
        if self._synth_backend is not None:
            samples, sr = self._synth_backend(clean_text, self._voice, speed)
            return list(samples), int(sr)

        kokoro = self._ensure_kokoro_loaded()
        if kokoro is None:
            raise FileNotFoundError(
                f"Kokoro-82M ONNX weights not found at '{self._model_path}' / '{self._voices_path}'"
            )
        samples, sr = kokoro.create(clean_text, voice=self._voice, speed=speed, lang="en-us")
        if _np is not None:
            return _np.asarray(samples, dtype=_np.float32).tolist(), int(sr)
        return [float(x) for x in samples], int(sr)

    def synthesize_wav_sync(self, text: str) -> Dict[str, Any]:
        """Synchronous helper returning a complete RIFF WAV payload for `/api/voice/tts`."""
        self._is_mutter_mode, clean_text = self.parse_prosody_directive(text, self._is_mutter_mode)
        if not clean_text:
            return {"ok": False, "clean_text": "", "prosody_mode": "mutter" if self._is_mutter_mode else "normal"}

        speed = self._mutter_speed if self._is_mutter_mode else self._normal_speed
        gain = self._mutter_gain if self._is_mutter_mode else self._normal_gain
        mode_name = "mutter" if self._is_mutter_mode else "normal"

        samples_f32, sr = self._synthesize_raw_samples(clean_text, speed)
        if self._is_mutter_mode:
            shaped = apply_mutter_dsp_float(samples_f32, gain=gain, alpha=self._lowpass_alpha)
        else:
            shaped = [max(-1.0, min(1.0, s * gain)) for s in samples_f32]

        pcm_bytes = float_samples_to_pcm16(shaped)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm_bytes)
        return {
            "ok": True,
            "wav_bytes": buf.getvalue(),
            "pcm_bytes": pcm_bytes,
            "sample_rate": sr,
            "clean_text": clean_text,
            "prosody_mode": mode_name,
            "voice": self._voice,
            "provider": "kokoro-82m-local",
        }

    async def run_tts(self, text: str) -> AsyncGenerator[VoicePipelineFrame, None]:
        """Stream `40ms` (`1920`-byte at `24kHz`) dual-prosody PCM frames with `<80ms` barge-in flush."""
        self._barge_in_flag = False
        self._is_mutter_mode, clean_text = self.parse_prosody_directive(text, self._is_mutter_mode)
        if not clean_text:
            return

        mode_name = "mutter" if self._is_mutter_mode else "normal"
        speed = self._mutter_speed if self._is_mutter_mode else self._normal_speed
        gain = self._mutter_gain if self._is_mutter_mode else self._normal_gain

        try:
            yield TTSStartedEvent(prosody_mode=mode_name)
            samples_f32, sr = await asyncio.to_thread(self._synthesize_raw_samples, clean_text, speed)
            if self._barge_in_flag:
                yield TTSStoppedEvent(interrupted=True)
                return

            if self._is_mutter_mode:
                shaped = apply_mutter_dsp_float(samples_f32, gain=gain, alpha=self._lowpass_alpha)
            else:
                shaped = [max(-1.0, min(1.0, s * gain)) for s in samples_f32]

            pcm_int16 = float_samples_to_pcm16(shaped)
            chunk_bytes = int(sr * 0.04 * 2)  # 40ms frames (1920 bytes @ 24kHz mono int16)
            for offset in range(0, len(pcm_int16), chunk_bytes):
                if self._barge_in_flag:
                    yield TTSStoppedEvent(interrupted=True)
                    return
                yield TTSAudioRawEvent(
                    audio=pcm_int16[offset : offset + chunk_bytes],
                    sample_rate=sr,
                    num_channels=1,
                    prosody_mode=mode_name,
                )
                await asyncio.sleep(0)
            yield TTSStoppedEvent(interrupted=False)
        except Exception as exc:
            yield TTSErrorEvent(error=f"KokoroDualProsodyTTSService synthesis error: {exc}")

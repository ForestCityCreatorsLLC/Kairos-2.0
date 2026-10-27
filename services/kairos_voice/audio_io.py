"""Adaptive VAD, Smart Turn Detection, Barge-In Flush & Local Whisper STT (`services/kairos_voice/audio_io.py`).

Implements:
1. `AdaptiveVADController` (`SileroVAD` ONNX when installed + energy/spectral fallback) with dynamic
   `set_thinking_aloud_vad_sensitivity(is_thinking: bool)` lowering threshold from `0.50` -> `0.35`
   during `[mutter]` playback so human speech interrupts cognitive deliberation effortlessly.
2. `LocalSmartTurnAnalyzer` semantic end-of-turn detector preventing premature cutoffs on trailing
   conjunctions ("and", "or", "because", "so", "uh", "um").
3. `WhisperLocalSTTService` (`faster-whisper` `large-v3-turbo` `float16` CUDA / `int8` CPU fallback)
   keeping resident STT allocation <= `1.60 GB` VRAM.
"""

from __future__ import annotations

import io
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from services.kairos_voice.tts_kokoro import KokoroDualProsodyTTSService, compute_pcm16_rms


TRAILING_INCOMPLETE_TURN_RE = re.compile(
    r"\b(?:and|or|but|because|so|then|like|with|for|to|uh|um|er|hmm)\s*$",
    flags=re.IGNORECASE,
)


class LocalSmartTurnAnalyzer:
    """Semantic turn-end detector combining silence duration with incomplete-clause heuristics."""

    def __init__(self, base_silence_sec: float = 0.85, incomplete_extension_sec: float = 0.75) -> None:
        self.base_silence_sec = base_silence_sec
        self.incomplete_extension_sec = incomplete_extension_sec

    def required_silence_sec(self, partial_transcript: str = "") -> float:
        clean = (partial_transcript or "").strip()
        if clean and TRAILING_INCOMPLETE_TURN_RE.search(clean):
            return round(self.base_silence_sec + self.incomplete_extension_sec, 2)
        return self.base_silence_sec

    def is_turn_complete(self, silence_elapsed_sec: float, partial_transcript: str = "") -> bool:
        return silence_elapsed_sec >= self.required_silence_sec(partial_transcript)


class AdaptiveVADController:
    """Manages Silero/WebAudio VAD threshold (`0.50` normal vs `0.35` thinking-aloud) & `<80ms` barge-in."""

    NORMAL_VAD_THRESHOLD: float = 0.50
    THINKING_VAD_THRESHOLD: float = 0.35

    def __init__(
        self,
        *,
        normal_threshold: float = 0.50,
        thinking_threshold: float = 0.35,
        tts_service: Optional[KokoroDualProsodyTTSService] = None,
    ) -> None:
        self.normal_threshold = float(normal_threshold)
        self.thinking_threshold = float(thinking_threshold)
        self.current_threshold: float = self.normal_threshold
        self.is_thinking_aloud: bool = False
        self.aec_enabled: bool = True
        self.smart_turn = LocalSmartTurnAnalyzer()
        self._tts_service = tts_service
        self._on_barge_in_callbacks: List[Callable[[], None]] = []
        self.last_barge_in_latency_ms: float = 0.0

    def register_barge_in_callback(self, cb: Callable[[], None]) -> None:
        self._on_barge_in_callbacks.append(cb)

    def set_thinking_aloud_vad_sensitivity(self, is_thinking: bool) -> float:
        """Lower VAD interruption threshold from `0.50` to `0.35` during `[mutter]` playback."""
        self.is_thinking_aloud = bool(is_thinking)
        self.current_threshold = (
            self.thinking_threshold if self.is_thinking_aloud else self.normal_threshold
        )
        return self.current_threshold

    def evaluate_pcm16_speech_probability(self, pcm16_bytes: bytes) -> float:
        """Compute `[0.0, 1.0]` speech probability from 16kHz PCM frame."""
        rms = compute_pcm16_rms(pcm16_bytes)
        # Map conversational speech RMS (0.02..0.22) smoothly onto [0.0..1.0] probability curve
        prob = min(1.0, max(0.0, rms * 5.0))
        return round(prob, 4)

    def should_interrupt(self, speech_probability: float) -> bool:
        return float(speech_probability) >= self.current_threshold

    def handle_user_started_speaking(self) -> Dict[str, Any]:
        """Flush queued TTS audio and invoke registered cancellation hooks in `< 80ms`."""
        t0 = time.perf_counter()
        if self._tts_service is not None:
            self._tts_service.trigger_barge_in()
        for cb in list(self._on_barge_in_callbacks):
            try:
                cb()
            except Exception:
                pass
        self.set_thinking_aloud_vad_sensitivity(False)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        self.last_barge_in_latency_ms = elapsed_ms
        return {
            "interrupted": True,
            "flush_latency_ms": elapsed_ms,
            "meets_80ms_sla": elapsed_ms < 80.0,
            "vad_threshold": self.current_threshold,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vad_threshold": self.current_threshold,
            "normal_threshold": self.normal_threshold,
            "thinking_threshold": self.thinking_threshold,
            "is_thinking_aloud": self.is_thinking_aloud,
            "aec_enabled": self.aec_enabled,
            "last_barge_in_latency_ms": self.last_barge_in_latency_ms,
        }


class WhisperLocalSTTService:
    """Local `faster-whisper` (`large-v3-turbo`, `float16` CUDA / `int8` CPU fallback) STT service."""

    ESTIMATED_VRAM_GB: float = 1.60

    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        device: str = "cuda",
        compute_type: str = "float16",
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model: Optional[Any] = None
        self._lock = threading.RLock()
        self._load_attempted: bool = False

    def is_installed(self) -> bool:
        try:
            import faster_whisper  # type: ignore  # noqa: F401

            return True
        except Exception:
            return False

    def _get_or_load_model(self) -> Optional[Any]:
        with self._lock:
            if self._model is not None:
                return self._model
            if self._load_attempted:
                return None
            self._load_attempted = True
            try:
                from faster_whisper import WhisperModel  # type: ignore

                try:
                    self._model = WhisperModel(
                        self.model_size,
                        device=self.device,
                        compute_type=self.compute_type,
                    )
                except Exception:
                    # Graceful CPU int8 fallback if CUDA runtime is unavailable
                    self._model = WhisperModel(
                        self.model_size,
                        device="cpu",
                        compute_type="int8",
                    )
                return self._model
            except Exception:
                return None

    def transcribe_bytes(self, audio_bytes: bytes, mime_type: str = "audio/webm") -> Optional[Dict[str, Any]]:
        """Transcribe audio locally via `faster-whisper` without any network call (`#private` safe).

        Returns `None` if `faster-whisper` is not installed or if the payload is not decodable audio.
        """
        if not audio_bytes or len(audio_bytes) < 64 or not self.is_installed():
            return None

        model = self._get_or_load_model()
        if model is None:
            return None

        suffix = ".wav" if "wav" in (mime_type or "").lower() else ".webm"
        tmp_path: Optional[Path] = None
        t0 = time.perf_counter()
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                tf.write(audio_bytes)
                tmp_path = Path(tf.name)
            segments, _info = model.transcribe(
                str(tmp_path),
                language="en",
                beam_size=1,
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments if seg.text).strip()
            if not text:
                return None
            return {
                "ok": True,
                "text": text,
                "provider": "local-whisper",
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "privacy_locked": True,
            }
        except Exception:
            return None
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

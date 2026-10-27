"""Isolated KAIROS 2.0 Voice Sidecar (`services/kairos_voice/voice_service.py` on port `8421`).

Runs completely decoupled from the UI process so audio hardware/VAD/STT/TTS never freezes the
workspace. Exposes REST + WebSocket controls for the Permanent KAIROS Top Bar & Voice Navigator HUD:
- `Play` (Activate Listening / Hands-Free Co-Pilot)
- `Pause` (Mute Voice & Mic)
- `Stop` (Immediate Barge-In / Halt Speech)
- `+1s` (Extend Thinking-Pause Silence Hold up to 5.5s)
- `POST /api/voice/config` (Hands-Free loop, `"Hey Kairos"` Wake-Word filter, Neural TTS voice)
- `POST /api/voice/audio-command` (Dual-Engine STT via `gemini-3.5-transcribe` with strict `#private` / `03_Personal/Finance` local hard-lock -> Core `:8420` -> Neural TTS)
- `POST /api/voice/tts` (Expressive `gemini-3.8-flash-lite-tts` WAV synthesis conditioned with `apply_raised_cosine_envelope` + browser TTS fallback)
"""

from __future__ import annotations

import array
import base64
import io
import math
import re
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, model_validator

from services.kairos_core.config import settings
from services.kairos_core.navigator import clean_text_for_speech, normalize_kairos_phonetics
from services.kairos_core.tool_registry import get_vram_envelope_telemetry
from services.kairos_core.vault_engine import VaultEngine, parse_markdown_note
from services.kairos_voice.audio_io import AdaptiveVADController, WhisperLocalSTTService
from services.kairos_voice.thought_verbalizer import TrainOfThoughtVerbalizer
from services.kairos_voice.tts_kokoro import KokoroDualProsodyTTSService, apply_dual_prosody_wav

MAX_AUDIO_PAYLOAD_BYTES = 15 * 1024 * 1024

kokoro_tts = KokoroDualProsodyTTSService(
    model_path=settings.kokoro_model_path,
    voices_path=settings.kokoro_voices_path,
    voice=settings.kokoro_voice,
)
vad_controller = AdaptiveVADController(tts_service=kokoro_tts)
whisper_stt = WhisperLocalSTTService(model_size=settings.whisper_model_size)


def apply_raised_cosine_envelope(
    pcm16_bytes: bytes,
    sample_rate: int = 24000,
    fade_in_ms: float = 20.0,
    fade_out_ms: float = 25.0,
) -> bytes:
    """Apply smooth raised-cosine fade-in/out to 16-bit mono PCM to eliminate speaker clicks/pops."""
    if not pcm16_bytes or len(pcm16_bytes) < 4:
        return pcm16_bytes
    samples = array.array("h")
    samples.frombytes(pcm16_bytes[: len(pcm16_bytes) - (len(pcm16_bytes) % 2)])
    n = len(samples)
    fade_in_n = min(n // 2, int(sample_rate * (fade_in_ms / 1000.0)))
    fade_out_n = min(n // 2, int(sample_rate * (fade_out_ms / 1000.0)))

    for i in range(fade_in_n):
        gain = 0.5 * (1.0 - math.cos(math.pi * (i / max(1, fade_in_n))))
        samples[i] = int(samples[i] * gain)
    for i in range(fade_out_n):
        idx = n - 1 - i
        gain = 0.5 * (1.0 - math.cos(math.pi * (i / max(1, fade_out_n))))
        samples[idx] = int(samples[idx] * gain)
    return samples.tobytes()


def condition_or_wrap_wav(audio_bytes: bytes, default_sample_rate: int = 24000) -> bytes:
    """Ensure audio bytes are valid RIFF WAV with raised-cosine PCM envelope conditioning."""
    if not audio_bytes:
        return b""
    if audio_bytes[:4] == b"RIFF" and b"WAVE" in audio_bytes[:16]:
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                nchannels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
                frames = wf.readframes(wf.getnframes())
            if sampwidth == 2 and nchannels == 1:
                conditioned = apply_raised_cosine_envelope(frames, sample_rate=framerate)
                out_buf = io.BytesIO()
                with wave.open(out_buf, "wb") as wout:
                    wout.setnchannels(1)
                    wout.setsampwidth(2)
                    wout.setframerate(framerate)
                    wout.writeframes(conditioned)
                return out_buf.getvalue()
            return audio_bytes
        except Exception:
            return audio_bytes

    # Raw 16-bit mono PCM (e.g. audio/L16 at 24kHz) -> condition & wrap in RIFF WAV
    conditioned = apply_raised_cosine_envelope(audio_bytes, sample_rate=default_sample_rate)
    out_buf = io.BytesIO()
    with wave.open(out_buf, "wb") as wout:
        wout.setnchannels(1)
        wout.setsampwidth(2)
        wout.setframerate(default_sample_rate)
        wout.writeframes(conditioned)
    return out_buf.getvalue()


def is_voice_context_private(active_note_path: str = "", text_hint: str = "") -> bool:
    """Enforce Canopy Vault Privacy Hard-Lock (`03_Personal/Finance/` or `#private` / YAML `tags: [private]`)."""
    raw_path = (active_note_path or "").strip()
    norm_path = raw_path.replace("\\", "/").strip("/")
    if norm_path.lower().startswith("03_personal/finance"):
        return True
    if "#private" in (text_hint or "").lower():
        return True
    if norm_path:
        vault = VaultEngine(settings.vault_path)
        try:
            candidate = vault.resolve_safe_path(norm_path)
        except ValueError:
            # Fail-closed to local-only privacy shield if path escapes Vault root
            return True
        if candidate.is_file():
            try:
                raw = candidate.read_text(encoding="utf-8", errors="ignore")
                fm, body = parse_markdown_note(raw)
                rel = vault.to_rel_path(candidate)
                if vault.is_private_note(rel, fm, body):
                    return True
            except Exception:
                return True
    return False


def check_wake_word(transcript: str, wake_word_only: bool) -> Tuple[bool, str]:
    """Filter transcript for `'Hey Kairos'` / `'Kairos'` (including phonetic `'Hey Kros'` variants) when `wake_word_only` is enabled."""
    clean = normalize_kairos_phonetics((transcript or "").strip())
    if not clean:
        return False, ""
    if not wake_word_only:
        return True, clean

    m = re.match(
        r"^(?:(?:hey|hi|hello|ok|okay|yo)\s+)?kairos(?:[\s,:;\-]+(.*))?$",
        clean,
        flags=re.IGNORECASE,
    )
    if m:
        remainder = (m.group(1) or "").strip()
        return True, (remainder if remainder else "Hey KAIROS")

    # Also allow wake word slightly mid-phrase if mic caught leading breath/noise
    m_mid = re.search(r"\b(?:hey|hi|hello|ok|okay)\s+kairos[\s,:;\-]*(.*)$", clean, flags=re.IGNORECASE)
    if m_mid:
        rem = (m_mid.group(1) or "").strip()
        return True, (rem if rem else "Hey KAIROS")

    return False, ""


STT_STRICT_PROMPT = (
    "You are a strict speech-to-text audio transcriber. "
    "Transcribe ONLY clearly audible human speech spoken directly into the microphone in English. "
    "CRITICAL RULES: "
    "1. If the audio contains silence, background room noise, typing, mouse clicks, breathing, music, "
    "muffled speaker bleed, or unintelligible sound, output ONLY the exact token [SILENCE]. "
    "2. NEVER invent, guess, autocomplete, or fabricate commands or example sentences. "
    "3. Return ONLY the exact spoken words (or [SILENCE]) with no quotes or extra explanation."
)

_SILENCE_OR_HALLUCINATION_RE = re.compile(
    r"^(?:"
    r"\[+\s*(?:silence|no[\s_]*speech|inaudible|blank[\s_]*audio|noise|music|applause|laughter|static)\s*\]+"
    r"|\(+\s*(?:silence|no[\s_]*speech|inaudible|blank[\s_]*audio|noise|music)\s*\)+"
    r"|silence\.?"
    r"|no\s+speech(?:\s+detected)?\.?"
    r"|thank\s+you(?:\s+for\s+watching|\s+for\s+listening)?[.!]?"
    r"|thanks\s+for\s+watching[.!]?"
    r"|subtitles?\s+by\b.*"
    r"|you\.?"
    r")$",
    flags=re.IGNORECASE,
)


def _sanitize_stt_transcript(raw_text: str) -> str:
    """Reject `[SILENCE]` markers, empty/noise tokens, and prompt-echo hallucinations from STT engines."""
    cleaned = (raw_text or "").strip().strip("\"'` ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    if _SILENCE_OR_HALLUCINATION_RE.match(cleaned):
        return ""
    low = cleaned.lower()
    if "strict speech-to-text" in low or "transcribe only clearly audible" in low:
        return ""
    # Reject strings containing zero alphanumeric characters or a single stray letter
    alnum_only = re.sub(r"[^A-Za-z0-9]+", "", cleaned)
    if len(alnum_only) <= 1:
        return ""
    return normalize_kairos_phonetics(cleaned)


def transcribe_audio_bytes(
    audio_bytes: bytes,
    mime_type: str = "audio/webm",
    is_private: bool = False,
) -> Dict[str, Any]:
    """Transcribe microphone audio via Gemini multimodal STT or strictly local STT when private."""
    if not audio_bytes:
        return {
            "ok": False,
            "text": "",
            "provider": "none",
            "privacy_locked": is_private,
            "error": "Empty audio payload",
        }

    # HARD PRIVACY GATE: Never transmit audio while viewing `03_Personal/Finance/` or `#private`
    if is_private:
        local_w = whisper_stt.transcribe_bytes(audio_bytes, mime_type=mime_type)
        if local_w and local_w.get("ok"):
            clean_local = _sanitize_stt_transcript(str(local_w.get("text") or ""))
            if clean_local:
                return {
                    "ok": True,
                    "text": clean_local,
                    "provider": "local-whisper",
                    "privacy_locked": True,
                    "latency_ms": local_w.get("latency_ms", 0.0),
                }
        try:
            r_local = requests.post(
                f"{settings.lmstudio_base_url.rstrip('/')}/audio/transcriptions",
                files={"file": ("command.webm", audio_bytes, mime_type)},
                data={"model": "whisper-1"},
                timeout=8,
            )
            if r_local.ok:
                txt = _sanitize_stt_transcript(str(r_local.json().get("text") or ""))
                return {
                    "ok": bool(txt),
                    "text": txt,
                    "provider": "local-whisper",
                    "privacy_locked": True,
                    "no_speech": not bool(txt),
                }
        except Exception:
            pass
        return {
            "ok": False,
            "text": "",
            "provider": "local-privacy-shield",
            "privacy_locked": True,
            "error": "Privacy Shield active (03_Personal/Finance or #private): Cloud STT blocked.",
        }

    if not settings.gemini_api_key:
        local_w = whisper_stt.transcribe_bytes(audio_bytes, mime_type=mime_type)
        if local_w and local_w.get("ok"):
            clean_local = _sanitize_stt_transcript(str(local_w.get("text") or ""))
            if clean_local:
                return {
                    "ok": True,
                    "text": clean_local,
                    "provider": "local-whisper",
                    "privacy_locked": False,
                    "latency_ms": local_w.get("latency_ms", 0.0),
                }
        return {
            "ok": False,
            "text": "",
            "provider": "unconfigured",
            "privacy_locked": False,
            "error": "GEMINI_API_KEY not configured for server-side STT fallback.",
        }

    mime_clean = (mime_type or "audio/webm").split(";")[0].strip() or "audio/webm"
    b64_audio = base64.b64encode(audio_bytes).decode("ascii")

    try:
        from google import genai  # type: ignore

        client = genai.Client(api_key=settings.gemini_api_key)
        if hasattr(client, "interactions"):
            try:
                interaction = client.interactions.create(
                    model=settings.gemini_stt_model,
                    store=False,
                    input=[
                        {"type": "audio", "data": b64_audio, "mime_type": mime_clean},
                        {"type": "text", "text": STT_STRICT_PROMPT},
                    ],
                )
                raw_inter = str(getattr(interaction, "output_text", "") or "").strip()
                if raw_inter:
                    clean_inter = _sanitize_stt_transcript(raw_inter)
                    if clean_inter:
                        return {
                            "ok": True,
                            "text": clean_inter,
                            "provider": settings.gemini_stt_model,
                            "privacy_locked": False,
                        }
                    return {
                        "ok": False,
                        "text": "",
                        "provider": settings.gemini_stt_model,
                        "privacy_locked": False,
                        "no_speech": True,
                        "error": "No clear speech detected",
                    }
            except Exception:
                pass

        # Fallback cascade to `models.generate_content` multimodal audio transcription (temperature=0.0, zero hallucination)
        part_audio = genai.types.Part.from_bytes(data=audio_bytes, mime_type=mime_clean)
        stt_candidates: List[str] = []
        for m_name in (settings.gemini_stt_model, settings.gemini_model, "gemini-2.5-flash", "gemini-2.0-flash"):
            if m_name and "tts" not in m_name.lower() and m_name not in stt_candidates:
                stt_candidates.append(m_name)
        last_stt_err: Optional[Exception] = None
        for stt_model in stt_candidates:
            try:
                resp = None
                for cfg_candidate in (
                    {"temperature": 0.0, "thinking_config": {"thinking_budget": 0}},
                    {"temperature": 0.0},
                    None,
                ):
                    try:
                        if cfg_candidate is not None:
                            resp = client.models.generate_content(
                                model=stt_model,
                                contents=[part_audio, STT_STRICT_PROMPT],
                                config=cfg_candidate,
                            )
                        else:
                            resp = client.models.generate_content(
                                model=stt_model,
                                contents=[part_audio, STT_STRICT_PROMPT],
                            )
                        break
                    except TypeError:
                        continue
                    except Exception as inner_cfg_exc:
                        if cfg_candidate is not None and "thinking" in str(inner_cfg_exc).lower():
                            continue
                        raise

                raw_txt2 = str(getattr(resp, "text", "") or "").strip() if resp is not None else ""
                if raw_txt2:
                    clean_txt2 = _sanitize_stt_transcript(raw_txt2)
                    if clean_txt2:
                        return {
                            "ok": True,
                            "text": clean_txt2,
                            "provider": stt_model,
                            "privacy_locked": False,
                        }
                    # Model succeeded and explicitly reported silence/noise — stop immediately without cascading!
                    return {
                        "ok": False,
                        "text": "",
                        "provider": stt_model,
                        "privacy_locked": False,
                        "no_speech": True,
                        "error": "No clear speech detected",
                    }
            except Exception as m_exc:
                last_stt_err = m_exc
        return {
            "ok": False,
            "text": "",
            "provider": "gemini-stt-error",
            "privacy_locked": False,
            "error": str(last_stt_err) if last_stt_err else "Empty transcription",
        }
    except Exception as exc:
        return {
            "ok": False,
            "text": "",
            "provider": "gemini-stt-error",
            "privacy_locked": False,
            "error": str(exc),
        }


def synthesize_tts_wav(
    text: str,
    is_private: bool = False,
    voice_name: str = "",
) -> Dict[str, Any]:
    """Synthesize expressive neural speech with `[mutter]` (`1.12x`, `-3.3 dB`) & `[normal]` dual-prosody DSP."""
    raw_in = text or ""
    is_mutter = "[mutter]" in raw_in and "[normal]" not in raw_in
    prosody_mode = "mutter" if is_mutter else "normal"
    stripped_directives = raw_in.replace("[mutter]", " ").replace("[normal]", " ")
    demuxed_txt, _ = TrainOfThoughtVerbalizer.demux_completed_text(stripped_directives)
    clean_text = clean_text_for_speech(demuxed_txt)

    voice_state.prosody_mode = prosody_mode
    vad_controller.set_thinking_aloud_vad_sensitivity(is_mutter)

    if not clean_text:
        return {
            "ok": False,
            "fallback_browser_tts": True,
            "clean_text": "",
            "prosody_mode": prosody_mode,
        }

    # 1. Local GPU/ONNX `Kokoro-82M` fast path (`<90ms`, 100% `#private` safe when weights are installed)
    if voice_state.neural_tts and kokoro_tts.is_local_model_available():
        try:
            k_res = kokoro_tts.synthesize_wav_sync(f"[{prosody_mode}] {clean_text}")
            if k_res.get("ok") and k_res.get("wav_bytes"):
                wav_bytes = condition_or_wrap_wav(k_res["wav_bytes"])
                return {
                    "ok": True,
                    "fallback_browser_tts": False,
                    "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                    "mime_type": "audio/wav",
                    "clean_text": clean_text,
                    "voice": k_res.get("voice", settings.kokoro_voice),
                    "provider": "kokoro-82m-local",
                    "prosody_mode": prosody_mode,
                    "privacy_locked": is_private,
                }
        except Exception:
            pass

    if is_private or not voice_state.neural_tts or not settings.gemini_api_key:
        return {
            "ok": False,
            "fallback_browser_tts": True,
            "privacy_locked": is_private,
            "clean_text": clean_text,
            "prosody_mode": prosody_mode,
            "reason": "privacy_locked_local_tts" if is_private else "browser_tts_selected",
        }

    chosen_voice = (voice_name or voice_state.tts_voice or settings.tts_voice or "Kore").strip()
    try:
        from google import genai  # type: ignore

        client = genai.Client(api_key=settings.gemini_api_key)
        if hasattr(client, "interactions"):
            try:
                interaction = client.interactions.create(
                    model=settings.gemini_tts_model,
                    input=clean_text,
                    response_format={"type": "audio"},
                    generation_config={"speech_config": [{"voice": chosen_voice}]},
                    store=False,
                )
                out_audio = getattr(interaction, "output_audio", None)
                raw_b64 = getattr(out_audio, "data", None) if out_audio is not None else None
                if raw_b64:
                    raw_bytes = base64.b64decode(raw_b64) if isinstance(raw_b64, str) else bytes(raw_b64)
                    wav_bytes = condition_or_wrap_wav(raw_bytes)
                    if is_mutter:
                        wav_bytes = apply_dual_prosody_wav(wav_bytes, prosody_mode="mutter")
                    return {
                        "ok": True,
                        "fallback_browser_tts": False,
                        "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                        "mime_type": "audio/wav",
                        "clean_text": clean_text,
                        "voice": chosen_voice,
                        "provider": settings.gemini_tts_model,
                        "prosody_mode": prosody_mode,
                        "privacy_locked": False,
                    }
            except Exception:
                pass

        # Cascade across Gemini TTS models via `models.generate_content` AUDIO modality
        tts_candidates: List[str] = []
        for tm in (
            settings.gemini_tts_model,
            "gemini-2.5-flash-preview-tts",
            "gemini-2.5-pro-preview-tts",
        ):
            if tm and tm not in tts_candidates:
                tts_candidates.append(tm)

        last_tts_err: Optional[Exception] = None
        for tts_model in tts_candidates:
            try:
                resp = client.models.generate_content(
                    model=tts_model,
                    contents=clean_text,
                    config={
                        "response_modalities": ["AUDIO"],
                        "speech_config": {
                            "voice_config": {"prebuilt_voice_config": {"voice_name": chosen_voice}}
                        },
                    },
                )
                candidates = getattr(resp, "candidates", None) or []
                for cand in candidates:
                    parts = getattr(getattr(cand, "content", None), "parts", None) or []
                    for p in parts:
                        inline = getattr(p, "inline_data", None)
                        if inline and getattr(inline, "data", None):
                            raw_data = inline.data
                            raw_bytes = base64.b64decode(raw_data) if isinstance(raw_data, str) else bytes(raw_data)
                            wav_bytes = condition_or_wrap_wav(raw_bytes)
                            if is_mutter:
                                wav_bytes = apply_dual_prosody_wav(wav_bytes, prosody_mode="mutter")
                            return {
                                "ok": True,
                                "fallback_browser_tts": False,
                                "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                                "mime_type": "audio/wav",
                                "clean_text": clean_text,
                                "voice": chosen_voice,
                                "provider": tts_model,
                                "prosody_mode": prosody_mode,
                                "privacy_locked": False,
                            }
            except Exception as t_exc:
                last_tts_err = t_exc
        if last_tts_err is not None:
            return {
                "ok": False,
                "fallback_browser_tts": True,
                "privacy_locked": False,
                "clean_text": clean_text,
                "prosody_mode": prosody_mode,
                "error": str(last_tts_err),
            }
    except Exception as exc:
        return {
            "ok": False,
            "fallback_browser_tts": True,
            "privacy_locked": False,
            "clean_text": clean_text,
            "prosody_mode": prosody_mode,
            "error": str(exc),
        }

    return {
        "ok": False,
        "fallback_browser_tts": True,
        "privacy_locked": False,
        "clean_text": clean_text,
        "prosody_mode": prosody_mode,
    }


class VoiceState:
    def __init__(self) -> None:
        self.status: str = "IDLE"  # IDLE | LISTENING | THINKING | SPEAKING | MUTED
        self.muted: bool = False
        self.hold_seconds: float = 1.5
        self.hands_free: bool = True
        self.wake_word_only: bool = False
        self.neural_tts: bool = True
        self.stt_provider: str = "hybrid"
        self.tts_voice: str = settings.tts_voice
        self.prosody_mode: str = "normal"
        self.last_transcript: str = "Standing by on Canopy Vault."
        self.last_reply: str = "Ready whenever you are, Jaime."
        self.vu_level: int = 8
        self.last_ui_commands: List[Dict[str, Any]] = []
        self.last_mutter_clauses: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "muted": self.muted,
            "hold_seconds": round(self.hold_seconds, 1),
            "hands_free": self.hands_free,
            "wake_word_only": self.wake_word_only,
            "neural_tts": self.neural_tts,
            "stt_provider": self.stt_provider,
            "tts_voice": self.tts_voice,
            "prosody_mode": self.prosody_mode,
            "vad_threshold": vad_controller.current_threshold,
            "is_thinking_aloud": vad_controller.is_thinking_aloud,
            "last_barge_in_latency_ms": vad_controller.last_barge_in_latency_ms,
            "kokoro_local_ready": kokoro_tts.is_local_model_available(),
            "whisper_local_ready": whisper_stt.is_installed(),
            "last_transcript": self.last_transcript,
            "last_reply": self.last_reply,
            "vu_level": self.vu_level,
            "last_ui_commands": self.last_ui_commands,
            "last_mutter_clauses": self.last_mutter_clauses,
            "vram_telemetry": get_vram_envelope_telemetry(cfg=settings),
        }


voice_state = VoiceState()
voice_ws_clients: List[WebSocket] = []

app = FastAPI(title="KAIROS 2.0 Voice Sidecar", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https?://(127\.0\.0\.1|localhost)(:\d+)?|app://.*)$",
    allow_methods=["*"],
    allow_headers=["*"],
)


class UtteranceInput(BaseModel):
    text: str = ""
    transcript: str = ""
    mode: str = "auto"
    active_note_path: str = ""
    active_task_id: str = ""
    active_browser_url: str = ""
    active_browser_title: str = ""
    session_id: str = ""
    persona: str = "companion"
    tone_mode: str = "DEFAULT"
    project_scope: str = "KAIROS_2_0"
    department_scope: str = "Software_Development"
    current_tab: str = ""
    current_view: str = ""
    synthesize_speech: bool = False
    bypass_wake_word: bool = True

    @model_validator(mode="before")
    @classmethod
    def _accept_transcript_or_prompt_alias(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if not any(k in out for k in ("text", "transcript", "prompt")):
            raise ValueError("Field 'text' or 'transcript' is required")
        if not out.get("text"):
            out["text"] = str(out.get("transcript") or out.get("prompt") or "")
        return out


class VoiceConfigUpdateInput(BaseModel):
    hands_free: Optional[bool] = None
    wake_word_only: Optional[bool] = None
    neural_tts: Optional[bool] = None
    hold_seconds: Optional[float] = None
    tts_voice: Optional[str] = None


class AudioCommandInput(BaseModel):
    audio_base64: str
    mime_type: str = "audio/webm"
    mode: str = "auto"
    active_note_path: str = ""
    active_task_id: str = ""
    active_browser_url: str = ""
    active_browser_title: str = ""
    session_id: str = ""
    persona: str = "companion"
    tone_mode: str = "DEFAULT"
    project_scope: str = "KAIROS_2_0"
    department_scope: str = "Software_Development"
    current_tab: str = ""
    current_view: str = ""
    synthesize_speech: bool = True


class TtsRequestInput(BaseModel):
    text: str
    active_note_path: str = ""
    is_private: bool = False
    voice: str = ""


async def _broadcast_ws_payload(payload: Dict[str, Any]) -> None:
    for ws in list(voice_ws_clients):
        try:
            await ws.send_json(payload)
        except Exception:
            if ws in voice_ws_clients:
                voice_ws_clients.remove(ws)


async def _broadcast_state() -> None:
    await _broadcast_ws_payload(voice_state.to_dict())


def _forward_command_to_core(
    prompt: str,
    *,
    mode: str = "auto",
    active_note_path: str = "",
    active_task_id: str = "",
    active_browser_url: str = "",
    active_browser_title: str = "",
    session_id: str = "",
    persona: str = "companion",
    tone_mode: str = "DEFAULT",
    project_scope: str = "KAIROS_2_0",
    department_scope: str = "Software_Development",
    current_tab: str = "",
    current_view: str = "",
) -> Dict[str, Any]:
    try:
        resp = requests.post(
            f"http://127.0.0.1:{settings.core_port}/api/kairos/command",
            json={
                "prompt": prompt,
                "mode": mode,
                "active_note_path": active_note_path,
                "active_task_id": active_task_id,
                "active_browser_url": active_browser_url,
                "active_browser_title": active_browser_title,
                "session_id": session_id,
                "persona": persona,
                "tone_mode": tone_mode,
                "project_scope": project_scope,
                "department_scope": department_scope,
                "current_tab": current_tab,
                "current_view": current_view,
            },
            timeout=30,
        )
        payload = resp.json()
        if not resp.ok and isinstance(payload, dict) and "reply" not in payload:
            detail = str(payload.get("detail") or f"Core returned HTTP {resp.status_code}")
            return {
                "reply": detail,
                "spoken_reply": detail,
                "agent": "Core-Guard",
                "status_code": resp.status_code,
                "ui_commands": [],
            }
        return payload
    except Exception as exc:
        return {
            "reply": f"Core service unavailable: {exc}",
            "spoken_reply": "Core service is currently unavailable.",
            "agent": "Voice-Fallback",
            "ui_commands": [],
        }


@app.get("/api/voice/state")
def get_voice_state() -> Dict[str, Any]:
    return voice_state.to_dict()


@app.post("/api/voice/config")
async def update_voice_config(req: VoiceConfigUpdateInput) -> Dict[str, Any]:
    if req.hands_free is not None:
        voice_state.hands_free = req.hands_free
    if req.wake_word_only is not None:
        voice_state.wake_word_only = req.wake_word_only
    if req.neural_tts is not None:
        voice_state.neural_tts = req.neural_tts
    if req.hold_seconds is not None:
        voice_state.hold_seconds = max(0.8, min(5.5, float(req.hold_seconds)))
    if req.tts_voice is not None and req.tts_voice.strip():
        voice_state.tts_voice = req.tts_voice.strip()
    await _broadcast_state()
    return voice_state.to_dict()


@app.post("/api/voice/play")
async def start_listening() -> Dict[str, Any]:
    voice_state.muted = False
    voice_state.status = "LISTENING"
    voice_state.vu_level = 34
    await _broadcast_state()
    return voice_state.to_dict()


@app.post("/api/voice/pause")
async def pause_listening() -> Dict[str, Any]:
    voice_state.muted = True
    voice_state.status = "MUTED"
    voice_state.vu_level = 0
    await _broadcast_state()
    return voice_state.to_dict()


@app.get("/api/voice/telemetry")
def get_voice_telemetry() -> Dict[str, Any]:
    """Return Cognitive Full-Duplex Voice telemetry (VAD sensitivity, 16 GB VRAM budget & local TTS/STT status)."""
    return {
        "ok": True,
        "vad": vad_controller.to_dict(),
        "prosody_mode": voice_state.prosody_mode,
        "kokoro_local_ready": kokoro_tts.is_local_model_available(),
        "whisper_local_ready": whisper_stt.is_installed(),
        "vram_telemetry": get_vram_envelope_telemetry(cfg=settings),
        "timers": {
            "lag_threshold_sec": settings.lag_threshold_sec,
            "prefill_watchdog_sec": settings.prefill_watchdog_sec,
            "thought_cadence_sec": settings.thought_cadence_sec,
            "cloud_timeout_sec": settings.cloud_timeout_sec,
        },
    }


@app.post("/api/voice/stop")
async def stop_speech_and_barge_in() -> Dict[str, Any]:
    barge = vad_controller.handle_user_started_speaking()
    voice_state.prosody_mode = "normal"
    voice_state.status = "IDLE"
    voice_state.vu_level = 6
    await _broadcast_state()
    return {**voice_state.to_dict(), "barge_in": barge}


@app.post("/api/voice/barge-in")
async def trigger_barge_in_endpoint() -> Dict[str, Any]:
    """Full-duplex `<80ms` user speech interruption: flushes TTS queues & restores normal VAD (`0.50`)."""
    barge = vad_controller.handle_user_started_speaking()
    voice_state.prosody_mode = "normal"
    voice_state.status = "MUTED" if voice_state.muted else "LISTENING"
    voice_state.vu_level = 38 if not voice_state.muted else 0
    snap = voice_state.to_dict()
    await _broadcast_ws_payload({"event": "voice_barge_in", **snap, "barge_in": barge})
    return {**snap, "barge_in": barge}


@app.post("/api/voice/extend-hold")
async def extend_thinking_hold() -> Dict[str, Any]:
    voice_state.hold_seconds = min(5.5, voice_state.hold_seconds + 1.0)
    await _broadcast_state()
    return voice_state.to_dict()


@app.post("/api/voice/utterance")
async def process_spoken_utterance(req: UtteranceInput) -> Dict[str, Any]:
    sanitized_in = _sanitize_stt_transcript(req.text)
    if not sanitized_in:
        return {
            **voice_state.to_dict(),
            "wake_word_ignored": True,
            "core_response": None,
            "tts": None,
        }
    triggered, effective_text = check_wake_word(
        sanitized_in,
        wake_word_only=(voice_state.wake_word_only and not req.bypass_wake_word),
    )
    if not triggered:
        return {
            **voice_state.to_dict(),
            "wake_word_ignored": True,
            "core_response": None,
            "tts": None,
        }

    voice_state.last_transcript = effective_text
    voice_state.status = "THINKING"
    await _broadcast_state()

    data = _forward_command_to_core(
        effective_text,
        mode=req.mode,
        active_note_path=req.active_note_path,
        active_task_id=req.active_task_id,
        active_browser_url=req.active_browser_url,
        active_browser_title=req.active_browser_title,
        session_id=req.session_id,
        persona=req.persona,
        tone_mode=req.tone_mode,
        project_scope=req.project_scope,
        department_scope=req.department_scope,
        current_tab=req.current_tab,
        current_view=req.current_view,
    )
    voice_state.last_reply = str(data.get("reply") or "")
    voice_state.last_ui_commands = list(data.get("ui_commands") or [])
    voice_state.last_mutter_clauses = list(data.get("mutter_clauses") or [])

    if voice_state.last_mutter_clauses:
        voice_state.prosody_mode = "mutter"
        vad_controller.set_thinking_aloud_vad_sensitivity(True)
        await _broadcast_ws_payload(
            {
                **voice_state.to_dict(),
                "event": "cognitive_mutter",
                "mutter_clauses": voice_state.last_mutter_clauses,
            }
        )
        vad_controller.set_thinking_aloud_vad_sensitivity(False)
        voice_state.prosody_mode = "normal"

    tts_payload: Optional[Dict[str, Any]] = None
    if req.synthesize_speech and voice_state.last_reply:
        is_priv = bool(data.get("privacy_locked")) or is_voice_context_private(
            req.active_note_path, effective_text
        )
        spoken_src = str(data.get("spoken_reply") or voice_state.last_reply)
        tts_payload = synthesize_tts_wav(f"[normal] {spoken_src}", is_private=is_priv)

    voice_state.status = (
        "MUTED"
        if voice_state.muted
        else ("LISTENING" if voice_state.hands_free else "IDLE")
    )
    await _broadcast_state()
    return {**voice_state.to_dict(), "core_response": data, "tts": tts_payload}


@app.post("/api/voice/audio-command")
async def process_recorded_audio_command(req: AudioCommandInput) -> Dict[str, Any]:
    """Full Dual-Engine Voice Turn: Audio Blob -> STT (`gemini-3.5-transcribe` / Privacy Lock) -> Core `:8420` -> Neural TTS."""
    max_b64_chars = (MAX_AUDIO_PAYLOAD_BYTES * 4) // 3 + 1024
    if len(req.audio_base64 or "") > max_b64_chars:
        raise HTTPException(status_code=413, detail="Audio payload exceeds 15 MB limit")
    try:
        audio_bytes = base64.b64decode(req.audio_base64)
    except Exception:
        audio_bytes = b""
    if len(audio_bytes) > MAX_AUDIO_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio payload exceeds 15 MB limit")

    is_priv_ctx = is_voice_context_private(req.active_note_path)
    voice_state.status = "THINKING"
    await _broadcast_state()

    stt_res = transcribe_audio_bytes(
        audio_bytes,
        mime_type=req.mime_type,
        is_private=is_priv_ctx,
    )
    transcript = str(stt_res.get("text") or "").strip()
    if not stt_res.get("ok") or not transcript:
        voice_state.status = (
            "MUTED"
            if voice_state.muted
            else ("LISTENING" if voice_state.hands_free else "IDLE")
        )
        await _broadcast_state()
        return {
            **voice_state.to_dict(),
            "transcript": "",
            "no_speech": bool(stt_res.get("no_speech")),
            "stt": stt_res,
            "core_response": None,
            "tts": None,
        }

    triggered, effective_text = check_wake_word(transcript, voice_state.wake_word_only)
    if not triggered:
        voice_state.status = "LISTENING" if not voice_state.muted else "MUTED"
        await _broadcast_state()
        return {
            **voice_state.to_dict(),
            "transcript": transcript,
            "wake_word_ignored": True,
            "stt": stt_res,
            "core_response": None,
            "tts": None,
        }

    voice_state.last_transcript = effective_text
    await _broadcast_state()

    data = _forward_command_to_core(
        effective_text,
        mode=req.mode,
        active_note_path=req.active_note_path,
        active_task_id=req.active_task_id,
        active_browser_url=req.active_browser_url,
        active_browser_title=req.active_browser_title,
        session_id=req.session_id,
        persona=req.persona,
        tone_mode=req.tone_mode,
        project_scope=req.project_scope,
        department_scope=req.department_scope,
        current_tab=req.current_tab,
        current_view=req.current_view,
    )
    voice_state.last_reply = str(data.get("reply") or "")
    voice_state.last_ui_commands = list(data.get("ui_commands") or [])
    voice_state.last_mutter_clauses = list(data.get("mutter_clauses") or [])

    if voice_state.last_mutter_clauses:
        voice_state.prosody_mode = "mutter"
        vad_controller.set_thinking_aloud_vad_sensitivity(True)
        await _broadcast_ws_payload(
            {
                **voice_state.to_dict(),
                "event": "cognitive_mutter",
                "mutter_clauses": voice_state.last_mutter_clauses,
            }
        )
        vad_controller.set_thinking_aloud_vad_sensitivity(False)
        voice_state.prosody_mode = "normal"

    tts_payload: Optional[Dict[str, Any]] = None
    if req.synthesize_speech and voice_state.last_reply:
        is_priv_final = (
            is_priv_ctx
            or bool(data.get("privacy_locked"))
            or is_voice_context_private(req.active_note_path, effective_text)
        )
        spoken_src = str(data.get("spoken_reply") or voice_state.last_reply)
        tts_payload = synthesize_tts_wav(f"[normal] {spoken_src}", is_private=is_priv_final)

    voice_state.status = (
        "MUTED"
        if voice_state.muted
        else ("LISTENING" if voice_state.hands_free else "IDLE")
    )
    await _broadcast_state()
    return {
        **voice_state.to_dict(),
        "transcript": effective_text,
        "stt": stt_res,
        "core_response": data,
        "tts": tts_payload,
    }


@app.post("/api/voice/tts")
async def synthesize_speech_endpoint(req: TtsRequestInput) -> Dict[str, Any]:
    is_priv = req.is_private or is_voice_context_private(req.active_note_path, req.text)
    return synthesize_tts_wav(req.text, is_private=is_priv, voice_name=req.voice)


@app.websocket("/ws/voice")
async def ws_voice_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    voice_ws_clients.append(ws)
    try:
        await ws.send_json(voice_state.to_dict())
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if ws in voice_ws_clients:
            voice_ws_clients.remove(ws)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=settings.voice_port)

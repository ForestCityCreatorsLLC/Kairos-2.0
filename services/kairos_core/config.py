"""Centralized configuration for KAIROS 2.0 (`services/kairos_core/config.py`)."""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = _REPO_ROOT
load_dotenv(_REPO_ROOT / ".env", override=True)

DEFAULT_CANOPY_VAULT = "C:/Users/igxxg/OneDrive/Documents/FCC Business Docs/Canopy Vault"

# Immutable Index-0 System Prompt Contract for >90% LM Studio KV Prefix Cache Hit Rate
STATIC_VOICE_SYSTEM_PROMPT: str = (
    "Act as a fast, lifelike, full-duplex voice assistant. "
    "Respond in natural, concise spoken sentences without markdown bullet points, numbered lists, "
    "or code blocks unless explicitly requested. "
    "When deliberating inside <think>...</think> tags, formulate internal thoughts as brief, natural, "
    "conversational musings (for example: \"Hmm, tracing how the billing router handles that timeout... "
    "checking the retry loop now.\") because prolonged deliberation is spoken softly aloud to keep the "
    "conversation fluid. Never repeat the <think> content in the final spoken answer."
)


def _clean_env(name: str, fallback_name: str = "", default: str = "") -> str:
    raw = os.environ.get(name, "")
    if not raw and fallback_name:
        raw = os.environ.get(fallback_name, "")
    if not raw:
        targets = {name.lower()}
        if fallback_name:
            targets.add(fallback_name.lower())
        for k, v in os.environ.items():
            if k.lower() in targets and v:
                raw = v
                break
    val = (raw or default).strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        val = val[1:-1].strip()
    return val


def _safe_env_int(name: str, default: int) -> int:
    raw = _clean_env(name, default=str(default))
    cleaned = raw.split("#", 1)[0].strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
        cleaned = cleaned[1:-1].strip()
    try:
        return int(cleaned)
    except (TypeError, ValueError):
        return default


def _safe_env_float(name: str, default: float) -> float:
    raw = _clean_env(name, default=str(default))
    cleaned = raw.split("#", 1)[0].strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
        cleaned = cleaned[1:-1].strip()
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return default


class KairosSettings:
    """Clean, environment-driven settings with zero cross-project bleed."""

    def __init__(
        self,
        vault_path: Path | str | None = None,
        gemini_api_key: str | None = None,
        lmstudio_base_url: str | None = None,
        lmstudio_model: str | None = None,
        cloud_timeout_sec: float | None = None,
    ) -> None:
        raw_vault = (
            str(vault_path)
            if vault_path is not None
            else _clean_env("KAIROS_VAULT_PATH", default=DEFAULT_CANOPY_VAULT)
        )
        self.vault_path: Path = Path(raw_vault)
        self.operator_name: str = _clean_env("KAIROS_OPERATOR_NAME", default="Jaime Flores")

        self.lmstudio_base_url: str = (
            lmstudio_base_url
            if lmstudio_base_url is not None
            else _clean_env("LMSTUDIO_BASE_URL", default="http://127.0.0.1:1234/v1")
        ).rstrip("/")
        self.lmstudio_model: str = (
            lmstudio_model
            if lmstudio_model is not None
            else _clean_env("LMSTUDIO_MODEL", default="gemma-4")
        )

        self.gemini_api_key: str = (
            gemini_api_key
            if gemini_api_key is not None
            else _clean_env("GEMINI_API_KEY", fallback_name="GOOGLE_API_KEY", default="")
        )
        self.gemini_model: str = _clean_env("GEMINI_MODEL", default="gemini-2.5-flash")
        self.gemini_stt_model: str = _clean_env("GEMINI_STT_MODEL", default="gemini-2.5-flash")
        self.gemini_tts_model: str = _clean_env(
            "GEMINI_TTS_MODEL", default="gemini-2.5-flash-preview-tts"
        )
        self.tts_voice: str = _clean_env("KAIROS_TTS_VOICE", default="Kore")

        self.google_oauth_credentials: str = _clean_env(
            "GOOGLE_OAUTH_CREDENTIALS_PATH", default="credentials.json"
        )
        self.google_oauth_token: str = _clean_env("GOOGLE_OAUTH_TOKEN_PATH", default="token.json")
        self.github_token: str = _clean_env("GITHUB_TOKEN", default="")
        self.github_username: str = _clean_env(
            "GitHub_Username", fallback_name="GITHUB_USERNAME", default=""
        )
        self.github_password: str = _clean_env(
            "GitHub_Password", fallback_name="GITHUB_PASSWORD", default=""
        )

        self.tomorrow_io_api_key: str = _clean_env(
            "TOMORROW_IO_API_KEY", fallback_name="Tomorrow", default=""
        )
        self.owm_api_key: str = _clean_env("OWM_API_KEY", default="")
        self.owm_base_url: str = _clean_env(
            "OWM_BASE_URL", default="https://api.openweathermap.org/data/2.5/weather"
        ).rstrip("?")
        self.default_city: str = _clean_env("KAIROS_DEFAULT_CITY", default="Cleveland,US")

        self.sendiio_api_key: str = _clean_env("SENDIIO_API_KEY", default="")
        self.sendiio_api_secret: str = _clean_env("SENDIIO_API_SECRET", default="")

        self.discord_bot_token: str = _clean_env("DISCORD_BOT_TOKEN", default="")
        self.discord_channel_id: str = _clean_env("DISCORD_CHANNEL_ID", default="")
        self.discord_authorized_user_id: str = _clean_env("DISCORD_AUTHORIZED_USER_ID", default="")
        self.discord_webhook_url: str = _clean_env("DISCORD_WEBHOOK_URL", default="")

        self.huggingface_api_key: str = _clean_env(
            "HUGGINGFACE_API_KEY", fallback_name="Hugging_Face", default=""
        )
        self.printful_api_key: str = _clean_env("PRINTFUL_API_KEY", default="")

        self.core_port: int = _safe_env_int("KAIROS_CORE_PORT", 8420)
        self.voice_port: int = _safe_env_int("KAIROS_VOICE_PORT", 8421)

        # Full-Duplex Cognitive Voice Pipeline & Latency Envelope Settings
        self.static_voice_system_prompt: str = STATIC_VOICE_SYSTEM_PROMPT
        self.lag_threshold_sec: float = _safe_env_float("LAG_THRESHOLD_SEC", 0.50)
        self.prefill_watchdog_sec: float = _safe_env_float("PREFILL_WATCHDOG_SEC", 0.55)
        self.thought_cadence_sec: float = _safe_env_float("THOUGHT_CADENCE_SEC", 3.20)
        self.cloud_timeout_sec: float = (
            float(cloud_timeout_sec)
            if cloud_timeout_sec is not None
            else _safe_env_float("CLOUD_TIMEOUT_SEC", 3.0)
        )
        self.audio_input_sample_rate: int = _safe_env_int("AUDIO_INPUT_SAMPLE_RATE", 16000)
        self.audio_output_sample_rate: int = _safe_env_int("AUDIO_OUTPUT_SAMPLE_RATE", 24000)
        self.kokoro_voice: str = _clean_env("KOKORO_VOICE", default="af_heart")
        self.kokoro_model_path: str = _clean_env(
            "KOKORO_MODEL_PATH", default="models/kokoro-v1.0.onnx"
        )
        self.kokoro_voices_path: str = _clean_env(
            "KOKORO_VOICES_PATH", default="models/voices-v1.0.bin"
        )
        self.whisper_model_size: str = _clean_env("WHISPER_MODEL_SIZE", default="large-v3-turbo")
        self.vram_ceiling_gb: float = _safe_env_float("KAIROS_VRAM_CEILING_GB", 11.86)

    @property
    def episodic_db_path(self) -> Path:
        return self.vault_path / "_System" / "Cache" / "episodic_memory.sqlite"

    @property
    def shadow_db_path(self) -> Path:
        return self.vault_path / "_System" / "Cache" / "vault_index.sqlite"

    @property
    def audit_log_path(self) -> Path:
        return self.vault_path / "_System" / "Logs" / "AI_Audit_Log.jsonl"


settings = KairosSettings()

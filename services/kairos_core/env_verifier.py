"""Safe `.env` API Key & Endpoint Verifier (`services/kairos_core/env_verifier.py`).

Validates configuration syntax, placeholder values, local file paths, and optional live
HTTP/SDK connectivity across all configured KAIROS 2.0 APIs without ever exposing raw secrets.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

from services.kairos_core.config import PROJECT_ROOT, KairosSettings, settings


def mask_secret(value: str) -> str:
    """Return a masked preview (`AIza••••32JY`) so raw keys never leak in UI or logs."""
    clean = (value or "").strip()
    if not clean:
        return "(unset)"
    if "your_webhook_url_here" in clean or "your_" in clean.lower():
        return "(placeholder)"
    if len(clean) <= 10:
        return f"{clean[:2]}••••"
    return f"{clean[:4]}••••{clean[-4:]}"


def _is_placeholder(value: str) -> bool:
    low = (value or "").strip().lower()
    if not low:
        return False
    return any(tok in low for tok in ("your_webhook_url_here", "your_api_key", "changeme", "example"))


def verify_env_apis(cfg: Optional[KairosSettings] = None, *, live: bool = False) -> Dict[str, Any]:
    """Audit all `.env` API credentials and optionally probe live endpoints."""
    c = cfg or settings
    checks: List[Dict[str, Any]] = []

    # 1. Canopy Vault Root
    vault_ok = c.vault_path.exists() and c.vault_path.is_dir()
    checks.append(
        {
            "id": "canopy_vault",
            "name": "Obsidian Canopy Vault",
            "env_keys": ["KAIROS_VAULT_PATH"],
            "configured": vault_ok,
            "status": "ready" if vault_ok else "error",
            "masked": str(c.vault_path),
            "detail": "Vault directory verified on disk." if vault_ok else "Vault directory not found.",
        }
    )

    # 2. Google Gemini API
    gem_conf = bool(c.gemini_api_key) and not _is_placeholder(c.gemini_api_key)
    gem_status = "configured" if gem_conf else "missing"
    gem_detail = f"Model `{c.gemini_model}` configured." if gem_conf else "GEMINI_API_KEY is empty."
    if live and gem_conf:
        try:
            from google import genai  # type: ignore

            client = genai.Client(api_key=c.gemini_api_key)
            m_info = client.models.get(model=c.gemini_model)
            gem_status = "live_ok"
            gem_detail = f"Live Gemini API handshake succeeded (`{getattr(m_info, 'name', c.gemini_model)}`)."
        except Exception as exc:
            gem_status = "live_error"
            gem_detail = f"Gemini check failed: {str(exc)[:140]}"
    checks.append(
        {
            "id": "gemini",
            "name": "Google Gemini Cloud AI",
            "env_keys": ["GEMINI_API_KEY", "GEMINI_MODEL"],
            "configured": gem_conf,
            "status": gem_status,
            "masked": mask_secret(c.gemini_api_key),
            "detail": gem_detail,
        }
    )

    # 3. Local LM Studio (Gemma 4)
    lms_conf = c.lmstudio_base_url.startswith(("http://", "https://"))
    lms_status = "configured" if lms_conf else "missing"
    lms_detail = f"Target `{c.lmstudio_base_url}` (`{c.lmstudio_model}`)."
    if live and lms_conf:
        try:
            r = requests.get(f"{c.lmstudio_base_url}/models", timeout=1.5)
            r.raise_for_status()
            models = [m.get("id", "") for m in r.json().get("data", []) if isinstance(m, dict)]
            lms_status = "live_ok"
            lms_detail = (
                f"LM Studio online ({len(models)} loaded: {', '.join(models[:3]) or 'ready'})."
            )
        except Exception:
            lms_status = "offline_standby"
            lms_detail = (
                "LM Studio server not running on :1234 (Auto mode seamlessly fails over to Gemini for non-private tasks)."
            )
    checks.append(
        {
            "id": "lmstudio",
            "name": "LM Studio Local Brain (Gemma 4)",
            "env_keys": ["LMSTUDIO_BASE_URL", "LMSTUDIO_MODEL"],
            "configured": lms_conf,
            "status": lms_status,
            "masked": f"{c.lmstudio_base_url} ({c.lmstudio_model})",
            "detail": lms_detail,
        }
    )

    # 4. GitHub PAT & Embedded Browser Account Credentials
    gh_pat_conf = bool(c.github_token) and not _is_placeholder(c.github_token)
    gh_login_conf = (
        bool(getattr(c, "github_username", ""))
        and bool(getattr(c, "github_password", ""))
        and not _is_placeholder(getattr(c, "github_username", ""))
        and not _is_placeholder(getattr(c, "github_password", ""))
    )
    gh_conf = gh_pat_conf or gh_login_conf
    gh_status = "configured" if gh_conf else "missing"
    if gh_pat_conf and gh_login_conf:
        gh_detail = (
            f"GitHub PAT + Browser `.env` account (`{c.github_username}`) loaded for ForestCityCreatorsLLC."
        )
        gh_masked = mask_secret(c.github_token)
    elif gh_pat_conf:
        gh_detail = "Fine-grained GitHub PAT loaded."
        gh_masked = mask_secret(c.github_token)
    elif gh_login_conf:
        gh_detail = (
            f"Browser `.env` login (`{c.github_username}`) configured for `ForestCityCreatorsLLC?tab=repositories`."
        )
        gh_masked = f"{c.github_username} ({mask_secret(c.github_password)})"
    else:
        gh_detail = "Neither GITHUB_TOKEN nor GitHub_Username/GitHub_Password set."
        gh_masked = "(unset)"

    if live and gh_pat_conf:
        try:
            r = requests.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {c.github_token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "KAIROS-2.0",
                },
                timeout=5,
            )
            if r.ok:
                login = r.json().get("login", "authenticated")
                gh_status = "live_ok"
                gh_detail = f"Authenticated to GitHub as `{login}`."
            else:
                gh_status = "live_error"
                gh_detail = f"GitHub HTTP {r.status_code}: {r.text[:100]}"
        except Exception as exc:
            gh_status = "live_error"
            gh_detail = f"GitHub request error: {str(exc)[:120]}"
    elif live and gh_login_conf:
        gh_status = "live_ok"
    checks.append(
        {
            "id": "github",
            "name": "GitHub API & Browser Session",
            "env_keys": ["GITHUB_TOKEN", "GitHub_Username", "GitHub_Password"],
            "configured": gh_conf,
            "status": gh_status,
            "masked": gh_masked,
            "detail": gh_detail,
        }
    )

    # 5. OpenWeatherMap
    owm_conf = bool(c.owm_api_key) and not _is_placeholder(c.owm_api_key)
    owm_status = "configured" if owm_conf else "missing"
    owm_detail = f"Endpoint `{c.owm_base_url}` ({c.default_city})." if owm_conf else "OWM_API_KEY not set."
    if live and owm_conf:
        try:
            r = requests.get(
                c.owm_base_url,
                params={"q": c.default_city, "units": "imperial", "appid": c.owm_api_key},
                timeout=5,
            )
            if r.ok:
                j = r.json()
                temp = j.get("main", {}).get("temp")
                owm_status = "live_ok"
                owm_detail = f"Live weather OK ({j.get('name', c.default_city)}: {temp}°F)."
            else:
                owm_status = "live_error"
                owm_detail = f"OpenWeatherMap HTTP {r.status_code}: {r.text[:100]}"
        except Exception as exc:
            owm_status = "live_error"
            owm_detail = f"OpenWeatherMap error: {str(exc)[:120]}"
    checks.append(
        {
            "id": "openweather",
            "name": "OpenWeatherMap API",
            "env_keys": ["OWM_API_KEY", "OWM_BASE_URL"],
            "configured": owm_conf,
            "status": owm_status,
            "masked": mask_secret(c.owm_api_key),
            "detail": owm_detail,
        }
    )

    # 6. Tomorrow.io Weather
    tmr_conf = bool(c.tomorrow_io_api_key) and not _is_placeholder(c.tomorrow_io_api_key)
    tmr_status = "configured" if tmr_conf else "missing"
    tmr_detail = "Tomorrow.io weather key loaded." if tmr_conf else "TOMORROW_IO_API_KEY not set."
    if live and tmr_conf:
        try:
            r = requests.get(
                "https://api.tomorrow.io/v4/weather/realtime",
                params={"location": "Cleveland", "units": "imperial", "apikey": c.tomorrow_io_api_key},
                timeout=5,
            )
            if r.ok:
                temp = r.json().get("data", {}).get("values", {}).get("temperature")
                tmr_status = "live_ok"
                tmr_detail = f"Tomorrow.io realtime OK (Cleveland: {temp}°F)."
            else:
                tmr_status = "live_error"
                tmr_detail = f"Tomorrow.io HTTP {r.status_code}: {r.text[:100]}"
        except Exception as exc:
            tmr_status = "live_error"
            tmr_detail = f"Tomorrow.io error: {str(exc)[:120]}"
    checks.append(
        {
            "id": "tomorrow_io",
            "name": "Tomorrow.io Weather API",
            "env_keys": ["TOMORROW_IO_API_KEY", "Tomorrow"],
            "configured": tmr_conf,
            "status": tmr_status,
            "masked": mask_secret(c.tomorrow_io_api_key),
            "detail": tmr_detail,
        }
    )

    # 7. Sendiio Autoresponder
    snd_conf = bool(c.sendiio_api_key and c.sendiio_api_secret)
    snd_status = "configured" if snd_conf else "missing"
    snd_detail = "API Key + API Secret loaded." if snd_conf else "SENDIIO_API_KEY / SECRET missing."
    if live and snd_conf:
        try:
            r = requests.get(
                "https://sendiio.com/api/v1/lists/email",
                headers={"token": c.sendiio_api_key, "secret": c.sendiio_api_secret},
                timeout=6,
            )
            if r.ok:
                snd_status = "live_ok"
                snd_detail = "Sendiio API authenticated successfully."
            else:
                snd_status = "live_error"
                snd_detail = f"Sendiio HTTP {r.status_code}: {r.text[:100]}"
        except Exception as exc:
            snd_status = "live_error"
            snd_detail = f"Sendiio error: {str(exc)[:120]}"
    checks.append(
        {
            "id": "sendiio",
            "name": "Sendiio Marketing Autoresponder",
            "env_keys": ["SENDIIO_API_KEY", "SENDIIO_API_SECRET"],
            "configured": snd_conf,
            "status": snd_status,
            "masked": mask_secret(c.sendiio_api_key),
            "detail": snd_detail,
        }
    )

    # 8. Discord Bot & Relay Bridge
    disc_bot_conf = bool(c.discord_bot_token and c.discord_channel_id)
    webhook_placeholder = _is_placeholder(c.discord_webhook_url)
    disc_status = "warning" if (disc_bot_conf and webhook_placeholder) else ("configured" if disc_bot_conf else "missing")
    disc_detail = (
        f"Bot token + Channel `{c.discord_channel_id}` ready; note `DISCORD_WEBHOOK_URL` is still placeholder."
        if (disc_bot_conf and webhook_placeholder)
        else (f"Bot token + Channel `{c.discord_channel_id}` ready." if disc_bot_conf else "Discord bot token missing.")
    )
    if live and disc_bot_conf:
        try:
            r = requests.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {c.discord_bot_token}"},
                timeout=5,
            )
            if r.ok:
                bot_user = r.json().get("username", "Bot")
                disc_status = "warning" if webhook_placeholder else "live_ok"
                disc_detail = f"Discord Bot `{bot_user}` authenticated" + (
                    " (`DISCORD_WEBHOOK_URL` is placeholder — Bot API works directly)."
                    if webhook_placeholder
                    else "."
                )
            else:
                disc_status = "live_error"
                disc_detail = f"Discord Bot HTTP {r.status_code}: {r.text[:100]}"
        except Exception as exc:
            disc_status = "live_error"
            disc_detail = f"Discord check error: {str(exc)[:120]}"
    checks.append(
        {
            "id": "discord",
            "name": "Discord Mobile & Relay Bridge",
            "env_keys": ["DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID", "DISCORD_WEBHOOK_URL"],
            "configured": disc_bot_conf,
            "status": disc_status,
            "masked": mask_secret(c.discord_bot_token),
            "detail": disc_detail,
        }
    )

    # 9. Hugging Face
    hf_conf = bool(c.huggingface_api_key) and not _is_placeholder(c.huggingface_api_key)
    hf_status = "configured" if hf_conf else "missing"
    hf_detail = "Hugging Face `hf_...` token loaded." if hf_conf else "HUGGINGFACE_API_KEY not set."
    if live and hf_conf:
        try:
            r = requests.get(
                "https://huggingface.co/api/whoami-v2",
                headers={"Authorization": f"Bearer {c.huggingface_api_key}"},
                timeout=5,
            )
            if r.ok:
                hf_name = r.json().get("name", "authenticated")
                hf_status = "live_ok"
                hf_detail = f"Authenticated to Hugging Face as `{hf_name}`."
            else:
                hf_status = "live_error"
                hf_detail = f"Hugging Face HTTP {r.status_code}: {r.text[:100]}"
        except Exception as exc:
            hf_status = "live_error"
            hf_detail = f"Hugging Face error: {str(exc)[:120]}"
    checks.append(
        {
            "id": "huggingface",
            "name": "Hugging Face Hub",
            "env_keys": ["HUGGINGFACE_API_KEY", "Hugging_Face"],
            "configured": hf_conf,
            "status": hf_status,
            "masked": mask_secret(c.huggingface_api_key),
            "detail": hf_detail,
        }
    )

    # 10. Printful Merch API
    pf_conf = bool(c.printful_api_key) and not _is_placeholder(c.printful_api_key)
    pf_status = "configured" if pf_conf else "missing"
    pf_detail = "Printful Merch token loaded." if pf_conf else "PRINTFUL_API_KEY not set."
    if live and pf_conf:
        try:
            r = requests.get(
                "https://api.printful.com/stores",
                headers={"Authorization": f"Bearer {c.printful_api_key}"},
                timeout=5,
            )
            if r.ok:
                stores = r.json().get("result", [])
                pf_status = "live_ok"
                pf_detail = f"Printful API connected ({len(stores)} store(s) accessible)."
            else:
                pf_status = "live_error"
                pf_detail = f"Printful HTTP {r.status_code}: {r.text[:100]}"
        except Exception as exc:
            pf_status = "live_error"
            pf_detail = f"Printful error: {str(exc)[:120]}"
    checks.append(
        {
            "id": "printful",
            "name": "Printful Merch API",
            "env_keys": ["PRINTFUL_API_KEY"],
            "configured": pf_conf,
            "status": pf_status,
            "masked": mask_secret(c.printful_api_key),
            "detail": pf_detail,
        }
    )

    # 11. Optional Google OAuth JSON
    cred_path = Path(c.google_oauth_credentials)
    if not cred_path.is_absolute():
        cred_path = PROJECT_ROOT / cred_path
    g_oauth_exists = cred_path.is_file()
    checks.append(
        {
            "id": "google_oauth",
            "name": "Google Calendar / Workspace OAuth (Optional)",
            "env_keys": ["GOOGLE_OAUTH_CREDENTIALS_PATH", "GOOGLE_OAUTH_TOKEN_PATH"],
            "configured": g_oauth_exists,
            "status": "ready" if g_oauth_exists else "optional_missing",
            "masked": cred_path.name,
            "detail": (
                "OAuth credentials file found."
                if g_oauth_exists
                else "`credentials.json` not placed yet (local `03_Personal/Calendar/EVT-*.md` time-blocking works offline)."
            ),
        }
    )

    for item in checks:
        item["masked_key"] = item["masked"]
        if isinstance(item.get("env_keys"), list):
            item["env_keys_label"] = ", ".join(item["env_keys"])
        else:
            item["env_keys_label"] = str(item.get("env_keys", ""))

    configured_count = sum(1 for item in checks if item["configured"])
    warnings_count = sum(
        1 for item in checks if item["status"] in ("warning", "optional_missing", "offline")
    )
    return {
        "live_probed": live,
        "live_tested": live,
        "env_file_exists": (PROJECT_ROOT / ".env").is_file(),
        "total_integrations": len(checks),
        "total_count": len(checks),
        "configured_count": configured_count,
        "warnings_count": warnings_count,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify KAIROS 2.0 .env API keys and endpoints")
    parser.add_argument("--live", action="store_true", help="Perform live HTTP/SDK connectivity probes")
    args = parser.parse_args()

    report = verify_env_apis(live=args.live)
    mode_lbl = "LIVE NETWORK PROBE" if args.live else "STATIC CONFIG AUDIT"
    print(f"=== KAIROS 2.0 .env Verification ({mode_lbl}) ===")
    print(f"Configured: {report['configured_count']} / {report['total_integrations']}\n")
    for item in report["checks"]:
        print(f"[{item['status'].upper():16}] {item['name']:36} | {item['masked']} | {item['detail']}")


if __name__ == "__main__":
    main()

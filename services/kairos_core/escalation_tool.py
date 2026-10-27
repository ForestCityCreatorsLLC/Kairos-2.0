"""Self-Escalation Tool Handler (`delegate_to_gemini`) for Local Gemma 4 12B (`escalation_tool.py`).

Allows local `google/gemma-4-12b` to escalate complex web-grounding or frontier reasoning queries
to Cloud `Gemini` while enforcing Canopy Vault's `#private` / `03_Personal/Finance/` zero-leak firewall.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.kairos_core.llm_cloud import CloudGeminiLLMService
from services.kairos_core.llm_local import LocalGemma4LLMService


DELEGATE_TO_GEMINI_SCHEMA: Dict[str, Any] = {
    "name": "delegate_to_gemini",
    "description": (
        "Escalate a non-private query to Cloud Gemini 2.5 Flash when real-time Google Search grounding "
        "or large-context cloud synthesis is required."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Self-contained public query to evaluate on Cloud Gemini.",
            },
            "require_web_search": {
                "type": "boolean",
                "description": "True when live Google Search grounding should be enabled.",
            },
        },
        "required": ["query", "require_web_search"],
    },
    "cancel_on_interruption": False,
}


def delegate_to_gemini(
    query: str,
    require_web_search: bool = True,
    *,
    cloud_llm: CloudGeminiLLMService,
    local_llm: Optional[LocalGemma4LLMService] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    is_private: bool = False,
    active_note_path: str = "",
) -> Dict[str, Any]:
    """Execute self-escalation to Cloud Gemini with `#private` hard-lock & `3.0s` fallback protection."""
    norm_path = (active_note_path or "").replace("\\", "/").lower().strip("/")
    if is_private or "#private" in (query or "").lower() or norm_path.startswith("03_personal/finance"):
        return {
            "ok": False,
            "escalated": False,
            "privacy_locked": True,
            "agent": "Gemma-4-Privacy-Shield",
            "reason": "privacy_hard_lock_blocked_escalation",
            "text": "Cloud escalation blocked: `#private` or `03_Personal/Finance/` context stays strictly on Local Gemma 4.",
        }

    cloud_res = cloud_llm.complete_chat(
        query,
        history=history,
        require_web_search=require_web_search,
    )
    if cloud_res.get("ok"):
        return {
            "ok": True,
            "escalated": True,
            "privacy_locked": False,
            "agent": "Gemini-Pro (Delegated)",
            "reason": "delegated_to_gemini_cloud",
            "text": cloud_res["text"],
            "latency_ms": cloud_res.get("latency_ms", 0),
        }

    # Circuit-breaker fallback to local Gemma 4 if cloud timed out or errored
    if local_llm is not None:
        fb = local_llm.complete_chat(query, history=history)
        return {
            "ok": bool(fb.get("ok")),
            "escalated": False,
            "privacy_locked": False,
            "agent": "Gemma-4 (Escalation-Fallback)",
            "reason": "cloud_timeout_fallback_to_local" if cloud_res.get("timed_out") else "cloud_error_fallback_to_local",
            "text": fb.get("text", ""),
            "latency_ms": fb.get("latency_ms", 0),
        }

    return {
        "ok": False,
        "escalated": False,
        "privacy_locked": False,
        "agent": "Gemini-Pro",
        "reason": "cloud_escalation_failed",
        "text": cloud_res.get("text", ""),
    }

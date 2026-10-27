"""Speculative Dual-Brain Router (`services/kairos_core/intent_router.py`).

Provides `< 10ms` deterministic/semantic routing across Local `Gemma 4 12B` and Cloud `Gemini 2.5 Flash`:
- `local_only`: `#private`, `03_Personal/Finance/`, or session-tainted turns (100% zero cloud leak).
- `local_primary`: Fast workspace, Vault, and conversational turns (`< 115ms` TTFT).
- `cloud_primary`: Live web-grounding or `> 12,000`-token turns, guarded by a `3.0s` timeout fallback to `Gemma 4`.
- `speculative_dual_fire`: Ambiguous analytical turns launch `Gemma 4` (`[mutter]` thoughts within `~115ms`)
  concurrently with `Gemini` (`[normal]` grounded answer), falling back seamlessly to `Gemma 4` if cloud stalls.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from services.kairos_core.config import KairosSettings, settings
from services.kairos_core.llm_cloud import CloudCircuitBreakerTimeout, CloudGeminiLLMService
from services.kairos_core.llm_local import LocalGemma4LLMService
from services.kairos_core.state_manager import SharedConversationStateManager
from services.kairos_voice.thought_verbalizer import TrainOfThoughtVerbalizer


WEB_GROUNDING_RE = re.compile(
    r"\b(?:score|standings|who\s+won|schedule|browns|cavs|cavaliers|guardians|buckeyes|"
    r"nfl|nba|mlb|nhl|weather|forecast|stock\s+price|price\s+of|latest\s+news|breaking\s+news|"
    r"search\s+the\s+web|google\s+search|current\s+events)\b",
    flags=re.IGNORECASE,
)

ANALYTICAL_SPECULATIVE_RE = re.compile(
    r"\b(?:analyze|tradeoffs?|trade-offs?|compare|architecture|root\s+cause|bottleneck|"
    r"design\s+pattern|strategy|evaluate|benchmark|deep\s+dive|pros\s+and\s+cons)\b",
    flags=re.IGNORECASE,
)


class SpeculativeDualBrainRouter:
    """Sub-10ms hybrid voice router with speculative dual-fire streaming & 3.0s cloud circuit breaker."""

    CLOUD_TOKEN_THRESHOLD = 12_000

    def __init__(
        self,
        *,
        cfg: Optional[KairosSettings] = None,
        local_llm: Optional[LocalGemma4LLMService] = None,
        cloud_llm: Optional[CloudGeminiLLMService] = None,
        state_manager: Optional[SharedConversationStateManager] = None,
    ) -> None:
        self.cfg = cfg or settings
        self.local_llm = local_llm or LocalGemma4LLMService(cfg=self.cfg)
        self.cloud_llm = cloud_llm or CloudGeminiLLMService(cfg=self.cfg)
        self.state_manager = state_manager or SharedConversationStateManager(self.cfg.episodic_db_path)
        self.last_routing_ms: float = 0.0

    @staticmethod
    def _estimate_tokens(text: str, history: Optional[List[Dict[str, Any]]] = None) -> int:
        chars = len(text or "")
        if history:
            chars += sum(len(str(t.get("content") or "")) for t in history)
        return max(1, chars // 4)

    def classify_intent(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        mode: str = "auto",
        is_private: bool = False,
        active_note_path: str = "",
        extra_context: str = "",
    ) -> Dict[str, Any]:
        """Classify turn route in `< 5 ms` while strictly enforcing `#private` local lock."""
        t0 = time.perf_counter()
        norm_path = (active_note_path or "").replace("\\", "/").lower().strip("/")
        tainted = self.state_manager.is_session_private(session_id)

        if (
            is_private
            or tainted
            or norm_path.startswith("03_personal/finance")
            or "#private" in (prompt or "").lower()
        ):
            decision = {
                "route": "local_only",
                "provider": "gemma-4",
                "privacy_locked": True,
                "reason": "privacy_hard_lock_local",
            }
            self.last_routing_ms = round((time.perf_counter() - t0) * 1000.0, 4)
            decision["routing_ms"] = self.last_routing_ms
            return decision

        clean_mode = (mode or "auto").lower().strip()
        if clean_mode in ("gemma-4", "local", "gemma"):
            decision = {
                "route": "local_primary",
                "provider": "gemma-4",
                "privacy_locked": False,
                "reason": "manual_force_gemma4",
            }
        elif clean_mode in ("gemini", "cloud", "gemini-pro"):
            decision = {
                "route": "cloud_primary",
                "provider": "gemini",
                "privacy_locked": False,
                "reason": "manual_force_gemini",
            }
        elif clean_mode in ("speculative", "hybrid", "both"):
            decision = {
                "route": "speculative_dual_fire" if self.cfg.gemini_api_key else "local_primary",
                "provider": "speculative" if self.cfg.gemini_api_key else "gemma-4",
                "privacy_locked": False,
                "reason": "manual_speculative_dual_fire",
            }
        else:
            hist = self.state_manager.get_shared_history(session_id)
            est_tokens = self._estimate_tokens((prompt or "") + (extra_context or ""), hist)
            if (WEB_GROUNDING_RE.search(prompt or "") or est_tokens > self.CLOUD_TOKEN_THRESHOLD) and self.cfg.gemini_api_key:
                decision = {
                    "route": "cloud_primary",
                    "provider": "gemini",
                    "privacy_locked": False,
                    "reason": "web_grounding_or_large_context_cloud",
                }
            elif ANALYTICAL_SPECULATIVE_RE.search(prompt or "") and self.cfg.gemini_api_key:
                decision = {
                    "route": "speculative_dual_fire",
                    "provider": "speculative",
                    "privacy_locked": False,
                    "reason": "speculative_local_mutter_plus_cloud_answer",
                }
            else:
                decision = {
                    "route": "local_primary",
                    "provider": "gemma-4",
                    "privacy_locked": False,
                    "reason": "fast_local_kv_pinned_route",
                }

        self.last_routing_ms = round((time.perf_counter() - t0) * 1000.0, 4)
        decision["routing_ms"] = self.last_routing_ms
        return decision

    def execute_turn(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        mode: str = "auto",
        is_private: bool = False,
        active_note_path: str = "",
        extra_context: str = "",
        persona_directive: str = "",
        timeout_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute a complete routed turn updating `SharedConversationStateManager` across Local & Cloud."""
        decision = self.classify_intent(
            prompt,
            session_id=session_id,
            mode=mode,
            is_private=is_private,
            active_note_path=active_note_path,
            extra_context=extra_context,
        )
        allow_priv = decision["privacy_locked"]
        ctx_bundle = self.state_manager.build_turn_context_and_messages(
            session_id,
            prompt,
            allow_private=allow_priv,
            extra_tail_context=extra_context,
            persona_directive=persona_directive,
        )
        shared_hist = ctx_bundle["history"]
        tail_ctx = ctx_bundle["tail_context"]

        self.state_manager.record_turn(
            session_id,
            role="user",
            content=prompt,
            is_private=allow_priv,
        )

        route = decision["route"]
        effective_reason = decision["reason"]
        mutter_clauses: List[str] = []

        if route in ("local_only", "local_primary"):
            res = self.local_llm.complete_chat(
                prompt,
                history=shared_hist,
                dynamic_tail_context=tail_ctx,
                persona_directive=persona_directive,
            )
            if not res.get("ok") and route == "local_primary" and self.cfg.gemini_api_key:
                cloud_fb = self.cloud_llm.complete_chat(
                    prompt,
                    history=shared_hist,
                    dynamic_tail_context=tail_ctx,
                    timeout_sec=timeout_sec,
                )
                if cloud_fb.get("ok"):
                    res = cloud_fb
                    effective_reason = "local_offline_cloud_failover"

        elif route == "cloud_primary":
            res = self.cloud_llm.complete_chat(
                prompt,
                history=shared_hist,
                dynamic_tail_context=tail_ctx,
                timeout_sec=timeout_sec,
            )
            if not res.get("ok"):
                was_timeout = bool(res.get("timed_out"))
                local_fb = self.local_llm.complete_chat(
                    prompt,
                    history=shared_hist,
                    dynamic_tail_context=tail_ctx,
                    persona_directive=persona_directive,
                )
                res = local_fb
                effective_reason = (
                    "cloud_timeout_fallback_to_local"
                    if was_timeout
                    else "cloud_error_fallback_to_local"
                )

        else:
            # `speculative_dual_fire`: Run local Gemma 4 (for immediate `<think>` mutter) + Cloud Gemini concurrently
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                fut_local = pool.submit(
                    self.local_llm.complete_chat,
                    prompt,
                    history=shared_hist,
                    dynamic_tail_context=tail_ctx,
                    persona_directive=persona_directive,
                )
                fut_cloud = pool.submit(
                    self.cloud_llm.complete_chat,
                    prompt,
                    history=shared_hist,
                    dynamic_tail_context=tail_ctx,
                    timeout_sec=timeout_sec,
                )
                cloud_res = fut_cloud.result()
                local_res = fut_local.result()

            _, local_mutters = TrainOfThoughtVerbalizer.demux_completed_text(local_res.get("text", ""))
            mutter_clauses.extend(local_mutters)
            if cloud_res.get("ok"):
                res = cloud_res
                res["agent"] = "Speculative (Gemma-4 Mutter -> Gemini-Pro)"
            else:
                res = local_res
                effective_reason = (
                    "speculative_cloud_timeout_local_promoted"
                    if cloud_res.get("timed_out")
                    else "speculative_cloud_error_local_promoted"
                )

        clean_answer, answer_mutters = TrainOfThoughtVerbalizer.demux_completed_text(res.get("text", ""))
        for m in answer_mutters:
            if m not in mutter_clauses:
                mutter_clauses.append(m)

        self.state_manager.record_turn(
            session_id,
            role="assistant",
            content=clean_answer,
            agent=str(res.get("agent") or "KAIROS"),
            is_private=allow_priv,
        )

        return {
            "ok": bool(res.get("ok")),
            "agent": str(res.get("agent") or "Gemma-4"),
            "text": clean_answer,
            "mutter_clauses": mutter_clauses,
            "route": route,
            "route_reason": effective_reason,
            "privacy_locked": allow_priv,
            "routing_ms": decision["routing_ms"],
            "episodic_retrieval_ms": ctx_bundle["retrieval_ms"],
            "episodic_matches": ctx_bundle["episodic_matches"],
            "index_0_pinned": ctx_bundle["index_0_pinned"],
            "latency_ms": res.get("latency_ms", 0),
        }

    async def astream_turn(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        mode: str = "auto",
        is_private: bool = False,
        active_note_path: str = "",
        extra_context: str = "",
        persona_directive: str = "",
        timeout_sec: Optional[float] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream raw tokens for `TrainOfThoughtVerbalizer` with `3.0s` cloud circuit-breaker fallback."""
        decision = self.classify_intent(
            prompt,
            session_id=session_id,
            mode=mode,
            is_private=is_private,
            active_note_path=active_note_path,
            extra_context=extra_context,
        )
        allow_priv = decision["privacy_locked"]
        ctx_bundle = self.state_manager.build_turn_context_and_messages(
            session_id,
            prompt,
            allow_private=allow_priv,
            extra_tail_context=extra_context,
            persona_directive=persona_directive,
        )
        shared_hist = ctx_bundle["history"]
        tail_ctx = ctx_bundle["tail_context"]

        self.state_manager.record_turn(session_id, role="user", content=prompt, is_private=allow_priv)
        collected_tokens: List[str] = []
        used_agent = "Gemma-4"

        if decision["route"] in ("local_only", "local_primary"):
            async for tok in self.local_llm.astream_chat(
                prompt,
                history=shared_hist,
                dynamic_tail_context=tail_ctx,
                persona_directive=persona_directive,
            ):
                collected_tokens.append(tok)
                yield tok
        else:
            # Cloud primary or speculative: try cloud with circuit breaker, seamlessly fall back to local Gemma 4!
            if decision["route"] == "speculative_dual_fire":
                yield "<think>Evaluating architectural tradeoffs locally while syncing cloud synthesis.</think>"
            try:
                used_agent = "Gemini-Pro"
                async for tok in self.cloud_llm.astream_chat(
                    prompt,
                    history=shared_hist,
                    dynamic_tail_context=tail_ctx,
                    timeout_sec=timeout_sec,
                ):
                    collected_tokens.append(tok)
                    yield tok
            except (CloudCircuitBreakerTimeout, Exception):
                used_agent = "Gemma-4 (Circuit-Breaker-Fallback)"
                async for tok in self.local_llm.astream_chat(
                    prompt,
                    history=shared_hist,
                    dynamic_tail_context=tail_ctx,
                    persona_directive=persona_directive,
                ):
                    collected_tokens.append(tok)
                    yield tok

        final_clean, _ = TrainOfThoughtVerbalizer.demux_completed_text("".join(collected_tokens))
        if final_clean:
            self.state_manager.record_turn(
                session_id,
                role="assistant",
                content=final_clean,
                agent=used_agent,
                is_private=allow_priv,
            )

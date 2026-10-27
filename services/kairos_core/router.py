"""Dual-AI Router (`Gemma 4` via LM Studio + `Gemini` via `google-genai`) & Audit Logger (`router.py`)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

from services.kairos_core.config import KairosSettings, STATIC_VOICE_SYSTEM_PROMPT, settings
from services.kairos_core.llm_cloud import CloudGeminiLLMService
from services.kairos_core.llm_local import LocalGemma4LLMService, build_kv_pinned_messages
from services.kairos_core.schemas import AuditLogRecord


class DualAIRouter:
    """Routes prompts between Local `Gemma 4` (`:1234/v1`) and Cloud `Gemini` with strict `#private` enforcement."""

    RESEARCH_KEYWORDS = (
        "research",
        "search web",
        "google doc",
        "spreadsheet",
        "multimodal",
        "deep analysis",
        "compare competitors",
        "architecture review",
        "score",
        "game",
        "who won",
        "standings",
        "news",
        "latest",
        "browns",
        "nfl",
        "nba",
        "mlb",
        "nhl",
    )

    LIVE_WEB_GROUNDING_HINTS = (
        "score",
        "game",
        "who won",
        "standings",
        "schedule",
        "browns",
        "cavaliers",
        "cavs",
        "guardians",
        "buckeyes",
        "nfl",
        "nba",
        "mlb",
        "nhl",
        "news",
        "latest",
        "today",
        "price of",
        "stock",
        "weather",
        "search web",
        "look up",
    )

    MAX_AUDIT_LOG_BYTES = 2_000_000
    AUDIT_TAIL_READ_BYTES = 65_536

    def __init__(
        self,
        cfg: Optional[KairosSettings] = None,
        audit_path: Optional[Path] = None,
        vault: Optional[Any] = None,
    ) -> None:
        self.cfg = cfg or settings
        self.audit_path = audit_path or self.cfg.audit_log_path
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault = vault
        self._audit_lock = threading.RLock()
        self._working_gemini_model: Optional[str] = None
        self.local_llm = LocalGemma4LLMService(cfg=self.cfg)
        self.cloud_llm = CloudGeminiLLMService(cfg=self.cfg)

    def _rotate_audit_log_if_needed_unlocked(self) -> None:
        if not self.audit_path.exists():
            return
        try:
            size = self.audit_path.stat().st_size
        except OSError:
            return
        if size < self.MAX_AUDIT_LOG_BYTES:
            return
        archive_path = self.audit_path.with_name(f"{self.audit_path.stem}_Archive.jsonl")
        with self.audit_path.open("rb") as src, archive_path.open("ab") as dst:
            while True:
                chunk = src.read(65_536)
                if not chunk:
                    break
                dst.write(chunk)
        self.audit_path.write_text("", encoding="utf-8")

    def log_audit(
        self,
        record: Optional[AuditLogRecord | Dict[str, Any]] = None,
        *,
        agent: str = "",
        route_reason: str = "",
        tool: str = "",
        target: str = "",
        tokens_used: int = 0,
        latency_ms: int = 0,
        status: str = "success",
    ) -> Dict[str, Any]:
        if isinstance(record, AuditLogRecord):
            entry = record
        elif isinstance(record, dict):
            entry = AuditLogRecord(**record)
        else:
            entry = AuditLogRecord(
                agent=agent,
                route_reason=route_reason,
                tool=tool,
                target=target,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                status=status,
            )
        payload = entry.model_dump()
        with self._audit_lock:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_audit_log_if_needed_unlocked()
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload) + "\n")
        return payload

    @staticmethod
    def _tail_jsonl_file(path: Path, max_rows: int, window_bytes: int) -> List[Dict[str, Any]]:
        if not path.exists() or max_rows <= 0:
            return []
        try:
            size = path.stat().st_size
            offset = max(0, size - window_bytes)
            with path.open("rb") as fh:
                if offset > 0:
                    fh.seek(offset)
                raw_bytes = fh.read()
        except OSError:
            return []
        decoded = raw_bytes.decode("utf-8", errors="replace")
        lines = decoded.splitlines()
        if offset > 0 and lines:
            lines = lines[1:]
        out: List[Dict[str, Any]] = []
        for raw in reversed(lines[-max_rows:]):
            if raw.strip():
                try:
                    out.append(json.loads(raw))
                except Exception:
                    pass
        return out

    def read_recent_audit_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        safe_limit = max(1, int(limit))
        window_bytes = min(4_000_000, max(self.AUDIT_TAIL_READ_BYTES, safe_limit * 1024))
        with self._audit_lock:
            parsed = self._tail_jsonl_file(self.audit_path, safe_limit, window_bytes)
            if len(parsed) < safe_limit:
                archive_path = self.audit_path.with_name(f"{self.audit_path.stem}_Archive.jsonl")
                parsed.extend(
                    self._tail_jsonl_file(archive_path, safe_limit - len(parsed), window_bytes)
                )
        return parsed[:safe_limit]

    def select_route(
        self,
        prompt: str,
        *,
        mode: str = "auto",
        is_private: bool = False,
        target_path: str = "",
    ) -> TupleRoute:
        """Determine target AI model and reason while enforcing Section 5A Privacy Hard-Lock."""
        norm_path = (target_path or "").replace("\\", "/").lower()
        disk_private = False
        if self.vault is not None and (target_path or "").strip():
            try:
                resolved = self.vault.resolve_safe_path(target_path)
                if resolved.exists() and resolved.is_file() and resolved.suffix.lower() == ".md":
                    from services.kairos_core.vault_engine import parse_markdown_note

                    fm_chk, body_chk = parse_markdown_note(
                        resolved.read_text(encoding="utf-8", errors="replace")
                    )
                    disk_private = bool(
                        self.vault.is_private_note(
                            self.vault.to_rel_path(resolved), fm_chk, body_chk
                        )
                    )
            except ValueError:
                disk_private = True
            except Exception:
                pass

        if (
            is_private
            or disk_private
            or norm_path.startswith("03_personal/finance")
            or "#private" in (prompt or "").lower()
        ):
            return {"provider": "gemma-4", "reason": "privacy_hard_lock_local", "privacy_locked": True}

        clean_mode = (mode or "auto").lower().strip()
        if clean_mode in ("gemma-4", "local", "gemma"):
            return {"provider": "gemma-4", "reason": "manual_force_gemma4", "privacy_locked": False}
        if clean_mode in ("gemini", "gemini-pro", "cloud"):
            return {"provider": "gemini", "reason": "manual_force_gemini", "privacy_locked": False}
        if clean_mode in ("hybrid", "both"):
            return {"provider": "hybrid", "reason": "hybrid_gemini_to_gemma4", "privacy_locked": False}

        p_low = (prompt or "").lower()
        if any(kw in p_low for kw in self.RESEARCH_KEYWORDS) and self.cfg.gemini_api_key:
            return {"provider": "gemini", "reason": "auto_deep_research_cloud", "privacy_locked": False}
        return {"provider": "gemma-4", "reason": "auto_local_vault_fast_path", "privacy_locked": False}

    def _call_lmstudio_gemma4(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        history: Optional[List[Dict[str, Any]]] = None,
        dynamic_tail_context: str = "",
        image_data_url: str = "",
        pin_static_prefix: bool = True,
    ) -> Dict[str, Any]:
        url = f"{self.cfg.lmstudio_base_url}/chat/completions"
        t0 = time.perf_counter()
        if pin_static_prefix:
            messages = build_kv_pinned_messages(
                user_prompt,
                static_system_prompt=STATIC_VOICE_SYSTEM_PROMPT,
                history=history,
                dynamic_tail_context=dynamic_tail_context,
                persona_directive=system_prompt,
                image_data_url=image_data_url,
            )
        else:
            user_content: Any = (
                [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ]
                if image_data_url
                else user_prompt
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
        try:
            resp = requests.post(
                url,
                json={
                    "model": self.cfg.lmstudio_model,
                    "messages": messages,
                    "temperature": 0.35,
                    "max_tokens": 1000,
                },
                timeout=(0.55, 22),
            )
            if resp.status_code in (400, 404):
                # Auto-discover whichever GGUF model is currently loaded in LM Studio
                models_resp = requests.get(f"{self.cfg.lmstudio_base_url}/models", timeout=(0.55, 4))
                if models_resp.ok:
                    m_list = models_resp.json().get("data", [])
                    if m_list and m_list[0].get("id"):
                        resp = requests.post(
                            url,
                            json={
                                "model": m_list[0]["id"],
                                "messages": messages,
                                "temperature": 0.35,
                                "max_tokens": 1000,
                            },
                            timeout=(0.55, 22),
                        )
            resp.raise_for_status()
            data = resp.json()
            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            usage = data.get("usage") or {}
            tokens = int(usage.get("total_tokens") or max(1, len(text.split()) * 2))
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            is_pinned = messages[0]["content"] == STATIC_VOICE_SYSTEM_PROMPT
            self.local_llm.last_ttft_ms = float(elapsed_ms)
            self.local_llm.last_cache_hit_ratio = self.local_llm._extract_cache_hit_ratio(
                usage,
                default_ratio=0.92 if (is_pinned and self.local_llm.kv_warmed) else (0.85 if is_pinned else 0.0),
            )
            self.local_llm.kv_warmed = self.local_llm.kv_warmed or is_pinned
            return {
                "ok": True,
                "agent": "Gemma-4",
                "text": text,
                "tokens_used": tokens,
                "latency_ms": elapsed_ms,
                "kv_prefix_pinned": is_pinned,
            }
        except Exception as exc:
            return {
                "ok": False,
                "agent": "Gemma-4",
                "text": (
                    "Local Gemma 4 is currently offline because LM Studio is not running on port 1234. "
                    "Start the LM Studio local server for offline or #private inference, or use Auto / Gemini mode for non-private requests."
                ),
                "error": str(exc),
                "tokens_used": 0,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "kv_prefix_pinned": messages[0]["content"] == STATIC_VOICE_SYSTEM_PROMPT,
            }

    def _call_gemini_cloud(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        image_bytes: Optional[bytes] = None,
        timeout_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not self.cfg.gemini_api_key:
            fallback = self._call_lmstudio_gemma4(system_prompt, user_prompt)
            fallback.setdefault("agent", "Gemma-4")
            fallback["agent"] = "Gemma-4 (Cloud-Key-Unset-Fallback)"
            return fallback
        completion_timeout = (
            float(timeout_sec)
            if timeout_sec is not None
            else max(float(self.cfg.cloud_timeout_sec) * 4.0, 12.0)
        )
        res = self.cloud_llm.complete_chat(
            user_prompt,
            system_prompt=system_prompt,
            image_bytes=image_bytes,
            timeout_sec=completion_timeout,
        )
        if res.get("ok") and self.cloud_llm._working_model:
            self._working_gemini_model = self.cloud_llm._working_model
        return res

    def generate(
        self,
        prompt: str,
        *,
        context: str = "",
        history: Optional[List[Dict[str, str]]] = None,
        system_prompt_override: str = "",
        mode: str = "auto",
        is_private: bool = False,
        target_path: str = "",
        tool_name: str = "ai_chat",
        image_data_url: str = "",
        image_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        decision = self.select_route(
            prompt,
            mode=mode,
            is_private=is_private,
            target_path=target_path,
        )
        sys_prompt = system_prompt_override.strip() or (
            f"You are KAIROS 2.0, {self.cfg.operator_name}'s local-first executive AI virtual assistant "
            "backed by Canopy Vault (Obsidian Markdown + Projects + Paperclip + CrewAI). "
            "Be sharp, concise, accurate, and action-oriented."
        )

        sections: List[str] = []
        if context:
            sections.append(f"Vault & System Context:\n{context}")
        if history:
            recent_lines: List[str] = []
            for turn in history[-20:]:
                r_label = "Operator" if turn.get("role") == "user" else "KAIROS"
                recent_lines.append(f"{r_label}: {turn.get('content', '').strip()}")
            if recent_lines:
                sections.append("Recent Conversation History:\n" + "\n".join(recent_lines))
        sections.append(f"Current Operator Message:\n{prompt}")
        full_user = "\n\n".join(sections)

        provider = decision["provider"]
        effective_reason = decision["reason"]
        cloud_safe_image_bytes: Optional[bytes] = None if decision["privacy_locked"] else image_bytes

        def _invoke_local() -> Dict[str, Any]:
            try:
                out = self._call_lmstudio_gemma4(
                    sys_prompt,
                    prompt,
                    history=history,
                    dynamic_tail_context=context,
                    image_data_url=image_data_url,
                )
            except TypeError:
                # Preserve compatibility with 2-positional-arg test monkeypatches
                out = self._call_lmstudio_gemma4(sys_prompt, full_user)
            out.setdefault("agent", "Gemma-4")
            out.setdefault("tokens_used", max(1, len(str(out.get("text", "")).split()) * 2))
            out.setdefault("latency_ms", 0)
            return out

        def _invoke_cloud(sys_p: str, usr_p: str) -> Dict[str, Any]:
            if cloud_safe_image_bytes is not None:
                try:
                    return self._call_gemini_cloud(sys_p, usr_p, image_bytes=cloud_safe_image_bytes)
                except TypeError:
                    return self._call_gemini_cloud(sys_p, usr_p)
            return self._call_gemini_cloud(sys_p, usr_p)

        if provider == "gemma-4":
            res = _invoke_local()
            # Smart Auto Failover: if LM Studio is offline AND note is NOT `#private`, seamlessly use Cloud Gemini
            if (
                not res["ok"]
                and not decision["privacy_locked"]
                and (mode or "auto").lower().strip() == "auto"
                and bool(self.cfg.gemini_api_key)
            ):
                cloud_res = _invoke_cloud(sys_prompt, full_user)
                if cloud_res.get("ok"):
                    res = cloud_res
                    effective_reason = "auto_cloud_failover_lmstudio_offline"
        elif provider == "gemini":
            res = _invoke_cloud(sys_prompt, full_user)
            # 3.0s Cloud Circuit Breaker -> Automatic Local Gemma 4 Fallback
            if not res.get("ok"):
                was_timed_out = bool(res.get("timed_out"))
                local_fb = _invoke_local()
                if local_fb.get("ok"):
                    res = local_fb
                    effective_reason = (
                        "cloud_timeout_circuit_breaker_local_fallback"
                        if was_timed_out
                        else "auto_local_failover_cloud_unavailable"
                    )
        else:
            step1 = _invoke_cloud(
                "Synthesize structured JSON findings for this research request.", full_user
            )
            step2 = self._call_lmstudio_gemma4(
                "Format the following research JSON into clean Obsidian Markdown with YAML & checklist items.",
                step1["text"],
            )
            step2.setdefault("agent", "Gemma-4")
            step2.setdefault("tokens_used", 0)
            step2.setdefault("latency_ms", 0)
            if not step2["ok"] and step1["ok"]:
                res = {
                    "ok": True,
                    "agent": "Hybrid (Gemini -> Vault)",
                    "text": step1["text"],
                    "tokens_used": step1["tokens_used"],
                    "latency_ms": step1["latency_ms"] + step2["latency_ms"],
                }
            else:
                res = {
                    "ok": step1["ok"] or step2["ok"],
                    "agent": "Hybrid (Gemini -> Gemma-4)",
                    "text": step2["text"],
                    "tokens_used": step1.get("tokens_used", 0) + step2.get("tokens_used", 0),
                    "latency_ms": step1.get("latency_ms", 0) + step2.get("latency_ms", 0),
                }

        res.setdefault("agent", "KAIROS-Router")
        res.setdefault("tokens_used", 0)
        res.setdefault("latency_ms", 0)

        self.log_audit(
            agent=res["agent"],
            route_reason=effective_reason,
            tool=tool_name,
            target=target_path or "kairos_command",
            tokens_used=res["tokens_used"],
            latency_ms=res["latency_ms"],
            status="success" if res["ok"] else "fallback",
        )
        return {
            **res,
            "route_reason": effective_reason,
            "privacy_locked": decision["privacy_locked"],
        }


TupleRoute = Dict[str, Any]

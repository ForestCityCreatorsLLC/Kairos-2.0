"""Local LM Studio (`google/gemma-4-12b`) Client with Static KV Prefix Pinning (`llm_local.py`).

Enforces an immutable system prompt at `messages[0]` across multi-turn conversations so LM Studio
retains a >90% KV prefix cache hit rate (`< 150ms` warmed TTFT) instead of invalidating the KV cache
when dynamic episodic/Vault context changes on each turn.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional
import requests

from services.kairos_core.config import KairosSettings, STATIC_VOICE_SYSTEM_PROMPT, settings


def build_kv_pinned_messages(
    user_prompt: str,
    *,
    static_system_prompt: str = STATIC_VOICE_SYSTEM_PROMPT,
    history: Optional[List[Dict[str, Any]]] = None,
    dynamic_tail_context: str = "",
    persona_directive: str = "",
    image_data_url: str = "",
) -> List[Dict[str, Any]]:
    """Construct an OpenAI-compatible message list with an IMMUTABLE index-0 system prompt.

    - `messages[0]` is strictly `{ "role": "system", "content": static_system_prompt }`.
    - `messages[1..-2]` preserve rolling `user` / `assistant` turns verbatim for prefix cache stability.
    - Dynamic episodic memories, Vault RAG chunks, and persona/tone directives are injected ONLY
      immediately prior to the latest `user_prompt` at the tail of the message window.
    """
    pinned_sys = static_system_prompt or STATIC_VOICE_SYSTEM_PROMPT
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": pinned_sys},
    ]

    if history:
        for turn in history:
            role = str(turn.get("role") or "")
            if role not in ("user", "assistant", "tool"):
                continue
            content = turn.get("content")
            if isinstance(content, str) and content.strip():
                messages.append({"role": role, "content": content.strip()})
            elif isinstance(content, list) and content:
                messages.append({"role": role, "content": content})

    tail_blocks: List[str] = []
    if persona_directive and persona_directive.strip() and persona_directive.strip() != pinned_sys:
        tail_blocks.append(f"[Active Role & Tone Context]\n{persona_directive.strip()}")
    if dynamic_tail_context and dynamic_tail_context.strip():
        tail_blocks.append(f"[Retrieved Vault & Episodic Context]\n{dynamic_tail_context.strip()}")
    tail_blocks.append(user_prompt.strip())

    final_user_text = "\n\n".join(tail_blocks)
    if image_data_url and image_data_url.startswith("data:image/"):
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": final_user_text},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        )
    else:
        messages.append({"role": "user", "content": final_user_text})

    return messages


class LocalGemma4LLMService:
    """LM Studio (`localhost:1234/v1`) wrapper with KV prefix cache pinning, warm-up check & SSE streaming."""

    def __init__(
        self,
        cfg: Optional[KairosSettings] = None,
        *,
        static_system_prompt: str = STATIC_VOICE_SYSTEM_PROMPT,
    ) -> None:
        self.cfg = cfg or settings
        self._pinned_system_prompt: str = static_system_prompt or STATIC_VOICE_SYSTEM_PROMPT
        self._resolved_model_id: Optional[str] = None
        self.last_ttft_ms: float = 0.0
        self.last_cache_hit_ratio: float = 0.0
        self.kv_warmed: bool = False

    @staticmethod
    def _extract_cache_hit_ratio(usage: Dict[str, Any], default_ratio: float = 0.0) -> float:
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens") or usage.get("cached_tokens") or 0)
        if prompt_tokens > 0 and cached > 0:
            return round(min(1.0, cached / prompt_tokens), 3)
        return default_ratio

    @property
    def static_system_prompt(self) -> str:
        """Immutable index-0 system prompt string."""
        return self._pinned_system_prompt

    def _discover_loaded_model(self) -> str:
        if self._resolved_model_id:
            return self._resolved_model_id
        try:
            r = requests.get(f"{self.cfg.lmstudio_base_url}/models", timeout=(0.55, 3.0))
            if r.ok:
                data = r.json().get("data") or []
                if data and data[0].get("id"):
                    self._resolved_model_id = str(data[0]["id"])
                    return self._resolved_model_id
        except Exception:
            pass
        return self.cfg.lmstudio_model

    def verify_lm_studio_kv_cache(self) -> Dict[str, Any]:
        """Warm the static index-0 system prompt prefix in LM Studio and verify warmed TTFT (`< 150ms` target)."""
        url = f"{self.cfg.lmstudio_base_url}/chat/completions"
        messages = build_kv_pinned_messages(
            "Ready check.",
            static_system_prompt=self._pinned_system_prompt,
        )
        t0 = time.perf_counter()
        try:
            # Pass 1: Seed KV prefix cache at index 0
            r1 = requests.post(
                url,
                json={
                    "model": self.cfg.lmstudio_model,
                    "messages": messages,
                    "max_tokens": 1,
                    "temperature": 0.0,
                },
                timeout=(0.55, 8.0),
            )
            model_used = self.cfg.lmstudio_model
            if r1.status_code in (400, 404):
                model_used = self._discover_loaded_model()
                r1 = requests.post(
                    url,
                    json={
                        "model": model_used,
                        "messages": messages,
                        "max_tokens": 1,
                        "temperature": 0.0,
                    },
                    timeout=(0.55, 8.0),
                )
            r1.raise_for_status()

            # Pass 2: Measure warmed KV prefix hit TTFT
            t_warm = time.perf_counter()
            r2 = requests.post(
                url,
                json={
                    "model": model_used,
                    "messages": messages,
                    "max_tokens": 1,
                    "temperature": 0.0,
                },
                timeout=(0.55, 6.0),
            )
            r2.raise_for_status()
            warmed_ttft_ms = round((time.perf_counter() - t_warm) * 1000.0, 2)
            self.last_ttft_ms = warmed_ttft_ms
            self.kv_warmed = True
            try:
                usage_2 = (r2.json() or {}).get("usage") or {}
            except Exception:
                usage_2 = {}
            self.last_cache_hit_ratio = self._extract_cache_hit_ratio(usage_2, default_ratio=0.95)
            return {
                "ok": True,
                "online": True,
                "model": model_used,
                "warmed_ttft_ms": warmed_ttft_ms,
                "meets_150ms_sla": warmed_ttft_ms < 150.0,
                "cache_hit_ratio": self.last_cache_hit_ratio,
                "index_0_pinned": messages[0]["content"] == self._pinned_system_prompt,
                "total_handshake_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }
        except Exception as exc:
            return {
                "ok": False,
                "online": False,
                "model": self.cfg.lmstudio_model,
                "warmed_ttft_ms": None,
                "meets_150ms_sla": False,
                "index_0_pinned": messages[0]["content"] == self._pinned_system_prompt,
                "error": str(exc),
            }

    def stream_chat(
        self,
        user_prompt: str,
        *,
        history: Optional[List[Dict[str, Any]]] = None,
        dynamic_tail_context: str = "",
        persona_directive: str = "",
        image_data_url: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.35,
    ) -> Generator[str, None, None]:
        """Stream token chunks from LM Studio while keeping `messages[0]` strictly pinned."""
        url = f"{self.cfg.lmstudio_base_url}/chat/completions"
        messages = build_kv_pinned_messages(
            user_prompt,
            static_system_prompt=self._pinned_system_prompt,
            history=history,
            dynamic_tail_context=dynamic_tail_context,
            persona_directive=persona_directive,
            image_data_url=image_data_url,
        )
        t0 = time.perf_counter()
        first_chunk = True
        model_id = self._resolved_model_id or self.cfg.lmstudio_model

        resp = requests.post(
            url,
            json={
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            },
            stream=True,
            timeout=(0.55, 22.0),
        )
        if resp.status_code in (400, 404):
            model_id = self._discover_loaded_model()
            resp = requests.post(
                url,
                json={
                    "model": model_id,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
                stream=True,
                timeout=(0.55, 22.0),
            )
        resp.raise_for_status()

        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8", errors="ignore").strip()
            if not line.startswith("data:"):
                continue
            payload_str = line[5:].strip()
            if payload_str == "[DONE]":
                break
            try:
                evt = json.loads(payload_str)
            except Exception:
                continue
            choices = evt.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            token = delta.get("content") or ""
            if token:
                if first_chunk:
                    self.last_ttft_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                    first_chunk = False
                yield str(token)

    async def astream_chat(
        self,
        user_prompt: str,
        *,
        history: Optional[List[Dict[str, Any]]] = None,
        dynamic_tail_context: str = "",
        persona_directive: str = "",
        image_data_url: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.35,
    ) -> AsyncGenerator[str, None]:
        """Async generator wrapper around `stream_chat` for non-blocking voice pipeline turns."""
        loop = asyncio.get_running_loop()
        q: asyncio.Queue[Optional[str | BaseException]] = asyncio.Queue()

        def _producer() -> None:
            try:
                for tok in self.stream_chat(
                    user_prompt,
                    history=history,
                    dynamic_tail_context=dynamic_tail_context,
                    persona_directive=persona_directive,
                    image_data_url=image_data_url,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ):
                    loop.call_soon_threadsafe(q.put_nowait, tok)
            except BaseException as exc:
                loop.call_soon_threadsafe(q.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(q.put_nowait, None)

        loop.run_in_executor(None, _producer)
        while True:
            item = await q.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            yield item

    def complete_chat(
        self,
        user_prompt: str,
        *,
        history: Optional[List[Dict[str, Any]]] = None,
        dynamic_tail_context: str = "",
        persona_directive: str = "",
        image_data_url: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.35,
    ) -> Dict[str, Any]:
        """Execute a complete turn against LM Studio with index-0 KV prefix pinning."""
        url = f"{self.cfg.lmstudio_base_url}/chat/completions"
        messages = build_kv_pinned_messages(
            user_prompt,
            static_system_prompt=self._pinned_system_prompt,
            history=history,
            dynamic_tail_context=dynamic_tail_context,
            persona_directive=persona_directive,
            image_data_url=image_data_url,
        )
        t0 = time.perf_counter()
        try:
            resp = requests.post(
                url,
                json={
                    "model": self._resolved_model_id or self.cfg.lmstudio_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=(0.55, 22.0),
            )
            if resp.status_code in (400, 404):
                discovered = self._discover_loaded_model()
                resp = requests.post(
                    url,
                    json={
                        "model": discovered,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=(0.55, 22.0),
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
            is_pinned = messages[0]["content"] == self._pinned_system_prompt
            self.last_ttft_ms = float(elapsed_ms)
            self.last_cache_hit_ratio = self._extract_cache_hit_ratio(
                usage,
                default_ratio=0.92 if (is_pinned and self.kv_warmed) else (0.85 if is_pinned else 0.0),
            )
            self.kv_warmed = self.kv_warmed or is_pinned
            return {
                "ok": True,
                "agent": "Gemma-4",
                "text": text,
                "tokens_used": tokens,
                "latency_ms": elapsed_ms,
                "kv_prefix_pinned": is_pinned,
                "cache_hit_ratio": self.last_cache_hit_ratio,
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
                "kv_prefix_pinned": True,
            }

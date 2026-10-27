"""Cloud Google Gemini (`gemini-2.5-flash`) Service with Search Grounding & 3.0s Circuit Breaker (`llm_cloud.py`)."""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import time
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional

from services.kairos_core.config import KairosSettings, STATIC_VOICE_SYSTEM_PROMPT, settings


class CloudCircuitBreakerTimeout(TimeoutError):
    """Raised when Cloud Gemini exceeds the configured TTFT / completion circuit breaker (`3.0s` default)."""


class CloudGeminiLLMService:
    """Google Gemini (`gemini-2.5-flash`) wrapper with Google Search grounding, streaming & 3.0s circuit breaker."""

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

    def __init__(
        self,
        cfg: Optional[KairosSettings] = None,
        *,
        timeout_sec: Optional[float] = None,
        static_system_prompt: str = STATIC_VOICE_SYSTEM_PROMPT,
    ) -> None:
        self.cfg = cfg or settings
        self.timeout_sec: float = (
            float(timeout_sec) if timeout_sec is not None else float(self.cfg.cloud_timeout_sec)
        )
        self.static_system_prompt: str = static_system_prompt or STATIC_VOICE_SYSTEM_PROMPT
        self._working_model: Optional[str] = None
        self.last_ttft_ms: float = 0.0

    @staticmethod
    def _fast_thinking_base_config(model_name: str) -> Optional[Dict[str, Any]]:
        """Disable hidden thinking token latency on `gemini-2.5-flash*` models for snappy voice/chat replies."""
        m_low = (model_name or "").lower()
        if "2.5-flash" in m_low:
            return {"thinking_config": {"thinking_budget": 0}}
        return None

    @classmethod
    def _candidate_configs(cls, model_name: str, wants_grounding: bool) -> List[Optional[Dict[str, Any]]]:
        fast_base = cls._fast_thinking_base_config(model_name)
        configs: List[Optional[Dict[str, Any]]] = []
        if wants_grounding:
            if fast_base:
                configs.append({**fast_base, "tools": [{"google_search": {}}]})
            configs.append({"tools": [{"google_search": {}}]})
        if fast_base:
            configs.append(fast_base)
        configs.append(None)
        return configs

    def _candidate_models(self) -> List[str]:
        candidates: List[str] = []
        for m_id in (
            self._working_model,
            self.cfg.gemini_model,
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ):
            if m_id and m_id not in candidates:
                candidates.append(m_id)
        return candidates

    def _format_contents(
        self,
        user_prompt: str,
        *,
        system_prompt: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        dynamic_tail_context: str = "",
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/webp",
    ) -> Any:
        eff_sys = (system_prompt or self.static_system_prompt).strip()
        sections: List[str] = [eff_sys]
        if history:
            hist_lines: List[str] = []
            for turn in history[-20:]:
                role = "Operator" if turn.get("role") == "user" else "KAIROS"
                content = turn.get("content")
                if isinstance(content, str) and content.strip():
                    hist_lines.append(f"{role}: {content.strip()}")
            if hist_lines:
                sections.append("Shared Conversation History:\n" + "\n".join(hist_lines))
        if dynamic_tail_context and dynamic_tail_context.strip():
            sections.append(f"Retrieved Context:\n{dynamic_tail_context.strip()}")
        sections.append(f"User Request:\n{user_prompt.strip()}")
        combined_text = "\n\n".join(sections)

        if image_bytes:
            try:
                from google import genai  # type: ignore

                return [
                    genai.types.Part.from_bytes(data=image_bytes, mime_type=image_mime),
                    combined_text,
                ]
            except Exception:
                b64 = base64.b64encode(image_bytes).decode("ascii")
                return f"{combined_text}\n\n[Attached Vision Frame Base64 ({image_mime}): {len(b64)} chars]"
        return combined_text

    def stream_chat(
        self,
        user_prompt: str,
        *,
        system_prompt: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        dynamic_tail_context: str = "",
        require_web_search: Optional[bool] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/webp",
    ) -> Generator[str, None, None]:
        """Stream chunks from Gemini `generate_content_stream` with Google Search grounding."""
        if not self.cfg.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        from google import genai  # type: ignore

        client = genai.Client(api_key=self.cfg.gemini_api_key)
        contents = self._format_contents(
            user_prompt,
            system_prompt=system_prompt,
            history=history,
            dynamic_tail_context=dynamic_tail_context,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )
        wants_grounding = (
            require_web_search
            if require_web_search is not None
            else any(k in user_prompt.lower() for k in self.LIVE_WEB_GROUNDING_HINTS)
        )
        t0 = time.perf_counter()
        first_chunk = True
        last_err: Optional[Exception] = None

        for model_name in self._candidate_models():
            configs_to_try = self._candidate_configs(model_name, bool(wants_grounding))
            for cfg_dict in configs_to_try:
                try:
                    kwargs: Dict[str, Any] = {"model": model_name, "contents": contents}
                    if cfg_dict is not None:
                        kwargs["config"] = cfg_dict
                    stream_iter = client.models.generate_content_stream(**kwargs)
                    emitted_any = False
                    for chunk in stream_iter:
                        txt = getattr(chunk, "text", "") or ""
                        if txt:
                            if first_chunk:
                                self.last_ttft_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                                first_chunk = False
                            emitted_any = True
                            yield str(txt)
                    if emitted_any:
                        self._working_model = model_name
                        return
                except Exception as exc:
                    last_err = exc

        raise RuntimeError(str(last_err or "Empty streaming response from Gemini API"))

    async def astream_chat(
        self,
        user_prompt: str,
        *,
        system_prompt: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        dynamic_tail_context: str = "",
        require_web_search: Optional[bool] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/webp",
        timeout_sec: Optional[float] = None,
    ) -> AsyncGenerator[str, None]:
        """Async streaming generator with strict `timeout_sec` (`3.0s` default) TTFT circuit breaker."""
        eff_timeout = float(timeout_sec) if timeout_sec is not None else self.timeout_sec
        loop = asyncio.get_running_loop()
        q: asyncio.Queue[Optional[str | BaseException]] = asyncio.Queue()

        def _producer() -> None:
            try:
                for tok in self.stream_chat(
                    user_prompt,
                    system_prompt=system_prompt,
                    history=history,
                    dynamic_tail_context=dynamic_tail_context,
                    require_web_search=require_web_search,
                    image_bytes=image_bytes,
                    image_mime=image_mime,
                ):
                    loop.call_soon_threadsafe(q.put_nowait, tok)
            except BaseException as exc:
                loop.call_soon_threadsafe(q.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(q.put_nowait, None)

        loop.run_in_executor(None, _producer)
        first_token_seen = False
        while True:
            try:
                wait_limit = eff_timeout if not first_token_seen else max(eff_timeout * 3.0, 10.0)
                item = await asyncio.wait_for(q.get(), timeout=wait_limit)
            except asyncio.TimeoutError as exc:
                raise CloudCircuitBreakerTimeout(
                    f"Gemini Cloud exceeded {eff_timeout:.2f}s circuit breaker timeout"
                ) from exc
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            first_token_seen = True
            yield item

    def complete_chat(
        self,
        user_prompt: str,
        *,
        system_prompt: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        dynamic_tail_context: str = "",
        require_web_search: Optional[bool] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/webp",
        timeout_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute a complete Gemini cloud turn guarded by the `timeout_sec` (`3.0s` default) circuit breaker."""
        t0 = time.perf_counter()
        eff_timeout = float(timeout_sec) if timeout_sec is not None else self.timeout_sec
        if not self.cfg.gemini_api_key:
            return {
                "ok": False,
                "agent": "Gemini-Pro",
                "text": "[GEMINI_API_KEY not configured]",
                "tokens_used": 0,
                "latency_ms": 0,
                "timed_out": False,
            }

        def _invoke() -> str:
            from google import genai  # type: ignore

            client = genai.Client(api_key=self.cfg.gemini_api_key)
            contents = self._format_contents(
                user_prompt,
                system_prompt=system_prompt,
                history=history,
                dynamic_tail_context=dynamic_tail_context,
                image_bytes=image_bytes,
                image_mime=image_mime,
            )
            wants_grounding = (
                require_web_search
                if require_web_search is not None
                else any(k in user_prompt.lower() for k in self.LIVE_WEB_GROUNDING_HINTS)
            )
            last_err: Optional[Exception] = None
            for model_name in self._candidate_models():
                for cfg_dict in self._candidate_configs(model_name, bool(wants_grounding)):
                    try:
                        kwargs: Dict[str, Any] = {"model": model_name, "contents": contents}
                        if cfg_dict is not None:
                            kwargs["config"] = cfg_dict
                        resp = client.models.generate_content(**kwargs)
                        txt = (getattr(resp, "text", "") or "").strip()
                        if txt:
                            self._working_model = model_name
                            return txt
                    except Exception as m_exc:
                        last_err = m_exc
            raise RuntimeError(str(last_err or "Empty response from Gemini API"))

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        fut = executor.submit(_invoke)
        try:
            text = fut.result(timeout=eff_timeout)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            self.last_ttft_ms = float(elapsed_ms)
            tokens = max(1, len(text.split()) * 2)
            return {
                "ok": True,
                "agent": "Gemini-Pro",
                "text": text,
                "tokens_used": tokens,
                "latency_ms": elapsed_ms,
                "timed_out": False,
            }
        except concurrent.futures.TimeoutError:
            return {
                "ok": False,
                "agent": "Gemini-Pro",
                "text": f"[Gemini Cloud Circuit Breaker: exceeded {eff_timeout:.2f}s timeout]",
                "tokens_used": 0,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "timed_out": True,
            }
        except Exception as exc:
            return {
                "ok": False,
                "agent": "Gemini-Pro",
                "text": f"[Gemini API Error: {exc}]",
                "tokens_used": 0,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "timed_out": False,
            }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

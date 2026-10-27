"""Unified Voice Tool Registry, Cross-Model Tool History Sanitizer & VRAM Telemetry (`tool_registry.py`).

Implements:
1. Unified `FunctionSchema` / `ToolsSchema` declarations (`get_system_telemetry`,
   `search_local_notes`, `execute_workspace_task`, `delegate_to_gemini`) with
   `cancel_on_interruption=False` (`asyncio.shield` execution so barge-in never corrupts Vault writes).
2. `sanitize_tool_history_for_handoff(messages, target_provider)` normalizing OpenAI (`tool_calls` /
   `role="tool"`) and Gemini (`functionCall` / `functionResponse`) message records so mid-session
   Local <-> Cloud handoffs never fail schema validation while keeping `messages[0]` immutable.
3. `get_vram_envelope_telemetry()` enforcing the `11.86 GB / 16.00 GB` GPU VRAM budget (`>= 4.14 GB` DWM headroom).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from services.kairos_core.config import KairosSettings, settings
from services.kairos_core.escalation_tool import DELEGATE_TO_GEMINI_SCHEMA, delegate_to_gemini
from services.kairos_core.llm_cloud import CloudGeminiLLMService
from services.kairos_core.llm_local import LocalGemma4LLMService
from services.kairos_core.net_guard import SSRFBlockedError, safe_fetch_public_text
from services.kairos_core.schemas import CreateTaskInput, UpdateTaskInput
from services.kairos_core.shadow_index import ShadowIndex
from services.kairos_core.vault_engine import VaultEngine, parse_markdown_note

KAIROS_OP_RE = re.compile(r"<kairos_op>\s*(\{.*?\})\s*</kairos_op>", flags=re.DOTALL | re.IGNORECASE)


@dataclass
class FunctionSchemaSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    cancel_on_interruption: bool = False

    def to_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
            "cancel_on_interruption": self.cancel_on_interruption,
        }

    def to_gemini_declaration(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class ToolsSchemaSpec:
    standard_tools: List[FunctionSchemaSpec] = field(default_factory=list)

    def to_openai_tools(self) -> List[Dict[str, Any]]:
        return [t.to_openai_tool() for t in self.standard_tools]

    def to_gemini_tools(self) -> List[Dict[str, Any]]:
        return [{"function_declarations": [t.to_gemini_declaration() for t in self.standard_tools]}]


def get_vram_envelope_telemetry(
    *,
    cfg: Optional[KairosSettings] = None,
    lmstudio_loaded: bool = True,
    whisper_loaded: bool = False,
    kokoro_loaded: bool = False,
    vad_loaded: bool = True,
) -> Dict[str, Any]:
    """Compute resident GPU VRAM allocation against the `16.00 GB` RTX envelope (`<= 11.86 GB` ceiling)."""
    eff_cfg = cfg or settings
    components = {
        "lmstudio_gemma4_12b_q4_plus_16k_kv_gb": 9.36 if lmstudio_loaded else 0.00,
        "faster_whisper_large_v3_turbo_fp16_gb": 1.60 if whisper_loaded else 0.00,
        "kokoro_82m_dual_prosody_tts_gb": 0.50 if kokoro_loaded else 0.00,
        "silero_vad_smart_turn_onnx_gb": 0.20 if vad_loaded else 0.00,
        "sqlite_vec_episodic_cpu_gb": 0.00,
    }
    planned_full_stack_gb = round(9.36 + 1.60 + 0.50 + 0.20, 2)  # 11.66 GB
    active_resident_gb = round(sum(components.values()), 2)
    ceiling_gb = float(eff_cfg.vram_ceiling_gb)
    gpu_total_gb = 16.00
    dwm_headroom_gb = round(gpu_total_gb - max(active_resident_gb, planned_full_stack_gb), 2)

    return {
        "gpu_envelope_gb": gpu_total_gb,
        "vram_ceiling_gb": ceiling_gb,
        "active_resident_vram_gb": active_resident_gb,
        "full_stack_budget_gb": planned_full_stack_gb,
        "dwm_safety_headroom_gb": dwm_headroom_gb,
        "headroom_gb": dwm_headroom_gb,
        "within_vram_ceiling": active_resident_gb <= ceiling_gb and planned_full_stack_gb <= ceiling_gb,
        "components_gb": components,
    }


def sanitize_tool_history_for_handoff(
    messages: List[Dict[str, Any]],
    target_provider: str = "gemini",
) -> List[Dict[str, Any]]:
    """Sanitize cross-model tool-call & tool-response records across Local (`Gemma-4`) <-> Cloud (`Gemini`) handoffs.

    Guarantees:
    - `messages[0]` (`system` prompt) is preserved byte-for-byte untouched for LM Studio KV cache stability.
    - OpenAI `tool_calls` + `role: "tool"` messages and Gemini `functionCall` / `functionResponse` parts are
      converted into schema-valid conversational records with zero orphaned `tool_call_id` or Jinja template crashes.
    """
    if not messages:
        return []

    sanitized: List[Dict[str, Any]] = []
    tool_outputs_by_id: Dict[str, str] = {}
    folded_tool_call_ids: set[str] = set()

    for msg in messages:
        if str(msg.get("role") or "") == "tool":
            tc_id = str(msg.get("tool_call_id") or msg.get("name") or "")
            if tc_id:
                tool_outputs_by_id[tc_id] = str(msg.get("content") or "")

    for idx, msg in enumerate(messages):
        if idx == 0 and msg.get("role") == "system":
            # Strictly preserve index-0 system prompt verbatim
            sanitized.append({"role": "system", "content": msg.get("content", "")})
            continue

        role = str(msg.get("role") or "user")
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")
        parts = msg.get("parts")

        # 1. OpenAI-style assistant message with `tool_calls`
        if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
            summaries: List[str] = []
            if isinstance(content, str) and content.strip():
                summaries.append(content.strip())
            for tc in tool_calls:
                fn = tc.get("function") or {}
                fn_name = str(fn.get("name") or tc.get("name") or "tool")
                fn_args = fn.get("arguments") or "{}"
                if not isinstance(fn_args, str):
                    fn_args = json.dumps(fn_args)
                tc_id = str(tc.get("id") or "")
                paired_out = tool_outputs_by_id.get(tc_id, "")
                if paired_out:
                    if tc_id:
                        folded_tool_call_ids.add(tc_id)
                    summaries.append(f"[Executed Tool `{fn_name}`({fn_args}) -> {paired_out}]")
                else:
                    summaries.append(f"[Invoked Tool `{fn_name}`({fn_args})]")
            sanitized.append({"role": "assistant", "content": "\n".join(summaries)})
            continue

        # 2. Skip standalone `role == "tool"` messages already folded or convert orphan tool result cleanly
        if role == "tool":
            tc_id = str(msg.get("tool_call_id") or "")
            if tc_id and tc_id in folded_tool_call_ids:
                continue
            t_name = str(msg.get("name") or "tool")
            sanitized.append(
                {
                    "role": "assistant",
                    "content": f"[Tool `{t_name}` Result: {msg.get('content', '')}]",
                }
            )
            continue

        # 3. Gemini-style `model` / `parts` containing `functionCall` or `functionResponse`
        if isinstance(parts, list):
            norm_role = "assistant" if role in ("model", "assistant") else "user"
            part_texts: List[str] = []
            for p in parts:
                if isinstance(p, dict):
                    if "text" in p and p["text"]:
                        part_texts.append(str(p["text"]).strip())
                    elif "functionCall" in p:
                        fc = p["functionCall"] or {}
                        part_texts.append(
                            f"[Invoked Tool `{fc.get('name', 'tool')}`({json.dumps(fc.get('args', {}))})]"
                        )
                    elif "functionResponse" in p:
                        fr = p["functionResponse"] or {}
                        part_texts.append(
                            f"[Tool `{fr.get('name', 'tool')}` Result: {json.dumps(fr.get('response', {}))}]"
                        )
            if part_texts:
                sanitized.append({"role": norm_role, "content": "\n".join(part_texts)})
            continue

        # 4. Standard user/assistant message (including multimodal `image_url` list on `gemma-4` or text extraction)
        norm_role = "assistant" if role in ("assistant", "model") else "user"
        if isinstance(content, list):
            if target_provider in ("gemma-4", "local", "openai"):
                sanitized.append({"role": norm_role, "content": content})
            else:
                # Flatten text blocks cleanly for cross-provider schema safety when image bytes aren't inline
                txt_only = "\n".join(
                    str(item.get("text", ""))
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ).strip()
                sanitized.append({"role": norm_role, "content": txt_only or "[Multimodal Turn]"})
        elif isinstance(content, str) and content.strip():
            sanitized.append({"role": norm_role, "content": content.strip()})

    return sanitized


def build_default_tools_schema() -> ToolsSchemaSpec:
    """Declare the 4 canonical full-duplex voice tools (`cancel_on_interruption=False`)."""
    return ToolsSchemaSpec(
        standard_tools=[
            FunctionSchemaSpec(
                name="get_system_telemetry",
                description="Return live KAIROS 2.0 GPU VRAM budget, KV prefix cache status, and service health.",
                parameters={"type": "object", "properties": {}, "required": []},
                cancel_on_interruption=False,
            ),
            FunctionSchemaSpec(
                name="search_local_notes",
                description="Search Canopy Vault notes via SQLite WAL FTS5 in <5ms while honoring #private rules.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Keywords to search in Canopy Vault."},
                        "folder": {"type": "string", "description": "Optional top-level folder filter."},
                    },
                    "required": ["query"],
                },
                cancel_on_interruption=False,
            ),
            FunctionSchemaSpec(
                name="execute_workspace_task",
                description="Create or update a Canopy Vault internal Projects task (respects Paperclip locks).",
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["create", "update_status"]},
                        "title": {"type": "string"},
                        "task_id": {"type": "string"},
                        "status": {"type": "string"},
                        "project": {"type": "string"},
                        "department": {"type": "string"},
                    },
                    "required": ["action"],
                },
                cancel_on_interruption=False,
            ),
            FunctionSchemaSpec(
                name=DELEGATE_TO_GEMINI_SCHEMA["name"],
                description=DELEGATE_TO_GEMINI_SCHEMA["description"],
                parameters=DELEGATE_TO_GEMINI_SCHEMA["parameters"],
                cancel_on_interruption=False,
            ),
        ]
    )


class UnifiedVoiceToolRegistry:
    """Executes voice tools asynchronously with `asyncio.shield` (`cancel_on_interruption=False`)."""

    def __init__(
        self,
        vault: VaultEngine,
        index: ShadowIndex,
        *,
        local_llm: Optional[LocalGemma4LLMService] = None,
        cloud_llm: Optional[CloudGeminiLLMService] = None,
        paperclip: Optional[Any] = None,
        cfg: Optional[KairosSettings] = None,
    ) -> None:
        self.vault = vault
        self.index = index
        self.cfg = cfg or settings
        self.local_llm = local_llm or LocalGemma4LLMService(cfg=self.cfg)
        self.cloud_llm = cloud_llm or CloudGeminiLLMService(cfg=self.cfg)
        self.paperclip = paperclip
        self.schema = build_default_tools_schema()
        self._custom_handlers: Dict[str, Callable[..., Dict[str, Any]]] = {}

    def get_tool_declarations(self) -> List[Dict[str, Any]]:
        """Return Gemini/MCP-compatible function declarations for all registered voice tools."""
        return [t.to_gemini_declaration() for t in self.schema.standard_tools]

    def register_handler(self, name: str, fn: Callable[..., Dict[str, Any]]) -> None:
        self._custom_handlers[name] = fn

    def _run_sync(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        is_private: bool = False,
        active_note_path: str = "",
    ) -> Dict[str, Any]:
        if tool_name in self._custom_handlers:
            return self._custom_handlers[tool_name](**arguments)

        if tool_name == "get_system_telemetry":
            return {
                "ok": True,
                "tool": tool_name,
                "vram": get_vram_envelope_telemetry(cfg=self.cfg),
                "rollup": self.index.get_rollup(),
            }

        if tool_name == "search_local_notes":
            query = str(arguments.get("query") or "")
            folder = str(arguments.get("folder") or "")
            hits = self.index.search_vault(query=query, folder=folder, limit=5)
            if not is_private:
                hits = [h for h in hits if not h.get("is_private")]
            return {
                "ok": True,
                "tool": tool_name,
                "count": len(hits),
                "results": [{"rel_path": h["rel_path"], "title": h["title"]} for h in hits],
            }

        if tool_name == "execute_workspace_task":
            action = str(arguments.get("action") or "create")
            if action == "create":
                created = self.vault.create_task(
                    CreateTaskInput(
                        title=str(arguments.get("title") or "Voice Captured Task"),
                        project=str(arguments.get("project") or "KAIROS_2_0"),
                        department=str(arguments.get("department") or "Software_Development"),
                    )
                )
                self.index.index_file(self.vault.resolve_safe_path(created["rel_path"]))
                return {
                    "ok": True,
                    "tool": tool_name,
                    "task_id": created["frontmatter"]["id"],
                    "rel_path": created["rel_path"],
                }
            tid = str(arguments.get("task_id") or "")
            if self.paperclip is not None and self.paperclip.get_active_lock(tid) is not None:
                return {"ok": False, "tool": tool_name, "error": f"Task {tid} is locked by Paperclip"}
            updated = self.vault.update_task(
                UpdateTaskInput(
                    task_id=tid,
                    status=str(arguments.get("status") or "In Progress"),  # type: ignore[arg-type]
                )
            )
            self.index.index_file(self.vault.resolve_safe_path(updated["rel_path"]))
            return {"ok": True, "tool": tool_name, "task_id": tid, "status": updated["frontmatter"]["status"]}

        if tool_name == "delegate_to_gemini":
            return delegate_to_gemini(
                query=str(arguments.get("query") or ""),
                require_web_search=bool(arguments.get("require_web_search", True)),
                cloud_llm=self.cloud_llm,
                local_llm=self.local_llm,
                is_private=is_private,
                active_note_path=active_note_path,
            )

        return {"ok": False, "tool": tool_name, "error": f"Unknown tool '{tool_name}'"}

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        is_private: bool = False,
        active_note_path: str = "",
    ) -> Dict[str, Any]:
        """Run tool inside `asyncio.shield` (`cancel_on_interruption=False`) so barge-in never aborts mid-write."""
        coro = asyncio.to_thread(
            self._run_sync,
            tool_name,
            arguments,
            is_private=is_private,
            active_note_path=active_note_path,
        )
        return await asyncio.shield(coro)


class PlatformActionExecutor:
    """Unified full-platform AI action executor across Canopy Vault, Projects, Inbox, Calendar, Browser Clipper, Paperclip, CrewAI & Hermes.

    Used by both `KairosAssistant` deterministic Fast Skills and `<kairos_op>{...}</kairos_op>` conversational LLM tool emissions.
    Guarantees:
    - Atomic Vault Markdown writes + immediate SQLite WAL `ShadowIndex` synchronization.
    - Paperclip checkout lock enforcement before mutating or archiving any `TSK-*.md`.
    - SSRF perimeter validation (`safe_fetch_public_text`) on outbound web clips.
    - `#private` isolation on Hermes memory retention and skill distillation.
    - Structured `ui_commands` + `action_summary` returned on every mutation so the Desktop UI updates in real time.
    """

    SUPPORTED_OPS = (
        "vault_write_note",
        "vault_scaffold_section",
        "vault_create_entry",
        "vault_update_frontmatter",
        "vault_rename_note",
        "daily_note_append",
        "inbox_capture",
        "inbox_move_note",
        "inbox_promote_to_task",
        "inbox_promote_to_section_entry",
        "projects_create_task",
        "projects_update_task",
        "projects_archive_task",
        "projects_restore_task",
        "projects_create_structure",
        "projects_create_wiki_note",
        "projects_create_base",
        "calendar_create_event",
        "calendar_update_event",
        "calendar_delete_event",
        "calendar_time_block_task",
        "browser_clip_url",
        "paperclip_dispatch_crew",
        "paperclip_release_lock",
        "github_sync_org_catalog",
        "hermes_retain_memory",
        "hermes_create_skill",
        "hermes_distill_task",
    )

    def __init__(
        self,
        *,
        vault: VaultEngine,
        index: ShadowIndex,
        connectors: Optional[Any] = None,
        crew: Optional[Any] = None,
        paperclip: Optional[Any] = None,
        hermes: Optional[Any] = None,
        cfg: Optional[KairosSettings] = None,
    ) -> None:
        self.vault = vault
        self.index = index
        self.connectors = connectors
        self.crew = crew
        self.paperclip = paperclip if paperclip is not None else getattr(crew, "paperclip", None)
        self.hermes = hermes
        self.cfg = cfg or settings

    def _resolve_inbox_note_rel_path(self, src_rel_path: str = "", query: str = "") -> str:
        """Resolve an `00_Inbox/` note by explicit relative path, keyword match, or newest file (`latest`)."""
        if src_rel_path and src_rel_path.strip():
            cand = src_rel_path.strip().replace("\\", "/")
            if not cand.startswith("00_Inbox/") and "/" not in cand:
                cand = f"00_Inbox/{cand}"
            if not cand.lower().endswith(".md"):
                cand = f"{cand}.md"
            p = self.vault.resolve_safe_path(cand)
            if p.is_file():
                return self.vault.to_rel_path(p)

        inbox_dir = self.vault.vault_path / "00_Inbox"
        if not inbox_dir.is_dir():
            raise FileNotFoundError("00_Inbox directory does not exist.")
        md_files = sorted(
            [p for p in inbox_dir.glob("*.md") if p.is_file() and not p.name.startswith("_")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not md_files:
            raise FileNotFoundError("No unprocessed Markdown notes found in `00_Inbox/`.")

        clean_q = (query or "").strip().lower()
        if not clean_q or clean_q in ("latest", "newest", "last", "most recent", "recent", "top"):
            return self.vault.to_rel_path(md_files[0])

        for p in md_files:
            raw = p.read_text(encoding="utf-8", errors="replace")
            fm, body = parse_markdown_note(raw)
            hay = f"{p.stem} {fm.get('title', '')} {body[:600]}".lower()
            if clean_q in hay:
                return self.vault.to_rel_path(p)

        hits = self.index.search_vault(query=clean_q, folder="00_Inbox", limit=1)
        if hits:
            return str(hits[0]["rel_path"])

        raise FileNotFoundError(f"No note matching '{query}' found in `00_Inbox/`.")

    def _reindex_project_index_for_task_path(self, task_path: Any) -> None:
        proj_folder = self.vault._find_parent_project_folder(task_path)
        if proj_folder is not None:
            proj_idx = proj_folder / "_Project_Index.md"
            if proj_idx.is_file():
                self.index.index_file(proj_idx)

    def execute(
        self,
        op_name: str,
        args: Optional[Dict[str, Any]] = None,
        *,
        is_private: bool = False,
        active_task_id: str = "",
        active_note_path: str = "",
        active_browser_url: str = "",
        active_browser_title: str = "",
        actor: str = "KAIROS-AI",
    ) -> Dict[str, Any]:
        """Execute a structured platform mutation and return `{ok, op, action_summary, ui_commands, data}`."""
        clean_op = (op_name or "").strip().lower()
        payload = dict(args or {})

        try:
            # 1. Second Brain Note Create / Overwrite / Append
            if clean_op == "vault_write_note":
                title = str(payload.get("title") or "").strip()
                raw_path = str(payload.get("file_path") or payload.get("rel_path") or "").strip()
                if not raw_path:
                    folder = str(payload.get("folder") or "04_Resources").strip().strip("/")
                    slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", title or "AI_Note").strip("_")[:64] or "AI_Note"
                    raw_path = f"{folder}/{slug}.md"
                elif not raw_path.lower().endswith((".md", ".canvas", ".base")):
                    raw_path = f"{raw_path}.md"
                mode = "append" if str(payload.get("mode") or "overwrite").lower() == "append" else "overwrite"
                fm = dict(payload.get("frontmatter") or {})
                if title and "title" not in fm:
                    fm["title"] = title
                if is_private:
                    tags = list(fm.get("tags") or [])
                    if "private" not in [str(t).lower() for t in tags]:
                        tags.append("private")
                    fm["tags"] = tags
                body = str(payload.get("body") or payload.get("content") or "")
                res = self.vault.write_note(file_path=raw_path, frontmatter=fm, body=body, mode=mode)
                self.index.index_file(self.vault.resolve_safe_path(res["rel_path"]))
                ui_cmds: List[Dict[str, Any]] = []
                if bool(payload.get("open_in_ui", True)):
                    ui_cmds = [
                        {"type": "navigate_tab", "tab": "second-brain"},
                        {"type": "open_note", "rel_path": res["rel_path"]},
                    ]
                verb = "Appended to" if mode == "append" else "Saved"
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"{verb} Vault note `{res['rel_path']}`",
                    "ui_commands": ui_cmds,
                    "data": res,
                }

            # 1b. Scaffold or Expand an Adaptable Obsidian Domain Section Hub (`_Hub_Index.md` + `.base` + `.canvas` + Collections)
            if clean_op == "vault_scaffold_section":
                sec_name = str(payload.get("section_name") or payload.get("title") or "").strip()
                bp_key = str(payload.get("blueprint_key") or "auto").strip()
                if not sec_name and bp_key.lower() in ("", "auto", "custom"):
                    return {"ok": False, "op": clean_op, "error": "Provide `section_name` or a preset `blueprint_key`."}
                res = self.vault.scaffold_vault_section(
                    sec_name,
                    blueprint_key=bp_key,
                    parent_folder=str(payload.get("parent_folder") or ""),
                    icon=str(payload.get("icon") or ""),
                    description=str(payload.get("description") or ""),
                    collections=payload.get("collections") if isinstance(payload.get("collections"), list) else None,
                    schema_fields=payload.get("schema_fields") if isinstance(payload.get("schema_fields"), list) else None,
                    external_links=payload.get("external_links") if isinstance(payload.get("external_links"), list) else None,
                    seed_starters=bool(payload.get("seed_starters", True)),
                    is_private=bool(is_private or payload.get("is_private", False)),
                )
                self.index.rebuild_all()
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": (
                        f"Scaffolded Obsidian Section Hub `{res['title']}` (`{res['section_rel']}/`) "
                        f"with live `.base` catalog & `.canvas` ecosystem map"
                    ),
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "second-brain"},
                        {"type": "open_note", "rel_path": res["hub_index_rel"]},
                    ],
                    "data": res,
                }

            # 1c. Create a Structured Entry inside a Vault Section Hub or Collection
            if clean_op == "vault_create_entry":
                entry_title = str(payload.get("title") or "").strip()
                if not entry_title:
                    return {"ok": False, "op": clean_op, "error": "Entry `title` is required."}
                sec_or_fld = str(
                    payload.get("section_or_folder")
                    or payload.get("section")
                    or payload.get("folder")
                    or "04_Resources"
                ).strip()
                res = self.vault.create_section_entry(
                    section_or_folder=sec_or_fld,
                    title=entry_title,
                    collection=str(payload.get("collection") or ""),
                    item_type=str(payload.get("item_type") or ""),
                    properties=payload.get("properties") if isinstance(payload.get("properties"), dict) else {},
                    body=str(payload.get("body") or ""),
                    checklist=payload.get("checklist") if isinstance(payload.get("checklist"), list) else None,
                    tags=payload.get("tags") if isinstance(payload.get("tags"), list) else None,
                    aliases=payload.get("aliases") if isinstance(payload.get("aliases"), list) else None,
                    is_private=bool(is_private or payload.get("is_private", False)),
                )
                self.index.index_file(self.vault.resolve_safe_path(res["rel_path"]))
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Created structured Vault entry `{res['title']}` (`{res['rel_path']}`)",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "second-brain"},
                        {"type": "open_note", "rel_path": res["rel_path"]},
                    ],
                    "data": res,
                }

            # 1d. Patch / Remove YAML Frontmatter Properties on a Vault Note
            if clean_op == "vault_update_frontmatter":
                f_path = str(payload.get("file_path") or payload.get("rel_path") or active_note_path or "").strip()
                if not f_path:
                    return {"ok": False, "op": clean_op, "error": "No `file_path` provided or open in Second Brain."}
                target = self.vault.resolve_safe_path(f_path)
                m_tsk = re.match(r"^(TSK-\d{8}-\d{3})\b", target.stem, flags=re.IGNORECASE)
                if m_tsk and self.paperclip is not None:
                    lock = self.paperclip.get_active_lock(m_tsk.group(1).upper())
                    if lock is not None and actor != lock.get("agent"):
                        return {
                            "ok": False,
                            "op": clean_op,
                            "error": f"Paperclip Lock Conflict: `{m_tsk.group(1).upper()}` is checked out by `{lock['agent']}`.",
                        }
                res = self.vault.update_note_frontmatter(
                    f_path,
                    updates=payload.get("updates") if isinstance(payload.get("updates"), dict) else {},
                    remove_keys=payload.get("remove_keys") if isinstance(payload.get("remove_keys"), list) else None,
                )
                self.index.index_file(self.vault.resolve_safe_path(res["rel_path"]))
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Updated YAML frontmatter on `{res['rel_path']}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "second-brain"},
                        {"type": "open_note", "rel_path": res["rel_path"]},
                    ],
                    "data": res,
                }

            # 1e. Link-Safe Rename / Move Vault Note (with `[[WikiLink]]` + `.canvas` refactoring)
            if clean_op == "vault_rename_note":
                src_p = str(
                    payload.get("src_rel_path") or payload.get("file_path") or active_note_path or ""
                ).strip()
                dest_p = str(
                    payload.get("dest_rel_path") or payload.get("new_path") or payload.get("new_name") or ""
                ).strip()
                if not src_p or not dest_p:
                    return {"ok": False, "op": clean_op, "error": "Both `src_rel_path` and `dest_rel_path` are required."}
                src_abs = self.vault.resolve_safe_path(src_p)
                m_tsk = re.match(r"^(TSK-\d{8}-\d{3})\b", src_abs.stem, flags=re.IGNORECASE)
                if m_tsk and self.paperclip is not None:
                    lock = self.paperclip.get_active_lock(m_tsk.group(1).upper())
                    if lock is not None and actor != lock.get("agent"):
                        return {
                            "ok": False,
                            "op": clean_op,
                            "error": f"Paperclip Lock Conflict: `{m_tsk.group(1).upper()}` is checked out by `{lock['agent']}`.",
                        }
                res = self.vault.rename_or_move_note(
                    src_p,
                    dest_p,
                    new_title=str(payload.get("new_title") or ""),
                    update_links=bool(payload.get("update_links", True)),
                )
                self.index.remove_file(src_abs)
                self.index.index_file(self.vault.resolve_safe_path(res["new_rel_path"]))
                for upd_rel in res.get("updated_backlink_files") or []:
                    self.index.index_file(self.vault.resolve_safe_path(upd_rel))
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": (
                        f"Renamed `{res['old_rel_path']}` -> `{res['new_rel_path']}` "
                        f"({len(res.get('updated_backlink_files') or [])} link file(s) updated)"
                    ),
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "second-brain"},
                        {"type": "open_note", "rel_path": res["new_rel_path"]},
                    ],
                    "data": res,
                }

            # 2. Daily Note Append (`03_Personal/Calendar/YYYY-MM-DD.md`)
            if clean_op == "daily_note_append":
                date_str = str(payload.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
                    date_str = datetime.now().strftime("%Y-%m-%d")
                entry = str(payload.get("entry") or payload.get("body") or payload.get("text") or "").strip()
                if not entry:
                    return {"ok": False, "op": clean_op, "error": "Daily note entry text is empty."}
                rel_path = f"03_Personal/Calendar/{date_str}.md"
                abs_path = self.vault.resolve_safe_path(rel_path)
                stamp = datetime.now().strftime("%H:%M")
                bullet = f"- **{stamp}:** {entry}"
                if abs_path.is_file():
                    res = self.vault.write_note(
                        file_path=rel_path,
                        frontmatter={},
                        body=bullet,
                        mode="append",
                    )
                else:
                    tags = ["daily-note", "calendar"] + (["private"] if is_private else [])
                    res = self.vault.write_note(
                        file_path=rel_path,
                        frontmatter={
                            "title": f"Daily Note — {date_str}",
                            "type": "daily_note",
                            "date": date_str,
                            "tags": tags,
                        },
                        body=f"# 🗓️ Daily Note — {date_str}\n\n## Daily Log\n{bullet}\n",
                        mode="overwrite",
                    )
                self.index.index_file(self.vault.resolve_safe_path(res["rel_path"]))
                ui_cmds = (
                    [
                        {"type": "navigate_tab", "tab": "second-brain"},
                        {"type": "open_note", "rel_path": res["rel_path"]},
                    ]
                    if bool(payload.get("open_in_ui", False))
                    else []
                )
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Appended entry to Daily Note `{res['rel_path']}`",
                    "ui_commands": ui_cmds,
                    "data": res,
                }

            # 3. Quick Capture to `00_Inbox/`
            if clean_op == "inbox_capture":
                body = str(payload.get("body") or payload.get("text") or payload.get("title") or "").strip()
                title = str(payload.get("title") or body[:64] or "Quick Capture").strip()
                slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", title).strip("_")[:48] or "Capture"
                rel_path = f"00_Inbox/Capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}.md"
                tags = list(payload.get("tags") or ["inbox", "quick-capture"])
                if is_private and "private" not in [str(t).lower() for t in tags]:
                    tags.append("private")
                res = self.vault.write_note(
                    file_path=rel_path,
                    frontmatter={
                        "title": title,
                        "type": "capture",
                        "captured_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                        "tags": tags,
                    },
                    body=f"# 📥 {title}\n\n{body}\n",
                    mode="overwrite",
                )
                self.index.index_file(self.vault.resolve_safe_path(res["rel_path"]))
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Captured `{res['rel_path']}` into `00_Inbox/`",
                    "ui_commands": [{"type": "navigate_tab", "tab": "inbox"}] if payload.get("open_in_ui") else [],
                    "data": res,
                }

            # 4. Move Inbox Note to Vault Folder
            if clean_op == "inbox_move_note":
                src_rel = self._resolve_inbox_note_rel_path(
                    src_rel_path=str(payload.get("src_rel_path") or ""),
                    query=str(payload.get("query") or ""),
                )
                dest_folder = str(payload.get("dest_folder") or "04_Resources").strip()
                old_abs = self.vault.resolve_safe_path(src_rel)
                moved = self.vault.move_note(src_rel, dest_folder)
                self.index.remove_file(old_abs)
                self.index.index_file(self.vault.resolve_safe_path(moved["rel_path"]))
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Moved `{src_rel}` -> `{moved['rel_path']}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "second-brain"},
                        {"type": "open_note", "rel_path": moved["rel_path"]},
                    ],
                    "data": moved,
                }

            # 5. Promote Inbox Capture / Clip into Structured Project Task
            if clean_op == "inbox_promote_to_task":
                src_rel = self._resolve_inbox_note_rel_path(
                    src_rel_path=str(payload.get("src_rel_path") or ""),
                    query=str(payload.get("query") or ""),
                )
                proj = str(payload.get("project") or "KAIROS_2_0").strip().strip("[]") or "KAIROS_2_0"
                dept = str(payload.get("department") or "Software_Development").strip() or "Software_Development"
                lst = str(payload.get("list") or payload.get("list_name") or "Sprint_01").strip() or "Sprint_01"
                prio = int(payload.get("priority") or 2)
                agent_val = str(payload.get("ai_agent") or "None")
                old_abs = self.vault.resolve_safe_path(src_rel)
                promoted = self.vault.promote_inbox_note_to_task(
                    src_rel_path=src_rel,
                    project=proj,
                    department=dept,
                    list_name=lst,
                    priority=max(1, min(4, prio)),
                    ai_agent=agent_val,
                )
                self.index.remove_file(old_abs)
                self.index.index_file(self.vault.resolve_safe_path(promoted["archived_capture"]))
                task_abs = self.vault.resolve_safe_path(promoted["task"]["rel_path"])
                self.index.index_file(task_abs)
                self._reindex_project_index_for_task_path(task_abs)
                tid = promoted["task"]["frontmatter"]["id"]
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Promoted `{src_rel}` -> Task `{tid}` in `{proj}/{dept}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "projects"},
                        {"type": "select_project_scope", "project": proj, "department": dept, "list": lst},
                        {"type": "open_task_drawer", "task_id": tid},
                    ],
                    "data": promoted,
                }

            # 5b. Promote Inbox Capture / Clip into Structured Obsidian Section Hub Entry
            if clean_op == "inbox_promote_to_section_entry":
                src_rel = self._resolve_inbox_note_rel_path(
                    src_rel_path=str(payload.get("src_rel_path") or ""),
                    query=str(payload.get("query") or ""),
                )
                sec_folder = str(
                    payload.get("section_or_folder")
                    or payload.get("section")
                    or "04_Resources/Music_Studio"
                ).strip()
                col_val = str(payload.get("collection") or "").strip()
                itype_val = str(payload.get("item_type") or "").strip()
                vendor_val = str(payload.get("vendor") or "").strip()
                props_val = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
                old_abs = self.vault.resolve_safe_path(src_rel)
                pre_sec = self.vault.resolve_safe_path(sec_folder)
                had_hub = (pre_sec / "_Hub_Index.md").is_file() or (pre_sec.parent / "_Hub_Index.md").is_file()
                promoted_sec = self.vault.promote_inbox_note_to_section_entry(
                    src_rel,
                    section_or_folder=sec_folder,
                    collection=col_val,
                    item_type=itype_val,
                    vendor=vendor_val,
                    properties=props_val,
                )
                if not had_hub:
                    self.index.rebuild_all()
                else:
                    self.index.remove_file(old_abs)
                    self.index.index_file(self.vault.resolve_safe_path(promoted_sec["archived_capture"]))
                    self.index.index_file(self.vault.resolve_safe_path(promoted_sec["entry"]["rel_path"]))
                ent_rel = promoted_sec["entry"]["rel_path"]
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Promoted Inbox `{src_rel}` -> Section Hub entry `{ent_rel}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "second-brain"},
                        {"type": "open_note", "rel_path": ent_rel},
                    ],
                    "data": promoted_sec,
                }

            # 6. Create Project Task
            if clean_op == "projects_create_task":
                title = str(payload.get("title") or "").strip()
                if not title:
                    return {"ok": False, "op": clean_op, "error": "Task title is required."}
                proj = str(payload.get("project") or "KAIROS_2_0").strip().strip("[]") or "KAIROS_2_0"
                dept = str(payload.get("department") or "Software_Development").strip() or "Software_Development"
                lst = str(payload.get("list") or payload.get("list_name") or "Sprint_01").strip() or "Sprint_01"
                prio = max(1, min(4, int(payload.get("priority") or 3)))
                tags = list(payload.get("tags") or [])
                if is_private and "private" not in [str(t).lower() for t in tags]:
                    tags.append("private")
                created = self.vault.create_task(
                    CreateTaskInput(
                        title=title,
                        project=proj,
                        department=dept,
                        list=lst,
                        status=str(payload.get("status") or "To Do"),  # type: ignore[arg-type]
                        priority=prio,
                        due_date=str(payload.get("due_date") or ""),
                        start_date=str(payload.get("start_date") or ""),
                        ai_agent=str(payload.get("ai_agent") or "None"),
                        parent_task=str(payload.get("parent_task") or ""),
                        depends_on=list(payload.get("depends_on") or []),
                        description=str(payload.get("description") or title),
                        checklist=list(payload.get("checklist") or []),
                        tags=tags,
                    )
                )
                task_abs = self.vault.resolve_safe_path(created["rel_path"])
                self.index.index_file(task_abs)
                self._reindex_project_index_for_task_path(task_abs)
                tid = created["frontmatter"]["id"]
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Created task `{tid}` ({title}) in `{proj}/{dept}/{lst}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "projects"},
                        {"type": "select_project_scope", "project": proj, "department": dept, "list": lst},
                        {"type": "open_task_drawer", "task_id": tid},
                    ],
                    "data": created,
                }

            # 7. Update Project Task (Status, Priority, Checklist Toggle/Add, Due Date, Subtask/Blocker, Time Log)
            if clean_op == "projects_update_task":
                tid = str(payload.get("task_id") or active_task_id or "").strip().upper()
                if not tid:
                    return {"ok": False, "op": clean_op, "error": "No `task_id` provided or open in TaskDrawer."}
                if self.paperclip is not None:
                    lock = self.paperclip.get_active_lock(tid)
                    if lock is not None and actor != lock.get("agent"):
                        return {
                            "ok": False,
                            "op": clean_op,
                            "error": f"Paperclip Lock Conflict: `{tid}` is currently checked out by `{lock['agent']}`.",
                        }
                old_abs = self.vault.find_task_file(tid)
                chk_idx = payload.get("toggle_checklist_index")
                updated = self.vault.update_task(
                    UpdateTaskInput(
                        task_id=tid,
                        title=payload.get("title"),
                        status=payload.get("status"),
                        priority=int(payload["priority"]) if payload.get("priority") is not None else None,
                        department=payload.get("department"),
                        ai_agent=payload.get("ai_agent"),
                        parent_task=payload.get("parent_task"),
                        depends_on=payload.get("depends_on"),
                        start_date=payload.get("start_date"),
                        due_date=payload.get("due_date"),
                        time_logged_delta=float(payload.get("time_logged_delta") or 0.0),
                        toggle_checklist_index=int(chk_idx) if chk_idx is not None else None,
                        add_checklist_item=payload.get("add_checklist_item"),
                        log_entry=payload.get("log_entry"),
                        actor=actor,
                    )
                )
                new_abs = self.vault.resolve_safe_path(updated["rel_path"])
                if old_abs.resolve() != new_abs.resolve():
                    self.index.remove_file(old_abs)
                self.index.index_file(new_abs)
                self._reindex_project_index_for_task_path(new_abs)
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Updated task `{tid}` (`{updated['frontmatter'].get('status', 'To Do')}`)",
                    "ui_commands": [{"type": "open_task_drawer", "task_id": tid}],
                    "data": updated,
                }

            # 8. Soft-Archive Task (`05_Archives/Tasks/[Project]/`)
            if clean_op == "projects_archive_task":
                tid = str(payload.get("task_id") or active_task_id or "").strip().upper()
                if not tid:
                    return {"ok": False, "op": clean_op, "error": "No `task_id` provided to archive."}
                if self.paperclip is not None:
                    lock = self.paperclip.get_active_lock(tid)
                    if lock is not None and actor != lock.get("agent"):
                        return {
                            "ok": False,
                            "op": clean_op,
                            "error": f"Paperclip Lock Conflict: `{tid}` is currently checked out by `{lock['agent']}`.",
                        }
                old_abs = self.vault.find_task_file(tid)
                proj_folder = self.vault._find_parent_project_folder(old_abs)
                # AI-initiated archives always soft-archive unless `allow_permanent=True` is explicitly set
                permanent = bool(payload.get("permanent", False) and payload.get("allow_permanent", False))
                res = self.vault.delete_or_archive_task(tid, permanent=permanent, actor=actor)
                self.index.remove_file(old_abs)
                if res.get("archived_rel_path"):
                    self.index.index_file(self.vault.resolve_safe_path(res["archived_rel_path"]))
                if proj_folder is not None and proj_folder.exists():
                    for sib in proj_folder.rglob("TSK-*.md"):
                        self.index.index_file(sib)
                    proj_idx = proj_folder / "_Project_Index.md"
                    if proj_idx.is_file():
                        self.index.index_file(proj_idx)
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Archived task `{res['task_id']}` -> `{res.get('archived_rel_path') or 'deleted'}`",
                    "ui_commands": [{"type": "navigate_tab", "tab": "projects"}],
                    "data": res,
                }

            # 9. Restore Archived Task (`05_Archives/Tasks/` -> `02_Projects/`)
            if clean_op == "projects_restore_task":
                raw_tid = str(payload.get("task_id") or "").strip()
                if not raw_tid or raw_tid.lower() in ("latest", "last", "newest", "most recent"):
                    archived_list = self.vault.list_archived_tasks()
                    if not archived_list:
                        return {"ok": False, "op": clean_op, "error": "No archived tasks found in `05_Archives/Tasks/`."}
                    raw_tid = str(archived_list[0]["id"])
                tid = raw_tid.upper()
                res = self.vault.restore_archived_task(tid, actor=actor)
                if res.get("old_archived_rel_path"):
                    self.index.remove_path(self.vault.vault_path / res["old_archived_rel_path"])
                restored_abs = self.vault.resolve_safe_path(res["rel_path"])
                self.index.index_file(restored_abs)
                self._reindex_project_index_for_task_path(restored_abs)
                fm = res.get("frontmatter") or {}
                proj = str(fm.get("project") or "KAIROS_2_0").strip("[]")
                dept = str(fm.get("department") or "Software_Development")
                lst = str(fm.get("list") or "Sprint_01")
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Restored archived task `{res['task_id']}` to `{proj}/{dept}/{lst}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "projects"},
                        {"type": "select_project_scope", "project": proj, "department": dept, "list": lst},
                        {"type": "open_task_drawer", "task_id": res["task_id"]},
                    ],
                    "data": res,
                }

            # 10. Scaffold Project or Custom Category Structure
            if clean_op == "projects_create_structure":
                proj = str(payload.get("project") or "").strip().strip("[]")
                if not proj:
                    return {"ok": False, "op": clean_op, "error": "Project name is required."}
                dept = str(payload.get("department") or "Software_Development").strip() or "Software_Development"
                lst = str(payload.get("list") or payload.get("list_name") or "Sprint_01").strip() or "Sprint_01"
                res = self.vault.create_project_structure(
                    project=proj,
                    department=dept,
                    list_name=lst,
                    scaffold_standard_departments=bool(payload.get("scaffold_standard_departments", True)),
                    owner=str(payload.get("owner") or self.cfg.operator_name),
                    target_end_date=str(payload.get("target_end_date") or ""),
                )
                proj_dir = self.vault.vault_path / "02_Projects" / res["project"]
                for md_file in proj_dir.rglob("*.md"):
                    self.index.index_file(md_file)
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Scaffolded project structure `02_Projects/{res['project']}/{res['department']}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "projects"},
                        {
                            "type": "select_project_scope",
                            "project": res["project"],
                            "department": res["department"],
                            "list": res["list"],
                        },
                    ],
                    "data": res,
                }

            # 11. Create Project Wiki Note (`02_Projects/[Project]/Docs/*.md`)
            if clean_op == "projects_create_wiki_note":
                proj = str(payload.get("project") or "KAIROS_2_0").strip().strip("[]") or "KAIROS_2_0"
                safe_proj = re.sub(r"[^A-Za-z0-9_\- ]+", "_", proj).strip().replace(" ", "_") or "KAIROS_2_0"
                title = str(payload.get("title") or "Architecture_Note").strip()
                slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", title).strip("_")[:56] or "Wiki_Doc"
                rel_path = f"02_Projects/{safe_proj}/Docs/{slug}.md"
                cat = str(payload.get("category") or "Spec")
                body = str(payload.get("body") or f"# 📄 {title}\n\n")
                res = self.vault.write_note(
                    file_path=rel_path,
                    frontmatter={
                        "title": title,
                        "type": "wiki_doc",
                        "project": f"[[{safe_proj}]]",
                        "category": cat,
                        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                        "tags": ["wiki", safe_proj.lower()] + (["private"] if is_private else []),
                    },
                    body=body if body.lstrip().startswith("#") else f"# 📄 {title}\n\n{body}\n",
                    mode="overwrite",
                )
                self.index.index_file(self.vault.resolve_safe_path(res["rel_path"]))
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Created Project Wiki page `{res['rel_path']}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "projects"},
                        {"type": "select_project_scope", "project": safe_proj, "department": "", "list": ""},
                        {"type": "set_projects_view", "view": "docs"},
                    ],
                    "data": res,
                }

            # 11b. Create or Refresh Project Obsidian `.base` Database (`02_Projects/[Project]/Docs/Project_Tasks.base`)
            if clean_op == "projects_create_base":
                proj = str(payload.get("project") or "KAIROS_2_0").strip().strip("[]") or "KAIROS_2_0"
                res = self.vault.ensure_project_tasks_base(proj)
                self.index.rebuild_all()
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Generated Project Obsidian Base `{res['base_rel_path']}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "projects"},
                        {"type": "select_project_scope", "project": res["project"], "department": "", "list": ""},
                        {"type": "set_projects_view", "view": "docs"},
                    ],
                    "data": res,
                }

            # 12. Calendar Events & Task Time-Blocking
            if clean_op == "calendar_create_event" and self.connectors is not None:
                start_iso = str(
                    payload.get("start_time_iso")
                    or payload.get("start_time")
                    or f"{datetime.now().strftime('%Y-%m-%d')}T09:00:00"
                )
                dur_hrs = float(payload.get("duration_hrs") or 1.0)
                res = self.connectors.create_calendar_event(
                    title=str(payload.get("title") or "Scheduled Block"),
                    start_time_iso=start_iso,
                    duration_hrs=dur_hrs,
                    category=str(payload.get("category") or "Business"),
                    location=str(payload.get("location") or ""),
                    linked_project=str(payload.get("linked_project") or payload.get("project") or ""),
                    linked_task=str(payload.get("linked_task") or ""),
                    notes=str(payload.get("notes") or ""),
                )
                self.index.index_file(self.vault.resolve_safe_path(res["rel_path"]))
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Scheduled Calendar event `{res['frontmatter']['id']}` ({res['frontmatter']['title']})",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "projects"},
                        {"type": "set_projects_view", "view": "calendar"},
                    ],
                    "data": res,
                }

            if clean_op == "calendar_update_event" and self.connectors is not None:
                res = self.connectors.update_calendar_event(
                    str(payload.get("event_id") or ""),
                    new_date_iso=str(payload.get("new_date_iso") or ""),
                    start_time_iso=str(payload.get("start_time_iso") or payload.get("start_time") or ""),
                    duration_hrs=float(payload["duration_hrs"]) if payload.get("duration_hrs") is not None else None,
                    title=payload.get("title"),
                    category=payload.get("category"),
                )
                self.index.index_file(self.vault.resolve_safe_path(res["rel_path"]))
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Updated Calendar event `{res['frontmatter']['id']}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "projects"},
                        {"type": "set_projects_view", "view": "calendar"},
                    ],
                    "data": res,
                }

            if clean_op == "calendar_delete_event" and self.connectors is not None:
                ev_id = str(payload.get("event_id") or "").strip()
                res = self.connectors.delete_calendar_event(ev_id)
                if res.get("rel_path"):
                    self.index.remove_path(self.vault.vault_path / res["rel_path"])
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Removed Calendar event `{ev_id}`",
                    "ui_commands": [],
                    "data": res,
                }

            if clean_op == "calendar_time_block_task" and self.connectors is not None:
                tid = str(payload.get("task_id") or active_task_id or "").strip().upper()
                start_iso = str(
                    payload.get("start_time_iso")
                    or payload.get("start_time")
                    or payload.get("start_iso")
                    or f"{datetime.now().strftime('%Y-%m-%d')}T10:00:00"
                )
                dur_hrs = float(payload["duration_hrs"]) if payload.get("duration_hrs") is not None else None
                res = self.connectors.time_block_task_on_calendar(
                    task_id=tid,
                    start_time_iso=start_iso,
                    duration_hrs=dur_hrs,
                    category=str(payload.get("category") or "Business"),
                )
                self.index.index_file(self.vault.find_task_file(tid))
                self.index.index_file(self.vault.resolve_safe_path(res["rel_path"]))
                evt_id = res["frontmatter"]["id"]
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Time-blocked task `{tid}` -> `{evt_id}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "projects"},
                        {"type": "set_projects_view", "view": "calendar"},
                    ],
                    "data": res,
                }

            # 13. Browser Clipper (SSRF-guarded Defuddle clip + optional immediate Task Promotion)
            if clean_op == "browser_clip_url":
                url = str(payload.get("url") or active_browser_url or "").strip()
                if not url:
                    return {"ok": False, "op": clean_op, "error": "No URL provided or open in Embedded Browser."}
                title = str(payload.get("title") or active_browser_title or "").strip()
                raw_text = str(payload.get("raw_html_or_text") or "").strip()
                if not raw_text:
                    try:
                        raw_text = safe_fetch_public_text(url, timeout=4.5, max_bytes=350_000)
                    except SSRFBlockedError as ssrf_exc:
                        return {"ok": False, "op": clean_op, "error": f"SSRF Guard blocked URL: {ssrf_exc}"}
                    except Exception:
                        raw_text = f"Clipped URL: {url}\nTitle: {title or url}"
                dest_folder = str(payload.get("dest_folder") or "00_Inbox").strip() or "00_Inbox"
                clipped = self.vault.defuddle_clip_to_vault(
                    url=url,
                    raw_html_or_text=raw_text,
                    title=title,
                    dest_folder=dest_folder,
                )
                self.index.index_file(self.vault.resolve_safe_path(clipped["rel_path"]))
                if bool(payload.get("promote_to_task", False)):
                    proj = str(payload.get("project") or "KAIROS_2_0").strip().strip("[]") or "KAIROS_2_0"
                    dept = str(payload.get("department") or "Software_Development").strip() or "Software_Development"
                    lst = str(payload.get("list") or "Sprint_01").strip() or "Sprint_01"
                    old_clip_abs = self.vault.resolve_safe_path(clipped["rel_path"])
                    promoted = self.vault.promote_inbox_note_to_task(
                        src_rel_path=clipped["rel_path"],
                        project=proj,
                        department=dept,
                        list_name=lst,
                        priority=int(payload.get("priority") or 2),
                    )
                    self.index.remove_file(old_clip_abs)
                    self.index.index_file(self.vault.resolve_safe_path(promoted["archived_capture"]))
                    task_abs = self.vault.resolve_safe_path(promoted["task"]["rel_path"])
                    self.index.index_file(task_abs)
                    self._reindex_project_index_for_task_path(task_abs)
                    tid = promoted["task"]["frontmatter"]["id"]
                    return {
                        "ok": True,
                        "op": clean_op,
                        "action_summary": f"Clipped `{url}` and promoted to task `{tid}` in `{proj}/{dept}`",
                        "ui_commands": [
                            {"type": "navigate_tab", "tab": "projects"},
                            {"type": "select_project_scope", "project": proj, "department": dept, "list": lst},
                            {"type": "open_task_drawer", "task_id": tid},
                        ],
                        "data": promoted,
                    }
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Clipped `{title or url}` -> `{clipped['rel_path']}`",
                    "ui_commands": [
                        {"type": "navigate_tab", "tab": "inbox" if dest_folder == "00_Inbox" else "second-brain"},
                        {"type": "open_note", "rel_path": clipped["rel_path"]},
                    ],
                    "data": clipped,
                }

            # 14. Paperclip CrewAI / Hermes Dispatch & Force Lock Release
            if clean_op == "paperclip_dispatch_crew" and self.crew is not None:
                tid = str(payload.get("task_id") or active_task_id or "").strip().upper()
                crew_name = str(payload.get("crew_name") or "CrewAI-Dev")
                res = self.crew.execute_task_with_crew(
                    task_id=tid,
                    crew_name=crew_name,
                    reference_url=str(payload.get("reference_url") or ""),
                )
                if res.get("artifact_rel_path"):
                    self.index.index_file(self.vault.resolve_safe_path(res["artifact_rel_path"]))
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Dispatched `{crew_name}` on `{tid}` via Paperclip",
                    "ui_commands": [{"type": "navigate_tab", "tab": "paperclip"}],
                    "data": res,
                }

            if clean_op == "paperclip_release_lock" and self.paperclip is not None:
                tid = str(payload.get("task_id") or active_task_id or "").strip().upper()
                if not tid:
                    return {"ok": False, "op": clean_op, "error": "No `task_id` provided to unlock."}
                res = self.paperclip.force_release_lock(
                    tid,
                    actor=actor,
                    reason=str(payload.get("reason") or "Operator/AI voice unlock"),
                )
                if res.get("released"):
                    summary = f"Force-released Paperclip lock on `{tid}` (held by `{res.get('previous_agent')}`)"
                else:
                    summary = f"No active Paperclip lock was held on `{tid}`"
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": summary,
                    "ui_commands": [],
                    "data": res,
                }

            # 14b. GitHub Organization Catalog Sync (`ForestCityCreatorsLLC` -> `04_Resources/Code_and_Research/`)
            if clean_op == "github_sync_org_catalog" and self.connectors is not None:
                org_val = str(payload.get("org") or "ForestCityCreatorsLLC").strip() or "ForestCityCreatorsLLC"
                res = self.connectors.sync_github_org_repos_to_vault(org=org_val)
                cat_rel = str(res.get("catalog_rel_path") or "")
                if cat_rel:
                    self.index.index_file(self.vault.resolve_safe_path(cat_rel))
                ui_cmds = (
                    [
                        {"type": "navigate_tab", "tab": "second-brain"},
                        {"type": "open_note", "rel_path": cat_rel},
                    ]
                    if cat_rel and bool(payload.get("open_in_ui", True))
                    else []
                )
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": (
                        f"Synchronized `{res.get('org', org_val)}` GitHub catalog "
                        f"({res.get('repo_count', 0)} repo(s), {res.get('private_count', 0)} private) -> `{cat_rel}`"
                    ),
                    "ui_commands": ui_cmds,
                    "data": res,
                }

            # 15. Hermes Continuity Memory & Skill Engine
            if clean_op == "hermes_retain_memory" and self.hermes is not None:
                fact = str(payload.get("fact") or payload.get("text") or "").strip()
                if not fact:
                    return {"ok": False, "op": clean_op, "error": "Memory fact is empty."}
                target = "user" if str(payload.get("target") or "memory").lower() == "user" else "memory"
                res = self.hermes.retain_memory(
                    fact,
                    target=target,
                    section=str(payload.get("section") or payload.get("category") or "Project Decisions & Lessons"),
                    source=actor,
                    is_private=is_private or ("#private" in fact.lower()),
                )
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Retained Hermes memory in `{res['rel_path']}`",
                    "ui_commands": [],
                    "data": res,
                }

            if clean_op == "hermes_create_skill" and self.hermes is not None:
                steps_raw = payload.get("steps")
                steps_md = (
                    "\n".join(f"{idx + 1}. {s}" for idx, s in enumerate(steps_raw))
                    if isinstance(steps_raw, list)
                    else str(payload.get("steps_markdown") or payload.get("procedure_markdown") or "")
                )
                res = self.hermes.create_skill(
                    title=str(payload.get("title") or "Reusable Workflow Skill"),
                    category=str(payload.get("category") or payload.get("domain") or "Workflow"),
                    trigger=str(payload.get("trigger") or payload.get("trigger_intent") or ""),
                    steps_markdown=steps_md,
                    verification_notes=str(payload.get("notes") or payload.get("verification_notes") or ""),
                    project=str(payload.get("project") or ""),
                    source_task_id=str(payload.get("source_task_id") or ""),
                    is_private=is_private,
                )
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Created Hermes skill `{res['skill_id']}` (`{res['rel_path']}`)",
                    "ui_commands": [{"type": "navigate_tab", "tab": "paperclip"}],
                    "data": res,
                }

            if clean_op == "hermes_distill_task" and self.hermes is not None:
                tid = str(payload.get("task_id") or active_task_id or "").strip().upper()
                res = self.hermes.distill_from_task(
                    tid,
                    deliverable_text=str(payload.get("deliverable_text") or ""),
                )
                return {
                    "ok": True,
                    "op": clean_op,
                    "action_summary": f"Distilled `{tid}` into Hermes skill `{res['skill_id']}`",
                    "ui_commands": [{"type": "navigate_tab", "tab": "paperclip"}],
                    "data": res,
                }

            return {"ok": False, "op": clean_op, "error": f"Unsupported platform operation '{clean_op}'."}
        except Exception as exc:
            return {"ok": False, "op": clean_op, "error": str(exc)}


def extract_and_execute_kairos_ops(
    raw_text: str,
    executor: PlatformActionExecutor,
    *,
    is_private: bool = False,
    active_task_id: str = "",
    active_note_path: str = "",
    active_browser_url: str = "",
    active_browser_title: str = "",
    actor: str = "KAIROS-AI",
) -> Tuple[str, List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse `<kairos_op>{"op":"...","args":{...}}</kairos_op>` blocks emitted by Gemma 4 or Gemini and execute them.

    Returns `(cleaned_text, action_summaries, ui_commands, raw_results)`.
    """
    if not raw_text or "<kairos_op>" not in raw_text.lower():
        return (raw_text or "").strip(), [], [], []

    action_summaries: List[str] = []
    ui_commands: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []

    for match in KAIROS_OP_RE.finditer(raw_text):
        try:
            spec = json.loads(match.group(1))
        except Exception:
            continue
        if not isinstance(spec, dict):
            continue
        op_name = str(spec.get("op") or spec.get("action") or "").strip()
        if not op_name:
            continue
        op_args = spec.get("args") if isinstance(spec.get("args"), dict) else {
            k: v for k, v in spec.items() if k not in ("op", "action")
        }
        res = executor.execute(
            op_name,
            op_args,
            is_private=is_private,
            active_task_id=active_task_id,
            active_note_path=active_note_path,
            active_browser_url=active_browser_url,
            active_browser_title=active_browser_title,
            actor=actor,
        )
        results.append(res)
        if res.get("ok"):
            if res.get("action_summary"):
                action_summaries.append(str(res["action_summary"]))
            for cmd in res.get("ui_commands") or []:
                if isinstance(cmd, dict) and cmd.get("type"):
                    ui_commands.append(cmd)
        else:
            action_summaries.append(f"Action `{op_name}` skipped: {res.get('error', 'failed')}")

    cleaned = KAIROS_OP_RE.sub("", raw_text).strip()
    return cleaned, action_summaries, ui_commands, results

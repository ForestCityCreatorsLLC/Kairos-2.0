"""Strict Pydantic v2 schemas for Obsidian YAML Frontmatter, Projects Engine, KAIROS Assistant & MCP Tools (`schemas.py`)."""

from __future__ import annotations

import builtins
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

TaskType = Literal["task", "subtask", "bug", "milestone", "epic"]
TaskStatus = Literal["Backlog", "To Do", "In Progress", "Review", "Blocked", "Done"]
ProjectStatus = Literal["Planning", "Active", "On Hold", "Completed", "Archived"]
PersonaRole = Literal["companion", "pm", "dev", "creative", "owner"]
ToneMode = Literal["DEFAULT", "CODE_RED"]
AIAgentName = Literal[
    "None",
    "Gemma-4",
    "Gemini-Pro",
    "Both",
    "CrewAI-Research",
    "CrewAI-Dev",
    "CrewAI-PM",
    "Hermes-Agent",
    "Hermes-Synthesizer",
]

STANDARD_DEPARTMENT_NAMES = [
    "Software_Development",
    "Marketing_and_Branding",
    "Documentation",
    "Website",
    "Merch",
]


def _normalize_dept_alias(raw: str) -> str:
    clean = (raw or "").strip()
    if clean.lower() in ("software_dev", "software dev", "dev"):
        return "Software_Development"
    return clean or "Software_Development"


class TaskFrontmatter(BaseModel):
    """Canonical Task YAML Schema (`02_Projects/[Project]/[Department]/[List]/Tasks/TSK-YYYYMMDD-XXX.md`)."""

    id: str
    title: str
    type: TaskType = "task"
    status: TaskStatus = "To Do"
    priority: int = Field(default=3, ge=1, le=4)
    project: str = "[[KAIROS_2_0]]"
    department: str = "Software_Development"
    list: str = "Sprint_01"
    parent_task: str = ""
    depends_on: List[str] = Field(default_factory=builtins.list)
    assignee: str = "Jaime"
    ai_agent: str = "None"
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    start_date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    due_date: str = ""
    time_estimate_hrs: float = Field(default=1.0, ge=0.0)
    time_logged_hrs: float = Field(default=0.0, ge=0.0)
    github_issue_url: str = ""
    github_branch: str = ""
    gcal_event_id: str = ""
    tags: List[str] = Field(default_factory=builtins.list)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_space_folder(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if not out.get("project") and out.get("folder"):
            raw_proj = str(out["folder"]).strip().strip("[]") or "KAIROS_2_0"
            out["project"] = f"[[{raw_proj}]]"
        elif out.get("project"):
            raw_proj = str(out["project"]).strip().strip("[]") or "KAIROS_2_0"
            out["project"] = f"[[{raw_proj}]]"

        if not out.get("department") and out.get("space"):
            out["department"] = _normalize_dept_alias(str(out["space"]))
        elif out.get("department"):
            out["department"] = _normalize_dept_alias(str(out["department"]))

        out.pop("space", None)
        out.pop("folder", None)
        return out


class ProjectFrontmatter(BaseModel):
    """Canonical Project Rollup Schema (`02_Projects/[Project]/_Project_Index.md`)."""

    id: str
    title: str
    type: Literal["project"] = "project"
    status: ProjectStatus = "Active"
    category: str = "Flagship"
    departments: List[str] = Field(default_factory=lambda: builtins.list(STANDARD_DEPARTMENT_NAMES))
    owner: str = "Jaime"
    start_date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    target_end_date: str = ""
    github_repo: str = ""
    gdrive_folder_url: str = ""
    progress_pct: int = Field(default=0, ge=0, le=100)
    tags: List[str] = Field(default_factory=builtins.list)


class CalendarEventFrontmatter(BaseModel):
    """Canonical Calendar Event Schema (`03_Personal/Calendar/EVT-YYYYMMDD-XXX.md`)."""

    id: str
    gcal_id: str = ""
    title: str
    type: Literal["event"] = "event"
    category: Literal["Business", "Personal", "Health_and_Fitness", "Family"] = "Business"
    start_time: str
    end_time: str
    location: str = ""
    linked_project: str = ""
    linked_task: str = ""
    synced_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    tags: List[str] = Field(default_factory=lambda: ["calendar"])


class CreateTaskInput(BaseModel):
    title: str
    project: str = "KAIROS_2_0"
    department: str = "Software_Development"
    list: str = "Sprint_01"
    status: TaskStatus = "To Do"
    priority: int = Field(default=3, ge=1, le=4)
    due_date: str = ""
    start_date: str = ""
    assignee: str = "Jaime"
    ai_agent: str = "None"
    parent_task: str = ""
    depends_on: List[str] = Field(default_factory=builtins.list)
    time_estimate_hrs: float = 1.0
    description: str = ""
    checklist: List[str] = Field(default_factory=builtins.list)
    tags: List[str] = Field(default_factory=builtins.list)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if "project" not in out and "folder" in out:
            out["project"] = str(out.pop("folder")).strip().strip("[]") or "KAIROS_2_0"
        if "department" not in out and "space" in out:
            out["department"] = _normalize_dept_alias(str(out.pop("space")))
        if "time_estimate_hrs" not in out and "time_estimate" in out:
            out["time_estimate_hrs"] = out.pop("time_estimate")
        return out


class UpdateTaskInput(BaseModel):
    task_id: str = ""
    title: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[int] = Field(default=None, ge=1, le=4)
    department: Optional[str] = None
    assignee: Optional[str] = None
    ai_agent: Optional[str] = None
    parent_task: Optional[str] = None
    depends_on: Optional[List[str]] = None
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    gcal_event_id: Optional[str] = None
    time_estimate_hrs: Optional[float] = None
    time_logged_hrs: Optional[float] = None
    time_logged_delta: float = 0.0
    description: Optional[str] = None
    toggle_checklist_index: Optional[int] = None
    add_checklist_item: Optional[str] = None
    log_entry: Optional[str] = None
    actor: str = "Jaime"


class WriteNoteInput(BaseModel):
    file_path: str
    frontmatter: Dict[str, Any] = Field(default_factory=dict)
    body: str = ""
    mode: Literal["overwrite", "append"] = "overwrite"

    @model_validator(mode="before")
    @classmethod
    def _accept_rel_path_alias(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if "file_path" not in out:
            if "rel_path" in out:
                out["file_path"] = out.pop("rel_path")
            elif "path" in out:
                out["file_path"] = out.pop("path")
        return out


class InboxCaptureInput(BaseModel):
    title: str
    body: str = ""
    source: str = "Quick-Capture"
    tags: List[str] = Field(default_factory=builtins.list)
    is_private: bool = False


class VaultSectionScaffoldInput(BaseModel):
    section_name: str = ""
    blueprint_key: str = "auto"
    parent_folder: str = ""
    icon: str = ""
    description: str = ""
    collections: List[Any] = Field(default_factory=builtins.list)
    schema_fields: List[str] = Field(default_factory=builtins.list)
    external_links: List[Dict[str, str]] = Field(default_factory=builtins.list)
    seed_starters: bool = True
    is_private: bool = False


class VaultSectionEntryInput(BaseModel):
    section_or_folder: str = "04_Resources"
    title: str
    collection: str = ""
    item_type: str = ""
    properties: Dict[str, Any] = Field(default_factory=dict)
    body: str = ""
    checklist: List[str] = Field(default_factory=builtins.list)
    tags: List[str] = Field(default_factory=builtins.list)
    aliases: List[str] = Field(default_factory=builtins.list)
    is_private: bool = False


class PromoteInboxToSectionInput(BaseModel):
    src_rel_path: str
    section_or_folder: str = "04_Resources/Music_Studio"
    collection: str = ""
    item_type: str = ""
    vendor: str = ""
    properties: Dict[str, Any] = Field(default_factory=dict)


class UpdateNoteFrontmatterInput(BaseModel):
    file_path: str
    updates: Dict[str, Any] = Field(default_factory=dict)
    remove_keys: List[str] = Field(default_factory=builtins.list)

    @model_validator(mode="before")
    @classmethod
    def _accept_rel_path_alias(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if "file_path" not in out:
            if "rel_path" in out:
                out["file_path"] = out.pop("rel_path")
            elif "path" in out:
                out["file_path"] = out.pop("path")
        return out


class RenameVaultNoteInput(BaseModel):
    src_rel_path: str
    dest_rel_path: str
    new_title: str = ""
    update_links: bool = True


class AssistantTurnRecord(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    agent: str = ""
    persona: str = "companion"
    tone_mode: str = "DEFAULT"
    privacy_locked: bool = False
    actions: List[str] = Field(default_factory=builtins.list)


class AuditLogRecord(BaseModel):
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    agent: str
    route_reason: str
    tool: str
    target: str
    tokens_used: int = 0
    latency_ms: int = 0
    status: str = "success"

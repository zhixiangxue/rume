"""System-level and repo-level state models.

SystemState is the global state shared across the entire SystemFlow.
RepoState is per-repo state managed within a single RepoFlow instance.
"""

from typing import Any
from pydantic import BaseModel, Field


class ServiceMeta(BaseModel):
    """Metadata for a single service tracked by SystemFlow."""

    repo_url: str = ""
    work_dir: str = ""
    role: str = ""  # e.g. "backend", "frontend", "database"
    expected_port: int | None = None
    depends_on: list[str] = Field(default_factory=list)
    status: str = "pending"  # pending | running | ready | failed
    result: dict[str, Any] = Field(default_factory=dict)  # port, url, pid, ...
    attempts: int = 0
    error: str = ""


class SystemState(BaseModel):
    """Global state for SystemFlow.

    Tracks what services exist, their status, execution order,
    and the overall system goal.
    """

    model_config = {"extra": "allow"}

    prompt: str = ""
    goal: str = ""  # LLM-refined system-level goal
    services: dict[str, ServiceMeta] = Field(default_factory=dict)
    execution_order: list[list[str]] = Field(default_factory=list)
    system_ready: bool = False
    global_config: dict[str, Any] = Field(default_factory=dict)
    retry_services: list[str] = Field(default_factory=list)
    current_batch: int = 0
    last_error: str = ""
    human_feedback: str = ""


class RepoState(BaseModel):
    """Per-repo state managed within a RepoFlow instance."""

    model_config = {"extra": "allow"}

    repo_url: str = ""
    work_dir: str = ""
    role: str = ""
    depends_on: list[str] = Field(default_factory=list)
    expected_port: int | None = None
    global_config: dict[str, Any] = Field(default_factory=dict)
    system_goal: str = ""  # User's high-level goal, passed from SystemFlow

    # observe output
    observations: dict[str, Any] = Field(default_factory=dict)

    # plan output
    plan: dict[str, Any] = Field(default_factory=dict)

    # execute log
    execution_log: list[str] = Field(default_factory=list)

    # final result
    result: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"  # pending | running | ready | failed
    error: str = ""
    attempts: int = 0

    # RUME.md skill file
    rume_path: str = ""  # path to generated RUME.md (in work_dir)

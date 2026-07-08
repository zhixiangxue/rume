"""Pydantic models for structured LLM output.

Used with chak's ``returns=`` parameter to get validated responses
instead of fragile manual JSON parsing via ``_extract_json()``.
"""

from typing import Any
from pydantic import BaseModel, Field


# ── Repo-level (RepoFlow) ─────────────────────────────────────────

class ObserveOutput(BaseModel):
    """Output from the observe node — repo analysis."""

    model_config = {"extra": "allow"}

    project_type: str = ""
    package_manager: str = ""
    entry_file: str = ""
    install_commands: list[str] = Field(default_factory=list)
    build_commands: list[str] = Field(default_factory=list)
    run_commands: list[str] = Field(default_factory=list)
    default_port: int | None = None
    external_dependencies: list[str] = Field(default_factory=list)
    key_files: list[str] = Field(default_factory=list)
    docker_available: bool = False
    docker_compose_file: str = ""
    docker_run_from_readme: str = ""
    docker_commands: dict[str, list[str]] = Field(default_factory=dict)
    config_required: bool = False
    config_files: list[str] = Field(default_factory=list)
    config_mount_point: str = ""
    config_example_path: str = ""


class PlanStep(BaseModel):
    """A single step in the execution plan."""

    model_config = {"extra": "allow"}

    description: str = ""
    command: str = ""
    purpose: str = ""


class SuccessCriteria(BaseModel):
    """Criteria for determining if the project is ready.

    No fixed enum — the LLM defines what success means based on project type.
    """

    model_config = {"extra": "allow"}

    description: str = ""


class PlanOutput(BaseModel):
    """Output from the plan node — execution plan."""

    model_config = {"extra": "allow"}

    steps: list[PlanStep] = Field(default_factory=list)
    success_criteria: SuccessCriteria = Field(default_factory=SuccessCriteria)
    wait_for_dependencies: bool = False
    dependency_check: str = ""
    use_docker: bool = False


class VerifyOutput(BaseModel):
    """Output from the verify node — project verification verdict.

    Verifies against the plan's self-defined success_criteria.description.
    """

    model_config = {"extra": "allow"}

    verdict: str = "FAILED"
    reason: str = ""
    port: int | None = None
    url: str = ""
    content_check: str = ""
    error_details: str = ""


# ── System-level (SystemFlow) ──────────────────────────────────────

class ServiceInfo(BaseModel):
    """Service metadata extracted from the user prompt."""

    model_config = {"extra": "allow"}

    repo_url: str = ""
    role: str = ""
    expected_port: int | None = None
    depends_on: list[str] = Field(default_factory=list)


class ObserveSystemOutput(BaseModel):
    """Output from observe_system — system composition analysis."""

    model_config = {"extra": "allow"}

    goal: str = ""
    services: dict[str, ServiceInfo] = Field(default_factory=dict)
    global_config: dict[str, Any] = Field(default_factory=dict)


class PlanSystemOutput(BaseModel):
    """Output from plan_system — service execution order."""

    model_config = {"extra": "allow"}

    execution_order: list[list[str]] = Field(default_factory=list)


class VerifySystemOutput(BaseModel):
    """Output from verify_system — system-level verification verdict."""

    model_config = {"extra": "allow"}

    verdict: str = "GIVE_UP"
    reason: str = ""
    retry_services: list[str] = Field(default_factory=list)
    human_question: str = ""

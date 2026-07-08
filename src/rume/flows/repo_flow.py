"""RepoFlow — single-repo orchestration flow.

Nodes: bootstrap_repo → observe → plan → execute → verify → done
Each LLM-powered node uses Chak Conversation with structured output.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from rill.flow import Flow, node, goto, DYNAMIC

from chak import Conversation
from chak.tools.std import Bash, FileSystem, Http, Search, Web

from ..state import RepoState
from ..tools.git import Git
from ..tools.docker import Docker
from ..prompts import load as load_prompt
from ..hitl import create_hitl_handler
from ..schemas import (
    ObserveOutput,
    PlanOutput,
    VerifyOutput,
)


def _print_plan(plan: dict, name: str) -> None:
    """Print the execution plan as a rich table."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()
    steps = plan.get("steps", [])
    sc = plan.get("success_criteria", {})
    use_docker = plan.get("use_docker", False)

    table = Table(title=f"📋 Execution Plan — {name}", border_style="cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Purpose", style="bold yellow")
    table.add_column("Description", style="white")
    table.add_column("Command", style="dim")

    for i, step in enumerate(steps, 1):
        purpose = step.get("purpose", "?")
        desc = step.get("description", "")
        cmd = step.get("command", "")
        # Truncate long commands for display
        if len(cmd) > 80:
            cmd = cmd[:77] + "..."
        table.add_row(str(i), purpose, desc, cmd)

    console.print()
    console.print(table)
    console.print()

    # Success criteria & Docker info
    details = []
    details.append(f"[bold]Success:[/bold] {sc.get('description', 'N/A')}")
    if use_docker:
        details.append("[bold cyan]🐳 Docker mode enabled[/bold cyan]")
    console.print(Panel.fit("\n".join(details), border_style="green"))
    console.print()


async def _chak_call(
    model_uri: str,
    api_key: str,
    system_prompt: str,
    message: str,
    tools: list[Any] | None = None,
    hitl_handler: Any = None,
    returns: type | None = None,
    timeout: int = 120,
) -> Any:
    """Make a single Chak Conversation call and return the response.

    All exceptions are wrapped as ValueError so callers' error handling
    can route to give_up/done cleanly instead of crashing the flow.
    """
    try:
        conv = Conversation(
            model_uri,
            api_key=api_key,
            system_prompt=system_prompt,
            tools=tools or [],
            hitl_handler=hitl_handler,
        )
        conv.tool.verbose.on()
        conv.tool.loop.unlimited()
        return await conv.asend(message, timeout=timeout, returns=returns)
    except Exception as e:
        raise ValueError(f"LLM call failed: {type(e).__name__}: {e}") from e


# ── RepoFlow ─────────────────────────────────────────────────────────

class RepoFlow(Flow):
    """Single repository orchestration flow.

    Usage:
        flow = RepoFlow(
            repo_url="https://github.com/user/repo",
            work_dir="/tmp/rume-xxx",
            role="my-service",
            model_uri="anthropic/claude-sonnet-4-6",
            api_key="sk-...",
            no_hitl=False,
        )
        await flow.run()
    """

    def __init__(
        self,
        repo_url: str,
        work_dir: str,
        role: str = "default",
        model_uri: str = "anthropic/claude-sonnet-4-6",
        api_key: str = "",
        no_hitl: bool = False,
        expected_port: int | None = None,
        depends_on: list[str] | None = None,
        global_config: dict[str, Any] | None = None,
        system_goal: str = "",
    ):
        self.model_uri = model_uri
        self.api_key = api_key
        self.no_hitl = no_hitl

        initial_state = RepoState(
            repo_url=repo_url,
            work_dir=work_dir,
            role=role,
            expected_port=expected_port,
            depends_on=depends_on or [],
            global_config=global_config or {},
            system_goal=system_goal,
        )
        super().__init__(initial_state=initial_state, max_steps=200, validate=True)
        self.state: RepoState

    # ── bootstrap_repo ────────────────────────────────────────────

    @node(start=True, goto=DYNAMIC)
    async def bootstrap_repo(self, _: Any) -> Any:
        """Clone the repository into work_dir.

        If clone fails, go directly to done — there is nothing to observe.
        """
        s: RepoState = self.state

        if s.repo_url.startswith(("http://", "https://", "git@")):
            parent = os.path.dirname(s.work_dir.rstrip("/"))
            os.makedirs(parent, exist_ok=True)
            print(f"[bootstrap] Cloning {s.repo_url} → {s.work_dir} ...")
            git = Git(work_dir=parent)
            try:
                result = git.clone(s.repo_url, os.path.basename(s.work_dir))
                print(f"[bootstrap] {result}")
            except RuntimeError as e:
                print(f"[bootstrap] Clone failed: {e}")
                s.status = "failed"
                s.error = str(e)
                return goto(self.done, {"error": str(e)})
        else:
            # Local path — just use as-is
            s.work_dir = os.path.abspath(s.repo_url)

        s.status = "running"
        return goto(self.observe, None)

    # ── observe ───────────────────────────────────────────────────

    @node(goto=DYNAMIC, max_loop=5)
    async def observe(self, _: Any) -> Any:
        """LLM explores the repo to understand its structure.

        If a RUME.md file exists in the repo root, load it as a
        pre-existing knowledge base and skip the exploration step.
        """
        s: RepoState = self.state
        s.attempts += 1

        # Check for existing RUME.md (skill file from a previous success)
        rume_path = os.path.join(s.work_dir, "RUME.md")
        if os.path.exists(rume_path):
            s.rume_path = rume_path
            rume_content = Path(rume_path).read_text(encoding="utf-8")
            s.observations = {"rume_content": rume_content, "from_rume": True}
            print(f"[observe] Found RUME.md ({len(rume_content)} chars) — "
                  f"skipping exploration, reusing knowledge base")
            return goto(self.plan, None)

        system_prompt = load_prompt("observe")
        message = (
            f"Explore the repository at {s.work_dir}.\n"
            f"Service role: {s.role}\n"
            f"Return your analysis as JSON."
        )

        tools = [
            FileSystem(workdir=s.work_dir),
            Docker(work_dir=s.work_dir),
            Web(),
            Search(),
        ]

        try:
            data = await _chak_call(
                self.model_uri, self.api_key, system_prompt, message,
                tools=tools, returns=ObserveOutput,
            )
            if data is None:
                raise ValueError("Structured output extraction failed — LLM returned None")
            # Convert to plain dict for backward compatibility with state
            s.observations = data.model_dump()
            print(f"[observe] project_type={data.project_type}, "
                  f"run_commands={data.run_commands}")
            return goto(self.plan, None)
        except ValueError as e:
            print(f"[observe] Failed to parse response: {e}")
            if s.attempts >= 5:
                s.status = "failed"
                s.error = str(e)
                return goto(self.done, {"error": str(e)})
            # Retry observe
            return goto(self.observe, None)

    # ── plan ──────────────────────────────────────────────────────

    @node(goto=DYNAMIC)
    async def plan(self, _: Any) -> Any:
        """LLM creates an execution plan based on observations."""
        s: RepoState = self.state

        system_prompt = load_prompt("plan")

        # Adapt message based on whether we're reusing a RUME.md
        if s.observations.get("from_rume"):
            message = (
                f"A RUME.md knowledge base already exists for this project:\n"
                f"---\n{s.observations.get('rume_content', '')}\n---\n\n"
                f"Role: {s.role}\n"
                f"Expected port: {s.expected_port or 'auto-detect'}\n"
                f"Depends on: {s.depends_on}\n"
                f"Use the RUME.md as your guide. "
                f"Validate it against the actual code and return your execution plan as JSON."
            )
        else:
            message = (
                f"Repository observations:\n{json.dumps(s.observations, indent=2)}\n\n"
                f"Role: {s.role}\n"
                f"Expected port: {s.expected_port or 'auto-detect'}\n"
                f"Depends on: {s.depends_on}\n"
                f"Return your execution plan as JSON."
            )

        tools = [
            FileSystem(workdir=s.work_dir),
            Docker(work_dir=s.work_dir),
            Web(),
            Search(),
        ]

        try:
            data = await _chak_call(
                self.model_uri, self.api_key, system_prompt, message,
                tools=tools, returns=PlanOutput,
            )
            if data is None:
                raise ValueError("Structured output extraction failed — LLM returned None")
            s.plan = data.model_dump()
            steps = s.plan.get("steps", [])
            _print_plan(s.plan, s.role or os.path.basename(s.work_dir))

            # Ask user to confirm before executing
            from rich.console import Console
            console = Console()
            try:
                answer = console.input(
                    "[bold yellow]Execute this plan?[/bold yellow] [dim](Y/n)[/dim] "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"

            if answer in ("n", "no"):
                print("[plan] Aborted by user.")
                s.status = "aborted"
                return goto(self.done, {"error": "User aborted after plan review"})

            return goto(self.execute, None)
        except ValueError as e:
            print(f"[plan] Failed to parse response: {e}")
            s.status = "failed"
            s.error = str(e)
            return goto(self.done, {"error": str(e)})

    # ── execute ───────────────────────────────────────────────────

    @node(goto=DYNAMIC)
    async def execute(self, _: Any) -> Any:
        """LLM executes the plan, with HITL on Bash calls."""
        s: RepoState = self.state

        plan_json = json.dumps(s.plan, indent=2)
        # Build goal message: include user's system-level intent if present
        goal_parts = [f"Get the {s.role} service running"]
        if s.expected_port:
            goal_parts.append(f"on port {s.expected_port}")
        if s.system_goal:
            goal_parts.append(f"\n\nUser's specific requirements: {s.system_goal}")
        goal_text = "".join(goal_parts)

        system_prompt = load_prompt("execute").format(
            plan=plan_json,
            goal=goal_text,
        )

        message = (
            f"Working directory: {s.work_dir}\n"
            f"Execute the plan step by step. "
            f"If a command fails, fix the issue and retry. "
            f"Report when the service appears to be running."
        )

        hitl_handler = create_hitl_handler(no_hitl=self.no_hitl)
        tools = [
            Bash(working_dir=s.work_dir, timeout=600),
            FileSystem(workdir=s.work_dir),
            Docker(work_dir=s.work_dir),
            Web(),
            Search(),
        ]

        try:
            resp = await _chak_call(
                self.model_uri,
                self.api_key,
                system_prompt,
                message,
                tools=tools,
                hitl_handler=hitl_handler,
                timeout=300,
            )
            s.execution_log.append(f"[execute] {resp.content[:500]}")
            print(f"[execute] Done. Output preview: {resp.content[:200]}")
        except ValueError as e:
            s.execution_log.append(f"[execute] LLM error: {e}")
            print(f"[execute] LLM call failed: {e}")

        return goto(self.verify, None)

    # ── verify ────────────────────────────────────────────────────

    @node(goto=DYNAMIC)
    async def verify(self, _: Any) -> Any:
        """LLM verifies whether the project is ready per the plan's success criteria."""
        s: RepoState = self.state

        system_prompt = load_prompt("verify")
        message_parts = [
            f"Plan:\n{json.dumps(s.plan, indent=2)}",
            f"Execution log:\n{chr(10).join(s.execution_log[-5:])}",
            f"Role: {s.role}",
            f"Expected port: {s.expected_port or 'auto-detect'}",
        ]
        if s.system_goal:
            message_parts.append(f"System goal (USER requirements): {s.system_goal}")
        message_parts.append("Verify against the plan's success_criteria. Return your verdict as JSON.")
        message = "\n\n".join(message_parts)

        tools = [
            Http(),
            FileSystem(workdir=s.work_dir),
        ]

        try:
            data = await _chak_call(
                self.model_uri, self.api_key, system_prompt, message,
                tools=tools, returns=VerifyOutput,
            )
            if data is None:
                raise ValueError("Structured output extraction failed — LLM returned None")
            verdict = data.verdict

            print(f"[verify] verdict={verdict}, reason={data.reason}")

            if verdict == "READY":
                s.status = "ready"
                s.result = {
                    "port": data.port,
                    "url": data.url,
                    "verdict": verdict,
                }
                # Skip RUME.md generation if it already exists (from reuse)
                if s.rume_path and os.path.exists(s.rume_path):
                    return goto(self.done, None)
                return goto(self.generate_rume, None)
            elif verdict == "RERUN":
                return goto(self.execute, None)
            elif verdict == "RETRY":
                return goto(self.observe, None)
            else:  # FAILED
                s.status = "failed"
                s.error = data.reason or "Unknown error"
                return goto(self.done, {"error": s.error})

        except ValueError as e:
            print(f"[verify] Failed to parse response: {e}")
            s.status = "failed"
            s.error = str(e)
            return goto(self.done, {"error": str(e)})

    # ── generate_rume ─────────────────────────────────────────────

    @node(goto=DYNAMIC)
    async def generate_rume(self, _: Any) -> Any:
        """Generate a RUME.md skill file after successful execution."""
        s: RepoState = self.state

        system_prompt = load_prompt("generate_rume")
        message = (
            f"Repository URL: {s.repo_url}\n"
            f"Role: {s.role}\n\n"
            f"## Observations\n{json.dumps(s.observations, indent=2)}\n\n"
            f"## Execution Plan\n{json.dumps(s.plan, indent=2)}\n\n"
            f"## Execution Log\n{chr(10).join(s.execution_log[-10:])}\n\n"
            f"## Verification Result\n{json.dumps(s.result, indent=2)}\n\n"
            f"Generate a comprehensive RUME.md file in markdown format."
        )

        try:
            resp = await _chak_call(
                self.model_uri,
                self.api_key,
                system_prompt,
                message,
                tools=[],
                timeout=120,
            )
            rume_content = resp.content

            # Strip code fences if present
            rume_content = re.sub(r"^```(?:markdown)?\s*\n?", "", rume_content)
            rume_content = re.sub(r"\n?```\s*$", "", rume_content)

            # Write RUME.md to work_dir
            rume_path = os.path.join(s.work_dir, "RUME.md")
            Path(rume_path).write_text(rume_content.strip() + "\n", encoding="utf-8")
            s.rume_path = rume_path
            print(f"[generate_rume] RUME.md written to {rume_path} ({len(rume_content)} chars)")

        except (ValueError, OSError) as e:
            print(f"[generate_rume] Failed: {e}")
            # Non-fatal — we still succeeded at running the service

        return goto(self.done, None)

    # ── done ──────────────────────────────────────────────────────

    @node()
    async def done(self, payload: dict | None = None) -> None:
        """Terminal node — results are stored in self.state for the caller."""
        s: RepoState = self.state
        if payload and payload.get("error"):
            s.status = "failed"
            s.error = payload["error"]
        print(f"[done] RepoFlow finished: status={s.status}")

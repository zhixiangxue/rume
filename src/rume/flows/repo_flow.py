"""RepoFlow — single-repo orchestration flow.

Nodes: bootstrap_repo → observe → plan → execute → verify → done
Each LLM-powered node uses Chak Conversation internally.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from rill.flow import Flow, node, goto, DYNAMIC

from chak import Conversation
from chak.tools.std import Bash, FileSystem, Http

from ..state import RepoState
from ..tools.git import Git
from ..prompts import load as load_prompt
from ..hitl import create_hitl_handler


# ── helpers ──────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM response text.

    Handles responses wrapped in ```json ... ``` fences or bare JSON.
    """
    # Try fenced block first
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()

    # Try to find first { ... } or [ ... ]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Failed to parse JSON from LLM response: {text[:200]}...")


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
        )
        super().__init__(initial_state=initial_state, max_steps=200, validate=True)
        self.state: RepoState

    # ── bootstrap_repo ────────────────────────────────────────────

    @node(start=True, goto="observe")
    async def bootstrap_repo(self, _: Any) -> dict:
        """Clone the repository into work_dir."""
        s: RepoState = self.state

        if s.repo_url.startswith(("http://", "https://", "git@")):
            # Clone into s.work_dir — must NOT pre-create the target directory,
            # otherwise git.clone will skip it (directory already exists check).
            parent = os.path.dirname(s.work_dir.rstrip("/"))
            os.makedirs(parent, exist_ok=True)
            git = Git(work_dir=parent)
            result = git.clone(s.repo_url, os.path.basename(s.work_dir))
            print(f"[bootstrap] {result}")
        else:
            # Local path — just use as-is
            s.work_dir = os.path.abspath(s.repo_url)

        s.status = "running"
        return {"work_dir": s.work_dir}

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

        tools = [FileSystem(workdir=s.work_dir)]

        try:
            resp = await _chak_call(
                self.model_uri, self.api_key, system_prompt, message, tools=tools
            )
            data = _extract_json(resp.content)
            s.observations = data
            print(f"[observe] project_type={data.get('project_type')}, "
                  f"run_commands={data.get('run_commands')}")
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

        tools = [FileSystem(workdir=s.work_dir)]

        try:
            resp = await _chak_call(
                self.model_uri, self.api_key, system_prompt, message, tools=tools
            )
            data = _extract_json(resp.content)
            s.plan = data
            steps = data.get("steps", [])
            print(f"[plan] {len(steps)} steps planned: "
                  f"{[st.get('purpose', '?') for st in steps]}")
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
        system_prompt = load_prompt("execute").format(
            plan=plan_json,
            goal=(
                f"Get the {s.role} service running"
                + (f" on port {s.expected_port}" if s.expected_port else "")
            ),
        )

        message = (
            f"Working directory: {s.work_dir}\n"
            f"Execute the plan step by step. "
            f"If a command fails, fix the issue and retry. "
            f"Report when the service appears to be running."
        )

        hitl_handler = create_hitl_handler(no_hitl=self.no_hitl)
        tools = [
            Bash(working_dir=s.work_dir),
            FileSystem(workdir=s.work_dir),
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
        """LLM verifies whether the service is running correctly."""
        s: RepoState = self.state

        system_prompt = load_prompt("verify")
        message = (
            f"Plan:\n{json.dumps(s.plan, indent=2)}\n\n"
            f"Execution log:\n{chr(10).join(s.execution_log[-5:])}\n\n"
            f"Role: {s.role}\n"
            f"Expected port: {s.expected_port or 'auto-detect'}\n"
            f"Is the service running? Return your verdict as JSON."
        )

        tools = [
            Http(),
            FileSystem(workdir=s.work_dir),
        ]

        try:
            resp = await _chak_call(
                self.model_uri, self.api_key, system_prompt, message, tools=tools
            )
            data = _extract_json(resp.content)
            verdict = data.get("verdict", "FAILED")

            print(f"[verify] verdict={verdict}, reason={data.get('reason', '?')}")

            if verdict == "READY":
                s.status = "ready"
                s.result = {
                    "port": data.get("port"),
                    "url": data.get("url"),
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
                s.error = data.get("reason", "Unknown error")
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

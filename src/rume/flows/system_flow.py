"""SystemFlow — system-level orchestration flow.

Nodes: bootstrap → observe_system → plan_system → dispatch → verify_system
       → output / ask_human / give_up

v0.1: Single-service mode — observes one repo, dispatches one RepoFlow.
"""

import asyncio
import json
import os
import tempfile
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from rill.flow import Flow, node, goto, DYNAMIC

from ..state import SystemState, ServiceMeta
from ..prompts import load as load_prompt
from ..flows.repo_flow import RepoFlow, _extract_json, _chak_call


class SystemFlow(Flow):
    """System-level orchestration flow.

    Usage:
        flow = SystemFlow(
            prompt="Start https://github.com/user/repo dev server",
            model_uri="anthropic/claude-sonnet-4-6",
            api_key="sk-...",
            no_hitl=False,
            max_attempts=3,
        )
        await flow.run()
    """

    def __init__(
        self,
        prompt: str,
        model_uri: str = "anthropic/claude-sonnet-4-6",
        api_key: str = "",
        no_hitl: bool = False,
        max_attempts: int = 3,
    ):
        self.model_uri = model_uri
        self.api_key = api_key
        self.no_hitl = no_hitl
        self._max_attempts = max_attempts
        self._system_attempts = 0
        self._console = Console()

        # Create a temp work directory for the entire system
        self._work_root = tempfile.mkdtemp(prefix="rume-")

        initial_state = SystemState(prompt=prompt)
        super().__init__(initial_state=initial_state, max_steps=200, validate=True)
        self.state: SystemState

    # ── bootstrap ─────────────────────────────────────────────────

    @node(start=True, goto="observe_system")
    async def bootstrap(self, _: Any) -> None:
        """Initialize system state."""
        s: SystemState = self.state
        self._console.print(Panel.fit(
            f"Work root: [dim]{self._work_root}[/dim]",
            title="🔧 bootstrap",
            border_style="blue",
        ))

    # ── observe_system ────────────────────────────────────────────

    @node(goto=DYNAMIC)
    async def observe_system(self, _: Any) -> Any:
        """LLM parses the prompt to extract system composition."""
        s: SystemState = self.state

        system_prompt = load_prompt("observe_system")

        try:
            resp = await _chak_call(
                self.model_uri,
                self.api_key,
                system_prompt,
                f"User prompt:\n{s.prompt}\n\nAnalyze and return JSON.",
                tools=[],
            )
            data = _extract_json(resp.content)
            s.goal = data.get("goal", s.prompt)
            s.global_config = data.get("global_config", {})

            services = data.get("services", {})
            for name, meta in services.items():
                s.services[name] = ServiceMeta(
                    repo_url=meta.get("repo_url", ""),
                    work_dir=os.path.join(self._work_root, name),
                    role=meta.get("role", "default"),
                    expected_port=meta.get("expected_port"),
                    depends_on=meta.get("depends_on", []),
                )

            print(f"[observe_system] goal={s.goal}")
            print(f"[observe_system] services={list(s.services.keys())}")

            if not s.services:
                self._console.print("[red]No services found in prompt — giving up[/red]")
                s.last_error = "Could not identify any services from the prompt"
                return goto(self.give_up, None)

            return goto(self.plan_system, None)

        except ValueError as e:
            self._console.print(f"[red]observe_system failed: {e}[/red]")
            s.last_error = str(e)
            return goto(self.give_up, None)

    # ── plan_system ───────────────────────────────────────────────

    @node(goto=DYNAMIC)
    async def plan_system(self, _: Any) -> Any:
        """LLM creates an execution order for services."""
        s: SystemState = self.state

        system_prompt = load_prompt("plan_system")
        services_desc = {
            name: {
                "role": svc.role,
                "expected_port": svc.expected_port,
                "depends_on": svc.depends_on,
            }
            for name, svc in s.services.items()
        }

        try:
            resp = await _chak_call(
                self.model_uri,
                self.api_key,
                system_prompt,
                f"Services:\n{json.dumps(services_desc, indent=2)}\nGoal: {s.goal}\nReturn JSON.",
                tools=[],
            )
            data = _extract_json(resp.content)
            s.execution_order = data.get("execution_order", [list(s.services.keys())])
            self._console.print(
                f"[bold]Execution order:[/bold] "
                f"{' → '.join('[' + '+'.join(b) + ']' for b in s.execution_order)}"
            )
            return goto(self.dispatch, None)

        except ValueError as e:
            # Fallback: all services in one batch
            s.execution_order = [list(s.services.keys())]
            self._console.print(f"[yellow]plan_system parse failed, using flat order: {e}[/yellow]")
            return goto(self.dispatch, None)

    # ── dispatch ──────────────────────────────────────────────────

    @node(goto=DYNAMIC)
    async def dispatch(self, _: Any) -> Any:
        """Dispatch RepoFlow instances batch by batch.

        v0.1: For single service, runs one RepoFlow sequentially.
        For multiple services in the same batch, uses asyncio.gather.
        """
        s: SystemState = self.state
        self._system_attempts += 1

        # Determine which services to run
        if s.retry_services:
            self._console.print(f"[yellow]Retrying: {', '.join(s.retry_services)}[/yellow]")
            retry_list = s.retry_services
            s.retry_services = []

            tasks = []
            for name in retry_list:
                svc = s.services[name]
                flow = RepoFlow(
                    repo_url=svc.repo_url,
                    work_dir=svc.work_dir,
                    role=svc.role,
                    model_uri=self.model_uri,
                    api_key=self.api_key,
                    no_hitl=self.no_hitl,
                    expected_port=svc.expected_port,
                    depends_on=svc.depends_on,
                    global_config=s.global_config,
                )
                tasks.append(self._run_repo_flow(name, flow))

            # Concurrent execution for retry services
            await asyncio.gather(*tasks)
        else:
            # Run all batches sequentially
            for batch in s.execution_order:
                if s.current_batch >= len(s.execution_order):
                    break
                batch_services = s.execution_order[s.current_batch]
                self._console.print(f"[bold]Batch {s.current_batch}:[/bold] {', '.join(batch_services)}")

                tasks = []
                for name in batch_services:
                    svc = s.services[name]
                    flow = RepoFlow(
                        repo_url=svc.repo_url,
                        work_dir=svc.work_dir,
                        role=svc.role,
                        model_uri=self.model_uri,
                        api_key=self.api_key,
                        no_hitl=self.no_hitl,
                        expected_port=svc.expected_port,
                        depends_on=svc.depends_on,
                        global_config=s.global_config,
                    )
                    tasks.append(self._run_repo_flow(name, flow))

                # Concurrent execution within the batch
                await asyncio.gather(*tasks)

                s.current_batch += 1

        return goto(self.verify_system, None)

    async def _run_repo_flow(self, name: str, flow: RepoFlow) -> None:
        """Run a single RepoFlow and update SystemState."""
        s: SystemState = self.state
        svc = s.services[name]

        self._console.print()
        self._console.print(Panel.fit(
            f"Starting RepoFlow for [bold cyan]{name}[/bold cyan]",
            border_style="cyan",
        ))

        try:
            final_state = await flow.run()
            # Update service metadata from RepoFlow state
            svc.status = final_state.status
            svc.result = final_state.result
            svc.error = final_state.error
            svc.attempts = final_state.attempts
            svc.work_dir = final_state.work_dir

            if final_state.rume_path:
                svc.result["rume_path"] = final_state.rume_path

            icon = "✅" if svc.status == "ready" else "❌"
            self._console.print(f"{icon} [bold]{name}[/bold]: {svc.status}")
            if final_state.rume_path:
                self._console.print(f"   📄 RUME.md → [dim]{final_state.rume_path}[/dim]")
        except Exception as e:
            svc.status = "failed"
            svc.error = str(e)
            self._console.print(f"[red]❌ {name}: {e}[/red]")

    # ── verify_system ─────────────────────────────────────────────

    @node(goto=DYNAMIC)
    async def verify_system(self, _: Any) -> Any:
        """LLM verifies the system as a whole."""
        s: SystemState = self.state

        system_prompt = load_prompt("verify_system")
        services_status = {
            name: {
                "status": svc.status,
                "result": svc.result,
                "error": svc.error,
                "role": svc.role,
            }
            for name, svc in s.services.items()
        }

        try:
            resp = await _chak_call(
                self.model_uri,
                self.api_key,
                system_prompt,
                (
                    f"User prompt: {s.prompt}\n"
                    f"Goal: {s.goal}\n"
                    f"Services:\n{json.dumps(services_status, indent=2)}\n"
                    f"Return your verdict as JSON."
                ),
                tools=[],
            )
            data = _extract_json(resp.content)
            verdict = data.get("verdict", "GIVE_UP")
            reason = data.get("reason", "Unknown")
            retry_services = data.get("retry_services", [])
            human_question = data.get("human_question", "")

            print(f"[verify_system] verdict={verdict}, reason={reason}")

            if verdict == "SYSTEM_READY":
                s.system_ready = True
                return goto(self.output, None)

            elif verdict == "RETRY_SPECIFIC":
                if self._system_attempts >= self._max_attempts:
                    self._console.print(
                        f"[yellow]Max attempts ({self._max_attempts}) reached[/yellow]"
                    )
                    return goto(self.give_up, None)

                s.retry_services = retry_services or list(s.services.keys())
                return goto(self.dispatch, None)

            elif verdict == "HITL":
                s.last_error = reason
                s.human_feedback = human_question
                return goto(self.ask_human, None)

            else:  # GIVE_UP
                s.last_error = reason
                return goto(self.give_up, None)

        except ValueError as e:
            self._console.print(f"[red]verify_system parse failed: {e}[/red]")

            # Heuristic: check if all services are ready
            all_ready = all(svc.status == "ready" for svc in s.services.values())
            if all_ready:
                s.system_ready = True
                return goto(self.output, None)
            else:
                s.last_error = str(e)
                return goto(self.give_up, None)

    # ── ask_human ─────────────────────────────────────────────────

    @node(goto=DYNAMIC)
    async def ask_human(self, _: Any) -> Any:
        """CLI interaction — ask the user for help."""
        s: SystemState = self.state

        # Build service status table
        table = Table(title="Service Status", border_style="yellow")
        table.add_column("Service", style="bold")
        table.add_column("Role")
        table.add_column("Status")
        table.add_column("Error", style="red")
        for name, svc in s.services.items():
            icon = "✅" if svc.status == "ready" else "❌"
            table.add_row(f"{icon} {name}", svc.role, svc.status,
                         svc.error[:60] if svc.error else "—")

        self._console.print()
        self._console.print(Panel(table, title="⚠️  Need your help", border_style="yellow"))

        if s.human_feedback:
            self._console.print(f"\n[bold]💬 {s.human_feedback}[/bold]")

        try:
            answer = input("\n  Enter fix instructions or [q] to give up: ").strip()
        except (EOFError, KeyboardInterrupt):
            return goto(self.give_up, None)

        if answer.lower() in ("q", "quit", "exit"):
            return goto(self.give_up, None)

        s.human_feedback = answer
        # Retry all failed services
        failed = [n for n, svc in s.services.items() if svc.status != "ready"]
        s.retry_services = failed or list(s.services.keys())
        return goto(self.dispatch, None)

    # ── output ────────────────────────────────────────────────────

    @node()
    async def output(self, _: Any = None) -> None:
        """Print final results with Rich formatting."""
        s: SystemState = self.state

        self._console.print()

        # Build result table
        table = Table(border_style="green")
        table.add_column("Service", style="bold cyan")
        table.add_column("Role")
        table.add_column("Endpoint", style="green")
        table.add_column("RUME.md", style="dim")

        rume_paths = []
        for name, svc in s.services.items():
            url = svc.result.get("url", "")
            port = svc.result.get("port", "")
            info = url or (f"port {port}" if port else "running")

            rume_path = svc.result.get("rume_path", "")
            rume_info = os.path.basename(rume_path) if rume_path else "—"
            if rume_path:
                rume_paths.append(rume_path)

            table.add_row(name, svc.role, info, rume_info)

        self._console.print(Panel(table, title="🎉 System is ready!", border_style="green"))

        # Show RUME.md locations prominently
        if rume_paths:
            self._console.print()
            for rp in rume_paths:
                self._console.print(Panel.fit(
                    f"[bold]📄 RUME.md[/bold] has been generated at:\n"
                    f"[cyan]{rp}[/cyan]\n\n"
                    f"[dim]Copy it to your repo root and commit it. "
                    f"Next time, rume will detect it and skip exploration.[/dim]",
                    border_style="green",
                ))

        self._console.print()

    # ── give_up ───────────────────────────────────────────────────

    @node()
    async def give_up(self, _: Any = None) -> None:
        """Print failure summary with Rich formatting."""
        s: SystemState = self.state

        self._console.print()

        # Build failure table
        table = Table(border_style="red")
        table.add_column("Service", style="bold")
        table.add_column("Status")
        table.add_column("Error", style="red")
        for name, svc in s.services.items():
            icon = "✅" if svc.status == "ready" else "❌"
            table.add_row(f"{icon} {name}", svc.status,
                         svc.error[:80] if svc.error else "—")

        self._console.print(Panel(
            f"[bold]Reason:[/bold] {s.last_error or 'Unknown'}\n\n{table}",
            title="❌ Could not get the system running",
            border_style="red",
        ))
        self._console.print()

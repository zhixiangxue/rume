"""rume CLI — get any system running automatically.

Usage:
    rume "Start https://github.com/user/repo dev server"
    rume "Backend: github.com/org/api (port 8080), Frontend: github.com/org/web"
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import typer
from dotenv import load_dotenv

# Auto-load .env from project root (or current directory)
_load_paths = [
    Path(__file__).resolve().parent.parent.parent / ".env",  # rume project root
    Path.cwd() / ".env",
]
for _p in _load_paths:
    if _p.exists():
        load_dotenv(_p)
        break

from .flows.system_flow import SystemFlow

app = typer.Typer(
    name="rume",
    help="Get any system running — automatically.",
)

# ── model / key auto-detection ────────────────────────────────────

_MODEL_CANDIDATES = [
    ("DEEPSEEK_API_KEY", "deepseek/deepseek-chat"),
    ("OPENAI_API_KEY", "openai/gpt-4o"),
    ("ANTHROPIC_API_KEY", "anthropic/claude-sonnet-4-6"),
    ("BAILIAN_API_KEY", "bailian/qwen-plus"),
    ("ZHIPU_API_KEY", "zhipu/glm-4"),
    ("DASHSCOPE_API_KEY", "dashscope/qwen-plus"),
]


def _resolve_api_key(model_uri: str) -> str:
    """Resolve API key based on model URI prefix or CHAK_API_KEY."""
    for env_var, model in _MODEL_CANDIDATES:
        if model_uri.startswith(env_var.split("_")[0].lower() + "/"):
            key = os.environ.get(env_var, "")
            if key:
                return key
    # Fallback: CHAK_API_KEY
    return os.environ.get("CHAK_API_KEY", "")


def _resolve_model() -> str:
    """Auto-detect the best available model from env vars."""
    for env_var, model in _MODEL_CANDIDATES:
        if os.environ.get(env_var, ""):
            return model
    return "deepseek/deepseek-chat"


# ── output tee (log to file + console) ────────────────────────────

class TeeWriter:
    """Write to both the original stream and a log file simultaneously."""

    def __init__(self, original, log_fp):
        self.original = original
        self.log_fp = log_fp

    def write(self, data):
        self.original.write(data)
        self.log_fp.write(data)

    def flush(self):
        self.original.flush()
        self.log_fp.flush()

    def isatty(self):
        return getattr(self.original, "isatty", lambda: False)()

    def fileno(self):
        return self.original.fileno()


def _setup_logging(log_file: Optional[str]) -> tuple:
    """Set up stdout/stderr tee to log file. Returns (log_path, None) or (None, None).

    If log_file is None, auto-generate a timestamped name.
    """
    if log_file is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_file = f"rume-{timestamp}.log"

    log_path = Path(log_file).resolve()
    fp = open(str(log_path), "w", encoding="utf-8")

    # Save originals before wrapping
    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr

    sys.stdout = TeeWriter(_orig_stdout, fp)
    sys.stderr = TeeWriter(_orig_stderr, fp)

    return log_path, fp


# ── main command ──────────────────────────────────────────────────

@app.callback(invoke_without_command=True)
def main(
    prompt: Annotated[
        Optional[str],
        typer.Argument(help="Natural language description of the system to run"),
    ] = None,
    model: Annotated[
        str,
        typer.Option(
            "-m", "--model",
            help="LLM model URI (auto-detected from .env if not set)",
        ),
    ] = "",
    api_key: Annotated[
        str,
        typer.Option(
            "-k", "--api-key",
            help="API key (auto-detected from .env if not set)",
        ),
    ] = "",
    hitl: Annotated[
        bool,
        typer.Option(
            "--hitl",
            help="Enable human-in-the-loop (disabled by default)",
        ),
    ] = False,
    max_attempts: Annotated[
        int,
        typer.Option(
            "--max-attempts",
            help="Maximum system-level retry attempts",
        ),
    ] = 3,
    log_file: Annotated[
        Optional[str],
        typer.Option(
            "--log-file",
            "-l",
            help="Save all console output to a file (auto-named if not provided)",
        ),
    ] = None,
):
    """Get any system running — automatically.

    Give rume a natural language prompt describing what repos to use
    and what "success" looks like. rume will clone, analyze, build,
    and start everything automatically.

    Examples:
        rume "Start https://github.com/user/my-app dev server"

        rume "Backend: github.com/org/api (port 8080),
               Frontend: github.com/org/web (depends on backend)"
    """
    if prompt is None:
        # Show help when no prompt is given
        typer.echo(typer.Context(main).get_help())
        raise typer.Exit()

    # Resolve model and API key
    model_uri = model or _resolve_model()
    key = api_key or _resolve_api_key(model_uri)

    if not key:
        typer.echo(
            "Error: No API key found.\n"
            "  Set one of: DEEPSEEK_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, "
            "BAILIAN_API_KEY, ZHIPU_API_KEY, DASHSCOPE_API_KEY, CHAK_API_KEY\n"
            "  Or use --api-key / -k to provide one directly.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Show header
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    console = Console()
    console.print()
    console.print(Panel.fit(
        f"[bold]{prompt}[/bold]",
        title="🚀 rume",
        subtitle=f"model: {model_uri}",
        border_style="cyan",
    ))

    # ── Safety warning & confirmation ──────────────────────────────
    console.print()
    warning = Text.assemble(
        ("⚠️  WARNING", "bold red reverse"),
        ("\n\n", ""),
        ("rume will perform automated operations on your system, including:\n", "yellow"),
        ("  • Cloning repositories\n", "dim"),
        ("  • Installing language runtimes & dependencies\n", "dim"),
        ("  • Running shell commands (build, test, start servers)\n", "dim"),
        ("  • Reading and writing files in the working directory\n", "dim"),
        ("  • Making network requests to external services\n", "dim"),
        ("\nOnly proceed if you trust the source repositories.\n", "bold"),
    )
    console.print(Panel(warning, border_style="red"))
    console.print()

    try:
        answer = console.input("[bold yellow]Continue?[/bold yellow] [dim](y/N)[/dim] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Aborted.[/yellow]")
        raise typer.Exit(code=0)

    if answer not in ("y", "yes"):
        console.print("[yellow]Aborted by user.[/yellow]")
        raise typer.Exit(code=0)

    console.print()
    # ── end warning ────────────────────────────────────────────────

    # ── Set up log file (tee stdout/stderr) ────────────────────────
    log_path, _log_fp = _setup_logging(log_file)
    console.print(f"[dim]📝 Logging to: {log_path}[/dim]")
    console.print()
    # ── end log setup ──────────────────────────────────────────────

    flow = SystemFlow(
        prompt=prompt,
        model_uri=model_uri,
        api_key=key,
        no_hitl=not hitl,
        max_attempts=max_attempts,
    )

    try:
        asyncio.run(flow.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        raise typer.Exit(code=1)


@app.command()
def version():
    """Print rume version."""
    from importlib.metadata import version as _version
    typer.echo(f"rume v{_version('rume')}")


if __name__ == "__main__":
    app()

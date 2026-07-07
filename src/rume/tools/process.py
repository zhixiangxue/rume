"""Process and port utilities for rume.

Based on Chak SkillBase for progressive disclosure to LLMs.
"""

import subprocess
import os
import signal
import socket
from chak.tools import SkillBase


class Process(SkillBase):
    """Process and port management utilities."""

    name = "process"
    description = (
        "Process and port management: check port usage, list processes, "
        "kill processes by port."
    )

    def check_port(self, port: int) -> str:
        """Check if a TCP port is currently in use (listening).

        Args:
            port: Port number to check.

        Returns:
            "open" if the port is listening, "free" if not.

        Example:
            process.check_port(8080)
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            result = s.connect_ex(("127.0.0.1", port))
            if result == 0:
                return f"Port {port} is in use (open)"
            return f"Port {port} is free"

    def kill_port(self, port: int) -> str:
        """Kill any process listening on the given TCP port.

        Args:
            port: Port number to free.

        Returns:
            Result message.

        Example:
            process.kill_port(3000)
        """
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
            )
            pids = result.stdout.strip().split("\n")
            pids = [p for p in pids if p]
            if not pids:
                return f"No process listening on port {port}"

            for pid in pids:
                os.kill(int(pid), signal.SIGTERM)

            return f"Killed process(es) on port {port}: {', '.join(pids)}"
        except Exception as e:
            return f"Failed to kill port {port}: {e}"

    def list_processes(self, pattern: str = "") -> str:
        """List running processes, optionally filtered by name pattern.

        Args:
            pattern: Optional name pattern to filter (e.g. "python", "node").

        Returns:
            Process list output.

        Example:
            process.list_processes("python")
        """
        if pattern:
            result = subprocess.run(
                ["pgrep", "-la", pattern],
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() or f"No processes matching '{pattern}'"
        else:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
            )
            # Return last 20 lines to avoid huge output
            lines = result.stdout.strip().split("\n")
            return "\n".join(lines[-20:])

"""Docker operations tool for rume — pull, run, compose, ps, logs.

Based on Chak SkillBase for progressive disclosure to LLMs.
"""

import subprocess
import os
from chak.tools import SkillBase


def _stream_command(cmd: list[str], cwd: str = ".") -> tuple[int, str, str]:
    """Run a command with real-time stderr streaming and capture both streams.

    Returns (returncode, stdout_text, stderr_text).
    """
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stderr_lines: list[str] = []
    if process.stderr:
        for line in process.stderr:
            line = line.rstrip("\n")
            stderr_lines.append(line)
            print(f"  {line}", flush=True)

    process.wait()
    stdout_text = process.stdout.read() if process.stdout else ""
    stderr_text = "\n".join(stderr_lines)

    return process.returncode, stdout_text.strip(), stderr_text


class Docker(SkillBase):
    """Docker operations — pull images, run containers, docker compose.

    Prefer this over raw Bash for Docker commands. It handles long-running
    operations (pull, build) with proper progress streaming.
    """

    name = "docker"
    description = (
        "Docker operations: pull images, run containers, docker compose up/down, "
        "check container status, view logs. Use this instead of Bash for any "
        "Docker command — it handles progress streaming and avoids timeouts."
    )

    def __init__(self, work_dir: str = "."):
        self.work_dir = work_dir

    # ── image operations ───────────────────────────────────────────

    def pull(self, image: str) -> str:
        """Pull a Docker image from a registry.

        Args:
            image: Image name with optional tag (e.g. "nginx:latest",
                   "ghcr.io/twin/gatus:stable").

        Returns:
            Pull result message.

        Example:
            docker.pull("ghcr.io/twin/gatus:stable")
        """
        print(f"[docker] Pulling {image} ...")
        returncode, stdout, stderr = _stream_command(
            ["docker", "pull", image],
            cwd=self.work_dir,
        )
        if returncode != 0:
            return f"Pull failed (exit {returncode}): {stderr or stdout}"
        return f"Successfully pulled {image}"

    # ── container operations ───────────────────────────────────────

    def run(
        self,
        image: str,
        port: str = "",
        name: str = "",
        env: str = "",
        volume: str = "",
        detach: bool = True,
        extra_args: str = "",
    ) -> str:
        """Run a Docker container.

        Args:
            image: Image name to run.
            port: Port mapping (e.g. "8080:8080" or "3000:3000").
            name: Container name.
            env: Environment variables (e.g. "-e KEY=val -e KEY2=val2").
            volume: Volume mount (e.g. "/host/path:/container/path").
            detach: Run in background (default True).
            extra_args: Any additional docker run arguments.

        Returns:
            Run result message with container ID.

        Example:
            docker.run("ghcr.io/twin/gatus:stable", port="8080:8080", name="gatus")
        """
        cmd = ["docker", "run"]
        if detach:
            cmd.append("-d")
        if name:
            cmd.extend(["--name", name])
        if port:
            cmd.extend(["-p", port])
        if env:
            # Split env string into individual -e flags if needed
            for var in env.split():
                if var.strip():
                    cmd.extend(["-e", var.strip()])
        if volume:
            cmd.extend(["-v", volume])
        if extra_args:
            cmd.extend(extra_args.split())
        cmd.append(image)

        print(f"[docker] Running: {' '.join(cmd)}")
        returncode, stdout, stderr = _stream_command(cmd, cwd=self.work_dir)
        if returncode != 0:
            return f"Run failed (exit {returncode}): {stderr or stdout}"
        container_id = stdout or "started"
        return f"Container started: {container_id.strip()}"

    def ps(self, all_containers: bool = False) -> str:
        """List Docker containers.

        Args:
            all_containers: Show all containers including stopped (default False).

        Returns:
            Container list.
        """
        cmd = ["docker", "ps"]
        if all_containers:
            cmd.append("-a")
        returncode, stdout, stderr = _stream_command(cmd, cwd=self.work_dir)
        if returncode != 0:
            return f"ps failed: {stderr}"
        return stdout or "(no containers)"

    def logs(self, container: str, tail: int = 50) -> str:
        """Show logs from a container.

        Args:
            container: Container name or ID.
            tail: Number of lines to show from the end (default 50).

        Returns:
            Container logs.
        """
        cmd = ["docker", "logs", "--tail", str(tail), container]
        returncode, stdout, stderr = _stream_command(cmd, cwd=self.work_dir)
        if returncode != 0:
            return f"Logs failed: {stderr}"
        return stdout or "(no logs)"

    def stop(self, container: str) -> str:
        """Stop a running container.

        Args:
            container: Container name or ID.

        Returns:
            Stop result.
        """
        cmd = ["docker", "stop", container]
        returncode, stdout, stderr = _stream_command(cmd, cwd=self.work_dir)
        if returncode != 0:
            return f"Stop failed: {stderr}"
        return f"Stopped {container}"

    def rm(self, container: str, force: bool = False) -> str:
        """Remove a container.

        Args:
            container: Container name or ID.
            force: Force remove running container (default False).

        Returns:
            Remove result.
        """
        cmd = ["docker", "rm"]
        if force:
            cmd.append("-f")
        cmd.append(container)
        returncode, stdout, stderr = _stream_command(cmd, cwd=self.work_dir)
        if returncode != 0:
            return f"Remove failed: {stderr}"
        return f"Removed {container}"

    # ── compose operations ─────────────────────────────────────────

    def compose_up(self, file: str = "docker-compose.yml") -> str:
        """Start services defined in a docker-compose file.

        Args:
            file: Path to docker-compose file (default "docker-compose.yml").

        Returns:
            Compose up result.

        Example:
            docker.compose_up()
            docker.compose_up("docker-compose.dev.yml")
        """
        cmd = ["docker", "compose"]
        if file != "docker-compose.yml":
            cmd.extend(["-f", file])
        cmd.extend(["up", "-d"])

        print(f"[docker] docker compose up -d ...")
        returncode, stdout, stderr = _stream_command(cmd, cwd=self.work_dir)
        if returncode != 0:
            return f"Compose up failed (exit {returncode}): {stderr or stdout}"
        return f"Compose started\n{stdout or stderr}"

    def compose_down(self, file: str = "docker-compose.yml") -> str:
        """Stop and remove services defined in a docker-compose file.

        Args:
            file: Path to docker-compose file (default "docker-compose.yml").

        Returns:
            Compose down result.
        """
        cmd = ["docker", "compose"]
        if file != "docker-compose.yml":
            cmd.extend(["-f", file])
        cmd.append("down")

        returncode, stdout, stderr = _stream_command(cmd, cwd=self.work_dir)
        if returncode != 0:
            return f"Compose down failed: {stderr}"
        return f"Compose stopped\n{stdout or stderr}"

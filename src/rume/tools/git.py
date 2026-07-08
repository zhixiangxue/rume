"""Git operations tool for rume — clone, pull, checkout, status.

Based on Chak SkillBase for progressive disclosure to LLMs.
"""

import subprocess
import os
from chak.tools import SkillBase


class Git(SkillBase):
    """Git repository operations — clone, status, pull, checkout."""

    name = "git"
    description = (
        "Git repository operations: clone repos, check status, switch branches. "
        "All operations run in the current working directory."
    )

    def __init__(self, work_dir: str = "."):
        self.work_dir = work_dir

    def clone(self, url: str, target_dir: str) -> str:
        """Clone a git repository from `url` into `target_dir`.

        Args:
            url: Git repository URL (https or ssh).
            target_dir: Local directory name to clone into (relative to work_dir).

        Returns:
            Clone result message.

        Example:
            git.clone("https://github.com/user/repo", "my-repo")
        """
        target = os.path.join(self.work_dir, target_dir)
        if os.path.exists(target):
            return f"Directory {target} already exists, skipping clone"

        # Use --progress to force git to emit progress to stderr even
        # when not attached to a terminal, then stream stderr in
        # real-time so the user can see clone progress.
        process = subprocess.Popen(
            ["git", "clone", "--progress", url, target_dir],
            cwd=self.work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Stream stderr (git progress) to stdout in real-time
        stderr_lines: list[str] = []
        if process.stderr:
            for line in process.stderr:
                line = line.rstrip("\n")
                stderr_lines.append(line)
                # Print progress lines (git progress uses \r for in-place updates)
                print(f"  {line}", flush=True)

        process.wait()
        stdout_text = process.stdout.read() if process.stdout else ""

        if process.returncode != 0:
            raise RuntimeError(f"Clone failed (exit {process.returncode}): "
                               f"{''.join(stderr_lines[-3:])}")

        msg = "\n".join(stderr_lines) or stdout_text.strip()
        return f"Cloned to {target}\n{msg}"

    def status(self) -> str:
        """Show the working tree status.

        Returns:
            Output of `git status`.
        """
        result = subprocess.run(
            ["git", "status"],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or result.stderr.strip()

    def pull(self) -> str:
        """Fetch from and integrate with the remote.

        Returns:
            Output of `git pull`.
        """
        result = subprocess.run(
            ["git", "pull"],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or result.stderr.strip()

    def checkout(self, branch: str) -> str:
        """Switch to a branch.

        Args:
            branch: Branch name to switch to.

        Returns:
            Output of `git checkout`.
        """
        result = subprocess.run(
            ["git", "checkout", branch],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return f"Checkout failed: {result.stderr.strip()}"
        return result.stdout.strip() or f"Switched to {branch}"

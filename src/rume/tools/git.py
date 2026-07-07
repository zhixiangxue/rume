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

        result = subprocess.run(
            ["git", "clone", url, target_dir],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return f"Clone failed: {result.stderr.strip()}"

        msg = result.stderr.strip() or result.stdout.strip()
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

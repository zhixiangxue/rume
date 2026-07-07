"""Prompt template loader.

Reads .md files from the prompts/ directory and returns their content as strings.
"""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load(name: str) -> str:
    """Load a prompt template by filename (without .md extension).

    Args:
        name: Prompt name, e.g. "observe", "plan_system".

    Returns:
        Prompt content as string.

    Raises:
        FileNotFoundError: if the prompt file does not exist.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")

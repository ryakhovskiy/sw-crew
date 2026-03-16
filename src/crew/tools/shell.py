"""Sandboxed shell execution — subprocess confined to a task workspace."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from crew.tools.files import PathEscapeError

# Maximum bytes returned from stdout/stderr to avoid blowing the LLM context.
_MAX_OUTPUT_BYTES = 50_000


def _check_path_escape(cmd: str) -> None:
    """Reject commands containing path traversal patterns."""
    # Match '..' anywhere — including cd.., ../, ..\\ etc.
    if re.search(r"\.\.", cmd):
        raise PathEscapeError(f"Command contains path traversal: {cmd!r}")


def _truncate(text: str, limit: int = _MAX_OUTPUT_BYTES) -> str:
    if len(text) > limit:
        return text[:limit] + f"\n... [truncated, {len(text) - limit} chars omitted]"
    return text


def run_bash(workspace: str | Path, cmd: str, timeout: int = 120) -> tuple[str, str, int]:
    """Execute *cmd* inside *workspace* via the system shell.

    Returns ``(stdout, stderr, returncode)``.

    Security:
    - Working directory is set to *workspace*.
    - Commands containing path-traversal sequences (``..``) are rejected.
    - stdout/stderr are truncated to ``_MAX_OUTPUT_BYTES``.
    """
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace directory does not exist: {workspace}")

    _check_path_escape(cmd)

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (
            _truncate(result.stdout),
            _truncate(result.stderr),
            result.returncode,
        )
    except subprocess.TimeoutExpired:
        return "", f"Command timed out after {timeout}s", -1

"""Sandboxed shell execution — subprocess confined to a task workspace."""

from __future__ import annotations

import subprocess
from pathlib import Path

from crew.tools.files import PathEscapeError


def run_bash(workspace: str | Path, cmd: str, timeout: int = 120) -> tuple[str, str, int]:
    """Execute *cmd* inside *workspace* via the system shell.

    Returns ``(stdout, stderr, returncode)``.

    Security:
    - Working directory is set to *workspace*.
    - Commands containing obvious path-escape sequences are rejected.
    """
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace directory does not exist: {workspace}")

    # Reject blatant escape attempts in the command string
    if ".." in cmd.split():
        raise PathEscapeError(f"Command contains path traversal: {cmd!r}")

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", f"Command timed out after {timeout}s", -1

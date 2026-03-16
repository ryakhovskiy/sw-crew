"""Sandboxed file operations — read, write, list.

Every path is validated to stay within the task workspace directory.
"""

from __future__ import annotations

from pathlib import Path


class PathEscapeError(Exception):
    """Raised when a path resolves outside the allowed workspace."""


def _safe_resolve(workspace: Path, relative: str) -> Path:
    """Resolve *relative* inside *workspace*, raising on escape attempts."""
    workspace = workspace.resolve()
    target = (workspace / relative).resolve()
    if not target.is_relative_to(workspace):
        raise PathEscapeError(
            f"Path '{relative}' resolves outside workspace ({workspace})"
        )
    return target


def read_file(workspace: str | Path, relative: str) -> str:
    """Read a file from the workspace.  Raises ``FileNotFoundError`` if missing."""
    target = _safe_resolve(Path(workspace), relative)
    return target.read_text(encoding="utf-8")


def write_file(workspace: str | Path, relative: str, content: str) -> str:
    """Write *content* to a file inside the workspace (creates parents)."""
    target = _safe_resolve(Path(workspace), relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target.relative_to(Path(workspace).resolve()))


def list_files(workspace: str | Path, relative: str = ".") -> list[str]:
    """List files/folders at *relative* inside the workspace."""
    target = _safe_resolve(Path(workspace), relative)
    if not target.is_dir():
        raise FileNotFoundError(f"Not a directory: {relative}")
    entries: list[str] = []
    for child in sorted(target.iterdir()):
        name = child.name + ("/" if child.is_dir() else "")
        entries.append(name)
    return entries

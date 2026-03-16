"""Git operations via GitPython — init, add, commit, diff, log."""

from __future__ import annotations

from pathlib import Path

import git as _git


def ensure_repo(workspace: str | Path) -> _git.Repo:
    """Return a ``Repo`` for *workspace*, initialising one if needed."""
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        return _git.Repo(str(workspace))
    except _git.InvalidGitRepositoryError:
        return _git.Repo.init(str(workspace))


def git_add(workspace: str | Path, paths: list[str] | None = None) -> None:
    """Stage files.  If *paths* is ``None``, stage everything (``git add -A``)."""
    repo = ensure_repo(workspace)
    if paths:
        repo.index.add(paths)
    else:
        repo.git.add(A=True)


def git_commit(workspace: str | Path, message: str) -> str:
    """Commit staged changes, returning the short commit hash."""
    repo = ensure_repo(workspace)
    # Ensure there is something to commit
    if not repo.is_dirty(untracked_files=True):
        return ""
    # Configure a default committer if not set
    with repo.config_writer("repository") as cw:
        if not cw.has_option("user", "name"):
            cw.set_value("user", "name", "crew-agent")
        if not cw.has_option("user", "email"):
            cw.set_value("user", "email", "agent@crew.local")
    git_add(workspace)
    commit = repo.index.commit(message)
    return commit.hexsha[:8]


def git_diff(workspace: str | Path) -> str:
    """Return the current diff (staged + unstaged)."""
    repo = ensure_repo(workspace)
    return repo.git.diff() + "\n" + repo.git.diff(cached=True)


def git_log(workspace: str | Path, n: int = 10) -> list[dict[str, str]]:
    """Return the last *n* commits as dicts with ``hash``, ``message``, ``date``."""
    repo = ensure_repo(workspace)
    entries: list[dict[str, str]] = []
    try:
        for commit in repo.iter_commits(max_count=n):
            entries.append({
                "hash": commit.hexsha[:8],
                "message": commit.message.strip(),
                "date": str(commit.committed_datetime),
            })
    except ValueError:
        pass  # empty repo, no commits
    return entries

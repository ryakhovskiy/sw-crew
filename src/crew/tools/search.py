"""Code search — stub for Phase 1, Chroma RAG in Phase 2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodeChunk:
    file: str
    start_line: int
    end_line: int
    content: str
    score: float


def search_code(workspace: str | Path, query: str, top_k: int = 10) -> list[CodeChunk]:
    """Stub: simple grep-like search over workspace files.

    Phase 2 replaces this with Chroma vector search.
    """
    workspace = Path(workspace).resolve()
    results: list[CodeChunk] = []
    query_lower = query.lower()

    for fpath in workspace.rglob("*"):
        if fpath.is_dir() or fpath.suffix in (".pyc", ".db", ".sqlite"):
            continue
        if ".git" in fpath.parts:
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if query_lower in line.lower():
                start = max(1, i - 2)
                lines = text.splitlines()
                end = min(len(lines), i + 2)
                snippet = "\n".join(lines[start - 1 : end])
                results.append(
                    CodeChunk(
                        file=str(fpath.relative_to(workspace)),
                        start_line=start,
                        end_line=end,
                        content=snippet,
                        score=1.0,
                    )
                )
                if len(results) >= top_k:
                    return results
    return results

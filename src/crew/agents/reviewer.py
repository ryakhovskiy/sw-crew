"""Code Reviewer agent — automated quality and security gate before testing."""

from __future__ import annotations

import json

from crew.agents.base import BaseAgent


class ReviewerAgent(BaseAgent):
    agent_name = "reviewer"

    def get_output_file(self) -> str:
        return "review.json"

    def build_system_prompt(self) -> str:
        return """\
You are the Code Reviewer in an autonomous software development pipeline.

Your job: review the code changes for quality, security, and correctness.
Run static analysis and security scanning tools. Produce a review report.

Workspace: the current working directory is your workspace.
You may only read/write files within this workspace.

Available tools:
- read_file(path)      — read a file from the workspace
- write_file(path, content) — write a file (creates parent dirs)
- list_files(path)     — list directory contents
- run_bash(command)    — run a shell command (for linters/scanners)
- search_code(query)   — search the codebase for patterns
- emit_escalation(question, context) — ask the operator a question

Output contract:
- You MUST write review.json before signalling completion.
- review.json must conform to this schema:

{
  "decision": "pass | block",
  "issues": [
    {
      "file": "src/foo.py",
      "line": 42,
      "severity": "critical | major | minor",
      "rule": "string",
      "message": "string"
    }
  ]
}

Review checklist:
1. Run the linter: ruff check . (or pylint, eslint as configured)
2. Run the security scanner: bandit -r . (for Python) or semgrep (for JS)
3. Read changes.json to know which files were changed.
4. Read the changed files and review for:
   - Correctness vs spec/arch contracts
   - Error handling and edge cases
   - Security vulnerabilities (injection, auth bypass, path traversal, etc.)
   - Code style and consistency with the existing codebase
   - Complexity (functions too long, too many branches)
5. For each issue found, classify severity:
   - critical: security vulnerability, data loss risk, crashes → BLOCKS pipeline
   - major: logic error, missing error handling, poor design → noted for coder
   - minor: style, naming, documentation → noted for coder
6. decision = "block" if ANY critical issues exist; "pass" otherwise.

Rules:
1. Read changes.json first to understand what was changed.
2. Read the actual changed files before reviewing.
3. Run ruff and bandit (or equivalent) — include their output in your analysis.
4. Be thorough but fair — don't block on style nitpicks.
5. If you cannot determine whether code is correct without understanding
   the broader architecture, read arch.md and spec.json.
6. Signal completion ONLY after writing review.json.
"""

    def build_initial_messages(self, task: dict) -> list[dict]:
        user_content = "## Code Review Task\n\n"
        user_content += (
            "Review the code changes for quality, security, and correctness. "
            "Run static analysis tools and produce review.json.\n"
        )

        # Include changes.json
        changes_path = self.workspace / "changes.json"
        if changes_path.exists():
            try:
                changes_text = changes_path.read_text(encoding="utf-8")
                changes = json.loads(changes_text)
                user_content += (
                    f"\n## Changes Made\n```json\n"
                    f"{json.dumps(changes, indent=2)}\n```\n"
                )
            except (json.JSONDecodeError, OSError):
                pass

        # Include arch.md for checking contract compliance
        arch_path = self.workspace / "arch.md"
        if arch_path.exists():
            arch_text = arch_path.read_text(encoding="utf-8")
            user_content += f"\n## Architecture\n{arch_text}\n"

        # Include spec.json for checking acceptance criteria
        spec_path = self.workspace / "spec.json"
        if spec_path.exists():
            try:
                spec_text = spec_path.read_text(encoding="utf-8")
                user_content += (
                    f"\n## Specification\n```json\n{spec_text}\n```\n"
                )
            except OSError:
                pass

        # Include the task body
        body = task.get("body", task.get("title", ""))
        user_content += f"\n## Original Requirement\n{body}\n"

        return [{"role": "user", "content": user_content}]

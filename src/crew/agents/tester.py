"""Tester agent — writes and runs tests based on source code and requirements."""

from __future__ import annotations

from crew.agents.base import BaseAgent


class TesterAgent(BaseAgent):
    agent_name = "tester"

    def get_output_file(self) -> str:
        return "test_report.json"

    def build_system_prompt(self) -> str:
        return """\
You are the Test Engineer in an autonomous software development pipeline.

Your job: write unit and integration tests for the source code, then run them.

Workspace: the current working directory is your workspace.

Available tools:
- read_file(path)      — read a file from the workspace
- write_file(path, content) — write a file (creates parent dirs)
- list_files(path)     — list directory contents
- run_bash(command)    — run a shell command in the workspace
- search_code(query)   — search the codebase for relevant code
- git_commit(message)  — stage all changes and commit
- emit_escalation(question, context) — ask the operator a question

Rules:
1. Read the source code first to understand what needs testing.
2. Each acceptance criterion should map to at least one test.
3. Write tests in the tests/ directory using pytest conventions.
4. Run tests with: pytest tests/ -v --tb=short
5. Run coverage with: pytest tests/ --cov=. --cov-report=term-missing
6. Coverage threshold: 80% line coverage minimum.
7. NEVER modify source code — only write test files.
8. Write test_report.json with results before signalling completion.
9. If tests fail, still write the test_report.json with failure details —
   the Debugger agent will handle fixing the source code.

test_report.json format:
{
  "run_id": "unique-id",
  "passed": 12,
  "failed": 3,
  "coverage_pct": 84.2,
  "threshold_met": true,
  "failures": [
    { "test": "tests/test_foo.py::test_bar", "error": "AssertionError: ...", "traceback": "..." }
  ]
}
"""

    def build_initial_messages(self, task: dict) -> list[dict]:
        body = task.get("body", task.get("title", ""))
        user_content = f"## Task\n\n{body}\n"
        user_content += (
            "\nPlease read the source files in the workspace, "
            "write comprehensive tests, run them, and produce "
            "test_report.json.\n"
        )

        # Include spec.json acceptance criteria if available
        spec_path = self.workspace / "spec.json"
        if spec_path.exists():
            spec_text = spec_path.read_text(encoding="utf-8")
            user_content += (
                f"\n## Specification (acceptance criteria)\n"
                f"```json\n{spec_text}\n```\n"
            )

        # Include arch.md interface contracts if available
        arch_path = self.workspace / "arch.md"
        if arch_path.exists():
            arch_text = arch_path.read_text(encoding="utf-8")
            user_content += (
                f"\n## Architecture (interface contracts)\n"
                f"{arch_text}\n"
            )

        return [{"role": "user", "content": user_content}]

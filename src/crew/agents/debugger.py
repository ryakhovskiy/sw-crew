"""Debugger agent — diagnoses test failures, fixes source code, re-runs tests."""

from __future__ import annotations

from crew.agents.base import BaseAgent


class DebuggerAgent(BaseAgent):
    agent_name = "debugger"

    def get_output_file(self) -> str:
        return "debug_log.json"

    def build_system_prompt(self) -> str:
        return """\
You are the Debugger in an autonomous software development pipeline.

Your job: analyse failing test output, find root causes in the source code,
apply fixes, and re-run tests to confirm the fixes work.

Workspace: the current working directory is your workspace.

Available tools:
- read_file(path)      — read a file from the workspace
- write_file(path, content) — write a file (creates parent dirs)
- list_files(path)     — list directory contents
- run_bash(command)    — run a shell command in the workspace
- search_code(query)   — search the codebase for relevant code
- git_commit(message)  — stage all changes and commit
- git_diff()           — show current changes
- emit_escalation(question, context) — ask the operator a question

Rules:
1. Read the test_report.json to understand what failed and why.
2. Read the relevant source files AND test files to understand the code.
3. ONLY modify source code — NEVER modify test files to make tests pass.
4. After applying a fix, re-run the tests to verify.
5. You may attempt multiple fix iterations within a single run.
6. Write debug_log.json with your analysis and fixes before completion.
7. If the issue seems to be a design problem (not a bug), use emit_escalation.

debug_log.json format:
{
  "fixes": [
    {
      "iteration": 1,
      "diagnosis": "Description of the root cause",
      "file_modified": "src/foo.py",
      "change_summary": "What was changed",
      "tests_after": { "passed": 15, "failed": 0 }
    }
  ],
  "final_status": "all_passing | still_failing",
  "remaining_failures": []
}
"""

    def build_initial_messages(self, task: dict) -> list[dict]:
        user_content = (
            "## Debug Task\n\n"
            "Tests are failing. Please diagnose and fix the source code.\n"
        )

        # Load test report
        report_path = self.workspace / "test_report.json"
        if report_path.exists():
            report_text = report_path.read_text(encoding="utf-8")
            user_content += f"\n## Test Report\n```json\n{report_text}\n```\n"

        # Include the task body for context
        user_content += f"\n## Original Task\n{task.get('body', '')}\n"

        # Include escalation answer if resuming
        escalation_answer = task.get("escalation_answer")
        if escalation_answer:
            user_content += f"\n## Operator Answer\n{escalation_answer}\n"

        return [{"role": "user", "content": user_content}]

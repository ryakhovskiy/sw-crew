"""Coder agent — writes production source code per task assignment."""

from __future__ import annotations

import json

from crew.agents.base import BaseAgent


class CoderAgent(BaseAgent):
    agent_name = "coder"

    def get_output_file(self) -> str:
        return "changes.json"

    def build_system_prompt(self) -> str:
        return """\
You are the Coder in an autonomous software development pipeline.

Your job: write production-quality source code for the assigned task.

Workspace: the current working directory is your workspace.
You may only read/write files within this workspace.

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
1. Always read an existing file before modifying it.
2. Write clean, well-structured code. Follow existing project conventions.
3. Run the linter (ruff check .) before finishing and fix any issues.
4. Create a git commit with a clear message after your changes.
5. Write changes.json listing all created/modified files.
6. If you face a design blocker or ambiguity, use emit_escalation — do NOT guess.
7. Signal completion ONLY after writing changes.json and committing.

changes.json format:
{
  "files_created": ["path/to/new.py"],
  "files_modified": ["path/to/existing.py"],
  "commit_hash": "abc12345",
  "summary": "Brief description of changes"
}
"""

    def build_initial_messages(self, task: dict) -> list[dict]:
        messages = []
        user_content = f"## Task\n\n{task.get('body', task.get('title', ''))}\n"

        # Include plan task details if available
        plan_task = task.get("plan_task")
        if plan_task:
            user_content += f"\n## Plan Task\n```json\n{json.dumps(plan_task, indent=2)}\n```\n"

        # Include arch.md if available
        arch_path = self.workspace / "arch.md"
        if arch_path.exists():
            user_content += f"\n## Architecture\n{arch_path.read_text(encoding='utf-8')}\n"

        # Include spec.json if available
        spec_path = self.workspace / "spec.json"
        if spec_path.exists():
            spec_text = spec_path.read_text(encoding="utf-8")
            user_content += f"\n## Specification\n```json\n{spec_text}\n```\n"

        # Include review feedback if this is a re-run after review block
        review_feedback = task.get("review_feedback")
        if review_feedback:
            fb = json.dumps(review_feedback, indent=2)
            user_content += f"\n## Review Feedback (must fix)\n```json\n{fb}\n```\n"

        # Include debug log if this is a re-run after debug exhaustion
        debug_context = task.get("debug_context")
        if debug_context:
            dl = json.dumps(debug_context, indent=2)
            user_content += (
                f"\n## Debug Log (previous fix attempts failed)\n"
                f"```json\n{dl}\n```\n"
            )

        # Include escalation answer if resuming after escalation
        escalation_answer = task.get("escalation_answer")
        if escalation_answer:
            user_content += f"\n## Operator Answer\n{escalation_answer}\n"

        messages.append({"role": "user", "content": user_content})
        return messages

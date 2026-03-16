"""Doc Writer agent — generates and maintains documentation in sync with code."""

from __future__ import annotations

import json

from crew.agents.base import BaseAgent


class DocWriterAgent(BaseAgent):
    agent_name = "docwriter"

    def get_output_file(self) -> str | None:
        # Doc Writer produces multiple files (README, CHANGELOG, docstrings)
        # rather than a single output artifact.
        return None

    def build_system_prompt(self) -> str:
        return """\
You are the Doc Writer in an autonomous software development pipeline.

Your job: generate and update documentation to match the current codebase.
You run in parallel with the Coder — keep docs in sync with code changes.

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

Documentation to produce/update:
1. README.md — project overview, setup instructions, usage, API reference.
2. CHANGELOG.md — what changed in this task (added, changed, fixed, removed).
3. Inline docstrings — ensure public functions/classes have docstrings.
4. OpenAPI spec — if the project has a REST API, generate/update openapi.json.

Rules:
1. Read existing documentation before modifying it — preserve existing content.
2. Read the source code and changes.json to understand what was built.
3. Use clear, concise language. Follow existing documentation conventions.
4. Include code examples where helpful.
5. Commit documentation changes with a clear message like "docs: update README".
6. If you cannot determine what the code does, use emit_escalation.
7. NEVER modify source code — only documentation files and docstrings.
"""

    def get_tools(self) -> list[dict]:
        """Doc Writer uses all tools except run_bash for safety."""
        return [t for t in super().get_tools() if t["name"] in {
            "read_file", "write_file", "list_files", "search_code",
            "git_commit", "git_diff", "emit_escalation",
        }]

    def build_initial_messages(self, task: dict) -> list[dict]:
        user_content = (
            "## Documentation Task\n\n"
            "Code has been written or updated. Please generate/update all "
            "documentation to match the current state of the codebase.\n"
        )

        # Include task description
        body = task.get("body", task.get("title", ""))
        user_content += f"\n## Original Requirement\n{body}\n"

        # Include changes manifest if available
        changes_path = self.workspace / "changes.json"
        if changes_path.exists():
            try:
                changes = json.loads(changes_path.read_text(encoding="utf-8"))
                user_content += (
                    f"\n## Changes Made\n```json\n"
                    f"{json.dumps(changes, indent=2)}\n```\n"
                )
            except (json.JSONDecodeError, OSError):
                pass

        # Include architecture doc if available
        arch_path = self.workspace / "arch.md"
        if arch_path.exists():
            arch_text = arch_path.read_text(encoding="utf-8")
            user_content += f"\n## Architecture\n{arch_text}\n"

        # Include spec for context
        spec_path = self.workspace / "spec.json"
        if spec_path.exists():
            try:
                spec_text = spec_path.read_text(encoding="utf-8")
                user_content += (
                    f"\n## Specification\n```json\n{spec_text}\n```\n"
                )
            except OSError:
                pass

        # Include existing README if present
        readme_path = self.workspace / "README.md"
        if readme_path.exists():
            readme_text = readme_path.read_text(encoding="utf-8")
            user_content += (
                f"\n## Existing README.md\n```markdown\n{readme_text}\n```\n"
            )

        # Include git log for changelog
        user_content += (
            "\nPlease read the source files, generate/update README.md, "
            "CHANGELOG.md, and add docstrings where missing. "
            "Commit your changes when done.\n"
        )

        return [{"role": "user", "content": user_content}]

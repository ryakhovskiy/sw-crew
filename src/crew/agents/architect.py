"""Architect agent — designs the technical solution from spec and existing code."""

from __future__ import annotations

import json

from crew.agents.base import BaseAgent


class ArchitectAgent(BaseAgent):
    agent_name = "architect"

    def get_output_file(self) -> str:
        return "arch.md"

    def build_system_prompt(self) -> str:
        return """\
You are the Architect in an autonomous software development pipeline.

Your job: read the specification and the existing codebase, then design
the technical solution. Output a complete architecture document.

Workspace: the current working directory is your workspace.
You may only read/write files within this workspace.

Available tools:
- read_file(path)      — read a file from the workspace
- write_file(path, content) — write a file (creates parent dirs)
- list_files(path)     — list directory contents
- search_code(query)   — search the codebase for relevant code
- emit_escalation(question, context) — ask the operator a question

Output contract:
- You MUST write arch.md before signalling completion.
- arch.md must include ALL of the following sections:

## Component Overview
What changes, what is new, what stays the same.

## Interface Contracts
Function signatures, API schemas, DB schema changes.

## Migration Plan
Database or API migration steps (if applicable; write "N/A" if none).

## Technical Risks
Each risk with a mitigation strategy.

## Architecture Diagram
A Mermaid diagram (```mermaid block) showing component relationships.

Rules:
1. ALWAYS read existing code before designing. Use list_files and read_file
   to explore the repo/ directory thoroughly.
2. Identify patterns in the existing system and respect them.
3. Flag breaking changes explicitly.
4. If the spec has gaps that affect architecture, use emit_escalation.
5. Be specific about interface contracts — include function signatures,
   request/response schemas, and data types.
6. Signal completion ONLY after writing arch.md.
"""

    def get_tools(self) -> list[dict]:
        """Architect uses read-only tools plus escalation — no bash/git."""
        return [t for t in super().get_tools() if t["name"] in {
            "read_file", "write_file", "list_files", "search_code",
            "emit_escalation",
        }]

    def build_initial_messages(self, task: dict) -> list[dict]:
        user_content = "## Architecture Task\n\n"
        user_content += (
            "Design the technical solution for the following specification. "
            "Read the existing codebase first, then produce arch.md.\n"
        )

        # Include spec.json
        spec_path = self.workspace / "spec.json"
        if spec_path.exists():
            try:
                spec_text = spec_path.read_text(encoding="utf-8")
                spec = json.loads(spec_text)
                user_content += (
                    f"\n## Specification\n```json\n"
                    f"{json.dumps(spec, indent=2)}\n```\n"
                )
            except (json.JSONDecodeError, OSError):
                user_content += "\n(spec.json exists but could not be parsed)\n"
        else:
            # Fall back to task body
            user_content += f"\n## Requirement\n{task.get('body', '')}\n"

        # Point to existing codebase
        repo_dir = self.workspace / "repo"
        if repo_dir.is_dir():
            user_content += (
                "\nThe existing codebase is in repo/. "
                "Explore it with list_files and read_file before designing.\n"
            )

        # Include rejection feedback if this is a re-run
        rejection_reason = task.get("rejection_reason")
        if rejection_reason:
            user_content += (
                f"\n## Previous Architecture Rejected\n"
                f"The operator rejected your previous architecture with this feedback:\n"
                f"{rejection_reason}\n\n"
                f"Please revise the architecture to address this feedback.\n"
            )

        # Include escalation answer if resuming
        escalation_answer = task.get("escalation_answer")
        if escalation_answer:
            user_content += f"\n## Operator Answer\n{escalation_answer}\n"

        return [{"role": "user", "content": user_content}]

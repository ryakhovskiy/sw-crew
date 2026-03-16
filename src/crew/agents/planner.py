"""Implementation Planner agent — translates architecture into an ordered task graph."""

from __future__ import annotations

import json

from crew.agents.base import BaseAgent


class PlannerAgent(BaseAgent):
    agent_name = "planner"

    def get_output_file(self) -> str:
        return "plan.json"

    def build_system_prompt(self) -> str:
        return """\
You are the Implementation Planner in an autonomous software development pipeline.

Your job: translate the architecture document into an ordered task graph
that can be assigned to agents (coder, tester, deployer).

Workspace: the current working directory is your workspace.
You may only read/write files within this workspace.

Available tools:
- read_file(path)      — read a file from the workspace
- write_file(path, content) — write a file (creates parent dirs)
- list_files(path)     — list directory contents
- search_code(query)   — search the codebase for relevant code
- emit_escalation(question, context) — ask the operator a question

Output contract:
- You MUST write plan.json before signalling completion.
- plan.json must conform to this schema:

{
  "tasks": [
    {
      "id": "T-01",
      "title": "string",
      "agent": "coder | tester | deployer",
      "depends_on": ["T-00"],
      "files_to_create": ["src/module.py"],
      "files_to_modify": ["src/existing.py"],
      "effort": "S | M | L",
      "notes": "string"
    }
  ]
}

Rules:
1. Read arch.md and spec.json to understand the full scope.
2. Break the work into small, well-defined tasks.
3. Each task must specify which agent type will execute it.
4. Use depends_on to define the execution order (DAG).
5. Identify files_to_create and files_to_modify for each coding task.
6. Estimate effort as S (< 1 file), M (2-4 files), or L (5+ files).
7. Coder tasks should come first, then tester tasks, then deployer tasks.
8. If the architecture is unclear or incomplete, use emit_escalation.
9. Signal completion ONLY after writing plan.json.
"""

    def get_tools(self) -> list[dict]:
        """Planner uses read-only tools plus write + escalation — no bash/git."""
        return [t for t in super().get_tools() if t["name"] in {
            "read_file", "write_file", "list_files", "search_code",
            "emit_escalation",
        }]

    def build_initial_messages(self, task: dict) -> list[dict]:
        user_content = "## Planning Task\n\n"
        user_content += (
            "Create an ordered task graph (plan.json) from the architecture "
            "and specification documents.\n"
        )

        # Include arch.md
        arch_path = self.workspace / "arch.md"
        if arch_path.exists():
            arch_text = arch_path.read_text(encoding="utf-8")
            user_content += f"\n## Architecture\n{arch_text}\n"

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
                pass

        # Point to existing codebase
        repo_dir = self.workspace / "repo"
        if repo_dir.is_dir():
            user_content += (
                "\nThe existing codebase is in repo/. "
                "Explore it to understand what already exists.\n"
            )

        # Include escalation answer if resuming
        escalation_answer = task.get("escalation_answer")
        if escalation_answer:
            user_content += f"\n## Operator Answer\n{escalation_answer}\n"

        return [{"role": "user", "content": user_content}]

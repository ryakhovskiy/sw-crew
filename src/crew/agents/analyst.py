"""Requirements Analyst agent — transforms raw requirements into a formal spec."""

from __future__ import annotations

from crew.agents.base import BaseAgent


class AnalystAgent(BaseAgent):
    agent_name = "analyst"

    def get_output_file(self) -> str:
        return "spec.json"

    def build_system_prompt(self) -> str:
        return """\
You are the Requirements Analyst in an autonomous software development pipeline.

Your job: transform the raw requirement into a formal, structured specification.

Workspace: the current working directory is your workspace.
You may only read/write files within this workspace.

Available tools:
- read_file(path)      — read a file from the workspace
- write_file(path, content) — write a file (creates parent dirs)
- list_files(path)     — list directory contents
- search_code(query)   — search the existing codebase for relevant code
- emit_escalation(question, context) — ask the operator a question

Output contract:
- You MUST write spec.json before signalling completion.
- spec.json must conform to this schema:

{
  "task_id": "string",
  "title": "string",
  "summary": "string",
  "user_stories": [
    {
      "id": "US-01",
      "as_a": "...",
      "i_want": "...",
      "so_that": "...",
      "acceptance_criteria": ["..."]
    }
  ],
  "out_of_scope": ["string"],
  "risks": ["string"],
  "open_questions": ["string"]
}

Rules:
1. Read any existing codebase in repo/ to understand current state.
2. Break the requirement into clear user stories with testable acceptance criteria.
3. Identify what is explicitly out of scope.
4. Flag risks that could impact delivery.
5. If the requirement is ambiguous and you cannot produce a complete spec,
   use emit_escalation to ask the operator — do NOT guess.
6. Keep open_questions empty if everything is clear; populate it if you
   had to make assumptions the operator should confirm.
7. Signal completion ONLY after writing spec.json.
"""

    def get_tools(self) -> list[dict]:
        """Analyst uses read-only tools plus escalation — no bash/git."""
        return [t for t in super().get_tools() if t["name"] in {
            "read_file", "write_file", "list_files", "search_code",
            "emit_escalation",
        }]

    def build_initial_messages(self, task: dict) -> list[dict]:
        user_content = f"## Requirement\n\n{task.get('body', task.get('title', ''))}\n"

        task_id = task.get("id", "")
        if task_id:
            user_content += f"\nTask ID: {task_id}\n"

        # Include existing codebase summary if repo/ exists
        repo_dir = self.workspace / "repo"
        if repo_dir.is_dir():
            user_content += (
                "\nAn existing codebase is available at repo/. "
                "Please explore it to understand the current system before writing the spec.\n"
            )

        # Include rejection feedback if this is a re-run
        rejection_reason = task.get("rejection_reason")
        if rejection_reason:
            user_content += (
                f"\n## Previous Spec Rejected\n"
                f"The operator rejected your previous spec with this feedback:\n"
                f"{rejection_reason}\n\n"
                f"Please revise the spec to address this feedback.\n"
            )

        # Include escalation answer if resuming
        escalation_answer = task.get("escalation_answer")
        if escalation_answer:
            user_content += f"\n## Operator Answer\n{escalation_answer}\n"

        return [{"role": "user", "content": user_content}]

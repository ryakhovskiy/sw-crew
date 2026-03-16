"""Deployer agent — builds, deploys, and smoke-tests the service."""

from __future__ import annotations

import json

from crew.agents.base import BaseAgent


class DeployerAgent(BaseAgent):
    agent_name = "deployer"

    def get_output_file(self) -> str:
        return "deploy_log.json"

    def build_system_prompt(self) -> str:
        return """\
You are the Deployer in an autonomous software development pipeline.

Your job: build the service, run any migrations, deploy it, and verify it works
via smoke tests. If smoke tests fail, roll back immediately and escalate.

Workspace: the current working directory is your workspace.

Available tools:
- read_file(path)      — read a file from the workspace
- write_file(path, content) — write a file (creates parent dirs)
- list_files(path)     — list directory contents
- run_bash(command)    — run a shell command in the workspace
- emit_escalation(question, context) — ask the operator a question

Deployment strategy (Docker-based):
1. Read the build spec and environment config from the workspace.
2. Build a Docker image: docker build -t <service-name> .
3. Stop any existing container for this service.
4. Run the new container with appropriate environment variables.
5. Wait a few seconds, then run smoke tests (health check endpoints, basic API calls).
6. If smoke tests pass → record success in deploy_log.json.
7. If smoke tests FAIL → stop the new container, restart the old one (rollback),
   then use emit_escalation to notify the operator.

Rules:
1. Always read existing deployment configs before deploying.
2. Create a rollback plan BEFORE deploying.
3. Run smoke tests AFTER deployment — never skip them.
4. If any smoke test fails, execute rollback IMMEDIATELY, then escalate.
5. Write deploy_log.json before signalling completion.
6. Do NOT guess environment variables or secrets — escalate if missing.

deploy_log.json format:
{
  "service": "service-name",
  "image": "image:tag",
  "health_check_url": "http://localhost:PORT/health",
  "smoke_results": [
    { "name": "health_check", "passed": true, "error": null },
    { "name": "api_basic", "passed": true, "error": null }
  ],
  "rollback_plan": "docker stop <new> && docker start <old>",
  "deployed_at": "2026-03-16T12:00:00Z",
  "status": "success | rolled_back | failed"
}
"""

    def get_tools(self) -> list[dict]:
        """Deployer uses a subset of tools — no git or code search."""
        return [t for t in super().get_tools() if t["name"] in {
            "read_file", "write_file", "list_files", "run_bash", "emit_escalation",
        }]

    def build_initial_messages(self, task: dict) -> list[dict]:
        user_content = (
            "## Deployment Task\n\n"
            "All tests have passed and the code has been reviewed. "
            "Please build, deploy, and smoke-test the service.\n"
        )

        # Include the task body
        body = task.get("body", task.get("title", ""))
        user_content += f"\n## Original Requirement\n{body}\n"

        # Include build/deploy config if available
        for cfg_name in ("Dockerfile", "docker-compose.yml", ".env.example"):
            cfg_path = self.workspace / cfg_name
            if cfg_path.exists():
                cfg_text = cfg_path.read_text(encoding="utf-8")
                user_content += (
                    f"\n## {cfg_name}\n```\n{cfg_text}\n```\n"
                )

        # Include deploy plan from arch.md if available
        arch_path = self.workspace / "arch.md"
        if arch_path.exists():
            arch_text = arch_path.read_text(encoding="utf-8")
            user_content += f"\n## Architecture\n{arch_text}\n"

        # Include test report summary
        report_path = self.workspace / "test_report.json"
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                user_content += (
                    f"\n## Test Results\n"
                    f"Passed: {report.get('passed', 0)}, "
                    f"Failed: {report.get('failed', 0)}, "
                    f"Coverage: {report.get('coverage_pct', 'N/A')}%\n"
                )
            except (json.JSONDecodeError, OSError):
                pass

        # Include review summary
        review_path = self.workspace / "review.json"
        if review_path.exists():
            try:
                review = json.loads(review_path.read_text(encoding="utf-8"))
                user_content += (
                    f"\n## Review Result\n"
                    f"Decision: {review.get('decision', 'unknown')}\n"
                )
            except (json.JSONDecodeError, OSError):
                pass

        return [{"role": "user", "content": user_content}]

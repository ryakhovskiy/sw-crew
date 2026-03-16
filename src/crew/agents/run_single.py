"""Standalone entry point for running a single agent — used inside Docker containers."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from crew.config import load_config
from crew.db.migrate import run_migrations
from crew.db.store import TaskStore

# Agent class registry
_AGENT_CLASSES = {
    "analyst": "crew.agents.analyst:AnalystAgent",
    "architect": "crew.agents.architect:ArchitectAgent",
    "planner": "crew.agents.planner:PlannerAgent",
    "coder": "crew.agents.coder:CoderAgent",
    "reviewer": "crew.agents.reviewer:ReviewerAgent",
    "tester": "crew.agents.tester:TesterAgent",
    "debugger": "crew.agents.debugger:DebuggerAgent",
    "deployer": "crew.agents.deployer:DeployerAgent",
    "docwriter": "crew.agents.docwriter:DocWriterAgent",
}


def _import_agent_class(agent_name: str):
    """Dynamically import an agent class by name."""
    if agent_name not in _AGENT_CLASSES:
        raise ValueError(f"Unknown agent: {agent_name}")

    module_path, class_name = _AGENT_CLASSES[agent_name].rsplit(":", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


@click.command()
@click.option("--agent", required=True, help="Agent name (e.g. coder, tester)")
@click.option("--task-id", required=True, help="Task ID to process")
def main(agent: str, task_id: str) -> None:
    """Run a single agent and write the result to the workspace."""
    config = load_config()
    config.ensure_dirs()
    run_migrations(config.db_path)

    store = TaskStore(config.db_path)
    store.connect()

    try:
        task = store.get_task(task_id)
        if not task:
            print(f"Task {task_id} not found", file=sys.stderr)
            sys.exit(1)

        agent_class = _import_agent_class(agent)
        agent_instance = agent_class(task_id, config, store)

        task_dict = {
            "id": task.id,
            "title": task.title,
            "body": task.body,
            "phase": task.phase,
            "status": task.status,
            "debug_attempts": task.debug_attempts,
        }

        result = asyncio.run(agent_instance.run(task_dict))

        # Write result as JSON to workspace for the host to read
        result_path = Path(config.workspace_root) / task_id / "_agent_result.json"
        result_data = {
            "success": result.success,
            "output_file": result.output_file,
            "escalation": result.escalation,
            "error": result.error,
            "token_usage": result.token_usage,
            "cost_usd": result.cost_usd,
        }
        result_path.write_text(json.dumps(result_data, indent=2), encoding="utf-8")

    finally:
        store.close()


if __name__ == "__main__":
    main()

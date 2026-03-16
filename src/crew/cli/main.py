"""crew CLI — operator interface to the AI Dev Crew gateway."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
import httpx
import yaml

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_cli_config() -> dict:
    """Load CLI config from ~/.crew/config.yaml or environment variables."""
    config: dict = {}
    config_path = Path.home() / ".crew" / "config.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    # Env var overrides
    config.setdefault("gateway_url", os.environ.get("CREW_GATEWAY_URL", "http://localhost:8080"))
    config.setdefault("token", os.environ.get("CREW_TOKEN", "change-me"))
    return config


def _client(config: dict) -> httpx.Client:
    return httpx.Client(
        base_url=config["gateway_url"],
        headers={"Authorization": f"Bearer {config['token']}"},
        timeout=30.0,
    )


def _print_json(data):
    click.echo(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.pass_context
def cli(ctx):
    """AI Dev Crew — operator CLI."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = _load_cli_config()


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("text", required=False)
@click.option(
    "--file", "-f", "filepath",
    type=click.Path(exists=True),
    help="Read requirement from file",
)
@click.option("--title", "-t", default=None, help="Optional task title")
@click.pass_context
def submit(ctx, text, filepath, title):
    """Submit a new requirement to the pipeline."""
    if filepath:
        body = Path(filepath).read_text(encoding="utf-8")
    elif text:
        body = text
    elif not sys.stdin.isatty():
        body = sys.stdin.read()
    else:
        body = click.edit("# Enter your requirement below\n")
        if not body:
            click.echo("Aborted — no input provided.", err=True)
            raise SystemExit(1)

    payload = {"body": body.strip()}
    if title:
        payload["title"] = title

    with _client(ctx.obj["config"]) as c:
        resp = c.post("/tasks", json=payload)
        resp.raise_for_status()
        data = resp.json()
        click.echo(f"Task created: {data['task_id']}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("task_id", required=False)
@click.pass_context
def status(ctx, task_id):
    """Show task status.  Without TASK_ID, lists all active tasks."""
    with _client(ctx.obj["config"]) as c:
        if task_id:
            resp = c.get(f"/tasks/{task_id}")
            resp.raise_for_status()
            data = resp.json()
            click.echo(f"Task:   {data['id']}")
            click.echo(f"Title:  {data['title']}")
            click.echo(f"Phase:  {data['phase']}")
            click.echo(f"Status: {data['status']}")
            click.echo(f"Agent:  {data.get('agent', '-')}")
            click.echo(f"Debug:  {data['debug_attempts']} attempts")
            if data.get("artifacts"):
                click.echo("Artifacts:")
                for a in data["artifacts"]:
                    click.echo(f"  - {a['name']}")
            if data.get("gates"):
                click.echo("Gates:")
                for g in data["gates"]:
                    click.echo(f"  - [{g['status']}] {g['type']} ({g['id']})")
        else:
            resp = c.get("/tasks")
            resp.raise_for_status()
            tasks = resp.json()
            if not tasks:
                click.echo("No tasks.")
                return
            for t in tasks:
                click.echo(
                    f"  {t['id']}  {t['phase']:20s}  {t['status']:10s}  {t['title'][:50]}"
                )


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def gates(ctx):
    """List all pending approval gates."""
    with _client(ctx.obj["config"]) as c:
        resp = c.get("/gates", params={"status": "pending"})
        resp.raise_for_status()
        gates_list = resp.json()
        if not gates_list:
            click.echo("No pending gates.")
            return
        for g in gates_list:
            line = f"  {g['id']}  task={g['task_id']}  type={g['type']}"
            if g.get("question"):
                line += f"  Q: {g['question'][:60]}"
            click.echo(line)


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("task_id")
@click.option("--comment", "-c", default=None, help="Approval comment")
@click.pass_context
def approve(ctx, task_id, comment):
    """Approve the pending gate for a task."""
    gate_id = _find_pending_gate(ctx, task_id)
    with _client(ctx.obj["config"]) as c:
        resp = c.post(f"/gates/{gate_id}/approve", json={"comment": comment})
        resp.raise_for_status()
        click.echo(f"Gate {gate_id} approved.")


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("task_id")
@click.option("--reason", "-r", required=True, help="Rejection reason")
@click.pass_context
def reject(ctx, task_id, reason):
    """Reject the pending gate for a task."""
    gate_id = _find_pending_gate(ctx, task_id)
    with _client(ctx.obj["config"]) as c:
        resp = c.post(f"/gates/{gate_id}/reject", json={"reason": reason})
        resp.raise_for_status()
        click.echo(f"Gate {gate_id} rejected.")


# ---------------------------------------------------------------------------
# answer
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("task_id")
@click.option("--message", "-m", default=None, help="Answer text (or opens editor)")
@click.pass_context
def answer(ctx, task_id, message):
    """Answer an escalation gate for a task."""
    gate_id = _find_pending_gate(ctx, task_id)
    if not message:
        message = click.edit("# Type your answer below\n")
        if not message:
            click.echo("Aborted — no answer provided.", err=True)
            raise SystemExit(1)

    with _client(ctx.obj["config"]) as c:
        resp = c.post(f"/gates/{gate_id}/answer", json={"message": message.strip()})
        resp.raise_for_status()
        click.echo(f"Gate {gate_id} answered.")


# ---------------------------------------------------------------------------
# artifact
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("task_id")
@click.argument("name")
@click.pass_context
def artifact(ctx, task_id, name):
    """Download and display an artifact."""
    with _client(ctx.obj["config"]) as c:
        resp = c.get(f"/tasks/{task_id}/artifacts/{name}")
        resp.raise_for_status()
        click.echo(resp.text)


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def history(ctx):
    """Show completed and failed tasks."""
    with _client(ctx.obj["config"]) as c:
        resp = c.get("/tasks")
        resp.raise_for_status()
        tasks = resp.json()
        done = [t for t in tasks if t["status"] in ("done", "failed")]
        if not done:
            click.echo("No completed tasks.")
            return
        for t in done:
            click.echo(
                f"  {t['id']}  {t['status']:10s}  {t['title'][:50]}"
            )


# ---------------------------------------------------------------------------
# log (SSE tail)
# ---------------------------------------------------------------------------

@cli.command(name="log")
@click.argument("task_id")
@click.pass_context
def log_cmd(ctx, task_id):
    """Tail live agent output for a task (Ctrl+C to stop)."""
    config = ctx.obj["config"]
    url = f"{config['gateway_url']}/stream/{task_id}"
    headers = {"Authorization": f"Bearer {config['token']}"}

    click.echo(f"Streaming events for {task_id} (Ctrl+C to stop)...")
    try:
        with httpx.stream("GET", url, headers=headers, timeout=None) as resp:
            resp.raise_for_status()
            event_type = ""
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    click.echo(f"[{event_type}] {data}")
                    if event_type == "stream:end":
                        return
    except KeyboardInterrupt:
        click.echo("\nStopped.")
    except httpx.HTTPStatusError as exc:
        click.echo(f"Error: {exc.response.status_code} {exc.response.text}", err=True)
        raise SystemExit(1) from None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_pending_gate(ctx, task_id: str) -> str:
    """Find the pending gate for a task, or exit with error."""
    with _client(ctx.obj["config"]) as c:
        resp = c.get("/gates", params={"status": "pending"})
        resp.raise_for_status()
        gates_list = resp.json()
        for g in gates_list:
            if g["task_id"] == task_id:
                return g["id"]

    click.echo(f"No pending gate found for task {task_id}", err=True)
    raise SystemExit(1)


if __name__ == "__main__":
    cli()

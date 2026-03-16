# AI Dev Crew

Autonomous multi-agent software development system. Submit a coding task, and a crew of AI agents writes, tests, and debugs the code — with human approval gates at key checkpoints.

Built on Claude (Anthropic API) with a FastAPI gateway, SQLite state machine, and a CLI for operator control.

## Status

**Phase 1 (Working Core Loop)** is implemented:

- **Coder** agent — writes source code, runs linter, commits
- **Tester** agent — generates and runs pytest tests, reports coverage
- **Debugger** agent — diagnoses test failures, fixes source code (up to 5 retries)
- **Orchestrator** — drives the `INTAKE → BUILD → TEST_LOOP → DONE` state machine
- **Gateway** — FastAPI REST API with Bearer token auth
- **CLI** (`crew`) — submit tasks, check status, manage approval gates

See [AGENTS.md](AGENTS.md) for the full specification (Phases 2–4 are next).

## Prerequisites

- Python 3.12+
- Git
- An [Anthropic API key](https://console.anthropic.com/)

## Quick Start

### 1. Install

```bash
git clone <repo-url> && cd sw-crew
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env           # add your ANTHROPIC_API_KEY and CREW_TOKEN
cp config.yaml.example config.yaml
```

Secrets (`ANTHROPIC_API_KEY`, `CREW_TOKEN`) live in `.env` — loaded automatically.
Non-secret settings go in `config.yaml`. See [.env.example](.env.example) and [config.yaml.example](config.yaml.example).

### 3. Run the Gateway

```bash
uvicorn crew.gateway.app:app
```

This starts the Gateway API on `http://localhost:8080` and the Orchestrator background loop.

### 4. Submit a Task

```bash
crew submit "Write a Python function that calculates factorial"
crew status
crew gates          # check for pending approval gates
crew approve <task-id>
```

## Docker

```bash
cp .env.example .env           # fill in your secrets
cp config.yaml.example config.yaml
docker compose up --build
```

The container runs as a non-root `crew` user, binds to `0.0.0.0:8080`, and persists `workspace/`, `db/`, and `logs/` in named volumes.

## CLI Reference

| Command | Description |
|---|---|
| `crew submit [TEXT]` | Submit a requirement (inline, `--file`, or stdin) |
| `crew status [TASK_ID]` | List active tasks or show detail for one task |
| `crew gates` | List pending approval gates |
| `crew approve TASK_ID` | Approve the pending gate (`--comment` optional) |
| `crew reject TASK_ID` | Reject the pending gate (`--reason` required) |
| `crew answer TASK_ID` | Answer an escalation (`--message` or opens editor) |
| `crew artifact TASK_ID NAME` | Display an artifact (e.g. `spec.json`, `test_report.json`) |
| `crew history` | Show completed and failed tasks |

CLI config: set `CREW_GATEWAY_URL` and `CREW_TOKEN` env vars, or create `~/.crew/config.yaml`.

## REST API

All endpoints require `Authorization: Bearer <token>`.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/tasks` | Create a task (`{ body, title? }`) |
| `GET` | `/tasks` | List tasks (`?status=pending\|running\|done`) |
| `GET` | `/tasks/{id}` | Task detail with artifacts and gates |
| `GET` | `/tasks/{id}/artifacts/{name}` | Download artifact file |
| `GET` | `/gates` | List gates (`?status=pending`) |
| `POST` | `/gates/{id}/approve` | Approve gate (`{ comment? }`) |
| `POST` | `/gates/{id}/reject` | Reject gate (`{ reason }`) |
| `POST` | `/gates/{id}/answer` | Answer escalation (`{ message }`) |
| `GET` | `/health` | System health check |

## Project Structure

```
sw-crew/
├── src/crew/
│   ├── config.py              # YAML + .env config loader
│   ├── db/
│   │   ├── schema.sql         # SQLite DDL (tasks, gates, audit, artifacts, notifications)
│   │   ├── migrate.py         # Idempotent schema runner
│   │   └── store.py           # TaskStore data-access layer
│   ├── agents/
│   │   ├── base.py            # BaseAgent: Anthropic tool-use loop
│   │   ├── orchestrator.py    # Pipeline state machine
│   │   ├── coder.py           # Writes and lints code
│   │   ├── tester.py          # Generates and runs tests
│   │   └── debugger.py        # Diagnoses and fixes test failures
│   ├── tools/
│   │   ├── files.py           # Sandboxed file I/O
│   │   ├── shell.py           # Sandboxed shell execution
│   │   ├── git.py             # Git operations (GitPython)
│   │   └── search.py          # Code search (grep-based; Chroma in Phase 2)
│   ├── gateway/
│   │   ├── app.py             # FastAPI app + lifespan
│   │   ├── auth.py            # Bearer token middleware
│   │   └── routes/            # tasks, gates, health endpoints
│   └── cli/
│       └── main.py            # Click-based `crew` CLI
├── tests/                     # pytest suite (35 tests)
├── Dockerfile
├── docker-compose.yml
├── config.yaml.example
├── .env.example
└── pyproject.toml
```

## Development

```bash
# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/

# Lint + auto-fix
ruff check src/ tests/ --fix
```

## Security

- Gateway binds to `127.0.0.1` by default (Docker uses `0.0.0.0`)
- All file/shell tools are sandboxed to the task workspace directory — path traversal is rejected
- API key loaded from `.env` / env vars — never written to workspace or logs
- Bearer token required on all API endpoints
- Audit log is append-only (no UPDATE/DELETE)
- Docker container runs as non-root user

## License

[MIT](LICENSE)

# AI Dev Crew — Implementation Brief
**Version:** 1.0 · **Date:** March 2026
**Purpose:** Complete specification for an autonomous multi-agent software development team. This document is the single source of truth for implementation.

---

## Table of Contents
1. [System Overview](#1-system-overview)
2. [Agent Roster](#2-agent-roster)
3. [Pipeline Architecture](#3-pipeline-architecture)
4. [Communication Channel (Gateway)](#4-communication-channel-gateway)
5. [Data Model](#5-data-model)
6. [File System Layout](#6-file-system-layout)
7. [Tech Stack](#7-tech-stack)
8. [Human-in-Loop Gates](#8-human-in-loop-gates)
9. [Gateway REST API](#9-gateway-rest-api)
10. [CLI Reference](#10-cli-reference)
11. [Agent Context Model](#11-agent-context-model)
12. [Feedback Loops](#12-feedback-loops)
13. [Deployment (systemd)](#13-deployment-systemd)
14. [Build Order (Phased)](#14-build-order-phased)
15. [Security Constraints](#15-security-constraints)

---

## 1. System Overview

The AI Dev Crew is an autonomous multi-agent system that accepts a software requirement from a human operator and produces deployed, tested code — with minimal human involvement limited to structured approval gates.

### Core Concept

```
Operator
  │
  │  (submit requirement)
  ▼
Gateway Service  ←──────────────────────────────────────────┐
  │                                                          │
  │  (task queue)                                            │ (gate events, SSE)
  ▼                                                          │
Orchestrator (state machine)  ──────────────────────────────┘
  │
  ├─► Requirements Analyst
  ├─► Architect
  ├─► Implementation Planner
  ├─► Coder
  ├─► Code Reviewer
  ├─► Test Engineer
  ├─► Debugger
  ├─► Deployer
  └─► Doc Writer (parallel)
```

### Fundamental Rules
- The **Gateway Service is the only process** that may communicate with the operator. No agent contacts the operator directly.
- All inter-agent communication happens via **files in /workspace/{task_id}/** and the **SQLite state store**.
- The operator interacts via **Web UI (localhost:8080)** or **`crew` CLI**.
- Human gates **never time out** — the pipeline waits indefinitely for operator input.

---

## 2. Agent Roster

Ten agents, each a separate Python process with its own system prompt, tools, inputs, and outputs.

### 2.1 Orchestrator

| Field | Value |
|---|---|
| **Role** | Central coordinator. Manages the pipeline state machine. The only agent that reads/writes `human_gates`. |
| **Tools** | SQLite R/W, task queue R/W, agent spawner (subprocess), notification bus publisher |
| **Inputs** | New task events, agent completion signals, gate resolution events, error signals |
| **Outputs** | Task assignments, gate creation, gate resolution routing, escalation forwarding |
| **Key behaviour** | On gate approval → advance pipeline. On gate rejection → inject feedback into producing agent context and re-run that agent. On escalation answer → inject answer into waiting agent context and resume. |

### 2.2 Requirements Analyst

| Field | Value |
|---|---|
| **Role** | Transforms raw requirements into a formal, structured specification. |
| **Tools** | Web search, document reader, file write |
| **Inputs** | Raw requirement text, any attached files, existing codebase summary |
| **Outputs** | `/workspace/{task_id}/spec.json` — formal spec with user stories, acceptance criteria, scope boundaries, open questions, risk flags |
| **Key behaviour** | If requirements are ambiguous and the spec cannot be completed, agent emits an escalation rather than guessing. |

**spec.json schema:**
```json
{
  "task_id": "string",
  "title": "string",
  "summary": "string",
  "user_stories": [
    { "id": "US-01", "as_a": "...", "i_want": "...", "so_that": "...", "acceptance_criteria": ["..."] }
  ],
  "out_of_scope": ["string"],
  "risks": ["string"],
  "open_questions": ["string"]
}
```

### 2.3 Architect

| Field | Value |
|---|---|
| **Role** | Reads the existing codebase and designs the technical solution. |
| **Tools** | File tree walker, code search (ripgrep), RAG over codebase (Chroma), file write, mermaid diagram generator |
| **Inputs** | `spec.json`, existing codebase at `/workspace/{task_id}/repo/` |
| **Outputs** | `/workspace/{task_id}/arch.md` — architecture document, interface contracts, migration plan, identified technical risks |
| **Key behaviour** | Always reads existing code before designing. Identifies patterns in the existing system and respects them. Flags breaking changes. |

**arch.md must include:**
- Component overview (what changes, what is new)
- Interface contracts (function signatures, API schemas, DB schema changes)
- Migration plan (if DB or API changes)
- Technical risks with mitigations
- Mermaid diagram (component or sequence)

### 2.4 Implementation Planner

| Field | Value |
|---|---|
| **Role** | Translates the architecture into an ordered task graph assignable to agents. |
| **Tools** | File read/write, DAG serializer |
| **Inputs** | `arch.md`, `spec.json`, list of available agent types |
| **Outputs** | `/workspace/{task_id}/plan.json` — task DAG with assignments, dependencies, effort estimates |

**plan.json schema:**
```json
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
```

### 2.5 Coder

| Field | Value |
|---|---|
| **Role** | Writes production-quality source code per task assignment. |
| **Tools** | File read, file write, bash executor (sandboxed to workspace), git (add/commit/diff), linter (pylint/eslint/ruff) |
| **Inputs** | Single task from `plan.json`, `arch.md`, `spec.json`, existing source files |
| **Outputs** | Source files, git commits, `/workspace/{task_id}/changes.json` (manifest of changed files per task) |
| **Key behaviour** | Always reads a file before modifying it. Commits after each task. Runs linter before signalling completion. If it hits a design blocker, emits escalation — does not guess. |

### 2.6 Code Reviewer

| Field | Value |
|---|---|
| **Role** | Automated quality and security gate before testing begins. |
| **Tools** | Static analyser (pylint/ruff for Python, eslint for JS), security scanner (bandit for Python, semgrep), diff reader, complexity metrics |
| **Inputs** | Changed files (from `changes.json`), `arch.md`, coding standards config |
| **Outputs** | `/workspace/{task_id}/review.json` — per-issue list with severity (critical/major/minor), pass/block decision |
| **Key behaviour** | Blocks pipeline on any `critical` issue. Passes with `major`/`minor` issues listed for coder awareness. Critical issues are routed back to Coder with the review report as context. |

**review.json schema:**
```json
{
  "decision": "pass | block",
  "issues": [
    { "file": "src/foo.py", "line": 42, "severity": "critical | major | minor", "rule": "string", "message": "string" }
  ]
}
```

### 2.7 Test Engineer

| Field | Value |
|---|---|
| **Role** | Authors and runs unit tests and integration tests based on acceptance criteria. |
| **Tools** | File read/write, test runner (pytest / jest), coverage tool, mock generator, bash executor |
| **Inputs** | `spec.json` (acceptance criteria), source files, `arch.md` (interface contracts) |
| **Outputs** | Test files in `/workspace/{task_id}/tests/`, `/workspace/{task_id}/test_report.json` |
| **Key behaviour** | Each acceptance criterion maps to at least one test. Coverage threshold: 80% lines minimum. Failing tests are passed to Debugger — Tester does not fix code. |

**test_report.json schema:**
```json
{
  "run_id": "string",
  "passed": 12,
  "failed": 3,
  "coverage_pct": 84.2,
  "threshold_met": true,
  "failures": [
    { "test": "test_foo.py::test_bar", "error": "AssertionError: ...", "traceback": "string" }
  ]
}
```

### 2.8 Debugger

| Field | Value |
|---|---|
| **Role** | Receives failing test output, performs root cause analysis, applies fixes, re-runs tests. |
| **Tools** | File read/write, bash executor, test runner, log analyser |
| **Inputs** | `test_report.json` (failures + tracebacks), source files |
| **Outputs** | Fixed source files, `/workspace/{task_id}/debug_log.json` (per-fix summary) |
| **Key behaviour** | Attempts up to 5 fix iterations autonomously. If still failing after 5 attempts, escalates to Orchestrator which routes back to Coder (with full debug log as context). Never modifies tests to make them pass — only modifies source. |

### 2.9 Deployer

| Field | Value |
|---|---|
| **Role** | Builds, migrates, and deploys the service. Runs smoke tests post-deploy. |
| **Tools** | Bash/shell, Docker CLI, systemd manager (systemctl), env file manager, health check runner |
| **Inputs** | Build spec, env config, migration scripts from workspace, smoke test suite |
| **Outputs** | Running service, `/workspace/{task_id}/deploy_log.json`, health check results, rollback plan |
| **Key behaviour** | Smoke test failure triggers automatic rollback followed by an escalation to the operator. |

### 2.10 Doc Writer

| Field | Value |
|---|---|
| **Role** | Generates and keeps documentation in sync with the code. Runs in parallel with Coder tasks. |
| **Tools** | File read/write, git log reader, OpenAPI spec generator |
| **Inputs** | Source files, `arch.md`, `changes.json`, git log |
| **Outputs** | `README.md`, `CHANGELOG.md`, inline docstrings, OpenAPI spec (if applicable) |
| **Key behaviour** | Runs concurrently with Coder wherever the task DAG permits. Updates docs in the same git commit as the code changes it documents. |

---

## 3. Pipeline Architecture

### 3.1 Phase State Machine

```
INTAKE → ANALYSIS → [GATE: spec approval] → ARCHITECTURE → [GATE: arch approval]
  → PLANNING → BUILD → REVIEW → TEST_LOOP → [GATE: deploy sign-off] → DEPLOY → DONE
```

Each phase is a row in the `tasks` table with `status = pending | running | done | failed`.

### 3.2 Phase Details

| Phase | Agent(s) | Completion Signal | Next Phase |
|---|---|---|---|
| INTAKE | Gateway | Task written to DB | ANALYSIS |
| ANALYSIS | Requirements Analyst | `spec.json` written | GATE (spec) |
| ARCHITECTURE | Architect | `arch.md` written | GATE (arch) |
| PLANNING | Planner | `plan.json` written | BUILD |
| BUILD | Coder + Doc Writer (parallel) | All plan tasks done, lint passes | REVIEW |
| REVIEW | Code Reviewer | `review.json` written, decision=pass | TEST_LOOP |
| TEST_LOOP | Tester → Debugger (loop) | `test_report.json`, threshold_met=true | GATE (deploy) |
| DEPLOY | Deployer | Smoke tests pass | DONE |

### 3.3 Orchestrator State Machine (pseudocode)

```python
while True:
    task = queue.pop_next_pending()
    match task.phase:
        case "INTAKE":
            spawn(RequirementsAnalyst, task)
        case "ANALYSIS_DONE":
            create_gate(task, type="spec_approval", artifact="spec.json")
            task.phase = "AWAITING_SPEC_GATE"
        case "ARCHITECTURE_DONE":
            create_gate(task, type="arch_approval", artifact="arch.md")
            task.phase = "AWAITING_ARCH_GATE"
        case "GATE_APPROVED":
            advance_to_next_phase(task)
        case "GATE_REJECTED":
            inject_feedback_and_respawn(task)  # back to producing agent
        case "REVIEW_BLOCK":
            inject_review_and_respawn(task, agent="coder")
        case "TEST_FAIL":
            if task.debug_attempts < 5:
                spawn(Debugger, task)
            else:
                spawn(Coder, task, context=debug_log)  # escalate to coder
        case "ESCALATION":
            create_gate(task, type="escalation", question=agent_question)
        case "ESCALATION_ANSWERED":
            resume_waiting_agent(task, answer=gate.answer)
        case "DEPLOY_DONE":
            task.status = "DONE"
```

---

## 4. Communication Channel (Gateway)

### 4.1 Architecture

```
┌─────────────────────────────────────┐
│           OPERATOR                  │
│  ┌──────────────┐  ┌─────────────┐  │
│  │  Web UI      │  │  crew CLI   │  │
│  │  :8080       │  │  (Python)   │  │
│  └──────┬───────┘  └──────┬──────┘  │
└─────────┼─────────────────┼─────────┘
          │   REST API + SSE│
          ▼                 ▼
┌─────────────────────────────────────┐
│        GATEWAY SERVICE              │
│        FastAPI · :8080              │
│  ┌────────────┐  ┌───────────────┐  │
│  │ REST API   │  │ SSE Emitter   │  │
│  ├────────────┤  ├───────────────┤  │
│  │ Gate       │  │ Notification  │  │
│  │ Manager    │  │ Listener      │  │
│  └────────────┘  └───────────────┘  │
│  ┌──────────────────────────────┐   │
│  │ SQLite: tasks · human_gates  │   │
│  │         audit_log            │   │
│  └──────────────────────────────┘   │
└──────────────┬──────────────────────┘
               │  task queue / gate events
               ▼
┌──────────────────────────────────────┐
│          ORCHESTRATOR                │
│          + Agent Processes           │
└──────────────────────────────────────┘
```

### 4.2 Web UI Views

| View | Purpose |
|---|---|
| **Dashboard** | Active tasks, phase/status, pending gate count, system health bar |
| **Submit** | Markdown textarea, optional title, file attachments, Submit button → returns Task ID |
| **Approvals Inbox** | All pending gates, sorted oldest-first. Click → Gate Detail: rendered artifact + Approve/Reject/Answer controls |
| **Task Detail** | Phase timeline, live agent log (SSE), artifact download list, gate history |
| **History** | Completed/failed tasks with duration and outcome |

### 4.3 CLI (`crew`) Commands

```bash
# Submit
crew submit [text]                # inline or prompts multi-line
crew submit --file spec.md        # from file
cat spec.md | crew submit         # from stdin

# Monitor
crew status                       # list all active tasks
crew status <task-id>             # phase timeline + last agent action
crew log <task-id>                # tail live SSE agent log (Ctrl+C to stop)
crew history                      # completed tasks

# Gates
crew gates                        # list all pending gates
crew approve <task-id>            # approve pending gate
crew approve <task-id> --comment "looks good"
crew reject <task-id> --reason "scope too broad"
crew answer <task-id>             # opens $EDITOR; save+quit to submit answer
crew answer <task-id> --message "use PostgreSQL not SQLite"

# Artifacts
crew artifact <task-id> spec.json
crew artifact <task-id> arch.md
crew artifact <task-id> review.json
crew artifact <task-id> test_report.json
```

CLI config at `~/.crew/config.yaml`:
```yaml
gateway_url: http://localhost:8080
token: <bearer-token>
default_editor: vim
poll_interval: 3
```

---

## 5. Data Model

### 5.1 SQLite Schema

```sql
-- Core task tracking
CREATE TABLE tasks (
    id          TEXT PRIMARY KEY,          -- e.g. "t-0042"
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,             -- raw requirement
    phase       TEXT NOT NULL,             -- INTAKE | ANALYSIS | ARCHITECTURE | ...
    status      TEXT NOT NULL,             -- pending | running | done | failed
    agent       TEXT,                      -- currently active agent
    created_at  INTEGER NOT NULL,          -- unix timestamp
    updated_at  INTEGER NOT NULL,
    debug_attempts INTEGER DEFAULT 0
);

-- Human approval gates
CREATE TABLE human_gates (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    type        TEXT NOT NULL,             -- spec_approval | arch_approval | deploy_signoff | escalation
    status      TEXT NOT NULL,             -- pending | approved | rejected | answered
    artifact    TEXT,                      -- path to artifact file shown to operator
    question    TEXT,                      -- for escalation type
    answer      TEXT,                      -- operator's free-text answer
    comment     TEXT,                      -- approval comment
    reason      TEXT,                      -- rejection reason
    operator    TEXT,                      -- who acted
    created_at  INTEGER NOT NULL,
    resolved_at INTEGER
);

-- Append-only audit trail
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    task_id     TEXT,
    agent       TEXT,
    action      TEXT NOT NULL,             -- task:created | gate:created | gate:approved | ...
    detail      TEXT                       -- JSON blob with context
);

-- Artifact registry
CREATE TABLE artifacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    name        TEXT NOT NULL,             -- spec.json | arch.md | review.json | ...
    path        TEXT NOT NULL,             -- absolute filesystem path
    created_at  INTEGER NOT NULL
);

-- Notification bus (polling or Redis channel)
CREATE TABLE notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    event       TEXT NOT NULL,             -- gate:pending | phase:change | task:done
    payload     TEXT,                      -- JSON
    created_at  INTEGER NOT NULL,
    consumed    INTEGER DEFAULT 0
);
```

### 5.2 Workspace File Structure Per Task

```
/workspace/{task_id}/
├── repo/                   # git clone of target codebase
├── spec.json               # output: Requirements Analyst
├── arch.md                 # output: Architect
├── plan.json               # output: Planner
├── changes.json            # output: Coder (per build task)
├── review.json             # output: Code Reviewer
├── test_report.json        # output: Test Engineer / Debugger
├── debug_log.json          # output: Debugger
├── deploy_log.json         # output: Deployer
├── context.json            # running context window: escalation Q&A history
├── src/                    # working copy of modified/new source files
└── tests/                  # generated test files
```

---

## 6. File System Layout

```
/opt/crew/
├── gateway/
│   ├── app.py              # FastAPI application
│   ├── static/             # React build (Web UI)
│   └── requirements.txt
├── agents/
│   ├── orchestrator.py
│   ├── analyst.py
│   ├── architect.py
│   ├── planner.py
│   ├── coder.py
│   ├── reviewer.py
│   ├── tester.py
│   ├── debugger.py
│   ├── deployer.py
│   ├── docwriter.py
│   ├── base.py             # BaseAgent class: LLM client, tool dispatch, escalation
│   └── tools/
│       ├── files.py        # read_file, write_file, list_files
│       ├── shell.py        # run_bash (sandboxed to /workspace/{task_id}/)
│       ├── git.py          # commit, diff, log
│       └── search.py       # code search, RAG query
├── workspace/              # per-task working directories
├── db/
│   ├── tasks.db            # main SQLite database
│   └── audit.db            # audit log (separate for append-only enforcement)
├── logs/                   # structured JSON logs, one file per agent per task
├── chroma/                 # vector DB for codebase RAG
└── config.yaml             # API keys, tool paths, gate config, thresholds
```

**config.yaml schema:**
```yaml
anthropic_api_key: sk-ant-...
gateway:
  host: 127.0.0.1
  port: 8080
  token: <bearer-token>
workspace_root: /opt/crew/workspace
repo_root: /path/to/target/codebase
model: claude-sonnet-4-20250514
coverage_threshold: 80
max_debug_attempts: 5
tools:
  linter: ruff          # or pylint, eslint
  test_runner: pytest   # or jest
  security_scanner: bandit
```

---

## 7. Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.12 (agents + gateway) |
| **Agent runtime** | asyncio · each agent = independent OS process |
| **LLM** | Claude claude-sonnet-4 via Anthropic API (`claude-sonnet-4-20250514`) |
| **Web framework** | FastAPI + uvicorn |
| **Web UI** | React (single-page, served by Gateway) |
| **State store** | SQLite (tasks.db) |
| **Message bus** | SQLite notifications table (simple) or Redis pub/sub (scalable) |
| **Codebase RAG** | Chroma vector DB + `nomic-embed-text` embeddings |
| **Code analysis** | ruff / pylint / eslint, bandit / semgrep |
| **Test runners** | pytest (Python), jest (JS/TS) |
| **Version control** | GitPython (programmatic git operations) |
| **Containerisation** | Docker (optional per-agent sandboxing) |
| **Process manager** | systemd |
| **Real-time push** | Server-Sent Events (SSE) from FastAPI to Web UI |

### Framework Recommendation

**Build a custom orchestrator** — do not use CrewAI or AutoGen. Reasons:
- The test→debug→re-test feedback loop requires precise state control that off-the-shelf frameworks make difficult.
- SQLite state machine is inspectable, restartable after crash, and produces a clean audit trail.
- LangGraph is acceptable as an optional overlay for visualising the state graph but is not required.

---

## 8. Human-in-Loop Gates

### Gate Types

| Gate | Trigger | Artifact shown | Operator action |
|---|---|---|---|
| `spec_approval` | Analyst writes `spec.json` | Rendered spec + user stories + acceptance criteria | **Approve** → advance to Architect. **Reject** + comment → Analyst revises. |
| `arch_approval` | Architect writes `arch.md` | Architecture doc + interface contracts + risk list | **Approve** → Planner starts. **Reject** + comment → Architect revises. |
| `escalation` | Any agent cannot proceed | Agent's question + context excerpt + optional choices | **Answer** (free text) → injected into agent context. Agent resumes. |
| `deploy_signoff` | Tests green, review passed | Coverage report + review summary + deploy plan + rollback plan | **Approve** → Deployer runs. **Reject** → stays pre-deploy. |

### Rejection Behaviour

Rejecting a gate does **not** restart the pipeline from scratch. The flow is:
1. Orchestrator reads the rejection reason from `human_gates`.
2. Orchestrator injects the reason as a User message into the producing agent's context.
3. Orchestrator re-spawns that agent (phase reverts to that agent's phase).
4. Agent produces revised output, writes updated artifact, signals completion.
5. Orchestrator creates a **new gate** (previous gate row preserved in history).
6. Operator reviews again.

### Escalation Behaviour

1. Agent emits a structured escalation object:
   ```json
   { "type": "escalation", "question": "string", "context": "string", "options": ["opt1", "opt2"] }
   ```
2. Orchestrator creates `escalation` gate row.
3. Operator answers in free text via Web UI or `crew answer`.
4. Gateway appends `{ "role": "user", "content": answer }` to `/workspace/{task_id}/context.json`.
5. Orchestrator resumes the waiting agent with the updated context.
6. If agent escalates again → new gate (chain preserved).

---

## 9. Gateway REST API

Base URL: `http://localhost:8080`
Auth: `Authorization: Bearer <token>` on all endpoints.

| Method | Endpoint | Request | Response |
|---|---|---|---|
| `POST` | `/tasks` | `{ title?, body, attachments[]? }` | `{ task_id }` |
| `GET` | `/tasks` | `?status=running\|pending\|done` | `[ task... ]` |
| `GET` | `/tasks/{id}` | — | Full task detail with phase history, artifacts, gates |
| `GET` | `/tasks/{id}/artifacts/{name}` | — | File download |
| `GET` | `/gates` | `?status=pending` | `[ gate... ]` |
| `POST` | `/gates/{id}/approve` | `{ comment? }` | `{ ok }` |
| `POST` | `/gates/{id}/reject` | `{ reason }` | `{ ok }` |
| `POST` | `/gates/{id}/answer` | `{ message }` | `{ ok }` |
| `GET` | `/stream/{task_id}` | — | SSE stream (text/event-stream) |
| `GET` | `/health` | — | `{ status, gateway, orchestrator, llm_api }` |

### SSE Event Types

```
event: phase:change   data: { task_id, phase, timestamp }
event: agent:log      data: { task_id, agent, line }
event: gate:pending   data: { task_id, gate_id, type }
event: task:done      data: { task_id, outcome, duration_s }
event: task:failed    data: { task_id, reason }
```

---

## 10. CLI Reference

See Section 4.3 for full command list. Key patterns:

```bash
# Typical approval workflow
crew gates                              # see what's waiting
crew artifact t-0042 spec.json          # read the artifact
crew approve t-0042                     # or: crew reject t-0042 --reason "..."

# Watching a task run live
crew submit --file my-feature.md        # submit, get task ID back
crew log t-0042                         # tail output in real time
```

---

## 11. Agent Context Model

Every agent is invoked with a context window assembled from:

| Layer | Content | Size |
|---|---|---|
| **System prompt** | Role, available tools, output format contract, chain-of-thought instructions | Fixed ~2K tokens |
| **Task context** | spec.json, arch.md, relevant plan task, prior agent outputs | Injected per invocation |
| **RAG results** | Top-k semantically relevant code chunks from Chroma | Dynamic, ~4K tokens |
| **Tool results** | Bash output, file contents, linter output fed back mid-turn | Dynamic |
| **Escalation history** | Prior Q&A pairs from context.json | Injected if present |
| **History summary** | For long tasks: compressed summary of previous turns | When context > 80% |

### BaseAgent Class Interface

```python
class BaseAgent:
    def __init__(self, task_id: str, config: Config): ...
    
    async def run(self, task: dict) -> AgentResult: ...
    
    def read_file(self, path: str) -> str: ...
    def write_file(self, path: str, content: str) -> None: ...
    def run_bash(self, cmd: str) -> tuple[str, str, int]: ...  # stdout, stderr, returncode
    def search_code(self, query: str) -> list[CodeChunk]: ...
    def emit_escalation(self, question: str, context: str, options: list[str] = None): ...
    def call_llm(self, messages: list[dict], tools: list[dict] = None) -> str: ...
```

### System Prompt Template (per agent)

```
You are the {ROLE} in an autonomous software development pipeline.

Your task: {TASK_DESCRIPTION}

Workspace: /workspace/{TASK_ID}/
You may only read/write files within this directory.

Input artifacts available:
{ARTIFACT_LIST}

Output contract:
- You MUST write {OUTPUT_FILE} before signalling completion.
- {OUTPUT_FILE} must conform to this schema: {SCHEMA}

Available tools:
- read_file(path) — read a file from the workspace
- write_file(path, content) — write a file to the workspace
- run_bash(cmd) — execute a shell command (sandboxed to workspace)
- search_code(query) — semantic search over the codebase
- emit_escalation(question, context) — block and ask the operator a question

Rules:
1. Always read existing files before modifying them.
2. If you are uncertain about a requirement or face a blocker, use emit_escalation.
3. Do not guess — emit_escalation is the correct tool for ambiguity.
4. Think step by step. Show your reasoning before taking actions.
5. Signal completion ONLY after writing the required output file.
```

---

## 12. Feedback Loops

### All Feedback Paths

| Loop | Trigger | Routing |
|---|---|---|
| **Review → Coder** | `review.json` has `decision: block` | Orchestrator injects review issues into Coder context, re-runs Coder on failed tasks only |
| **Test fail → Debugger** | `test_report.json` has `threshold_met: false` | Orchestrator spawns Debugger with failing test details |
| **Debugger → Coder** | `debug_attempts >= max_debug_attempts` | Orchestrator routes back to Coder with full `debug_log.json` as context |
| **Coder → Architect** | Coder emits escalation about architectural blocker | Escalation gate → operator answers OR Orchestrator routes to Architect for design revision |
| **Gate rejection → Producer** | Operator rejects spec/arch gate | Rejection reason injected into Analyst/Architect context, agent re-runs |
| **Smoke fail → Rollback** | Deployer smoke test fails | Deployer auto-rolls back, emits escalation to operator |

### Test-Debug Loop (detail)

```
Tester runs tests
    │
    ├─ all pass + coverage ≥ threshold → advance to deploy gate
    │
    └─ failures detected
           │
           ▼
       Debugger
           │
           ├─ fix + re-run tests → loop back to Tester eval
           │
           └─ attempts >= max_debug_attempts
                  │
                  ▼
              Back to Coder (full debug_log as context)
                  │
                  └─ Coder rewrites → back to Review → back to Test loop
```

---

## 13. Deployment (systemd)

### Unit Files

**`/etc/systemd/system/crew-gateway.service`**
```ini
[Unit]
Description=AI Dev Crew Gateway Service
After=network.target

[Service]
Type=simple
User=crew
WorkingDirectory=/opt/crew/gateway
ExecStart=/opt/crew/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8080
Restart=on-failure
RestartSec=5
EnvironmentFile=/opt/crew/config.env

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/crew-orchestrator.service`**
```ini
[Unit]
Description=AI Dev Crew Orchestrator
After=crew-gateway.service
Requires=crew-gateway.service

[Service]
Type=simple
User=crew
WorkingDirectory=/opt/crew
ExecStart=/opt/crew/venv/bin/python agents/orchestrator.py
Restart=on-failure
RestartSec=5
EnvironmentFile=/opt/crew/config.env

[Install]
WantedBy=multi-user.target
```

### Start / Stop

```bash
sudo systemctl enable crew-gateway crew-orchestrator
sudo systemctl start crew-gateway crew-orchestrator
sudo systemctl status crew-gateway
sudo journalctl -u crew-orchestrator -f
```

### Security Hardening

- Gateway binds to `127.0.0.1` only — not externally reachable.
- All agent bash execution is sandboxed to `/opt/crew/workspace/{task_id}/` — the shell tool must reject any path outside this prefix.
- `config.yaml` (contains API key): `chmod 600 /opt/crew/config.yaml; chown crew:crew /opt/crew/config.yaml`
- SQLite audit_log: the `crew` OS user has INSERT but not DELETE/UPDATE on `audit_log` table (enforce via application layer or separate DB user).
- LLM API key never written to workspace or logs.

---

## 14. Build Order (Phased)

Build in this order to get value at each phase:

### Phase 1 — Working Core Loop (implement first)
1. SQLite schema + migration script
2. `/opt/crew` directory layout + config.yaml loader
3. `BaseAgent` class (LLM call, tool dispatch, file read/write, bash sandbox, escalation emit)
4. **Orchestrator** — state machine (INTAKE → BUILD → TEST_LOOP only for now)
5. **Coder agent** — reads task, writes files, commits, runs linter
6. **Test Engineer agent** — runs pytest, writes test_report.json
7. **Debugger agent** — reads failures, fixes source, re-runs
8. **Gateway** — `POST /tasks`, `GET /tasks`, `GET /gates`, `POST /gates/{id}/approve`
9. **`crew` CLI** — `submit`, `status`, `gates`, `approve`

**Milestone:** Submit a coding task, crew writes code, tests it, debugs, completes.

### Phase 2 — Full Pipeline
10. **Requirements Analyst** agent
11. **Architect** agent + Chroma RAG setup
12. **Planner** agent
13. **Code Reviewer** agent (ruff + bandit)
14. Full gate flow: spec_approval → arch_approval gates
15. SSE stream (`GET /stream/{task_id}`) + Web UI Dashboard + Approvals inbox

**Milestone:** Submit a requirement in English, get a fully reviewed and tested implementation.

### Phase 3 — Production Quality
16. **Deployer** agent (Docker/systemd)
17. **Doc Writer** agent (parallel with Coder)
18. Deploy sign-off gate
19. Web UI: Submit view, Task Detail, History
20. Structured JSON logging per agent per task
21. Notification bus (upgrade from SQLite polling to Redis if needed)

**Milestone:** Full end-to-end: requirement → deployed service.

### Phase 4 — Hardening
22. Retry + circuit-breaker per agent (max retries, backoff)
23. Cost tracking (token counts per task, logged to audit_log)
24. Context window management (summarisation for long tasks)
25. Docker sandboxing per agent process
26. Async parallel execution where plan DAG permits (Doc Writer + Coder)
27. `crew history` + search
28. Health dashboard in Web UI

---

## 15. Security Constraints

| Constraint | Implementation |
|---|---|
| **No external network from agents** | Shell sandbox rejects outbound connections; agents use tools only |
| **Workspace isolation** | `run_bash` tool prepends `cd /workspace/{task_id} &&` and rejects `../` in paths |
| **API key protection** | Key read from env var / config.yaml; never written to workspace or logged |
| **Gateway auth** | Bearer token required on all endpoints; token set in config.yaml |
| **Audit immutability** | Audit log table: no DELETE, no UPDATE; INSERT only |
| **localhost only** | Gateway bound to 127.0.0.1; not reachable from LAN |
| **OS user** | All services run as dedicated `crew` user, not root |

---

## Appendix A — Agent Output Contract Summary

| Agent | Must write before completion |
|---|---|
| Requirements Analyst | `/workspace/{task_id}/spec.json` |
| Architect | `/workspace/{task_id}/arch.md` |
| Planner | `/workspace/{task_id}/plan.json` |
| Coder | Source files + `/workspace/{task_id}/changes.json` + git commit |
| Code Reviewer | `/workspace/{task_id}/review.json` |
| Test Engineer | Test files + `/workspace/{task_id}/test_report.json` |
| Debugger | Fixed source files + `/workspace/{task_id}/debug_log.json` |
| Deployer | `/workspace/{task_id}/deploy_log.json` |
| Doc Writer | Inline docs + `README.md` / `CHANGELOG.md` updates |

---

## Appendix B — Quick Reference: Operator Workflow

| I want to… | Command |
|---|---|
| Submit a requirement | `crew submit --file spec.md` |
| Check what's running | `crew status` |
| See what needs approval | `crew gates` |
| Read the spec before approving | `crew artifact t-XXXX spec.json` |
| Approve the spec | `crew approve t-XXXX` |
| Reject with feedback | `crew reject t-XXXX --reason "..."` |
| Answer an agent question | `crew answer t-XXXX` |
| Watch live agent output | `crew log t-XXXX` |
| Approve production deploy | `crew approve t-XXXX --comment "ship it"` |
| Check system health | `curl localhost:8080/health` |

---

*End of implementation brief. Start with Phase 1 items in Section 14.*

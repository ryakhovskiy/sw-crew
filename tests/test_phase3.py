"""Tests for Phase 3 components: Deployer, DocWriter, logging, notifications, SSE."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from crew.agents.deployer import DeployerAgent
from crew.agents.docwriter import DocWriterAgent
from crew.config import Config, GatewayConfig
from crew.db.migrate import run_migrations
from crew.db.store import TaskStore
from crew.gateway.routes import gates, health, stream, tasks
from crew.logging import JSONLineFormatter, TaskFileHandler, get_agent_logger
from crew.notifications import SQLiteNotificationBus, create_notification_bus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        anthropic_api_key="test-key",
        gateway=GatewayConfig(token="test-token"),
        workspace_root=tmp_path / "workspace",
        db_path=tmp_path / "db" / "test.db",
        model="claude-sonnet-4-20250514",
    )


@pytest.fixture
def store(config: Config) -> TaskStore:
    config.ensure_dirs()
    run_migrations(config.db_path)
    s = TaskStore(config.db_path)
    s.connect()
    yield s
    s.close()


@pytest.fixture
def task_id(store: TaskStore) -> str:
    return store.create_task("Test Task", "Build a widget")


# ---------------------------------------------------------------------------
# Deployer Agent
# ---------------------------------------------------------------------------

class TestDeployerAgent:
    def test_agent_name(self, config, store, task_id):
        agent = DeployerAgent(task_id, config, store)
        assert agent.agent_name == "deployer"

    def test_output_file(self, config, store, task_id):
        agent = DeployerAgent(task_id, config, store)
        assert agent.get_output_file() == "deploy_log.json"

    def test_system_prompt(self, config, store, task_id):
        agent = DeployerAgent(task_id, config, store)
        prompt = agent.build_system_prompt()
        assert "Deployer" in prompt
        assert "smoke" in prompt.lower()
        assert "rollback" in prompt.lower()
        assert "deploy_log.json" in prompt

    def test_tools_restricted(self, config, store, task_id):
        agent = DeployerAgent(task_id, config, store)
        tool_names = {t["name"] for t in agent.get_tools()}
        assert "run_bash" in tool_names
        assert "read_file" in tool_names
        assert "emit_escalation" in tool_names
        # Deployer should NOT have git or search tools
        assert "git_commit" not in tool_names
        assert "search_code" not in tool_names

    def test_initial_messages(self, config, store, task_id):
        agent = DeployerAgent(task_id, config, store)
        task_dict = {"id": task_id, "body": "Deploy the service", "title": "Deploy"}
        messages = agent.build_initial_messages(task_dict)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Deployment Task" in messages[0]["content"]
        assert "Deploy the service" in messages[0]["content"]

    def test_initial_messages_with_artifacts(self, config, store, task_id):
        agent = DeployerAgent(task_id, config, store)
        ws = config.workspace_root / task_id
        ws.mkdir(parents=True, exist_ok=True)
        # Create test report
        (ws / "test_report.json").write_text(
            json.dumps({"passed": 10, "failed": 0, "coverage_pct": 92.5}),
            encoding="utf-8",
        )
        # Create review
        (ws / "review.json").write_text(
            json.dumps({"decision": "pass"}), encoding="utf-8"
        )
        task_dict = {"id": task_id, "body": "Deploy it", "title": "Deploy"}
        messages = agent.build_initial_messages(task_dict)
        content = messages[0]["content"]
        assert "Passed: 10" in content
        assert "Coverage: 92.5%" in content
        assert "Decision: pass" in content


# ---------------------------------------------------------------------------
# DocWriter Agent
# ---------------------------------------------------------------------------

class TestDocWriterAgent:
    def test_agent_name(self, config, store, task_id):
        agent = DocWriterAgent(task_id, config, store)
        assert agent.agent_name == "docwriter"

    def test_output_file_is_none(self, config, store, task_id):
        agent = DocWriterAgent(task_id, config, store)
        assert agent.get_output_file() is None

    def test_system_prompt(self, config, store, task_id):
        agent = DocWriterAgent(task_id, config, store)
        prompt = agent.build_system_prompt()
        assert "Doc Writer" in prompt
        assert "README.md" in prompt
        assert "CHANGELOG.md" in prompt
        assert "NEVER modify source code" in prompt

    def test_tools_restricted(self, config, store, task_id):
        agent = DocWriterAgent(task_id, config, store)
        tool_names = {t["name"] for t in agent.get_tools()}
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "git_commit" in tool_names
        assert "search_code" in tool_names
        # DocWriter should NOT have run_bash
        assert "run_bash" not in tool_names

    def test_initial_messages(self, config, store, task_id):
        agent = DocWriterAgent(task_id, config, store)
        task_dict = {"id": task_id, "body": "Build a widget", "title": "Widget"}
        messages = agent.build_initial_messages(task_dict)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Documentation Task" in messages[0]["content"]

    def test_initial_messages_with_changes(self, config, store, task_id):
        agent = DocWriterAgent(task_id, config, store)
        ws = config.workspace_root / task_id
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "changes.json").write_text(
            json.dumps({"files_created": ["src/widget.py"], "summary": "Added widget"}),
            encoding="utf-8",
        )
        task_dict = {"id": task_id, "body": "Build widget", "title": "Widget"}
        messages = agent.build_initial_messages(task_dict)
        content = messages[0]["content"]
        assert "Changes Made" in content
        assert "widget.py" in content


# ---------------------------------------------------------------------------
# Structured JSON Logging
# ---------------------------------------------------------------------------

class TestLogging:
    def test_json_formatter(self):
        import logging
        formatter = JSONLineFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        result = formatter.format(record)
        data = json.loads(result)
        assert data["message"] == "hello"
        assert data["level"] == "INFO"
        assert "timestamp" in data

    def test_json_formatter_with_extras(self):
        import logging
        formatter = JSONLineFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="tool call", args=(), exc_info=None,
        )
        record.task_id = "t-123"
        record.agent = "coder"
        record.tool = "read_file"
        result = formatter.format(record)
        data = json.loads(result)
        assert data["task_id"] == "t-123"
        assert data["agent"] == "coder"
        assert data["tool"] == "read_file"

    def test_task_file_handler(self, tmp_path: Path):
        handler = TaskFileHandler(tmp_path / "logs", "t-abc", "coder")
        assert (tmp_path / "logs" / "t-abc").is_dir()
        handler.close()

    def test_get_agent_logger(self, tmp_path: Path):
        log = get_agent_logger(tmp_path / "logs", "t-test", "tester")
        assert log.name == "crew.agents.tester.t-test"
        log.info("test message")
        # Verify log file was created
        log_file = tmp_path / "logs" / "t-test" / "tester.jsonl"
        assert log_file.exists()
        line = log_file.read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert data["message"] == "test message"

    def test_no_duplicate_handlers(self, tmp_path: Path):
        log1 = get_agent_logger(tmp_path / "logs", "t-dup", "coder")
        log2 = get_agent_logger(tmp_path / "logs", "t-dup", "coder")
        assert log1 is log2
        assert len(log1.handlers) == 1


# ---------------------------------------------------------------------------
# Notification Bus
# ---------------------------------------------------------------------------

class TestNotificationBus:
    def test_create_sqlite_bus(self, store):
        bus = create_notification_bus("sqlite", store=store)
        assert isinstance(bus, SQLiteNotificationBus)

    def test_create_unknown_bus(self):
        with pytest.raises(ValueError, match="Unknown notification bus"):
            create_notification_bus("kafka")

    def test_create_sqlite_bus_no_store(self):
        with pytest.raises(ValueError, match="requires a TaskStore"):
            create_notification_bus("sqlite")

    @pytest.mark.asyncio
    async def test_publish(self, store, task_id):
        bus = SQLiteNotificationBus(store)
        await bus.publish(task_id, "phase:change", {"phase": "BUILD"})
        notifications = store.get_unconsumed_notifications(task_id)
        assert len(notifications) == 1
        # Note: store.create_task already pushes a gate:pending notification sometimes
        # but our fixture only calls create_task, so we should have just the one we published

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self, store, task_id):
        bus = SQLiteNotificationBus(store)
        await bus.publish(task_id, "task:done", {"outcome": "success"})

        events = []
        async for event in bus.subscribe(task_id, poll_interval=0.1):
            events.append(event)
            break  # Stop after first event

        assert len(events) == 1
        assert events[0].event == "task:done"
        assert events[0].payload["outcome"] == "success"


# ---------------------------------------------------------------------------
# Store: get_unconsumed_notifications
# ---------------------------------------------------------------------------

class TestStoreNotifications:
    def test_get_unconsumed_notifications(self, store, task_id):
        store.push_notification(task_id, "phase:change", {"phase": "BUILD"})
        store.push_notification(task_id, "task:done", {"outcome": "ok"})
        store.push_notification("other-task", "phase:change", {"phase": "X"})

        notifications = store.get_unconsumed_notifications(task_id)
        assert len(notifications) == 2
        assert all(n.task_id == task_id for n in notifications)

    def test_get_unconsumed_since_id(self, store, task_id):
        store.push_notification(task_id, "event1", {"a": 1})
        store.push_notification(task_id, "event2", {"a": 2})

        first_batch = store.get_unconsumed_notifications(task_id)
        assert len(first_batch) >= 1
        last_id = first_batch[-1].id

        store.push_notification(task_id, "event3", {"a": 3})
        second_batch = store.get_unconsumed_notifications(task_id, since_id=last_id)
        assert len(second_batch) == 1
        assert second_batch[0].event == "event3"


# ---------------------------------------------------------------------------
# SSE Stream Endpoint
# ---------------------------------------------------------------------------

class TestSSEStream:
    @pytest.fixture
    def app_client(self, tmp_path):
        config = Config(
            anthropic_api_key="test-key",
            gateway=GatewayConfig(token="test-token"),
            workspace_root=tmp_path / "workspace",
            db_path=tmp_path / "db" / "test.db",
        )
        config.ensure_dirs()
        run_migrations(config.db_path)

        s = TaskStore(config.db_path)
        s.connect()

        app = FastAPI()
        app.state.config = config
        app.state.store = s
        app.state.orchestrator = None
        app.state.notification_bus = None
        app.include_router(tasks.router)
        app.include_router(gates.router)
        app.include_router(health.router)
        app.include_router(stream.router)

        client = TestClient(app, raise_server_exceptions=True)
        yield client, s
        s.close()

    def test_stream_endpoint_exists(self, app_client):
        client, store = app_client
        task_id = store.create_task("T", "B")
        # Mark task as done so the stream ends immediately
        store.update_task(task_id, phase="DONE", status="done")
        # Push a notification so there's something to stream
        store.push_notification(task_id, "task:done", {"outcome": "success"})

        headers = {"Authorization": "Bearer test-token"}
        resp = client.get(f"/stream/{task_id}", headers=headers)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Shell Hardening
# ---------------------------------------------------------------------------

class TestShellHardening:
    def test_dotdot_rejected(self, tmp_path: Path):
        from crew.tools.files import PathEscapeError
        from crew.tools.shell import run_bash

        (tmp_path / "ws").mkdir()
        with pytest.raises(PathEscapeError):
            run_bash(tmp_path / "ws", "cd .. && ls")

    def test_dotdot_in_path_rejected(self, tmp_path: Path):
        from crew.tools.files import PathEscapeError
        from crew.tools.shell import run_bash

        (tmp_path / "ws").mkdir()
        with pytest.raises(PathEscapeError):
            run_bash(tmp_path / "ws", "cat ../etc/passwd")

    def test_output_truncation(self, tmp_path: Path):
        from crew.tools.shell import _MAX_OUTPUT_BYTES, run_bash

        ws = tmp_path / "ws"
        ws.mkdir()
        # Generate output larger than the limit
        cmd = f"python -c \"print('x' * {_MAX_OUTPUT_BYTES + 1000})\""
        stdout, _, _ = run_bash(ws, cmd)
        assert len(stdout) <= _MAX_OUTPUT_BYTES + 200  # truncation message overhead
        assert "truncated" in stdout


# ---------------------------------------------------------------------------
# Deploy Gate in Orchestrator
# ---------------------------------------------------------------------------

class TestDeployGate:
    def test_deploy_signoff_gate_created(self, store, task_id):
        """When we create a deploy_signoff gate, it should be pending."""
        gate_id = store.create_gate(
            task_id, gate_type="deploy_signoff",
            artifact="test_report.json",
            question="Tests: 10 passed, 0 failed, coverage 90%",
        )
        gate = store.get_gate(gate_id)
        assert gate.type == "deploy_signoff"
        assert gate.status == "pending"
        assert gate.artifact == "test_report.json"

    def test_deploy_gate_approve(self, store, task_id):
        gate_id = store.create_gate(task_id, gate_type="deploy_signoff")
        store.resolve_gate(gate_id, "approved", comment="Ship it!")
        gate = store.get_gate(gate_id)
        assert gate.status == "approved"
        assert gate.comment == "Ship it!"

    def test_deploy_gate_reject(self, store, task_id):
        gate_id = store.create_gate(task_id, gate_type="deploy_signoff")
        store.resolve_gate(gate_id, "rejected", reason="Not ready")
        gate = store.get_gate(gate_id)
        assert gate.status == "rejected"
        assert gate.reason == "Not ready"

"""Tests for the Gateway API endpoints."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from crew.config import Config, GatewayConfig
from crew.db.migrate import run_migrations
from crew.db.store import TaskStore
from crew.gateway.routes import gates, health, tasks


@pytest.fixture
def app_client(tmp_path):
    """Create a test client with a fresh DB and no lifespan/orchestrator."""
    config = Config(
        anthropic_api_key="test-key",
        gateway=GatewayConfig(token="test-token"),
        workspace_root=tmp_path / "workspace",
        db_path=tmp_path / "db" / "test.db",
    )
    config.ensure_dirs()
    run_migrations(config.db_path)

    store = TaskStore(config.db_path)
    store.connect()

    # Build a minimal app without the lifespan (no orchestrator)
    app = FastAPI()
    app.state.config = config
    app.state.store = store
    app.state.orchestrator = None
    app.include_router(tasks.router)
    app.include_router(gates.router)
    app.include_router(health.router)

    client = TestClient(app, raise_server_exceptions=True)
    yield client, store
    store.close()


HEADERS = {"Authorization": "Bearer test-token"}


class TestAuth:
    def test_no_token(self, app_client):
        client, _ = app_client
        resp = client.get("/tasks")
        assert resp.status_code == 401

    def test_bad_token(self, app_client):
        client, _ = app_client
        resp = client.get("/tasks", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_valid_token(self, app_client):
        client, _ = app_client
        resp = client.get("/tasks", headers=HEADERS)
        assert resp.status_code == 200


class TestTaskRoutes:
    def test_create_task(self, app_client):
        client, _ = app_client
        resp = client.post("/tasks", json={"body": "Build X"}, headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data
        assert data["task_id"].startswith("t-")

    def test_list_tasks(self, app_client):
        client, _ = app_client
        client.post("/tasks", json={"body": "Task 1"}, headers=HEADERS)
        client.post("/tasks", json={"body": "Task 2"}, headers=HEADERS)
        resp = client.get("/tasks", headers=HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_task(self, app_client):
        client, _ = app_client
        create = client.post("/tasks", json={"body": "Hello", "title": "T1"}, headers=HEADERS)
        task_id = create.json()["task_id"]
        resp = client.get(f"/tasks/{task_id}", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "T1"
        assert data["phase"] == "INTAKE"

    def test_get_nonexistent_task(self, app_client):
        client, _ = app_client
        resp = client.get("/tasks/t-nope", headers=HEADERS)
        assert resp.status_code == 404


class TestGateRoutes:
    def test_list_gates_empty(self, app_client):
        client, _ = app_client
        resp = client.get("/gates", params={"status": "pending"}, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_approve_gate(self, app_client):
        client, store = app_client
        task_id = store.create_task("T", "B")
        gate_id = store.create_gate(task_id, "spec_approval")

        resp = client.post(
            f"/gates/{gate_id}/approve",
            json={"comment": "lgtm"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"]

        gate = store.get_gate(gate_id)
        assert gate.status == "approved"

    def test_reject_gate(self, app_client):
        client, store = app_client
        task_id = store.create_task("T", "B")
        gate_id = store.create_gate(task_id, "arch_approval")

        resp = client.post(
            f"/gates/{gate_id}/reject",
            json={"reason": "too broad"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        gate = store.get_gate(gate_id)
        assert gate.status == "rejected"

    def test_answer_gate(self, app_client):
        client, store = app_client
        task_id = store.create_task("T", "B")
        gate_id = store.create_gate(task_id, "escalation", question="Which DB?")

        resp = client.post(
            f"/gates/{gate_id}/answer",
            json={"message": "Use SQLite"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        gate = store.get_gate(gate_id)
        assert gate.status == "answered"
        assert gate.answer == "Use SQLite"

    def test_double_resolve(self, app_client):
        client, store = app_client
        task_id = store.create_task("T", "B")
        gate_id = store.create_gate(task_id, "spec_approval")
        client.post(f"/gates/{gate_id}/approve", json={}, headers=HEADERS)

        resp = client.post(f"/gates/{gate_id}/approve", json={}, headers=HEADERS)
        assert resp.status_code == 400


class TestHealthRoute:
    def test_health(self, app_client):
        client, _ = app_client
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gateway"] is True
        assert data["database"] is True

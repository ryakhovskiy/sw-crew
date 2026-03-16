"""Tests for the DB store layer."""

from __future__ import annotations

from crew.db.store import TaskStore


def test_create_and_get_task(store: TaskStore):
    task_id = store.create_task("Test task", "Build a hello world")
    assert task_id.startswith("t-")

    task = store.get_task(task_id)
    assert task is not None
    assert task.title == "Test task"
    assert task.body == "Build a hello world"
    assert task.phase == "INTAKE"
    assert task.status == "pending"


def test_list_tasks_by_status(store: TaskStore):
    id1 = store.create_task("Task 1", "body1")
    id2 = store.create_task("Task 2", "body2")
    store.update_task(id2, status="running")

    pending = store.list_tasks(status="pending")
    assert len(pending) == 1
    assert pending[0].id == id1

    running = store.list_tasks(status="running")
    assert len(running) == 1
    assert running[0].id == id2


def test_update_task(store: TaskStore):
    task_id = store.create_task("T", "B")
    store.update_task(task_id, phase="BUILD", status="running", agent="coder")
    task = store.get_task(task_id)
    assert task.phase == "BUILD"
    assert task.status == "running"
    assert task.agent == "coder"


def test_gate_lifecycle(store: TaskStore):
    task_id = store.create_task("T", "B")
    gate_id = store.create_gate(task_id, "spec_approval", artifact="spec.json")
    assert gate_id.startswith("g-")

    gate = store.get_gate(gate_id)
    assert gate.status == "pending"
    assert gate.artifact == "spec.json"

    # Approve
    store.resolve_gate(gate_id, "approved", comment="looks good", operator="dev")
    gate = store.get_gate(gate_id)
    assert gate.status == "approved"
    assert gate.comment == "looks good"
    assert gate.resolved_at is not None


def test_gate_rejection(store: TaskStore):
    task_id = store.create_task("T", "B")
    gate_id = store.create_gate(task_id, "arch_approval")
    store.resolve_gate(gate_id, "rejected", reason="too complex")
    gate = store.get_gate(gate_id)
    assert gate.status == "rejected"
    assert gate.reason == "too complex"


def test_escalation_gate(store: TaskStore):
    task_id = store.create_task("T", "B")
    gate_id = store.create_gate(task_id, "escalation", question="Which DB?")
    store.resolve_gate(gate_id, "answered", answer="Use PostgreSQL")
    gate = store.get_gate(gate_id)
    assert gate.status == "answered"
    assert gate.answer == "Use PostgreSQL"


def test_list_pending_gates(store: TaskStore):
    t1 = store.create_task("A", "a")
    t2 = store.create_task("B", "b")
    store.create_gate(t1, "spec_approval")
    store.create_gate(t2, "escalation", question="?")

    pending = store.list_gates(status="pending")
    assert len(pending) == 2


def test_artifacts(store: TaskStore):
    task_id = store.create_task("T", "B")
    store.register_artifact(task_id, "spec.json", "/workspace/t-1/spec.json")
    a = store.get_artifact(task_id, "spec.json")
    assert a is not None
    assert a.name == "spec.json"

    arts = store.list_artifacts(task_id)
    assert len(arts) == 1


def test_notifications(store: TaskStore):
    task_id = store.create_task("T", "B")
    store.push_notification(task_id, "phase:change", {"phase": "BUILD"})

    notes = store.pop_notifications()
    # At least one notification from push_notification
    phase_notes = [n for n in notes if n.event == "phase:change"]
    assert len(phase_notes) >= 1

    # After pop, they should be consumed
    notes2 = store.pop_notifications()
    phase_notes2 = [n for n in notes2 if n.event == "phase:change"]
    assert len(phase_notes2) == 0


def test_audit_log(store: TaskStore):
    task_id = store.create_task("T", "B")
    store.append_audit(task_id, "coder", "agent:completed", {"files": 3})
    # We can't directly list audits via TaskStore, but verify no error
    # The audit was inserted during create_task too (task:created)

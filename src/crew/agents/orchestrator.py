"""Orchestrator — central coordinator and pipeline state machine.

Phase 1 simplified flow:
    INTAKE → BUILD → TEST_LOOP → DONE

Phase 2 adds:
    INTAKE → ANALYSIS → [gate] → ARCHITECTURE → [gate]
    → PLANNING → BUILD → REVIEW → TEST_LOOP → [gate] → DONE
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from crew.agents.base import AgentResult
from crew.agents.coder import CoderAgent
from crew.agents.debugger import DebuggerAgent
from crew.agents.tester import TesterAgent
from crew.config import Config
from crew.db.store import TaskStore

logger = logging.getLogger(__name__)

# Phase constants
PHASE_INTAKE = "INTAKE"
PHASE_BUILD = "BUILD"
PHASE_TEST_LOOP = "TEST_LOOP"
PHASE_DONE = "DONE"
PHASE_FAILED = "FAILED"
PHASE_AWAITING_GATE = "AWAITING_GATE"

# Status constants
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


class Orchestrator:
    """Pipeline state machine.  Polls the task table and drives agents."""

    def __init__(self, config: Config, store: TaskStore) -> None:
        self.config = config
        self.store = store
        self._running = False

    # -- public interface -----------------------------------------------------

    async def run_forever(self, poll_interval: float = 2.0) -> None:
        """Main event loop — poll for actionable tasks and drive them."""
        self._running = True
        logger.info("Orchestrator started")
        while self._running:
            try:
                await self._tick()
            except Exception:
                logger.exception("Orchestrator tick error")
            await asyncio.sleep(poll_interval)

    def stop(self) -> None:
        self._running = False

    async def process_task(self, task_id: str) -> None:
        """Drive a single task through its current phase (one step)."""
        task = self.store.get_task(task_id)
        if not task:
            logger.warning("Task %s not found", task_id)
            return

        logger.info(
            "Processing task %s  phase=%s status=%s",
            task_id, task.phase, task.status,
        )

        match task.phase:
            case "INTAKE":
                await self._handle_intake(task_id, task)
            case "BUILD":
                await self._handle_build(task_id, task)
            case "TEST_LOOP":
                await self._handle_test_loop(task_id, task)
            case "AWAITING_GATE":
                self._handle_awaiting_gate(task_id, task)
            case "DONE" | "FAILED":
                pass  # terminal states
            case _:
                logger.warning("Unknown phase %s for task %s", task.phase, task_id)

    # -- private tick ---------------------------------------------------------

    async def _tick(self) -> None:
        """Process one batch of actionable tasks."""
        # Check for gate resolutions first
        for gate in self.store.list_gates(status="approved"):
            self._on_gate_resolved(gate)
        for gate in self.store.list_gates(status="rejected"):
            self._on_gate_resolved(gate)
        for gate in self.store.list_gates(status="answered"):
            self._on_gate_resolved(gate)

        # Process pending/running tasks
        tasks = self.store.list_tasks(status=STATUS_PENDING)
        for task in tasks:
            if task.phase not in (PHASE_DONE, PHASE_FAILED, PHASE_AWAITING_GATE):
                await self.process_task(task.id)

    # -- phase handlers -------------------------------------------------------

    async def _handle_intake(self, task_id: str, task) -> None:
        """INTAKE → advance to BUILD and launch Coder."""
        self.store.update_task(task_id, phase=PHASE_BUILD, status=STATUS_RUNNING)
        self.store.push_notification(
            task_id, "phase:change", {"phase": PHASE_BUILD}
        )
        await self._run_coder(task_id, task)

    async def _handle_build(self, task_id: str, task) -> None:
        """BUILD — run Coder agent."""
        self.store.update_task(task_id, status=STATUS_RUNNING)
        await self._run_coder(task_id, task)

    async def _handle_test_loop(self, task_id: str, task) -> None:
        """TEST_LOOP — run Tester, then Debugger if failures."""
        self.store.update_task(task_id, status=STATUS_RUNNING)

        # Run Tester
        tester = TesterAgent(task_id, self.config, self.store)
        task_dict = self._task_to_dict(task)
        result = await tester.run(task_dict)

        if result.escalation:
            await self._handle_escalation(task_id, result, "tester")
            return

        # Check test results
        report = self._read_json(task_id, "test_report.json")
        if report and report.get("failed", 0) == 0 and report.get("threshold_met", False):
            # All tests pass — DONE
            self.store.update_task(
                task_id, phase=PHASE_DONE, status=STATUS_DONE, agent=None
            )
            self.store.push_notification(task_id, "task:done", {"outcome": "success"})
            logger.info("Task %s completed successfully", task_id)
            return

        # Tests failed — try Debugger
        debug_attempts = task.debug_attempts + 1
        self.store.update_task(task_id, debug_attempts=debug_attempts)

        if debug_attempts > self.config.max_debug_attempts:
            # Exceeded max debug attempts — send back to Coder with debug log
            logger.warning(
                "Task %s exceeded max debug attempts (%d), routing back to Coder",
                task_id, self.config.max_debug_attempts,
            )
            debug_log = self._read_json(task_id, "debug_log.json")
            self.store.update_task(task_id, phase=PHASE_BUILD, debug_attempts=0)
            await self._run_coder(task_id, task, debug_context=debug_log)
            return

        # Run Debugger
        debugger = DebuggerAgent(task_id, self.config, self.store)
        debug_result = await debugger.run(task_dict)

        if debug_result.escalation:
            await self._handle_escalation(task_id, debug_result, "debugger")
            return

        # Re-check: re-run the test loop
        self.store.update_task(task_id, status=STATUS_PENDING)

    # -- agent runners --------------------------------------------------------

    async def _run_coder(
        self, task_id: str, task, *,
        review_feedback: dict | None = None,
        debug_context: dict | None = None,
        escalation_answer: str | None = None,
    ) -> None:
        coder = CoderAgent(task_id, self.config, self.store)
        task_dict = self._task_to_dict(task)
        if review_feedback:
            task_dict["review_feedback"] = review_feedback
        if debug_context:
            task_dict["debug_context"] = debug_context
        if escalation_answer:
            task_dict["escalation_answer"] = escalation_answer

        result = await coder.run(task_dict)

        if result.escalation:
            await self._handle_escalation(task_id, result, "coder")
            return

        if result.success:
            # Coder done → advance to TEST_LOOP
            self.store.update_task(
                task_id,
                phase=PHASE_TEST_LOOP,
                status=STATUS_PENDING,
                debug_attempts=0,
            )
            self.store.push_notification(
                task_id, "phase:change", {"phase": PHASE_TEST_LOOP}
            )
        else:
            self.store.update_task(
                task_id, phase=PHASE_FAILED, status=STATUS_FAILED
            )
            self.store.push_notification(
                task_id, "task:failed", {"reason": result.error or "Coder failed"}
            )

    # -- escalation handling --------------------------------------------------

    async def _handle_escalation(
        self, task_id: str, result: AgentResult, agent: str
    ) -> None:
        escalation = result.escalation or {}
        gate_id = self.store.create_gate(
            task_id,
            gate_type="escalation",
            question=escalation.get("question", "Agent needs help"),
        )
        self.store.update_task(
            task_id,
            status=STATUS_PENDING,
            phase=PHASE_AWAITING_GATE,
            agent=agent,
        )
        logger.info("Task %s escalated by %s — gate %s", task_id, agent, gate_id)

    def _handle_awaiting_gate(self, task_id: str, task) -> None:
        """Check if a pending gate has been resolved."""
        gate = self.store.get_pending_gate_for_task(task_id)
        if gate is None:
            # Gate already resolved — should have been caught in _tick
            pass

    def _on_gate_resolved(self, gate) -> None:
        """Called when a gate is resolved (approved/rejected/answered)."""
        task = self.store.get_task(gate.task_id)
        if not task or task.phase != PHASE_AWAITING_GATE:
            return

        if gate.type == "escalation" and gate.status == "answered":
            # Resume the waiting agent with the answer
            # For now, we re-enter the phase the agent was in (stored in task.agent)
            previous_agent = task.agent
            if previous_agent == "coder":
                self.store.update_task(
                    gate.task_id, phase=PHASE_BUILD, status=STATUS_PENDING
                )
            elif previous_agent in ("tester", "debugger"):
                self.store.update_task(
                    gate.task_id, phase=PHASE_TEST_LOOP, status=STATUS_PENDING
                )

    # -- helpers --------------------------------------------------------------

    def _task_to_dict(self, task) -> dict:
        return {
            "id": task.id,
            "title": task.title,
            "body": task.body,
            "phase": task.phase,
            "status": task.status,
            "debug_attempts": task.debug_attempts,
        }

    def _read_json(self, task_id: str, filename: str) -> dict | None:
        path = Path(self.config.workspace_root) / task_id / filename
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return None

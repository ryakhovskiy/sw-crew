"""Orchestrator — central coordinator and pipeline state machine.

Phase 1 simplified flow:
    INTAKE → BUILD → TEST_LOOP → DONE

Phase 2 adds:
    INTAKE → ANALYSIS → [gate] → ARCHITECTURE → [gate]
    → PLANNING → BUILD → REVIEW → TEST_LOOP → [gate] → DONE

Phase 3 adds:
    ... → TEST_LOOP → [deploy gate] → DEPLOY → DONE
    Doc Writer runs in parallel with Coder during BUILD.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from crew.agents.base import AgentResult
from crew.agents.coder import CoderAgent
from crew.agents.debugger import DebuggerAgent
from crew.agents.deployer import DeployerAgent
from crew.agents.docwriter import DocWriterAgent
from crew.agents.tester import TesterAgent
from crew.config import Config
from crew.db.store import TaskStore

logger = logging.getLogger(__name__)

# Phase constants
PHASE_INTAKE = "INTAKE"
PHASE_BUILD = "BUILD"
PHASE_TEST_LOOP = "TEST_LOOP"
PHASE_AWAITING_GATE = "AWAITING_GATE"
PHASE_DEPLOY = "DEPLOY"
PHASE_DONE = "DONE"
PHASE_FAILED = "FAILED"

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
            case "DEPLOY":
                await self._handle_deploy(task_id, task)
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
        """BUILD — run Coder and Doc Writer in parallel."""
        self.store.update_task(task_id, status=STATUS_RUNNING)

        task_dict = self._task_to_dict(task)

        # Launch Coder and Doc Writer concurrently.
        # Doc Writer failure is non-blocking — code still advances.
        coder_coro = self._run_coder(task_id, task)
        docwriter_coro = self._run_docwriter(task_id, task_dict)

        coder_result, doc_result = await asyncio.gather(
            coder_coro, docwriter_coro, return_exceptions=True,
        )

        if isinstance(doc_result, Exception):
            logger.warning(
                "Task %s: Doc Writer failed (non-blocking): %s",
                task_id, doc_result,
            )
        if isinstance(coder_result, Exception):
            logger.error("Task %s: Coder raised exception: %s", task_id, coder_result)

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
            # All tests pass — create deploy sign-off gate
            self._create_deploy_gate(task_id)
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

        # Re-run Tester to verify fixes (don't read stale report)
        tester2 = TesterAgent(task_id, self.config, self.store)
        result2 = await tester2.run(task_dict)

        if result2.escalation:
            await self._handle_escalation(task_id, result2, "tester")
            return

        report2 = self._read_json(task_id, "test_report.json")
        if report2 and report2.get("failed", 0) == 0 and report2.get("threshold_met", False):
            self._create_deploy_gate(task_id)
            logger.info("Task %s tests pass after debug fix, deploy gate created", task_id)
            return

        # Still failing — loop back for another debug attempt
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

    async def _run_docwriter(self, task_id: str, task_dict: dict) -> None:
        """Run Doc Writer agent.  Failures are non-blocking."""
        docwriter = DocWriterAgent(task_id, self.config, self.store)
        result = await docwriter.run(task_dict)
        if result.escalation:
            logger.info(
                "Task %s: Doc Writer escalated (non-blocking): %s",
                task_id, result.escalation.get("question", ""),
            )
        elif not result.success:
            logger.warning(
                "Task %s: Doc Writer failed (non-blocking): %s",
                task_id, result.error,
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

    def _create_deploy_gate(self, task_id: str) -> None:
        """Create a deploy sign-off gate after tests pass."""
        # Build artifact summary for operator review
        report = self._read_json(task_id, "test_report.json") or {}
        review = self._read_json(task_id, "review.json") or {}
        summary = (
            f"Tests: {report.get('passed', 0)} passed, "
            f"{report.get('failed', 0)} failed, "
            f"coverage {report.get('coverage_pct', 'N/A')}%\n"
            f"Review: {review.get('decision', 'N/A')}"
        )

        gate_id = self.store.create_gate(
            task_id,
            gate_type="deploy_signoff",
            artifact="test_report.json",
            question=summary,
        )
        self.store.update_task(
            task_id,
            status=STATUS_PENDING,
            phase=PHASE_AWAITING_GATE,
            agent=None,
        )
        self.store.push_notification(
            task_id, "gate:pending", {"gate_id": gate_id, "type": "deploy_signoff"}
        )
        logger.info("Task %s: deploy sign-off gate %s created", task_id, gate_id)

    async def _handle_deploy(self, task_id: str, task) -> None:
        """DEPLOY — run Deployer agent."""
        self.store.update_task(task_id, status=STATUS_RUNNING)

        deployer = DeployerAgent(task_id, self.config, self.store)
        task_dict = self._task_to_dict(task)
        result = await deployer.run(task_dict)

        if result.escalation:
            await self._handle_escalation(task_id, result, "deployer")
            return

        if result.success:
            # Check deploy log for smoke test results
            deploy_log = self._read_json(task_id, "deploy_log.json")
            smoke_ok = True
            if deploy_log:
                for smoke in deploy_log.get("smoke_results", []):
                    if not smoke.get("passed", False):
                        smoke_ok = False
                        break

            if smoke_ok:
                self.store.update_task(
                    task_id, phase=PHASE_DONE, status=STATUS_DONE, agent=None
                )
                self.store.push_notification(
                    task_id, "task:done", {"outcome": "deployed"}
                )
                logger.info("Task %s deployed successfully", task_id)
            else:
                # Smoke tests failed — deployer should have rolled back + escalated
                # but if it didn't, we escalate here
                await self._handle_escalation(
                    task_id,
                    AgentResult(
                        success=False,
                        escalation={
                            "question": "Deployment smoke tests failed. Please review.",
                            "context": json.dumps(deploy_log, indent=2) if deploy_log else "",
                        },
                    ),
                    "deployer",
                )
        else:
            self.store.update_task(
                task_id, phase=PHASE_FAILED, status=STATUS_FAILED
            )
            self.store.push_notification(
                task_id, "task:failed", {"reason": result.error or "Deploy failed"}
            )

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
            previous_agent = task.agent
            if previous_agent == "coder":
                self.store.update_task(
                    gate.task_id, phase=PHASE_BUILD, status=STATUS_PENDING
                )
            elif previous_agent in ("tester", "debugger"):
                self.store.update_task(
                    gate.task_id, phase=PHASE_TEST_LOOP, status=STATUS_PENDING
                )
            elif previous_agent == "deployer":
                self.store.update_task(
                    gate.task_id, phase=PHASE_DEPLOY, status=STATUS_PENDING
                )

        elif gate.type == "deploy_signoff":
            if gate.status == "approved":
                # Advance to DEPLOY phase
                self.store.update_task(
                    gate.task_id, phase=PHASE_DEPLOY, status=STATUS_PENDING
                )
                self.store.push_notification(
                    gate.task_id, "phase:change", {"phase": PHASE_DEPLOY}
                )
                logger.info("Task %s: deploy approved, advancing to DEPLOY", gate.task_id)
            elif gate.status == "rejected":
                # Stay pre-deploy — operator can re-approve later or task can be
                # re-submitted.  Revert to TEST_LOOP so operator sees it.
                self.store.update_task(
                    gate.task_id, phase=PHASE_TEST_LOOP, status=STATUS_PENDING
                )
                logger.info("Task %s: deploy rejected, reverting to TEST_LOOP", gate.task_id)

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

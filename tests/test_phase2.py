"""Tests for Phase 2 components: Analyst, Architect, Planner, Reviewer, full pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from crew.agents.analyst import AnalystAgent
from crew.agents.architect import ArchitectAgent
from crew.agents.base import AgentResult
from crew.agents.orchestrator import (
    PHASE_ANALYSIS,
    PHASE_ARCHITECTURE,
    PHASE_AWAITING_GATE,
    PHASE_BUILD,
    PHASE_FAILED,
    PHASE_PLANNING,
    PHASE_REVIEW,
    PHASE_TEST_LOOP,
    Orchestrator,
)
from crew.agents.planner import PlannerAgent
from crew.agents.reviewer import ReviewerAgent
from crew.config import Config, GatewayConfig
from crew.db.migrate import run_migrations
from crew.db.store import TaskStore

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
    return store.create_task("Test Task", "Build a REST API for user management")


@pytest.fixture
def orchestrator(config: Config, store: TaskStore) -> Orchestrator:
    return Orchestrator(config, store)


# ---------------------------------------------------------------------------
# Requirements Analyst Agent
# ---------------------------------------------------------------------------


class TestAnalystAgent:
    def test_agent_name(self, config, store, task_id):
        agent = AnalystAgent(task_id, config, store)
        assert agent.agent_name == "analyst"

    def test_output_file(self, config, store, task_id):
        agent = AnalystAgent(task_id, config, store)
        assert agent.get_output_file() == "spec.json"

    def test_system_prompt(self, config, store, task_id):
        agent = AnalystAgent(task_id, config, store)
        prompt = agent.build_system_prompt()
        assert "Requirements Analyst" in prompt
        assert "spec.json" in prompt
        assert "user_stories" in prompt
        assert "acceptance_criteria" in prompt
        assert "emit_escalation" in prompt

    def test_tools_restricted(self, config, store, task_id):
        agent = AnalystAgent(task_id, config, store)
        tool_names = {t["name"] for t in agent.get_tools()}
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "search_code" in tool_names
        assert "emit_escalation" in tool_names
        # Analyst should NOT have bash or git
        assert "run_bash" not in tool_names
        assert "git_commit" not in tool_names
        assert "git_diff" not in tool_names

    def test_initial_messages(self, config, store, task_id):
        agent = AnalystAgent(task_id, config, store)
        task_dict = {
            "id": task_id,
            "body": "Build a REST API",
            "title": "REST API",
        }
        messages = agent.build_initial_messages(task_dict)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Requirement" in messages[0]["content"]
        assert "Build a REST API" in messages[0]["content"]

    def test_initial_messages_with_rejection(self, config, store, task_id):
        agent = AnalystAgent(task_id, config, store)
        task_dict = {
            "id": task_id,
            "body": "Build a REST API",
            "rejection_reason": "Missing authentication requirements",
        }
        messages = agent.build_initial_messages(task_dict)
        content = messages[0]["content"]
        assert "Previous Spec Rejected" in content
        assert "Missing authentication requirements" in content

    def test_initial_messages_with_repo(self, config, store, task_id):
        agent = AnalystAgent(task_id, config, store)
        repo_dir = config.workspace_root / task_id / "repo"
        repo_dir.mkdir(parents=True)
        task_dict = {"id": task_id, "body": "Add feature"}
        messages = agent.build_initial_messages(task_dict)
        assert "existing codebase" in messages[0]["content"].lower()

    def test_initial_messages_with_escalation_answer(self, config, store, task_id):
        agent = AnalystAgent(task_id, config, store)
        task_dict = {
            "id": task_id,
            "body": "Build something",
            "escalation_answer": "Use PostgreSQL for the database",
        }
        messages = agent.build_initial_messages(task_dict)
        assert "Use PostgreSQL" in messages[0]["content"]


# ---------------------------------------------------------------------------
# Architect Agent
# ---------------------------------------------------------------------------


class TestArchitectAgent:
    def test_agent_name(self, config, store, task_id):
        agent = ArchitectAgent(task_id, config, store)
        assert agent.agent_name == "architect"

    def test_output_file(self, config, store, task_id):
        agent = ArchitectAgent(task_id, config, store)
        assert agent.get_output_file() == "arch.md"

    def test_system_prompt(self, config, store, task_id):
        agent = ArchitectAgent(task_id, config, store)
        prompt = agent.build_system_prompt()
        assert "Architect" in prompt
        assert "arch.md" in prompt
        assert "Component Overview" in prompt
        assert "Interface Contracts" in prompt
        assert "Migration Plan" in prompt
        assert "Technical Risks" in prompt
        assert "Mermaid" in prompt

    def test_tools_restricted(self, config, store, task_id):
        agent = ArchitectAgent(task_id, config, store)
        tool_names = {t["name"] for t in agent.get_tools()}
        assert "read_file" in tool_names
        assert "search_code" in tool_names
        assert "emit_escalation" in tool_names
        assert "run_bash" not in tool_names
        assert "git_commit" not in tool_names

    def test_initial_messages_with_spec(self, config, store, task_id):
        agent = ArchitectAgent(task_id, config, store)
        ws = config.workspace_root / task_id
        ws.mkdir(parents=True, exist_ok=True)
        spec = {"task_id": task_id, "title": "REST API", "summary": "A REST API"}
        (ws / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        task_dict = {"id": task_id, "body": "Build API"}
        messages = agent.build_initial_messages(task_dict)
        content = messages[0]["content"]
        assert "Specification" in content
        assert "REST API" in content

    def test_initial_messages_without_spec(self, config, store, task_id):
        agent = ArchitectAgent(task_id, config, store)
        task_dict = {"id": task_id, "body": "Build something new"}
        messages = agent.build_initial_messages(task_dict)
        content = messages[0]["content"]
        assert "Build something new" in content

    def test_initial_messages_with_rejection(self, config, store, task_id):
        agent = ArchitectAgent(task_id, config, store)
        task_dict = {
            "id": task_id,
            "body": "Build API",
            "rejection_reason": "Need microservices not monolith",
        }
        messages = agent.build_initial_messages(task_dict)
        content = messages[0]["content"]
        assert "Previous Architecture Rejected" in content
        assert "microservices" in content


# ---------------------------------------------------------------------------
# Planner Agent
# ---------------------------------------------------------------------------


class TestPlannerAgent:
    def test_agent_name(self, config, store, task_id):
        agent = PlannerAgent(task_id, config, store)
        assert agent.agent_name == "planner"

    def test_output_file(self, config, store, task_id):
        agent = PlannerAgent(task_id, config, store)
        assert agent.get_output_file() == "plan.json"

    def test_system_prompt(self, config, store, task_id):
        agent = PlannerAgent(task_id, config, store)
        prompt = agent.build_system_prompt()
        assert "Implementation Planner" in prompt
        assert "plan.json" in prompt
        assert "depends_on" in prompt
        assert "effort" in prompt

    def test_tools_restricted(self, config, store, task_id):
        agent = PlannerAgent(task_id, config, store)
        tool_names = {t["name"] for t in agent.get_tools()}
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "search_code" in tool_names
        assert "emit_escalation" in tool_names
        assert "run_bash" not in tool_names
        assert "git_commit" not in tool_names

    def test_initial_messages_with_artifacts(self, config, store, task_id):
        agent = PlannerAgent(task_id, config, store)
        ws = config.workspace_root / task_id
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "arch.md").write_text("## Architecture\nMonolith", encoding="utf-8")
        spec = {"task_id": task_id, "title": "API"}
        (ws / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        task_dict = {"id": task_id, "body": "Build it"}
        messages = agent.build_initial_messages(task_dict)
        content = messages[0]["content"]
        assert "Architecture" in content
        assert "Monolith" in content
        assert "Specification" in content


# ---------------------------------------------------------------------------
# Code Reviewer Agent
# ---------------------------------------------------------------------------


class TestReviewerAgent:
    def test_agent_name(self, config, store, task_id):
        agent = ReviewerAgent(task_id, config, store)
        assert agent.agent_name == "reviewer"

    def test_output_file(self, config, store, task_id):
        agent = ReviewerAgent(task_id, config, store)
        assert agent.get_output_file() == "review.json"

    def test_system_prompt(self, config, store, task_id):
        agent = ReviewerAgent(task_id, config, store)
        prompt = agent.build_system_prompt()
        assert "Code Reviewer" in prompt
        assert "review.json" in prompt
        assert "critical" in prompt
        assert "block" in prompt
        assert "ruff" in prompt
        assert "bandit" in prompt

    def test_tools_include_bash(self, config, store, task_id):
        """Reviewer needs bash for running linters and security scanners."""
        agent = ReviewerAgent(task_id, config, store)
        tool_names = {t["name"] for t in agent.get_tools()}
        assert "run_bash" in tool_names
        assert "read_file" in tool_names
        assert "search_code" in tool_names

    def test_initial_messages_with_changes(self, config, store, task_id):
        agent = ReviewerAgent(task_id, config, store)
        ws = config.workspace_root / task_id
        ws.mkdir(parents=True, exist_ok=True)
        changes = {
            "files_created": ["src/api.py"],
            "files_modified": ["src/main.py"],
            "summary": "Added API endpoint",
        }
        (ws / "changes.json").write_text(
            json.dumps(changes), encoding="utf-8"
        )
        task_dict = {"id": task_id, "body": "Build API"}
        messages = agent.build_initial_messages(task_dict)
        content = messages[0]["content"]
        assert "Changes Made" in content
        assert "api.py" in content

    def test_initial_messages_with_arch_and_spec(self, config, store, task_id):
        agent = ReviewerAgent(task_id, config, store)
        ws = config.workspace_root / task_id
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "arch.md").write_text("## Design\nREST API", encoding="utf-8")
        (ws / "spec.json").write_text(
            json.dumps({"title": "API spec"}), encoding="utf-8"
        )
        task_dict = {"id": task_id, "body": "Build it"}
        messages = agent.build_initial_messages(task_dict)
        content = messages[0]["content"]
        assert "Architecture" in content
        assert "Specification" in content


# ---------------------------------------------------------------------------
# Orchestrator — Full Pipeline Phase Transitions
# ---------------------------------------------------------------------------


class TestOrchestratorPipeline:
    """Test orchestrator phase transitions for the full pipeline."""

    @pytest.mark.asyncio
    async def test_intake_advances_to_analysis(self, orchestrator, store, task_id):
        """INTAKE should advance to ANALYSIS and attempt to run Analyst."""
        with patch.object(
            AnalystAgent, "run",
            new_callable=AsyncMock,
            return_value=AgentResult(success=True, output_file="spec.json"),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_intake(task_id, task)

        task = store.get_task(task_id)
        assert task.phase == PHASE_AWAITING_GATE
        # Should have a spec_approval gate
        gates = store.list_gates()
        spec_gates = [g for g in gates if g.type == "spec_approval"]
        assert len(spec_gates) == 1
        assert spec_gates[0].status == "pending"

    @pytest.mark.asyncio
    async def test_spec_gate_approve_advances_to_architecture(
        self, orchestrator, store, task_id
    ):
        """Approving spec gate should advance task to ARCHITECTURE."""
        with patch.object(
            AnalystAgent, "run",
            new_callable=AsyncMock,
            return_value=AgentResult(success=True, output_file="spec.json"),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_intake(task_id, task)

        # Find and approve the gate
        gates = store.list_gates(status="pending")
        spec_gate = next(g for g in gates if g.type == "spec_approval")
        store.resolve_gate(spec_gate.id, "approved", comment="Looks good")

        # Simulate tick to process gate resolution
        orchestrator._on_gate_resolved(store.get_gate(spec_gate.id))

        task = store.get_task(task_id)
        assert task.phase == PHASE_ARCHITECTURE

    @pytest.mark.asyncio
    async def test_spec_gate_reject_reruns_analyst(
        self, orchestrator, store, task_id
    ):
        """Rejecting spec gate should revert to ANALYSIS for re-run."""
        with patch.object(
            AnalystAgent, "run",
            new_callable=AsyncMock,
            return_value=AgentResult(success=True, output_file="spec.json"),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_intake(task_id, task)

        gates = store.list_gates(status="pending")
        spec_gate = next(g for g in gates if g.type == "spec_approval")
        store.resolve_gate(spec_gate.id, "rejected", reason="Too vague")

        orchestrator._on_gate_resolved(store.get_gate(spec_gate.id))

        task = store.get_task(task_id)
        assert task.phase == PHASE_ANALYSIS

    @pytest.mark.asyncio
    async def test_architecture_creates_arch_gate(self, orchestrator, store, task_id):
        """ARCHITECTURE should create arch_approval gate on success."""
        store.update_task(task_id, phase=PHASE_ARCHITECTURE)
        with patch.object(
            ArchitectAgent, "run",
            new_callable=AsyncMock,
            return_value=AgentResult(success=True, output_file="arch.md"),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_architecture(task_id, task)

        task = store.get_task(task_id)
        assert task.phase == PHASE_AWAITING_GATE
        gates = store.list_gates()
        arch_gates = [g for g in gates if g.type == "arch_approval"]
        assert len(arch_gates) == 1

    @pytest.mark.asyncio
    async def test_arch_gate_approve_advances_to_planning(
        self, orchestrator, store, task_id
    ):
        """Approving arch gate should advance to PLANNING."""
        store.update_task(task_id, phase=PHASE_ARCHITECTURE)
        with patch.object(
            ArchitectAgent, "run",
            new_callable=AsyncMock,
            return_value=AgentResult(success=True, output_file="arch.md"),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_architecture(task_id, task)

        gates = store.list_gates(status="pending")
        arch_gate = next(g for g in gates if g.type == "arch_approval")
        store.resolve_gate(arch_gate.id, "approved")

        orchestrator._on_gate_resolved(store.get_gate(arch_gate.id))

        task = store.get_task(task_id)
        assert task.phase == PHASE_PLANNING

    @pytest.mark.asyncio
    async def test_arch_gate_reject_reruns_architect(
        self, orchestrator, store, task_id
    ):
        """Rejecting arch gate should revert to ARCHITECTURE."""
        store.update_task(task_id, phase=PHASE_ARCHITECTURE)
        with patch.object(
            ArchitectAgent, "run",
            new_callable=AsyncMock,
            return_value=AgentResult(success=True, output_file="arch.md"),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_architecture(task_id, task)

        gates = store.list_gates(status="pending")
        arch_gate = next(g for g in gates if g.type == "arch_approval")
        store.resolve_gate(arch_gate.id, "rejected", reason="Too complex")

        orchestrator._on_gate_resolved(store.get_gate(arch_gate.id))

        task = store.get_task(task_id)
        assert task.phase == PHASE_ARCHITECTURE

    @pytest.mark.asyncio
    async def test_planning_advances_to_build(self, orchestrator, store, task_id):
        """PLANNING should advance to BUILD on success."""
        store.update_task(task_id, phase=PHASE_PLANNING)
        with patch.object(
            PlannerAgent, "run",
            new_callable=AsyncMock,
            return_value=AgentResult(success=True, output_file="plan.json"),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_planning(task_id, task)

        task = store.get_task(task_id)
        assert task.phase == PHASE_BUILD

    @pytest.mark.asyncio
    async def test_review_pass_advances_to_test_loop(
        self, orchestrator, store, task_id
    ):
        """REVIEW with pass decision should advance to TEST_LOOP."""
        store.update_task(task_id, phase=PHASE_REVIEW)
        # Write a passing review.json
        ws = config_workspace(orchestrator.config, task_id)
        (ws / "review.json").write_text(
            json.dumps({"decision": "pass", "issues": []}),
            encoding="utf-8",
        )
        with patch.object(
            ReviewerAgent, "run",
            new_callable=AsyncMock,
            return_value=AgentResult(success=True, output_file="review.json"),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_review(task_id, task)

        task = store.get_task(task_id)
        assert task.phase == PHASE_TEST_LOOP

    @pytest.mark.asyncio
    async def test_review_block_routes_back_to_build(
        self, orchestrator, store, task_id
    ):
        """REVIEW with block decision should route back to BUILD."""
        store.update_task(task_id, phase=PHASE_REVIEW)
        ws = config_workspace(orchestrator.config, task_id)
        review = {
            "decision": "block",
            "issues": [
                {
                    "file": "src/api.py",
                    "line": 10,
                    "severity": "critical",
                    "rule": "sql-injection",
                    "message": "SQL injection vulnerability",
                }
            ],
        }
        (ws / "review.json").write_text(
            json.dumps(review), encoding="utf-8"
        )
        with patch.object(
            ReviewerAgent, "run",
            new_callable=AsyncMock,
            return_value=AgentResult(success=True, output_file="review.json"),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_review(task_id, task)

        task = store.get_task(task_id)
        assert task.phase == PHASE_BUILD

    @pytest.mark.asyncio
    async def test_analyst_failure_sets_failed(self, orchestrator, store, task_id):
        """Analyst failure should set phase to FAILED."""
        with patch.object(
            AnalystAgent, "run",
            new_callable=AsyncMock,
            return_value=AgentResult(success=False, error="LLM error"),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_intake(task_id, task)

        task = store.get_task(task_id)
        assert task.phase == PHASE_FAILED

    @pytest.mark.asyncio
    async def test_analyst_escalation_creates_gate(
        self, orchestrator, store, task_id
    ):
        """Analyst escalation should create an escalation gate."""
        with patch.object(
            AnalystAgent, "run",
            new_callable=AsyncMock,
            return_value=AgentResult(
                success=False,
                escalation={
                    "question": "Which database to use?",
                    "context": "The requirement doesn't specify",
                },
            ),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_intake(task_id, task)

        task = store.get_task(task_id)
        assert task.phase == PHASE_AWAITING_GATE
        assert task.agent == "analyst"
        gates = store.list_gates(status="pending")
        escalation_gates = [g for g in gates if g.type == "escalation"]
        assert len(escalation_gates) >= 1

    @pytest.mark.asyncio
    async def test_escalation_answer_resumes_analyst(
        self, orchestrator, store, task_id
    ):
        """Answering an analyst escalation should resume ANALYSIS."""
        store.update_task(
            task_id,
            phase=PHASE_AWAITING_GATE,
            status="pending",
            agent="analyst",
        )
        gate_id = store.create_gate(
            task_id, gate_type="escalation", question="Which DB?"
        )
        store.resolve_gate(gate_id, "answered", answer="Use PostgreSQL")

        gate = store.get_gate(gate_id)
        orchestrator._on_gate_resolved(gate)

        task = store.get_task(task_id)
        assert task.phase == PHASE_ANALYSIS

    @pytest.mark.asyncio
    async def test_escalation_answer_resumes_architect(
        self, orchestrator, store, task_id
    ):
        """Answering an architect escalation should resume ARCHITECTURE."""
        store.update_task(
            task_id, phase=PHASE_AWAITING_GATE, status="pending", agent="architect"
        )
        gate_id = store.create_gate(
            task_id, gate_type="escalation", question="REST or GraphQL?"
        )
        store.resolve_gate(gate_id, "answered", answer="REST")

        gate = store.get_gate(gate_id)
        orchestrator._on_gate_resolved(gate)

        task = store.get_task(task_id)
        assert task.phase == PHASE_ARCHITECTURE

    @pytest.mark.asyncio
    async def test_escalation_answer_resumes_planner(
        self, orchestrator, store, task_id
    ):
        """Answering a planner escalation should resume PLANNING."""
        store.update_task(
            task_id, phase=PHASE_AWAITING_GATE, status="pending", agent="planner"
        )
        gate_id = store.create_gate(
            task_id, gate_type="escalation", question="Split into microservices?"
        )
        store.resolve_gate(gate_id, "answered", answer="No, keep monolith")

        gate = store.get_gate(gate_id)
        orchestrator._on_gate_resolved(gate)

        task = store.get_task(task_id)
        assert task.phase == PHASE_PLANNING

    @pytest.mark.asyncio
    async def test_escalation_answer_resumes_reviewer(
        self, orchestrator, store, task_id
    ):
        """Answering a reviewer escalation should resume REVIEW."""
        store.update_task(
            task_id, phase=PHASE_AWAITING_GATE, status="pending", agent="reviewer"
        )
        gate_id = store.create_gate(
            task_id, gate_type="escalation", question="Is this pattern acceptable?"
        )
        store.resolve_gate(gate_id, "answered", answer="Yes, it is fine")

        gate = store.get_gate(gate_id)
        orchestrator._on_gate_resolved(gate)

        task = store.get_task(task_id)
        assert task.phase == PHASE_REVIEW


# ---------------------------------------------------------------------------
# Orchestrator helpers
# ---------------------------------------------------------------------------


class TestOrchestratorHelpers:
    def test_get_last_rejection_none(self, orchestrator, store, task_id):
        result = orchestrator._get_last_rejection(task_id, "spec_approval")
        assert result is None

    def test_get_last_rejection_with_rejected_gate(
        self, orchestrator, store, task_id
    ):
        gate_id = store.create_gate(task_id, gate_type="spec_approval")
        store.resolve_gate(gate_id, "rejected", reason="Too vague")
        result = orchestrator._get_last_rejection(task_id, "spec_approval")
        assert result == "Too vague"

    def test_get_last_rejection_returns_latest(
        self, orchestrator, store, task_id
    ):
        g1 = store.create_gate(task_id, gate_type="spec_approval")
        store.resolve_gate(g1, "rejected", reason="First rejection")
        g2 = store.create_gate(task_id, gate_type="spec_approval")
        store.resolve_gate(g2, "rejected", reason="Second rejection")
        result = orchestrator._get_last_rejection(task_id, "spec_approval")
        assert result == "Second rejection"

    def test_get_last_rejection_ignores_other_types(
        self, orchestrator, store, task_id
    ):
        gate_id = store.create_gate(task_id, gate_type="arch_approval")
        store.resolve_gate(gate_id, "rejected", reason="Wrong type")
        result = orchestrator._get_last_rejection(task_id, "spec_approval")
        assert result is None


# ---------------------------------------------------------------------------
# Coder → Review flow
# ---------------------------------------------------------------------------


class TestCoderReviewFlow:
    @pytest.mark.asyncio
    async def test_coder_success_advances_to_review(
        self, orchestrator, store, task_id
    ):
        """After Coder succeeds, task should advance to REVIEW (not TEST_LOOP)."""
        from crew.agents.coder import CoderAgent

        store.update_task(task_id, phase=PHASE_BUILD)
        with (
            patch.object(
                CoderAgent, "run",
                new_callable=AsyncMock,
                return_value=AgentResult(success=True, output_file="changes.json"),
            ),
            patch(
                "crew.agents.orchestrator.DocWriterAgent.run",
                new_callable=AsyncMock,
                return_value=AgentResult(success=True),
            ),
        ):
            task = store.get_task(task_id)
            await orchestrator._handle_build(task_id, task)

        task = store.get_task(task_id)
        assert task.phase == PHASE_REVIEW


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def config_workspace(config: Config, task_id: str) -> Path:
    ws = Path(config.workspace_root) / task_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws

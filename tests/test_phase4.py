"""Tests for Phase 4 — Hardening components."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from crew.config import Config, DockerSandboxConfig, GatewayConfig, PricingConfig
from crew.context import estimate_tokens, summarize_history
from crew.db.store import TaskStore
from crew.resilience import CircuitBreaker, CircuitOpenError, CircuitState, RetryPolicy

# ──────────────────────────────────────────────────────────────────────────────
# RetryPolicy
# ──────────────────────────────────────────────────────────────────────────────


class TestRetryPolicy:
    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        policy = RetryPolicy(max_retries=3, backoff_base=0.01)
        fn = MagicMock(return_value="ok")
        result = await policy.execute(fn)
        assert result == "ok"
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit(self):
        import anthropic

        policy = RetryPolicy(max_retries=2, backoff_base=0.01)
        fn = MagicMock(
            side_effect=[
                anthropic.RateLimitError(
                    message="rate limited",
                    response=MagicMock(status_code=429, headers={}),
                    body=None,
                ),
                "success",
            ]
        )
        result = await policy.execute(fn)
        assert result == "success"
        assert fn.call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_auth_error(self):
        import anthropic

        policy = RetryPolicy(max_retries=3, backoff_base=0.01)
        fn = MagicMock(
            side_effect=anthropic.AuthenticationError(
                message="bad key",
                response=MagicMock(status_code=401, headers={}),
                body=None,
            )
        )
        with pytest.raises(anthropic.AuthenticationError):
            await policy.execute(fn)
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        import anthropic

        policy = RetryPolicy(max_retries=2, backoff_base=0.01)
        fn = MagicMock(
            side_effect=anthropic.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body=None,
            )
        )
        with pytest.raises(anthropic.RateLimitError):
            await policy.execute(fn)
        assert fn.call_count == 3  # 1 initial + 2 retries


# ──────────────────────────────────────────────────────────────────────────────
# CircuitBreaker
# ──────────────────────────────────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(threshold=3, reset_seconds=60)
        assert cb.state == CircuitState.CLOSED
        cb.check()  # should not raise

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(threshold=3, reset_seconds=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            cb.check()

    def test_resets_on_success(self):
        cb = CircuitBreaker(threshold=3, reset_seconds=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        # Should be able to take 2 more failures without opening
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_after_reset_time(self):
        cb = CircuitBreaker(threshold=2, reset_seconds=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            cb.check()
        # After reset time elapses, transitions to HALF_OPEN
        time.sleep(1.1)
        assert cb.state == CircuitState.HALF_OPEN
        cb.check()  # should not raise in HALF_OPEN

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(threshold=2, reset_seconds=0)
        cb.record_failure()
        cb.record_failure()
        # reset_seconds=0 means immediate half-open
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(threshold=2, reset_seconds=100)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # Manually set to HALF_OPEN to simulate timeout elapsed
        cb._state = CircuitState.HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN
        # Another failure should reopen
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


# ──────────────────────────────────────────────────────────────────────────────
# Context Window Management
# ──────────────────────────────────────────────────────────────────────────────


class TestContextManagement:
    def test_estimate_tokens_simple(self):
        messages = [{"role": "user", "content": "Hello world"}]
        tokens = estimate_tokens(messages)
        # "Hello world" = 11 chars, ~2-3 tokens
        assert 1 <= tokens <= 5

    def test_estimate_tokens_list_content(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "x" * 400},
                ],
            },
        ]
        tokens = estimate_tokens(messages)
        assert tokens >= 90  # 400 chars / 4

    def test_estimate_tokens_empty(self):
        assert estimate_tokens([]) == 0

    def test_summarize_short_history_unchanged(self):
        """Messages shorter than keep_last_turns should not be modified."""
        client = MagicMock()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = summarize_history(client, messages, "test-model", keep_last_turns=2)
        assert result == messages
        client.messages.create.assert_not_called()

    def test_summarize_compresses_old_messages(self):
        """Long history should be summarized."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Summary of previous work.")]
        client = MagicMock()
        client.messages.create.return_value = mock_response

        messages = [
            {"role": "user", "content": f"Message {i}"} for i in range(10)
        ]
        result = summarize_history(client, messages, "test-model", keep_last_turns=2)

        # Should have: summary + ack + last 4 messages (2 turns)
        assert len(result) == 6
        assert "[Summary of previous conversation]" in result[0]["content"]
        assert result[1]["role"] == "assistant"
        client.messages.create.assert_called_once()

    def test_summarize_fallback_on_error(self):
        """If summarization LLM call fails, return original messages."""
        client = MagicMock()
        client.messages.create.side_effect = Exception("API error")

        messages = [{"role": "user", "content": f"Msg {i}"} for i in range(10)]
        result = summarize_history(client, messages, "test-model", keep_last_turns=2)
        assert result == messages


# ──────────────────────────────────────────────────────────────────────────────
# Cost Tracking (DB)
# ──────────────────────────────────────────────────────────────────────────────


class TestCostTracking:
    def test_task_has_cost_field(self, store: TaskStore):
        task_id = store.create_task("Test", "body")
        task = store.get_task(task_id)
        assert task.total_cost_usd == 0.0

    def test_update_task_cost(self, store: TaskStore):
        task_id = store.create_task("Test", "body")
        store.update_task(task_id, total_cost_usd=1.5)
        task = store.get_task(task_id)
        assert task.total_cost_usd == 1.5

    def test_cost_breakdown_empty(self, store: TaskStore):
        task_id = store.create_task("Test", "body")
        breakdown = store.get_cost_breakdown(task_id)
        assert breakdown == []

    def test_cost_breakdown_with_audit(self, store: TaskStore):
        task_id = store.create_task("Test", "body")
        store.append_audit(
            task_id, "coder", "agent:completed",
            {"input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.01},
        )
        store.append_audit(
            task_id, "tester", "agent:completed",
            {"input_tokens": 2000, "output_tokens": 800, "cost_usd": 0.02},
        )
        breakdown = store.get_cost_breakdown(task_id)
        assert len(breakdown) == 2
        assert breakdown[0]["agent"] == "coder"
        assert breakdown[0]["cost_usd"] == 0.01
        assert breakdown[1]["agent"] == "tester"

    def test_cost_computation(self):
        """Verify cost computation formula."""
        pricing = PricingConfig(input_per_1m_usd=3.0, output_per_1m_usd=15.0)
        input_tokens = 10000
        output_tokens = 5000
        cost = (
            input_tokens * pricing.input_per_1m_usd
            + output_tokens * pricing.output_per_1m_usd
        ) / 1_000_000
        assert abs(cost - 0.105) < 0.001


# ──────────────────────────────────────────────────────────────────────────────
# Search Tasks (DB)
# ──────────────────────────────────────────────────────────────────────────────


class TestSearchTasks:
    def test_search_by_text(self, store: TaskStore):
        store.create_task("Build API endpoint", "REST API for users")
        store.create_task("Fix CSS bug", "Button alignment issue")

        results = store.search_tasks(q="API")
        assert len(results) == 1
        assert "API" in results[0].title

    def test_search_by_status(self, store: TaskStore):
        store.create_task("T1", "b1")
        id2 = store.create_task("T2", "b2")
        store.update_task(id2, status="done")

        results = store.search_tasks(status="done")
        assert len(results) == 1
        assert results[0].id == id2

    def test_search_sort_by_cost(self, store: TaskStore):
        id1 = store.create_task("T1", "b1")
        id2 = store.create_task("T2", "b2")
        store.update_task(id1, total_cost_usd=5.0)
        store.update_task(id2, total_cost_usd=1.0)

        results = store.search_tasks(sort="total_cost_usd", order="desc")
        assert results[0].total_cost_usd == 5.0

    def test_search_invalid_sort_defaults(self, store: TaskStore):
        store.create_task("T1", "b1")
        # Invalid sort field should fall back to created_at
        results = store.search_tasks(sort="invalid_field")
        assert len(results) == 1

    def test_search_since_filter(self, store: TaskStore):
        import time
        before = int(time.time()) - 10
        store.create_task("T1", "b1")
        results = store.search_tasks(since=before)
        assert len(results) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Config (new fields)
# ──────────────────────────────────────────────────────────────────────────────


class TestConfig:
    def test_default_retry_config(self):
        config = Config()
        assert config.max_agent_retries == 3
        assert config.retry_backoff_base == 2.0
        assert config.circuit_breaker_threshold == 5
        assert config.circuit_breaker_reset_seconds == 300

    def test_default_pricing_config(self):
        config = Config()
        assert config.pricing.input_per_1m_usd == 3.0
        assert config.pricing.output_per_1m_usd == 15.0

    def test_default_context_config(self):
        config = Config()
        assert config.context_budget_tokens == 150_000
        assert config.summarization_trigger_pct == 0.8

    def test_default_docker_config(self):
        config = Config()
        assert config.docker_sandbox.enabled is False
        assert config.docker_sandbox.image == "crew-agent:latest"
        assert config.docker_sandbox.network_mode == "none"


# ──────────────────────────────────────────────────────────────────────────────
# Docker Sandbox
# ──────────────────────────────────────────────────────────────────────────────


class TestDockerSandbox:
    @pytest.mark.asyncio
    async def test_sandbox_disabled_returns_none(self):
        """When Docker sandbox is disabled, orchestrator should use in-process."""
        from pathlib import Path

        from crew.agents.orchestrator import Orchestrator

        config = Config(
            anthropic_api_key="test",
            gateway=GatewayConfig(token="test"),
            workspace_root=Path("/tmp/test-workspace"),
            docker_sandbox=DockerSandboxConfig(enabled=False),
        )
        store = MagicMock()
        orch = Orchestrator(config, store)

        result = await orch._run_agent_docker("coder", "t-test")
        assert result is None

    @pytest.mark.asyncio
    async def test_sandbox_runner_creates_container(self, tmp_path):
        """Test DockerAgentRunner creates container with correct params."""
        import json

        from crew.sandbox import DockerAgentRunner

        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        workspace_dir = workspace_root / "t-test"
        workspace_dir.mkdir()

        config = Config(
            anthropic_api_key="test-key",
            workspace_root=workspace_root,
            docker_sandbox=DockerSandboxConfig(
                enabled=True,
                image="crew-agent:test",
                memory_limit="256m",
                cpu_limit=0.5,
                network_mode="none",
                timeout=300,
            ),
        )

        result_file = workspace_dir / "_agent_result.json"

        def fake_wait(**kwargs):
            """Simulate container writing result before wait returns."""
            result_file.write_text(json.dumps({
                "success": True,
                "output_file": "changes.json",
                "cost_usd": 0.05,
            }))
            return {"StatusCode": 0}

        mock_docker = MagicMock()
        mock_container = MagicMock()
        mock_container.wait.side_effect = fake_wait
        mock_container.logs.return_value = b"done"
        mock_docker.containers.run.return_value = mock_container

        runner = DockerAgentRunner(config)
        runner._client = mock_docker

        result = await runner.run_agent("coder", "t-test")

        assert mock_docker.containers.run.called
        call_kwargs = mock_docker.containers.run.call_args
        assert call_kwargs.kwargs["image"] == "crew-agent:test"
        assert call_kwargs.kwargs["mem_limit"] == "256m"
        assert call_kwargs.kwargs["network_mode"] == "none"
        assert result.success is True
        assert result.cost_usd == 0.05


# ──────────────────────────────────────────────────────────────────────────────
# Orchestrator circuit breakers
# ──────────────────────────────────────────────────────────────────────────────


class TestOrchestratorResilience:
    def test_circuit_breaker_per_agent(self):
        from pathlib import Path

        from crew.agents.orchestrator import Orchestrator

        config = Config(
            anthropic_api_key="test",
            gateway=GatewayConfig(token="test"),
            workspace_root=Path("/tmp/test-workspace"),
            circuit_breaker_threshold=3,
            circuit_breaker_reset_seconds=60,
        )
        store = MagicMock()
        orch = Orchestrator(config, store)

        cb1 = orch._get_circuit_breaker("coder")
        cb2 = orch._get_circuit_breaker("tester")
        cb3 = orch._get_circuit_breaker("coder")

        assert cb1 is cb3  # same instance
        assert cb1 is not cb2
        assert cb1.threshold == 3

    def test_cost_accumulation(self):
        from pathlib import Path

        from crew.agents.base import AgentResult
        from crew.agents.orchestrator import Orchestrator

        config = Config(
            anthropic_api_key="test",
            gateway=GatewayConfig(token="test"),
            workspace_root=Path("/tmp/test-workspace"),
        )
        mock_store = MagicMock()
        mock_task = MagicMock()
        mock_task.total_cost_usd = 1.0
        mock_store.get_task.return_value = mock_task

        orch = Orchestrator(config, mock_store)
        result = AgentResult(success=True, cost_usd=0.5)
        orch._accumulate_cost("t-test", result)

        mock_store.update_task.assert_called_once_with("t-test", total_cost_usd=1.5)

    def test_cost_accumulation_skips_zero(self):
        from pathlib import Path

        from crew.agents.base import AgentResult
        from crew.agents.orchestrator import Orchestrator

        config = Config(
            anthropic_api_key="test",
            gateway=GatewayConfig(token="test"),
            workspace_root=Path("/tmp/test-workspace"),
        )
        mock_store = MagicMock()
        orch = Orchestrator(config, mock_store)

        result = AgentResult(success=True, cost_usd=0.0)
        orch._accumulate_cost("t-test", result)
        mock_store.get_task.assert_not_called()

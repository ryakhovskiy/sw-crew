"""BaseAgent — abstract base class for all pipeline agents.

Provides:
- Anthropic API client with tool-use loop
- Sandboxed file I/O, bash execution, code search
- Escalation emission
- System-prompt templating
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic

from crew.config import Config
from crew.context import estimate_tokens, summarize_history
from crew.db.store import TaskStore
from crew.logging import get_agent_logger
from crew.resilience import CircuitBreaker, CircuitOpenError, RetryPolicy
from crew.tools import files as file_tools
from crew.tools import git as git_tools
from crew.tools import search as search_tools
from crew.tools import shell as shell_tools

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    success: bool
    output_file: str | None = None
    escalation: dict | None = None
    error: str | None = None
    token_usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic tool-use schema)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read the contents of a file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within the workspace.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file in the workspace. Creates parent directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within the workspace.",
                },
                "content": {
                    "type": "string",
                    "description": "File content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List files and directories at a path in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path (default: workspace root).",
                    "default": ".",
                },
            },
            "required": [],
        },
    },
    {
        "name": "run_bash",
        "description": (
            "Execute a shell command in the workspace directory. "
            "Returns stdout, stderr, and return code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "search_code",
        "description": "Search the workspace codebase for files containing the query string.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to search for in source files.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "git_commit",
        "description": "Stage all changes and create a git commit with the given message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Commit message.",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "git_diff",
        "description": "Show the current git diff (staged + unstaged changes).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "emit_escalation",
        "description": (
            "Signal that you cannot proceed and need human input. "
            "This blocks until the operator answers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Your question for the operator.",
                },
                "context": {
                    "type": "string",
                    "description": "Relevant context to help the operator answer.",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of suggested answers.",
                },
            },
            "required": ["question", "context"],
        },
    },
]


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """Abstract base for every pipeline agent.

    Subclasses implement :meth:`build_system_prompt` and :meth:`build_initial_messages`
    which define the agent's personality and initial task context.  The tool-use loop
    is handled generically by :meth:`run`.
    """

    # Subclasses should set these
    agent_name: str = "base"

    def __init__(
        self,
        task_id: str,
        config: Config,
        store: TaskStore,
        *,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.task_id = task_id
        self.config = config
        self.store = store
        self.workspace = Path(config.workspace_root) / task_id
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._retry_policy = RetryPolicy(
            max_retries=config.max_agent_retries,
            backoff_base=config.retry_backoff_base,
        )
        self._circuit_breaker = circuit_breaker
        # Per-agent structured log file: logs/{task_id}/{agent_name}.jsonl
        self._agent_logger = get_agent_logger("logs", task_id, self.agent_name)

    # -- abstract interface ---------------------------------------------------

    @abstractmethod
    def build_system_prompt(self) -> str:
        """Return the system prompt for this agent."""

    @abstractmethod
    def build_initial_messages(self, task: dict) -> list[dict]:
        """Return the initial conversation messages given the task context."""

    def get_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions available to this agent.  Override to restrict."""
        return TOOL_DEFINITIONS

    def get_output_file(self) -> str | None:
        """Return the expected output filename (e.g. 'changes.json').  None = no check."""
        return None

    # -- main run loop --------------------------------------------------------

    async def run(self, task: dict) -> AgentResult:
        """Execute the agent's tool-use loop until completion or escalation."""
        system_prompt = self.build_system_prompt()
        messages = self.build_initial_messages(task)
        tools = self.get_tools()
        escalation: dict | None = None

        self.store.update_task(self.task_id, agent=self.agent_name, status="running")
        git_tools.ensure_repo(self.workspace)

        # Circuit breaker check — fail fast if circuit is open
        if self._circuit_breaker:
            try:
                self._circuit_breaker.check()
            except CircuitOpenError as exc:
                logger.error("[%s] %s", self.task_id, exc)
                return AgentResult(success=False, error=str(exc))

        for iteration in range(self.config.max_tool_calls):
            logger.info(
                "[%s] agent=%s iteration=%d", self.task_id, self.agent_name, iteration
            )

            # Context window management — summarize if approaching budget
            budget = self.config.context_budget_tokens
            trigger = int(budget * self.config.summarization_trigger_pct)
            estimated = estimate_tokens(messages)
            if estimated > trigger and len(messages) > 4:
                logger.info(
                    "[%s] Context ~%d tokens exceeds trigger %d, summarizing",
                    self.task_id, estimated, trigger,
                )
                messages = summarize_history(
                    self._client, messages, self.config.model
                )

            try:
                response = await self._retry_policy.execute(
                    self._client.messages.create,
                    model=self.config.model,
                    max_tokens=16384,
                    system=system_prompt,
                    messages=messages,
                    tools=tools,
                )
                if self._circuit_breaker:
                    self._circuit_breaker.record_success()
            except anthropic.APIError as exc:
                logger.error("[%s] Anthropic API error: %s", self.task_id, exc)
                if self._circuit_breaker:
                    self._circuit_breaker.record_failure()
                return AgentResult(success=False, error=str(exc))

            self._total_input_tokens += response.usage.input_tokens
            self._total_output_tokens += response.usage.output_tokens

            # Collect text and tool-use blocks from the response
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            # If the model stopped without tool use, we're done
            if response.stop_reason == "end_turn":
                break

            # Process tool calls
            tool_results = []
            for block in assistant_content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input
                tool_id = block.id

                logger.info(
                    "[%s] tool_call: %s(%s)", self.task_id, tool_name, json.dumps(tool_input)[:200]
                )
                self._agent_logger.info(
                    "Tool call: %s", tool_name,
                    extra={
                        "task_id": self.task_id,
                        "agent": self.agent_name,
                        "tool": tool_name,
                        "tool_args": {k: str(v)[:200] for k, v in tool_input.items()},
                    },
                )

                result_text, is_escalation = self._dispatch_tool(tool_name, tool_input)
                if is_escalation:
                    escalation = tool_input
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": "Escalation emitted. Waiting for operator response.",
                    })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_text,
                    })

            messages.append({"role": "user", "content": tool_results})

            if escalation:
                break

        token_usage = {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
        }

        # Compute cost based on pricing config
        pricing = self.config.pricing
        cost_usd = (
            self._total_input_tokens * pricing.input_per_1m_usd
            + self._total_output_tokens * pricing.output_per_1m_usd
        ) / 1_000_000

        if escalation:
            self.store.append_audit(
                self.task_id, self.agent_name, "agent:escalation",
                {"question": escalation.get("question")}
            )
            self._agent_logger.info(
                "Agent escalated",
                extra={
                    "task_id": self.task_id,
                    "agent": self.agent_name,
                    "token_usage": token_usage,
                    "cost_usd": cost_usd,
                },
            )
            return AgentResult(
                success=False,
                escalation=escalation,
                token_usage=token_usage,
                cost_usd=cost_usd,
            )

        output_file = self.get_output_file()
        if output_file:
            out_path = self.workspace / output_file
            if out_path.exists():
                # Validate JSON output files
                if output_file.endswith(".json"):
                    try:
                        json.loads(out_path.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.warning(
                            "[%s] Output %s is not valid JSON: %s",
                            self.task_id, output_file, exc,
                        )
                self.store.register_artifact(
                    self.task_id, output_file, str(out_path)
                )

        self.store.append_audit(
            self.task_id, self.agent_name, "agent:completed",
            {"output_file": output_file, "cost_usd": cost_usd, **token_usage}
        )
        self._agent_logger.info(
            "Agent completed",
            extra={
                "task_id": self.task_id,
                "agent": self.agent_name,
                "token_usage": token_usage,
                "cost_usd": cost_usd,
            },
        )
        return AgentResult(
            success=True,
            output_file=output_file,
            token_usage=token_usage,
            cost_usd=cost_usd,
        )

    # -- tool dispatch --------------------------------------------------------

    def _dispatch_tool(self, name: str, args: dict) -> tuple[str, bool]:
        """Execute a tool and return ``(result_text, is_escalation)``."""
        try:
            match name:
                case "read_file":
                    content = file_tools.read_file(self.workspace, args["path"])
                    return content, False

                case "write_file":
                    written = file_tools.write_file(
                        self.workspace, args["path"], args["content"]
                    )
                    return f"Written: {written}", False

                case "list_files":
                    entries = file_tools.list_files(
                        self.workspace, args.get("path", ".")
                    )
                    return "\n".join(entries), False

                case "run_bash":
                    stdout, stderr, rc = shell_tools.run_bash(
                        self.workspace, args["command"]
                    )
                    parts = []
                    if stdout:
                        parts.append(f"STDOUT:\n{stdout}")
                    if stderr:
                        parts.append(f"STDERR:\n{stderr}")
                    parts.append(f"EXIT CODE: {rc}")
                    result = "\n".join(parts)
                    return result, False

                case "search_code":
                    chunks = search_tools.search_code(
                        self.workspace, args["query"]
                    )
                    if not chunks:
                        return "No matches found.", False
                    lines: list[str] = []
                    for c in chunks:
                        lines.append(
                            f"--- {c.file} (L{c.start_line}-{c.end_line}) ---\n{c.content}"
                        )
                    return "\n\n".join(lines), False

                case "git_commit":
                    sha = git_tools.git_commit(self.workspace, args["message"])
                    return f"Committed: {sha}" if sha else "Nothing to commit.", False

                case "git_diff":
                    diff = git_tools.git_diff(self.workspace)
                    return diff or "No changes.", False

                case "emit_escalation":
                    return "", True

                case _:
                    return f"Unknown tool: {name}", False

        except Exception as exc:
            logger.warning("[%s] Tool %s error: %s", self.task_id, name, exc)
            return f"Error: {exc}", False

"""Structured JSON logging for the AI Dev Crew pipeline.

Each agent logs to ``logs/{task_id}/{agent_name}.jsonl`` — one JSON object per
line.  Sensitive data (API keys) is never logged.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


class JSONLineFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "timestamp": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Attach extra fields injected by agent logging helpers
        for key in ("task_id", "agent", "tool", "tool_args", "token_usage"):
            val = getattr(record, key, None)
            if val is not None:
                obj[key] = val
        if record.exc_info and record.exc_info[0] is not None:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, default=str)


class TaskFileHandler(logging.FileHandler):
    """Handler that writes to ``logs/{task_id}/{agent}.jsonl``."""

    def __init__(self, logs_dir: str | Path, task_id: str, agent_name: str) -> None:
        log_dir = Path(logs_dir) / task_id
        log_dir.mkdir(parents=True, exist_ok=True)
        filepath = log_dir / f"{agent_name}.jsonl"
        super().__init__(str(filepath), encoding="utf-8")
        self.setFormatter(JSONLineFormatter())


def setup_root_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with a JSON formatter for console output."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONLineFormatter())
        root.addHandler(handler)
    root.setLevel(level)


def get_agent_logger(
    logs_dir: str | Path,
    task_id: str,
    agent_name: str,
) -> logging.Logger:
    """Return a logger that writes structured JSON to a per-agent log file.

    The logger is a child of the ``crew.agents`` namespace so that it also
    inherits console handlers set up on the root logger.
    """
    logger_name = f"crew.agents.{agent_name}.{task_id}"
    logger = logging.getLogger(logger_name)

    # Avoid adding duplicate handlers on re-runs
    if not logger.handlers:
        handler = TaskFileHandler(logs_dir, task_id, agent_name)
        logger.addHandler(handler)

    logger.setLevel(logging.DEBUG)
    return logger

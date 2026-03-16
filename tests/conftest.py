"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from crew.config import Config, GatewayConfig
from crew.db.migrate import run_migrations
from crew.db.store import TaskStore


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """Config pointing at temp directories."""
    return Config(
        anthropic_api_key="test-key",
        gateway=GatewayConfig(token="test-token"),
        workspace_root=tmp_path / "workspace",
        db_path=tmp_path / "db" / "test.db",
        model="claude-sonnet-4-20250514",
    )


@pytest.fixture
def store(config: Config) -> TaskStore:
    """A TaskStore backed by a fresh in-memory-like temp DB."""
    config.ensure_dirs()
    run_migrations(config.db_path)
    s = TaskStore(config.db_path)
    s.connect()
    yield s
    s.close()

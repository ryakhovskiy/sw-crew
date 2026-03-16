"""Tests for the config loader."""

from __future__ import annotations

from pathlib import Path

import yaml

from crew.config import load_config


def test_load_default_config(tmp_path: Path):
    """Loading from a non-existent file yields defaults."""
    cfg = load_config(tmp_path / "nope.yaml")
    assert cfg.gateway.port == 8080
    assert cfg.coverage_threshold == 80
    assert cfg.max_debug_attempts == 5


def test_load_from_file(tmp_path: Path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({
        "anthropic_api_key": "sk-test",
        "gateway": {"port": 9999, "token": "my-secret"},
        "coverage_threshold": 90,
    }))
    cfg = load_config(cfg_file)
    assert cfg.anthropic_api_key == "sk-test"
    assert cfg.gateway.port == 9999
    assert cfg.gateway.token == "my-secret"
    assert cfg.coverage_threshold == 90


def test_env_var_override(tmp_path: Path, monkeypatch):
    """Env vars take precedence over config file values."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"anthropic_api_key": "from-file"}))

    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    cfg = load_config(cfg_file)
    assert cfg.anthropic_api_key == "from-env"

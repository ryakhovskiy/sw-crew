"""Configuration loader — YAML file + .env + environment variable overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class GatewayConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    token: str = "change-me"


@dataclass
class ToolsConfig:
    linter: str = "ruff"
    test_runner: str = "pytest"
    security_scanner: str = "bandit"


@dataclass
class Config:
    anthropic_api_key: str = ""
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    workspace_root: Path = Path("workspace")
    repo_root: Path = Path("")
    db_path: Path = Path("db/crew.db")
    model: str = "claude-sonnet-4-20250514"
    coverage_threshold: int = 80
    max_debug_attempts: int = 5
    max_tool_calls: int = 20
    tools: ToolsConfig = field(default_factory=ToolsConfig)

    def ensure_dirs(self) -> None:
        """Create runtime directories if they don't exist."""
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(parents=True, exist_ok=True)


def load_config(path: str | Path | None = None) -> Config:
    """Load configuration from YAML file with env-var overrides.

    Resolution order for the config file path:
      1. Explicit ``path`` argument
      2. ``CREW_CONFIG`` environment variable
      3. ``config.yaml`` in the current working directory
    """
    # Load .env file (no-op if absent); existing env vars take precedence
    load_dotenv(override=False)

    if path is None:
        path = os.environ.get("CREW_CONFIG", "config.yaml")
    path = Path(path)

    raw: dict = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    gw_raw = raw.get("gateway", {})
    gateway = GatewayConfig(
        host=gw_raw.get("host", GatewayConfig.host),
        port=int(gw_raw.get("port", GatewayConfig.port)),
        token=os.environ.get("CREW_TOKEN", gw_raw.get("token", GatewayConfig.token)),
    )

    tools_raw = raw.get("tools", {})
    tools = ToolsConfig(
        linter=tools_raw.get("linter", ToolsConfig.linter),
        test_runner=tools_raw.get("test_runner", ToolsConfig.test_runner),
        security_scanner=tools_raw.get("security_scanner", ToolsConfig.security_scanner),
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", raw.get("anthropic_api_key", ""))

    config = Config(
        anthropic_api_key=api_key,
        gateway=gateway,
        workspace_root=Path(raw.get("workspace_root", "workspace")),
        repo_root=Path(raw.get("repo_root", "")),
        db_path=Path(raw.get("db_path", "db/crew.db")),
        model=raw.get("model", Config.model),
        coverage_threshold=int(raw.get("coverage_threshold", Config.coverage_threshold)),
        max_debug_attempts=int(raw.get("max_debug_attempts", Config.max_debug_attempts)),
        max_tool_calls=int(raw.get("max_tool_calls", Config.max_tool_calls)),
        tools=tools,
    )
    return config

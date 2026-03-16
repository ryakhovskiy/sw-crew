"""Docker sandbox — run agents inside disposable containers."""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import Any

from crew.agents.base import AgentResult
from crew.config import Config, DockerSandboxConfig

logger = logging.getLogger(__name__)


class DockerAgentRunner:
    """Runs an agent inside a Docker container.

    Requires the ``docker`` Python package and access to the Docker daemon
    (via ``/var/run/docker.sock``).
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._sandbox_cfg: DockerSandboxConfig = config.docker_sandbox
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import docker  # type: ignore[import-untyped]
            self._client = docker.from_env()
        return self._client

    async def run_agent(
        self,
        agent_name: str,
        task_id: str,
    ) -> AgentResult:
        """Run an agent in a container and return the result.

        The agent writes its result to ``/workspace/{task_id}/_agent_result.json``.
        """
        client = self._get_client()
        workspace_host = str(Path(self.config.workspace_root).resolve() / task_id)
        result_file = Path(workspace_host) / "_agent_result.json"

        # Clean up any stale result file
        if result_file.exists():
            result_file.unlink()

        # Build container command
        cmd = [
            "python", "-m", "crew.agents.run_single",
            "--agent", agent_name,
            "--task-id", task_id,
        ]

        # Container config
        container_name = f"crew-{agent_name}-{task_id}"[:63]
        volumes = {
            workspace_host: {"bind": f"/app/workspace/{task_id}", "mode": "rw"},
        }

        # Mount config read-only if it exists
        config_path = Path("config.yaml").resolve()
        if config_path.exists():
            volumes[str(config_path)] = {"bind": "/app/config.yaml", "mode": "ro"}

        # Environment: pass API key
        environment = {
            "ANTHROPIC_API_KEY": self.config.anthropic_api_key,
            "CREW_CONFIG": "/app/config.yaml",
        }

        try:
            logger.info(
                "Starting container %s for agent=%s task=%s",
                container_name, agent_name, task_id,
            )

            container = client.containers.run(
                image=self._sandbox_cfg.image,
                command=cmd,
                name=container_name,
                volumes=volumes,
                environment=environment,
                network_mode=self._sandbox_cfg.network_mode,
                mem_limit=self._sandbox_cfg.memory_limit,
                nano_cpus=int(self._sandbox_cfg.cpu_limit * 1e9),
                detach=True,
                auto_remove=False,
            )

            # Wait for completion with timeout
            exit_info = container.wait(timeout=self._sandbox_cfg.timeout)
            exit_code = exit_info.get("StatusCode", -1)
            logs = container.logs(tail=200).decode("utf-8", errors="replace")

            # Clean up container
            with contextlib.suppress(Exception):
                container.remove(force=True)

            if exit_code != 0:
                logger.error(
                    "Container %s exited with code %d: %s",
                    container_name, exit_code, logs[-500:],
                )
                return AgentResult(
                    success=False,
                    error=f"Container exited with code {exit_code}: {logs[-500:]}",
                )

            # Read result from workspace
            if not result_file.exists():
                return AgentResult(
                    success=False,
                    error="Agent did not write result file",
                )

            data = json.loads(result_file.read_text(encoding="utf-8"))
            return AgentResult(
                success=data.get("success", False),
                output_file=data.get("output_file"),
                escalation=data.get("escalation"),
                error=data.get("error"),
                token_usage=data.get("token_usage", {}),
                cost_usd=data.get("cost_usd", 0.0),
            )

        except Exception as exc:
            logger.exception("Docker agent runner failed: %s", exc)
            # Clean up on error
            with contextlib.suppress(Exception):
                client.containers.get(container_name).remove(force=True)
            return AgentResult(success=False, error=f"Docker error: {exc}")

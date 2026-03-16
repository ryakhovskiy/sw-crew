"""FastAPI application factory for the AI Dev Crew Gateway."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from crew.agents.orchestrator import Orchestrator
from crew.config import Config, load_config
from crew.db.migrate import run_migrations
from crew.db.store import TaskStore
from crew.gateway.routes import gates, health, stream, tasks
from crew.logging import setup_root_logging
from crew.notifications import SQLiteNotificationBus

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks: init DB, start orchestrator."""
    setup_root_logging()

    config: Config = app.state.config
    config.ensure_dirs()
    run_migrations(config.db_path)

    store = TaskStore(config.db_path)
    store.connect()
    app.state.store = store

    # Notification bus
    app.state.notification_bus = SQLiteNotificationBus(store)

    orchestrator = Orchestrator(config, store)
    app.state.orchestrator = orchestrator

    # Run the orchestrator loop in the background
    orch_task = asyncio.create_task(orchestrator.run_forever())

    logger.info("Gateway started — listening on %s:%d", config.gateway.host, config.gateway.port)
    yield

    # Shutdown
    orchestrator.stop()
    orch_task.cancel()
    store.close()
    logger.info("Gateway stopped")


def create_app(config: Config | None = None) -> FastAPI:
    """Build and return the FastAPI application."""
    if config is None:
        config = load_config()

    app = FastAPI(
        title="AI Dev Crew Gateway",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.config = config

    # Register API routers
    app.include_router(tasks.router)
    app.include_router(gates.router)
    app.include_router(health.router)
    app.include_router(stream.router)

    # Serve React SPA static files if the build directory exists
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


# Uvicorn entry point: `uvicorn crew.gateway.app:app`
app = create_app()

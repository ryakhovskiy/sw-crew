"""Health check endpoint."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    store = request.app.state.store
    # Basic check: can we query the DB?
    try:
        all_tasks = store.list_tasks()
        db_ok = True
    except Exception:
        all_tasks = []
        db_ok = False

    gateway_ok = True  # if we're serving this, gateway is up
    orchestrator = getattr(request.app.state, "orchestrator", None)
    orch_ok = orchestrator is not None

    overall = "ok" if (db_ok and orch_ok) else "degraded"

    # Extended metrics
    pending_tasks = [t for t in all_tasks if t.status == "pending"]
    running_tasks = [t for t in all_tasks if t.status == "running"]
    done_tasks = [t for t in all_tasks if t.status == "done"]
    failed_tasks = [t for t in all_tasks if t.status == "failed"]

    active_agents = list({t.agent for t in running_tasks if t.agent})
    total_cost = sum(t.total_cost_usd for t in all_tasks)

    # Circuit breaker states
    cb_states: dict[str, str] = {}
    if orchestrator:
        for name, cb in orchestrator._circuit_breakers.items():
            cb_states[name] = cb.state.value

    # Uptime
    startup_time = getattr(request.app.state, "startup_time", None)
    uptime_seconds = time.time() - startup_time if startup_time else 0

    return {
        "status": overall,
        "gateway": gateway_ok,
        "orchestrator": orch_ok,
        "database": db_ok,
        "queue_depth": len(pending_tasks),
        "active_agents": active_agents,
        "circuit_breakers": cb_states,
        "total_cost_usd": round(total_cost, 4),
        "tasks_completed": len(done_tasks),
        "tasks_failed": len(failed_tasks),
        "uptime_seconds": round(uptime_seconds, 1),
    }

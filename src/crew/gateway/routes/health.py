"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    store = request.app.state.store
    # Basic check: can we query the DB?
    try:
        store.list_tasks()
        db_ok = True
    except Exception:
        db_ok = False

    gateway_ok = True  # if we're serving this, gateway is up
    orchestrator = getattr(request.app.state, "orchestrator", None)
    orch_ok = orchestrator is not None

    overall = "ok" if (db_ok and orch_ok) else "degraded"
    return {
        "status": overall,
        "gateway": gateway_ok,
        "orchestrator": orch_ok,
        "database": db_ok,
    }

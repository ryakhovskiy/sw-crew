"""Cost metrics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from crew.gateway.auth import verify_token

router = APIRouter(dependencies=[Depends(verify_token)])


@router.get("/tasks/{task_id}/costs")
async def task_costs(task_id: str, request: Request):
    """Return per-agent cost breakdown for a task."""
    store = request.app.state.store
    task = store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    breakdown = store.get_cost_breakdown(task_id)
    total = sum(entry["cost_usd"] for entry in breakdown)

    return {
        "task_id": task_id,
        "total_usd": total,
        "agents": breakdown,
    }

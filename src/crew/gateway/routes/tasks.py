"""Task CRUD routes."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from crew.gateway.auth import verify_token

router = APIRouter(dependencies=[Depends(verify_token)])


class TaskCreate(BaseModel):
    title: str | None = None
    body: str


class TaskResponse(BaseModel):
    task_id: str


@router.post("/tasks", response_model=TaskResponse)
async def create_task(payload: TaskCreate, request: Request):
    store = request.app.state.store
    title = payload.title or payload.body[:80]
    task_id = store.create_task(title, payload.body)

    # Trigger orchestrator to pick up the new task
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator:
        asyncio.create_task(orchestrator.process_task(task_id))

    return TaskResponse(task_id=task_id)


@router.get("/tasks")
async def list_tasks(request: Request, status: str | None = None):
    store = request.app.state.store
    tasks = store.list_tasks(status=status)
    return [
        {
            "id": t.id,
            "title": t.title,
            "phase": t.phase,
            "status": t.status,
            "agent": t.agent,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
            "debug_attempts": t.debug_attempts,
        }
        for t in tasks
    ]


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request):
    store = request.app.state.store
    task = store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    artifacts = store.list_artifacts(task_id)
    gates = store.list_gates()
    task_gates = [g for g in gates if g.task_id == task_id]

    return {
        "id": task.id,
        "title": task.title,
        "body": task.body,
        "phase": task.phase,
        "status": task.status,
        "agent": task.agent,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "debug_attempts": task.debug_attempts,
        "artifacts": [
            {"name": a.name, "path": a.path, "created_at": a.created_at}
            for a in artifacts
        ],
        "gates": [
            {
                "id": g.id,
                "type": g.type,
                "status": g.status,
                "question": g.question,
                "answer": g.answer,
                "comment": g.comment,
                "reason": g.reason,
                "created_at": g.created_at,
                "resolved_at": g.resolved_at,
            }
            for g in task_gates
        ],
    }


@router.get("/tasks/{task_id}/artifacts/{name}")
async def get_artifact(task_id: str, name: str, request: Request):
    store = request.app.state.store
    artifact = store.get_artifact(task_id, name)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    file_path = Path(artifact.path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing")

    return FileResponse(str(file_path), filename=name)

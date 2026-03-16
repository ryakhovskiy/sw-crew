"""SSE stream endpoint — real-time pipeline events for a task."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from crew.gateway.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_token)])


@router.get("/stream/{task_id}")
async def stream_task(task_id: str, request: Request):
    """Server-Sent Events stream for a specific task.

    Event types emitted:
    - ``phase:change``  — task phase transition
    - ``agent:log``     — agent log line
    - ``gate:pending``  — human gate created
    - ``task:done``     — task completed
    - ``task:failed``   — task failed
    """
    store = request.app.state.store

    async def event_generator():
        last_id = 0
        while True:
            # Check if the client disconnected
            if await request.is_disconnected():
                break

            # Poll notifications from the store (works with or without bus)
            notifications = store.get_unconsumed_notifications(task_id, since_id=last_id)
            for n in notifications:
                payload = json.loads(n.payload) if n.payload else {}
                data = json.dumps({"task_id": n.task_id, **payload})
                yield f"event: {n.event}\ndata: {data}\n\n"
                last_id = max(last_id, n.id)

            # Check if task is in a terminal state
            task = store.get_task(task_id)
            if task and task.phase in ("DONE", "FAILED"):
                # Send final event and close
                data_payload = json.dumps({"task_id": task_id, "phase": task.phase})
                yield f"event: stream:end\ndata: {data_payload}\n\n"
                break

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

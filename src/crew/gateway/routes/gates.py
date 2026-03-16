"""Gate resolution routes — approve, reject, answer."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from crew.gateway.auth import verify_token

router = APIRouter(dependencies=[Depends(verify_token)])


class ApproveRequest(BaseModel):
    comment: str | None = None


class RejectRequest(BaseModel):
    reason: str


class AnswerRequest(BaseModel):
    message: str


@router.get("/gates")
async def list_gates(request: Request, status: str | None = None):
    store = request.app.state.store
    gates = store.list_gates(status=status)
    return [
        {
            "id": g.id,
            "task_id": g.task_id,
            "type": g.type,
            "status": g.status,
            "artifact": g.artifact,
            "question": g.question,
            "answer": g.answer,
            "comment": g.comment,
            "reason": g.reason,
            "created_at": g.created_at,
            "resolved_at": g.resolved_at,
        }
        for g in gates
    ]


@router.post("/gates/{gate_id}/approve")
async def approve_gate(gate_id: str, payload: ApproveRequest, request: Request):
    store = request.app.state.store
    gate = store.get_gate(gate_id)
    if not gate:
        raise HTTPException(status_code=404, detail="Gate not found")
    if gate.status != "pending":
        raise HTTPException(status_code=400, detail=f"Gate already resolved: {gate.status}")

    store.resolve_gate(gate_id, "approved", comment=payload.comment, operator="cli")
    return {"ok": True}


@router.post("/gates/{gate_id}/reject")
async def reject_gate(gate_id: str, payload: RejectRequest, request: Request):
    store = request.app.state.store
    gate = store.get_gate(gate_id)
    if not gate:
        raise HTTPException(status_code=404, detail="Gate not found")
    if gate.status != "pending":
        raise HTTPException(status_code=400, detail=f"Gate already resolved: {gate.status}")

    store.resolve_gate(gate_id, "rejected", reason=payload.reason, operator="cli")
    return {"ok": True}


@router.post("/gates/{gate_id}/answer")
async def answer_gate(gate_id: str, payload: AnswerRequest, request: Request):
    store = request.app.state.store
    gate = store.get_gate(gate_id)
    if not gate:
        raise HTTPException(status_code=404, detail="Gate not found")
    if gate.status != "pending":
        raise HTTPException(status_code=400, detail=f"Gate already resolved: {gate.status}")

    store.resolve_gate(gate_id, "answered", answer=payload.message, operator="cli")
    return {"ok": True}

"""Approval queue — FastAPI service + Redis-backed pending list.

Time-boxed approval (default 15 min in-incident, 4 h scheduled) with
default-deny on timeout. Pre-approved templates are versioned policy
artifacts, not shortcuts.
"""

import json
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class ApprovalRequest(BaseModel):
    action_name: str
    params: dict
    tenant: str
    actor: str
    trace_id: str
    reason: str
    bundle_version: str
    ttl_seconds: int = 900  # 15 minutes default


class ApprovalDecision(BaseModel):
    approver: str
    decision: str  # "approve" or "deny"
    note: str = ""


class ApprovalQueue:
    def __init__(self, redis):
        self.redis = redis

    def enqueue(self, req: ApprovalRequest) -> str:
        approval_id = str(uuid.uuid4())
        record = {
            "id": approval_id,
            "request": req.model_dump(),
            "enqueued_at": int(time.time()),
            "status": "pending",
        }
        key = f"approval:{approval_id}"
        self.redis.set(key, json.dumps(record), ex=req.ttl_seconds)
        self.redis.zadd(
            "approval:pending",
            {approval_id: int(time.time()) + req.ttl_seconds},
        )
        return approval_id

    def get(self, approval_id: str) -> Optional[dict]:
        raw = self.redis.get(f"approval:{approval_id}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def list_pending(self) -> list[dict]:
        ids = self.redis.zrange("approval:pending", 0, -1)
        out = []
        for i in ids:
            if isinstance(i, bytes):
                i = i.decode("utf-8")
            r = self.get(i)
            if r and r["status"] == "pending":
                out.append(r)
        return out

    def decide(self, approval_id: str, decision: ApprovalDecision) -> dict:
        record = self.get(approval_id)
        if record is None:
            raise KeyError("approval not found or expired (default deny)")
        if record["status"] != "pending":
            raise ValueError(f"approval already in status {record['status']}")
        record["status"] = decision.decision
        record["decided_by"] = decision.approver
        record["decided_at"] = int(time.time())
        record["note"] = decision.note
        self.redis.set(f"approval:{approval_id}", json.dumps(record))
        self.redis.zrem("approval:pending", approval_id)
        return record


def build_app(queue: ApprovalQueue) -> FastAPI:
    app = FastAPI(title="Bounded Autonomy — Approval Queue")

    @app.get("/pending")
    def list_pending() -> list[dict]:
        return queue.list_pending()

    @app.post("/approvals")
    def enqueue(req: ApprovalRequest) -> dict:
        approval_id = queue.enqueue(req)
        return {"approval_id": approval_id}

    @app.get("/approvals/{approval_id}")
    def get(approval_id: str) -> dict:
        record = queue.get(approval_id)
        if record is None:
            raise HTTPException(404, "approval not found or expired (default deny)")
        return record

    @app.post("/approvals/{approval_id}/decide")
    def decide(approval_id: str, decision: ApprovalDecision) -> dict:
        try:
            return queue.decide(approval_id, decision)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    return app

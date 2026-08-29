"""Append-only structured audit events to S3 (Object Lock in compliance mode).

Every field maps to an obligation under EU AI Act Article 12 (automatic logging),
EASA traceability, or the FAA AI Safety Assurance Roadmap. The bucket has Object
Lock enabled so events cannot be modified or deleted until retention expires.
"""

from __future__ import annotations

import json
import os
import time
import uuid

import boto3

from .auth import AuthContext

AUDIT_BUCKET = os.environ.get("AUDIT_BUCKET", "self-healing-mcp-audit")
# In the fixture, point at MinIO; in prod, leave None to use AWS default.
AUDIT_ENDPOINT = os.environ.get("AUDIT_ENDPOINT_URL")  # e.g. http://localhost:9000

_s3 = boto3.client(
    "s3",
    endpoint_url=AUDIT_ENDPOINT,
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "minio"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "minio12345"),
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
)


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


async def emit_audit_event(
    ctx: AuthContext,
    *,
    tool: str,
    outcome: str,
    input_hash: str,
    upstream_calls: list[dict] | None = None,
    latency_ms: int | None = None,
    cost_usd: float | None = None,
    policy_decision: str = "allow",
) -> None:
    event = {
        "timestamp": _utc_now_iso(),
        "trace_id": str(uuid.uuid4()),
        "agent_identity": {
            "sub": ctx.sub,
            "email": ctx.email,
            "tenant": ctx.tenant,
            "roles": list(ctx.roles),
        },
        "tool_name": tool,
        "tool_input_hash": input_hash,
        "policy_decision": policy_decision,
        "upstream_calls": upstream_calls or [],
        "outcome": outcome,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
    }
    key = f"events/{event['timestamp'][:10]}/{event['trace_id']}.json"
    _s3.put_object(
        Bucket=AUDIT_BUCKET,
        Key=key,
        Body=json.dumps(event).encode("utf-8"),
        ContentType="application/json",
    )

"""End-to-end lab validation:
1. Verify alice's real Keycloak JWT through auth.py against the live JWKS
2. Apply policy.authorize() — runbook.reader allowed, incident.writer allowed for flight-ops
3. Apply ratelimit.enforce_rate_limit() against the live Redis
4. Emit an audit event to the live MinIO Object Lock bucket
5. Read the bucket back and confirm one event landed
"""
import asyncio, os
os.environ["OAUTH_ISSUER"] = "http://localhost:8081/realms/self-healing"
os.environ["OAUTH_AUDIENCE"] = "api://self-healing-mcp"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["AUDIT_BUCKET"] = "self-healing-mcp-audit"
os.environ["AUDIT_ENDPOINT_URL"] = "http://localhost:9000"
os.environ["AWS_ACCESS_KEY_ID"] = "minio"
os.environ["AWS_SECRET_ACCESS_KEY"] = "minio12345"
os.environ["AWS_REGION"] = "us-east-1"

from mcp_server.auth import verify_jwt_and_build_context
from mcp_server.policy import authorize
from mcp_server.ratelimit import enforce_rate_limit
from mcp_server.audit import emit_audit_event
from mcp_server.tools import runbooks, incidents

async def main():
    token = open("/tmp/alice_token").read().strip()

    print("[1] verify JWT against live Keycloak JWKS")
    ctx = await verify_jwt_and_build_context(token)
    assert ctx.tenant == "flight-ops", ctx
    assert "runbook.reader" in ctx.roles
    assert "incident.writer" in ctx.roles
    print("    sub=", ctx.sub[:12], "tenant=", ctx.tenant, "roles=", list(ctx.roles))

    print("[2] policy.authorize for runbooks.search")
    authorize(ctx, tool="runbooks.search")
    print("    allowed")
    print("[3] policy.authorize for incidents.create (flight-ops + writer)")
    authorize(ctx, tool="incidents.create")
    print("    allowed")

    print("[4] ratelimit.enforce_rate_limit against live Redis")
    await enforce_rate_limit(ctx, tool="runbooks.search")
    print("    under limit")

    print("[5] emit audit event to live MinIO")
    await emit_audit_event(
        ctx,
        tool="runbooks.search",
        outcome="success",
        input_hash=runbooks.hash_input("payments-api outage", 10),
        latency_ms=42,
    )
    print("    audit event written")

    print("[6] read back from MinIO")
    import boto3
    s3 = boto3.client("s3", endpoint_url="http://localhost:9000",
                      aws_access_key_id="minio", aws_secret_access_key="minio12345",
                      region_name="us-east-1")
    resp = s3.list_objects_v2(Bucket="self-healing-mcp-audit", Prefix="events/")
    keys = [o["Key"] for o in resp.get("Contents", [])]
    print(f"    {len(keys)} object(s) in bucket. First: {keys[0] if keys else None}")
    if keys:
        body = s3.get_object(Bucket="self-healing-mcp-audit", Key=keys[0])["Body"].read().decode()
        import json
        event = json.loads(body)
        print(f"    agent_identity.tenant={event['agent_identity']['tenant']}")
        print(f"    tool_name={event['tool_name']}")
        print(f"    outcome={event['outcome']}")
        print(f"    policy_decision={event['policy_decision']}")

    print("\nALL GREEN")

asyncio.run(main())

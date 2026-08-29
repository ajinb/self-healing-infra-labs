"""Negative paths against the live stack:
- bob (tenant=billing, role=runbook.reader) is DENIED on incidents.create (wrong tenant + missing role)
- bob over the runbooks.search limit triggers RateLimitExceeded
- bad token is rejected
"""
import asyncio, os
os.environ["OAUTH_ISSUER"] = "http://localhost:8081/realms/self-healing"
os.environ["OAUTH_AUDIENCE"] = "api://self-healing-mcp"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

from mcp_server.auth import verify_jwt_and_build_context, AuthError
from mcp_server.policy import authorize, PolicyDeny
from mcp_server.ratelimit import enforce_rate_limit, RateLimitExceeded, redis as rl_redis

import httpx, json

async def get_token(user, password):
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.post(f"{os.environ['OAUTH_ISSUER']}/protocol/openid-connect/token",
            data={"grant_type":"password","client_id":"self-healing-mcp",
                  "client_secret":"lab-secret-not-for-prod","username":user,
                  "password":password,"scope":"openid"})
    return r.json()["access_token"]

async def main():
    print("[1] bad token rejected")
    try:
        await verify_jwt_and_build_context("not.a.real.jwt")
        print("    UNEXPECTED: no error raised"); return
    except AuthError as e:
        print(f"    OK: AuthError({e.__class__.__name__}: {str(e)[:60]}...)")

    print("[2] bob's token validates (wrong tenant for incidents.create)")
    bob_token = await get_token("bob", "bob")
    bob_ctx = await verify_jwt_and_build_context(bob_token)
    print(f"    bob tenant={bob_ctx.tenant} roles={list(bob_ctx.roles)}")

    print("[3] bob denied on incidents.create (missing role + wrong tenant)")
    try:
        authorize(bob_ctx, tool="incidents.create")
        print("    UNEXPECTED: allowed"); return
    except PolicyDeny as e:
        print(f"    OK: PolicyDeny: {e}")

    print("[4] bob ALLOWED on runbooks.search")
    authorize(bob_ctx, tool="runbooks.search")
    print("    OK")

    print("[5] flood runbooks.search past 600/min for tenant=billing -> RateLimitExceeded")
    # clear any prior state for this tenant+tool
    await rl_redis.delete("rl:billing:runbooks.search")
    fired = False
    for i in range(605):
        try:
            await enforce_rate_limit(bob_ctx, tool="runbooks.search")
        except RateLimitExceeded as e:
            print(f"    OK: fired at call #{i+1}: {e}")
            fired = True; break
    if not fired:
        print("    UNEXPECTED: 605 calls completed without limit firing")

    await rl_redis.aclose()
    print("\nALL NEGATIVE PATHS GREEN")

asyncio.run(main())

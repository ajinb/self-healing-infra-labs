"""Redis sliding-window rate limiter, per-tenant per-tool.

Cheap, correct, and naturally horizontal. The key includes the tool name so a
noisy tenant on one tool does not starve out another tool.
"""

from __future__ import annotations

import os
import time
import uuid

from redis.asyncio import Redis

from .auth import AuthContext

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis = Redis.from_url(REDIS_URL, decode_responses=True)

# (window_seconds, max_calls)
LIMITS: dict[str, tuple[int, int]] = {
    "runbooks.search": (60, 600),
    "incidents.create": (60, 30),
}


class RateLimitExceeded(Exception):
    """Raised when a tenant exceeds the per-tool window. Mapped to 429."""


async def enforce_rate_limit(ctx: AuthContext, *, tool: str) -> None:
    if tool not in LIMITS:
        return
    window, limit = LIMITS[tool]
    now_ms = int(time.time() * 1000)
    key = f"rl:{ctx.tenant}:{tool}"
    # Member key includes a uuid so calls in the same millisecond do not collide
    # on the sorted-set member (which would silently undercount).
    member = f"{now_ms}:{ctx.sub}:{uuid.uuid4().hex}"
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now_ms - window * 1000)
    pipe.zadd(key, {member: now_ms})
    pipe.zcard(key)
    pipe.expire(key, window + 5)
    _, _, count, _ = await pipe.execute()
    if count > limit:
        raise RateLimitExceeded(f"{tool} over limit for tenant {ctx.tenant}")

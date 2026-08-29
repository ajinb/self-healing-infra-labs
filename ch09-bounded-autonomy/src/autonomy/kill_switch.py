"""Kill-switch service — three scopes (action, tenant, global) with
recovery procedures rehearsed quarterly.

The kill-switch is the panic button. Every check is a single Redis EXISTS
call; the cost must be sub-millisecond because the runner consults it
before every action on the hot path.
"""

import json
import time
from typing import Optional


class KillSwitch:
    def __init__(self, redis):
        self.redis = redis

    def trip(
        self,
        scope: str,
        reason: str,
        actor: str,
        until_unix: Optional[int] = None,
    ) -> None:
        """Trip the kill-switch for a scope. `until_unix` is an automatic
        recovery time; default tenant TTL is 4h, default global has no TTL
        (must be reset manually by two operators)."""
        key = f"killswitch:{scope}"
        record = {
            "reason": reason,
            "tripped_by": actor,
            "tripped_at": int(time.time()),
        }
        if until_unix is not None:
            ttl = max(1, until_unix - int(time.time()))
            self.redis.set(key, json.dumps(record), ex=ttl)
        else:
            self.redis.set(key, json.dumps(record))
        self._audit("trip", scope, actor, reason)

    def is_tripped(self, scope: str) -> bool:
        return bool(self.redis.exists(f"killswitch:{scope}"))

    def reset(self, scope: str, actor: str, second_actor: Optional[str] = None) -> None:
        """Reset a kill-switch. Global reset requires a second operator
        (four-eyes principle)."""
        if scope == "global" and not second_actor:
            raise PermissionError("global kill-switch reset requires a second operator")
        if scope == "global" and second_actor == actor:
            raise PermissionError("global reset requires two distinct operators")
        self.redis.delete(f"killswitch:{scope}")
        self._audit(
            "reset",
            scope,
            actor,
            f"reset (second_actor={second_actor})" if second_actor else "reset",
        )

    def info(self, scope: str) -> Optional[dict]:
        raw = self.redis.get(f"killswitch:{scope}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def _audit(self, op: str, scope: str, actor: str, reason: str) -> None:
        # In production this writes to the same audit sink as the Ch 8 runner.
        # The lab keeps an in-process trail on the Redis instance for
        # introspection from tests.
        event = {
            "op": op,
            "scope": scope,
            "actor": actor,
            "reason": reason,
            "ts": int(time.time()),
        }
        self.redis.rpush("killswitch:audit", json.dumps(event))

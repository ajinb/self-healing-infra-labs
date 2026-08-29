"""OAuth 2.1 JWT verification + CABP AuthContext.

Verifies inbound user tokens against the configured OIDC issuer's JWKS.
Builds the per-request AuthContext that policy, rate limit, audit, and
tools all read from.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx
from jose import jwt


@dataclass(frozen=True)
class AuthContext:
    sub: str
    email: str
    tenant: str
    roles: tuple[str, ...]
    deadline_ms: int  # ATBA: chain-wide deadline carried in context

    def roles_include(self, role: str) -> bool:
        return role in self.roles


OAUTH_ISSUER = os.environ.get(
    "OAUTH_ISSUER",
    "http://localhost:8081/realms/self-healing",  # Keycloak fixture default
)
JWKS_URL = f"{OAUTH_ISSUER}/protocol/openid-connect/certs"
EXPECTED_AUDIENCE = os.environ.get("OAUTH_AUDIENCE", "api://self-healing-mcp")
DEFAULT_CHAIN_DEADLINE_MS = int(os.environ.get("CHAIN_DEADLINE_MS", "5000"))

_jwks_cache: dict | None = None
_jwks_expiry: float = 0.0
_JWKS_TTL_SECONDS = 600


class AuthError(Exception):
    """Raised on any auth failure; mapped to 401 by the server."""


async def _get_jwks() -> dict:
    global _jwks_cache, _jwks_expiry
    if _jwks_cache and time.monotonic() < _jwks_expiry:
        return _jwks_cache
    async with httpx.AsyncClient(timeout=2.0) as c:
        r = await c.get(JWKS_URL)
        r.raise_for_status()
    _jwks_cache = r.json()
    _jwks_expiry = time.monotonic() + _JWKS_TTL_SECONDS
    return _jwks_cache


async def verify_jwt_and_build_context(token: str) -> AuthContext:
    if not token:
        raise AuthError("missing bearer token")
    try:
        jwks = await _get_jwks()
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=EXPECTED_AUDIENCE,
            issuer=OAUTH_ISSUER,
            options={"verify_at_hash": False},
        )
    except Exception as e:  # jose-specific errors get normalized
        raise AuthError(f"invalid token: {e}") from e

    if "tenant" not in claims:
        raise AuthError("token missing required tenant claim")

    return AuthContext(
        sub=claims["sub"],
        email=claims.get("email", ""),
        tenant=claims["tenant"],
        roles=tuple(claims.get("roles", [])),
        deadline_ms=int(time.monotonic() * 1000) + DEFAULT_CHAIN_DEADLINE_MS,
    )

# Integration Tests — opt-in

These tests run against the live `fixtures/docker-compose.yaml` stack (Keycloak + Redis + MinIO).
They are NOT included in the default `pytest -q` run.

## How to run

```bash
# 1. bring up the fixture stack (Keycloak realm + Redis + MinIO with Object Lock)
docker compose -f fixtures/docker-compose.yaml up -d

# 2. wait for Keycloak (takes 25-40s on first boot)
until curl -sf http://localhost:8081/realms/self-healing/.well-known/openid-configuration; do sleep 3; done

# 3. mint alice's token
curl -s -X POST 'http://localhost:8081/realms/self-healing/protocol/openid-connect/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=password' -d 'client_id=self-healing-mcp' \
  -d 'client_secret=lab-secret-not-for-prod' \
  -d 'username=alice' -d 'password=alice' -d 'scope=openid' \
  | python3 -c 'import json, sys; open("/tmp/alice_token","w").write(json.load(sys.stdin)["access_token"])'

# 4. run integration tests
.venv/bin/python tests/integration/test_e2e_happy_path.py
.venv/bin/python tests/integration/test_e2e_negative_paths.py

# 5. tear down
docker compose -f fixtures/docker-compose.yaml down -v
```

## What they validate

**Happy path (`test_e2e_happy_path.py`)**:
1. Real JWT from Keycloak verified against live JWKS through `auth.py`
2. `policy.authorize()` allows alice's `runbooks.search` and `incidents.create`
3. `enforce_rate_limit()` against live Redis: under limit
4. `emit_audit_event()` writes a JSON event to the live MinIO Object Lock bucket
5. Read-back from bucket — event has the correct `agent_identity`, `tool_name`, `policy_decision`

**Negative paths (`test_e2e_negative_paths.py`)**:
1. Bad token rejected by `verify_jwt_and_build_context`
2. Bob's token validates (tenant=billing, role=runbook.reader)
3. Bob denied on `incidents.create` by `policy.authorize` (wrong tenant)
4. Bob allowed on `runbooks.search`
5. Flooding past the 600/min `runbooks.search` limit fires `RateLimitExceeded` at call #601

These tests gate-keep the lab claims in Chapter 4: every code snippet in the chapter
has a real, tested execution against real Keycloak/Redis/MinIO behind it.

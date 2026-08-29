# self-healing-infra-labs

Companion code for the book **_Self-Healing Infrastructure: Building Autonomous
Cloud Systems with AI_** by Ajin Baby.

Every lab in the book lives here, in a directory matching its chapter number.
Each one is self-contained: its own `README.md`, `pyproject.toml`, fixtures, and
tests. Each runs on a laptop — no corporate cloud account, no paid
identity-provider tenant.

## The labs

| Lab | Chapter | What it is |
|---|---|---|
| [`ch04-mcp-production/`](ch04-mcp-production/) | 4 | A production MCP server: OAuth 2.1, per-tool RBAC, per-tenant rate limiting, and an immutable audit trail |
| [`ch05-alert-explainer/`](ch05-alert-explainer/) | 5 | Alert enrichment that keeps paging when the model provider is down |
| [`ch06-incident-scribe/`](ch06-incident-scribe/) | 6 | A blameless postmortem drafted from an incident thread |
| [`ch07-sre-agent/`](ch07-sre-agent/) | 7 | A three-agent investigation system with a human review gate |
| [`ch08-closed-loop-remediation/`](ch08-closed-loop-remediation/) | 8 | A remediator that acts behind a reversibility gate and rolls back when a probe says the world got worse |
| [`ch09-bounded-autonomy/`](ch09-bounded-autonomy/) | 9 | A policy contract with per-action budgets, an approval queue, and a kill switch |

## Prerequisites

- **Python 3.11+** (3.12 recommended; CI runs 3.12)
- **Docker** and **docker compose** for the labs that need backing services
- An **API key** for an LLM provider where a lab calls one. Each lab reads it
  from the environment and names the variable in its own README.

Per-lab prerequisites are listed in each lab's README and in the corresponding
chapter of the book. Nothing here requires a cloud account.

## Running a lab

```bash
cd ch05-alert-explainer
python3.12 -m venv ~/.venvs/ch05-alert-explainer
source ~/.venvs/ch05-alert-explainer/bin/activate
pip install -e '.[dev]'
pytest
```

Keep the virtualenv outside the working tree if your checkout sits in a synced
folder (iCloud Drive, Dropbox, OneDrive). File-sync daemons corrupt editable
installs, and the failure looks like an unrelated import error.

## If a lab does not run

That is a defect, and I would like to know. **Open an issue** — it is the
fastest route to a fix. Include your Python version, the lab, and the failing
output.

## License

The code in this repository is **MIT-licensed** (see [LICENSE](LICENSE)). Use it
in your own systems, commercial or otherwise, without asking.

The book's prose, figures, and cover are not covered by that license; they
remain © 2026 Ajin Baby, all rights reserved.

## Related

- The book: <https://leanpub.com/self-healing-infra-with-ai>
- Longer-form writing on this material: <https://cloudandsre.com>
- Other tooling: <https://github.com/ajinb>

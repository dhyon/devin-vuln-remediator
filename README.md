# Devin Vulnerability Remediator

A small event-driven vulnerability remediation control plane for a take-home assignment. It accepts GitHub issue label webhooks, starts Devin sessions, polls session insights, tracks remediation jobs in SQLite, comments back on GitHub issues, and exposes a simple dashboard and report.

## Quick Demo

```bash
docker-compose up
```

Then open:

- Health: http://localhost:8000/health
- Dashboard: http://localhost:8000/dashboard
- Metrics: http://localhost:8000/metrics
- Report: http://localhost:8000/report

Seed demo issues:

```bash
curl -X POST http://localhost:8000/demo/seed
```

Simulate the primary trigger without credentials:

```bash
curl -X POST http://localhost:8000/demo/simulate-webhook
curl -X POST http://localhost:8000/poll
```

The Docker Compose path runs with `APP_MODE=demo`, `DEVIN_MODE=mock`, and `GITHUB_MODE=mock`, so it does not require `DEVIN_API_KEY` or `GITHUB_TOKEN`. It uses SQLite storage in a Docker volume and seeds sample remediation jobs on startup.

Reviewer flow:

```bash
docker-compose up
```

Open http://localhost:8000/dashboard.

Seed or reset demo data:

```bash
curl -X POST http://localhost:8000/demo/seed
```

Simulate a GitHub issue receiving the `devin-remediate` label:

```bash
curl -X POST http://localhost:8000/demo/simulate-webhook
```

Advance mock Devin sessions:

```bash
curl -X POST http://localhost:8000/poll
```

## Real Mode

Set real credentials and disable demo mode:

```bash
export DEMO_MODE=false
export APP_MODE=real
export DEVIN_MODE=real
export GITHUB_MODE=real
export GITHUB_WEBHOOK_SECRET="your-webhook-secret"
export GITHUB_TOKEN="github-token-with-issue-comment-permission"
export DEVIN_API_KEY="your-devin-api-key"
export DEVIN_ORG_ID="your-devin-org-id"
export DEVIN_BASE_URL="https://api.devin.ai"
export DEVIN_REPOS="your-user/superset"
# Optional:
# export DEVIN_MAX_ACU_LIMIT=10
# export DEVIN_ENTERPRISE_ANALYTICS=true
export DATABASE_PATH="data/remediator.db"
uvicorn app.main:app --reload
```

Configure a GitHub issue webhook on your forked Apache Superset repository:

- Payload URL: `https://your-host/webhooks/github`
- Content type: `application/json`
- Secret: same value as `GITHUB_WEBHOOK_SECRET`
- Events: issue label events

When an issue receives the label `devin-remediate`, the control plane validates the webhook signature and starts a Devin remediation session.

In real mode, startup validates that `DEVIN_API_KEY`, `DEVIN_ORG_ID`, `GITHUB_TOKEN`, and `GITHUB_WEBHOOK_SECRET` are present. Demo mode intentionally skips those requirements.

## Endpoints

- `GET /health`
- `POST /webhooks/github`
- `POST /poll`
- `GET /metrics`
- `GET /dashboard`
- `GET /report`
- `POST /demo/seed`
- `POST /demo/simulate-webhook`

## Local Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
pytest
uvicorn app.main:app --reload
```

## Scripts

- `scripts/run_bandit_superset.sh` runs Bandit against a Superset checkout.
- `scripts/run_safety_superset.sh` runs `pip-audit` or Safety against a Superset checkout.
- `scripts/create_github_issues_from_findings.py` creates GitHub issues from normalized finding JSON.
- `scripts/simulate_webhook.py` sends a signed GitHub webhook to the local app.
- `scripts/seed_demo_data.py` seeds the demo endpoint.

## Creating Credible Superset Issues

The take-home demo is strongest when the 5 to 8 GitHub issues come from real scanner output or real security-hygiene review findings in your forked Apache Superset repository. Do not invent CVEs or claim exploitability beyond what the scanner or code review supports. `demo/findings.example.json` contains demo templates only; use it for formatting, not as final submission evidence.

Recommended workflow:

1. Fork Apache Superset and clone your fork locally.
2. Run Bandit and a dependency scanner:

```bash
SUPSERSET_REPO_PATH=/path/to/superset bash scripts/run_bandit_superset.sh
SUPSERSET_REPO_PATH=/path/to/superset bash scripts/run_safety_superset.sh
```

The scripts write raw scanner output to:

- `demo/bandit-results.json`
- `demo/dependency-results.json`

3. Curate 5 to 8 real findings into `demo/findings.json`. Use `demo/findings.example.json` as the schema and tone guide, but replace the examples with real affected files, packages, scanner IDs, risks, and verification steps from your fork.
4. Preview issue payloads:

```bash
GITHUB_REPOSITORY=your-user/superset python scripts/create_github_issues_from_findings.py --dry-run
```

5. Create issues in your fork:

```bash
export GITHUB_TOKEN=your-token
export GITHUB_REPOSITORY=your-user/superset
python scripts/create_github_issues_from_findings.py --limit 8
```

Each created issue gets the labels `security`, `devin-remediate`, and `demo`. If your webhook is configured, applying or creating the issue with `devin-remediate` can trigger the control plane automation.

You can filter curated findings by estimated complexity (`small`, `medium`, `large`, or `1` to `3`):

```bash
python scripts/create_github_issues_from_findings.py --dry-run --min-complexity small --max-complexity medium
```

## Design Notes

This intentionally avoids Celery, Redis, Kafka, React, and a workflow engine. The control plane is a FastAPI app with SQLite and a manual `/poll` endpoint, which keeps it simple enough to review while still showing production-shaped concerns: authenticated webhooks, idempotent job creation, session lifecycle tracking, comments, metrics, and demo-safe clients.

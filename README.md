# Devin Vulnerability Remediation Control Plane

## Problem

Regulated engineering organizations accumulate CVE and security-finding backlogs faster than product teams can reliably burn them down. Security scanners and review programs are good at finding issues, but remediation work often sits outside sprint planning, competes with roadmap work, and creates growing audit pressure.

Manual remediation is also repetitive: inspect the finding, understand the repository context, make the narrow code or dependency change, run checks, open a PR, and report status. That work is automatable, but it still requires codebase awareness and test discipline.

## Solution

This project is a small remediation control plane for Devin-driven vulnerability work:

- A GitHub issue with the `devin-remediate` label triggers a remediation job.
- The app starts a Devin session with repository, issue, acceptance, and non-goal context.
- Devin investigates, patches, runs focused checks where practical, and opens a reviewable PR.
- The control plane tracks job status, Devin sessions, PRs, failures, ACUs, and throughput in SQLite.
- The dashboard, metrics endpoint, and report endpoint answer the operational question: is this automation working?

This is intentionally a focused take-home implementation: FastAPI, SQLite, Docker Compose, GitHub webhooks, Devin API clients, mock demo mode, and tests. It is production-shaped, not production-complete.

## Architecture

```text
        GitHub issue labeled "devin-remediate"
                         |
                         v
                POST /webhooks/github
                         |
          signature validation + event parsing
                         |
                         v
                 remediation_jobs table
                         |
                         v
              Devin session creation API
                         |
                         v
         Devin investigates, patches, tests, opens PR
                         |
                         v
                  POST /poll or scheduler
                         |
          Devin insights + optional ACU consumption
                         |
                         v
        SQLite status, PR URL, failures, local events
                         |
             +-----------+-----------+
             |                       |
             v                       v
      /dashboard, /metrics       GitHub issue comments
          and /report
```

Implemented components:

- `app/main.py`: FastAPI routes for webhooks, polling, dashboard, metrics, report, and demo controls.
- `app/github_webhook.py`: GitHub issue-event parsing and HMAC signature validation.
- `app/devin_client.py`: real and mock Devin session clients.
- `app/analytics_client.py`: Devin session insights and optional enterprise consumption lookup.
- `app/poller.py`: job lifecycle orchestration and GitHub issue comments.
- `app/store.py`: SQLite persistence for remediation jobs and lifecycle events.
- `scripts/`: Superset scanner helpers, curated issue creation, demo seeding, and webhook simulation.

## Why Devin

Scanners find vulnerabilities. Ticketing systems route them. Devin is the remediation worker: it can inspect the repository, understand context, make the code change, run checks, and open a reviewable pull request.

## One-Command Mock Demo

Demo mode does not call external APIs. It uses mock Devin and GitHub clients plus an isolated Docker volume.

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml up --build
```

Open:

```text
http://localhost:8000/dashboard
```

Useful demo commands:

```bash
curl -X POST http://localhost:8000/demo/seed
curl -X POST http://localhost:8000/demo/simulate-webhook
curl -X POST http://localhost:8000/poll
curl http://localhost:8000/metrics
curl http://localhost:8000/report
```

The `/demo/*` endpoints are disabled outside `APP_MODE=demo`.

## Real Mode Setup

The default `docker-compose.yml` runs real mode:

```bash
cp .env.example .env
# Edit .env with real credentials first.
docker compose up --build
```

Required environment variables:

- `GITHUB_WEBHOOK_SECRET`: shared secret used to validate `X-Hub-Signature-256`.
- `GITHUB_TOKEN`: GitHub token with issue comment access and PR read access for the target repo.
- `DEVIN_API_KEY`: Devin API key.
- `DEVIN_ORG_ID`: Devin organization ID.
- `DEVIN_REPOS`: comma-separated repository allowlist, for example `your-github-user/superset`.

Common optional variables:

- `TRIGGER_LABEL`: defaults to `devin-remediate`.
- `DEVIN_MAX_ACU_LIMIT`: optional max ACU limit sent when creating Devin sessions.
- `DEVIN_ENTERPRISE_ANALYTICS`: set `true` to attempt enterprise consumption lookups.
- `POLL_LIMIT`: defaults to `25`.
- `ENGINEER_HOURS_PER_REMEDIATION`: defaults to `2.0`.
- `ENGINEER_HOURLY_COST`: defaults to `150.0`.

Real mode uses SQLite to persist state at `/data/remediator-real.db` inside the container, bind-mounted to `./data` by Compose.

Health check:

```bash
curl http://localhost:8000/health
```

Expected real-mode shape:

```json
{"ok":true,"app_mode":"real","demo_mode":false}
```

For GitHub webhooks, expose the service (http://localhost:8000) with a tunnel such as ngrok and configure:

- Payload URL: `https://<host>/webhooks/github`
- Content type: `application/json`
- Secret: `GITHUB_WEBHOOK_SECRET`
- Events: Issues

## Creating Real Github Issues for Superset Repo

Note: Skip to steps 4 and 5 if you just want to upload the pre-curated issues in `demo/findings.json` to Github.

Recommended workflow:

1. Fork Apache Superset.
2. Run Bandit and a dependency scanner against the fork:

```bash
SUPERSET_REPO_PATH=/path/to/superset bash scripts/run_bandit_superset.sh
SUPERSET_REPO_PATH=/path/to/superset bash scripts/run_safety_superset.sh
```

3. Curate your findings into `demo/findings.json`. Keep scanner output and affected paths grounded in the fork you actually scanned.
4. Preview the GitHub issues:

```bash
python scripts/create_github_issues_from_findings.py --repo your-github-user/superset --dry-run
```

5. Create the issues:

```bash
export GITHUB_TOKEN=your-token
python scripts/create_github_issues_from_findings.py --repo your-github-user/superset --limit 8
```

The script creates issues with `security`, `devin-remediate`, and `demo` labels. If the webhook is configured, creating or labeling those issues triggers Devin sessions.

This repository includes real, curated Superset-style findings and sample scanner output under `demo/`, including `demo/findings.json`, `demo/bandit-results.json`, `demo/dependency-results.json`, and `demo/pip-audit-results.json`.

## Observability

- `GET /dashboard`: operational dashboard with backlog, active sessions, PRs, completion, failures, ACUs, timing, and recent lifecycle events.
- `GET /metrics`: JSON metrics for automation or lightweight reporting.
- `GET /report`: plain-text executive report.
- Devin session insights: status, PR URLs, failures, message counts, session size, and ACUs when available.
- Local lifecycle events: session starts, start failures, comment failures, and recent event history in SQLite.

## Business Impact

The dashboard and report estimate impact from completed remediations using configurable assumptions:

- `ENGINEER_HOURS_PER_REMEDIATION`
- `ENGINEER_HOURLY_COST`

These are not production claims. They are the kind of operating metrics the control plane is designed to surface once connected to real findings and real Devin sessions.

## Limitations

- Human review is required; this system does not auto-merge.
- Polling is exposed as `POST /poll`; a production deployment would typically run it on a schedule.
- Enterprise ACU analytics may require account permissions and can be unavailable.
- Remediation quality depends on scanning quality and acceptance criteria quality.
- Scanner integration is intentionally simple: scripts produce raw output, and humans curate the final issue set.
- SQLite is appropriate for the assignment and local operation, not a multi-region control plane.

## Phase 2

- Scheduled scans.
- Semgrep, Snyk, and GitHub code scanning integrations.
- Jira and Slack integration.
- Policy-based approvals.
- Concurrency limits and queue controls.
- SLA reporting.
- Multi-repo support.

## Testing

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
pytest
```

## Security Notes

- GitHub webhooks are validated with HMAC SHA-256 signatures unless unsigned webhooks are explicitly allowed.
- Demo mode does not call external APIs.
- The app does not intentionally log secrets; keep API keys in environment variables or `.env`.
- Use least-privilege GitHub tokens scoped to the repository and permissions required for issue comments and PR reads.
- Devin credentials are required only in real mode.

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.analytics_client import AnalyticsClient, MockAnalyticsClient
from app.config import settings
from app.dashboard import render_dashboard
from app.devin_client import MockDevinClient, RealDevinClient
from app.github_client import MockGitHubClient, RealGitHubClient
from app.github_webhook import is_remediation_trigger, parse_github_issue_event, validate_github_request
from app.metrics import build_metrics
from app.models import GitHubIssueEvent, SessionInsights
from app.poller import RemediationPoller
from app.store import Store


settings.ensure_paths()
store = Store(settings.database_path)
use_mock_devin = settings.devin_mode == "mock" or settings.demo_mode
devin_client = (
    MockDevinClient()
    if use_mock_devin
    else RealDevinClient(
        api_key=settings.devin_api_key,
        org_id=settings.devin_org_id,
        base_url=settings.devin_api_base_url,
        max_acu_limit=settings.devin_max_acu_limit,
        default_repos=list(settings.devin_repos),
    )
)
analytics_client = (
    MockAnalyticsClient()
    if use_mock_devin
    else AnalyticsClient(
        api_key=settings.devin_api_key,
        org_id=settings.devin_org_id,
        base_url=settings.devin_api_base_url,
        enterprise_consumption_enabled=settings.devin_enterprise_analytics,
    )
)
github_client = MockGitHubClient() if settings.github_mode == "mock" or settings.demo_mode else RealGitHubClient(settings.github_token, settings.github_api_base_url)
poller = RemediationPoller(store, devin_client, analytics_client, github_client)


DEMO_FINDINGS = [
    GitHubIssueEvent(
        action="labeled",
        label=settings.target_label,
        repository="demo/superset",
        issue_number=201,
        issue_title="Bandit: subprocess call uses shell=True",
        issue_body="Replace shell=True with an argument list and add a regression test.",
        issue_url="https://github.com/demo/superset/issues/201",
    ),
    GitHubIssueEvent(
        action="labeled",
        label=settings.target_label,
        repository="demo/superset",
        issue_number=202,
        issue_title="Safety: vulnerable dependency requires patch upgrade",
        issue_body="Upgrade the affected dependency to a patched version.",
        issue_url="https://github.com/demo/superset/issues/202",
    ),
    GitHubIssueEvent(
        action="labeled",
        label=settings.target_label,
        repository="demo/superset",
        issue_number=203,
        issue_title="Security hygiene: secure cookie flag can be disabled",
        issue_body="Keep secure cookies enabled outside local development.",
        issue_url="https://github.com/demo/superset/issues/203",
    ),
    GitHubIssueEvent(
        action="labeled",
        label=settings.target_label,
        repository="demo/superset",
        issue_number=204,
        issue_title="Dependency hygiene: stale transitive package",
        issue_body="Refresh constraints and verify dependency tests.",
        issue_url="https://github.com/demo/superset/issues/204",
    ),
    GitHubIssueEvent(
        action="labeled",
        label=settings.target_label,
        repository="demo/superset",
        issue_number=205,
        issue_title="Semgrep: missing path normalization",
        issue_body="Normalize user-controlled paths before filesystem access.",
        issue_url="https://github.com/demo/superset/issues/205",
    ),
    GitHubIssueEvent(
        action="labeled",
        label=settings.target_label,
        repository="demo/superset",
        issue_number=206,
        issue_title="Failed demo: remediation needs maintainer input",
        issue_body="This seeded demo job represents a failed remediation outcome.",
        issue_url="https://github.com/demo/superset/issues/206",
    ),
]


def seed_demo_control_plane(reset: bool = False) -> int:
    if reset:
        store.clear()
    if store.count_jobs() > 0:
        return 0

    for index, event in enumerate(DEMO_FINDINGS):
        job = store.create_or_get_job(event)
        if index == 0:
            continue

        session_id = f"demo-seed-{event.issue_number}"
        if index == len(DEMO_FINDINGS) - 1:
            session_id = "demo-seed-fail"
        job = store.attach_session(job.id, session_id, f"https://app.devin.ai/sessions/{session_id}")

        if index == 1:
            continue
        if index == 2:
            store.update_from_insights(
                job.id,
                SessionInsights(
                    session_id=session_id,
                    status="running",
                    acu_used=2.1,
                    pr_url="https://github.com/demo/superset/pull/302",
                    pull_requests=["https://github.com/demo/superset/pull/302"],
                ),
            )
            continue
        if index in {3, 4}:
            pr_url = f"https://github.com/demo/superset/pull/{300 + index}"
            store.update_from_insights(
                job.id,
                SessionInsights(
                    session_id=session_id,
                    status="completed",
                    acu_used=3.4 + index,
                    pr_url=pr_url,
                    pull_requests=[pr_url],
                    summary="Demo remediation completed successfully.",
                ),
            )
            continue
        store.update_from_insights(
            job.id,
            SessionInsights(
                session_id=session_id,
                status="failed",
                acu_used=2.8,
                failure_reason="Demo failure: tests exposed a behavior change that needs maintainer input.",
            ),
        )

    return len(DEMO_FINDINGS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.demo_mode:
        seed_demo_control_plane(reset=False)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    return {"ok": True, "app_mode": settings.app_mode, "demo_mode": settings.demo_mode}


@app.post("/webhooks/github")
async def github_webhook(request: Request) -> dict[str, object]:
    body = await validate_github_request(
        request,
        settings.github_webhook_secret,
        allow_unsigned=settings.allow_unsigned_github_webhooks,
    )
    event = parse_github_issue_event(json.loads(body))
    if event is None:
        return {"accepted": False, "reason": "not a GitHub issue event or issue is a pull request"}
    if not is_remediation_trigger(event, settings.target_label):
        return {"accepted": False, "reason": "event is not a remediation trigger"}
    job = await poller.start_remediation(event)
    return {"accepted": True, "job": job.model_dump(mode="json")}


@app.post("/poll")
async def poll() -> dict[str, object]:
    jobs = await poller.poll_once(settings.poll_limit)
    return {"updated": len(jobs), "jobs": [job.model_dump(mode="json") for job in jobs]}


@app.get("/metrics")
async def metrics() -> dict[str, object]:
    return build_metrics(
        store.list_jobs(),
        engineer_hours_per_remediation=settings.engineer_hours_per_remediation,
        engineer_hourly_cost=settings.engineer_hourly_cost,
    ).model_dump()


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    return render_dashboard(
        store.list_jobs(),
        events=store.list_recent_events(),
        demo_mode=settings.demo_mode,
        engineer_hours_per_remediation=settings.engineer_hours_per_remediation,
        engineer_hourly_cost=settings.engineer_hourly_cost,
    )


@app.get("/report", response_class=PlainTextResponse)
async def report() -> str:
    summary = build_metrics(
        store.list_jobs(),
        engineer_hours_per_remediation=settings.engineer_hours_per_remediation,
        engineer_hourly_cost=settings.engineer_hourly_cost,
    )
    return "\n".join(
        [
            "# Devin Vulnerability Remediation Executive Report",
            "",
            f"The control plane is tracking {summary.total_jobs} security findings, with {summary.active_jobs} active Devin sessions and {summary.completed_jobs} completed remediations.",
            f"Devin has opened {summary.pr_created_jobs} remediation PRs with a {summary.success_rate:.0%} success rate across completed or failed jobs.",
            f"Estimated engineering effort avoided: {summary.engineer_hours_avoided:.1f} hours (${summary.estimated_cost_avoided:,.0f}).",
            f"Backlog reduction: {summary.backlog_reduction_percentage:.1f}%. Total ACUs consumed: {summary.total_acus_consumed:.1f}.",
            f"Average time to PR: {format_seconds(summary.average_time_to_pr_seconds)}. Average completion cycle: {format_seconds(summary.average_time_to_completion_seconds)}.",
            "",
            "Operational readout:",
            f"- Waiting for user or approval: {summary.waiting_jobs}",
            f"- Failed jobs requiring review: {summary.failed_jobs}",
            f"- Throughput: {summary.throughput_jobs_per_day:.2f} jobs/day",
        ]
    )


def format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "not yet available"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


@app.post("/demo/seed")
async def seed_demo() -> dict[str, object]:
    seeded = seed_demo_control_plane(reset=True)
    return {"seeded": seeded}


@app.get("/demo/seed")
async def seed_demo_from_browser() -> dict[str, object]:
    seeded = seed_demo_control_plane(reset=True)
    return {"seeded": seeded}


@app.post("/demo/simulate-webhook")
async def simulate_webhook() -> dict[str, object]:
    event = GitHubIssueEvent(
        action="labeled",
        label=settings.target_label,
        repository="demo/superset",
        issue_number=999,
        issue_title="Demo vulnerable dependency hygiene finding",
        issue_body="A scanner found a dependency hygiene issue suitable for automated remediation.",
        issue_url="https://github.com/demo/superset/issues/999",
    )
    job = await poller.start_remediation(event)
    return {"accepted": True, "job": job.model_dump(mode="json")}

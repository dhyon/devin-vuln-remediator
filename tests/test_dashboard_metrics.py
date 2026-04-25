from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.dashboard import render_dashboard
from app.metrics import build_metrics
from app.models import JobStatus, RemediationJob


def job(
    job_id: int,
    status: JobStatus,
    created_at: datetime,
    pr_after: int | None = None,
    completed_after: int | None = None,
    acus: float = 0,
    pr_url: str | None = None,
) -> RemediationJob:
    return RemediationJob(
        id=job_id,
        repository="me/superset",
        issue_number=job_id,
        issue_title=f"Finding {job_id}",
        status=status,
        devin_session_id=f"session-{job_id}",
        devin_session_url=f"https://app.devin.ai/sessions/{job_id}",
        pr_url=pr_url,
        acus_consumed=acus,
        created_at=created_at,
        updated_at=created_at,
        pr_opened_at=created_at + timedelta(seconds=pr_after) if pr_after is not None else None,
        completed_at=created_at + timedelta(seconds=completed_after) if completed_after is not None else None,
    )


def test_metrics_calculate_core_counts_and_rates() -> None:
    base = datetime(2026, 4, 24, 12, tzinfo=UTC)
    metrics = build_metrics(
        [
            job(1, JobStatus.COMPLETED, base, pr_after=300, completed_after=900, acus=3, pr_url="https://github.com/me/superset/pull/1"),
            job(2, JobStatus.FAILED, base, completed_after=1200, acus=2),
            job(3, JobStatus.WAITING_FOR_USER, base, acus=1),
            job(4, JobStatus.RUNNING, base, acus=0.5),
            job(5, JobStatus.PR_OPENED, base, pr_after=400, acus=1.5, pr_url="https://github.com/me/superset/pull/5"),
        ],
        engineer_hours_per_remediation=2.5,
        engineer_hourly_cost=200,
    )

    assert metrics.total_jobs == 5
    assert metrics.active_jobs == 3
    assert metrics.active_devin_sessions == 2
    assert metrics.completed_jobs == 1
    assert metrics.failed_jobs == 1
    assert metrics.waiting_jobs == 1
    assert metrics.pr_created_jobs == 2
    assert metrics.completion_rate == 0.2
    assert metrics.success_rate == 0.5
    assert metrics.total_acus_consumed == 8
    assert metrics.engineer_hours_avoided == 2.5
    assert metrics.estimated_cost_avoided == 500
    assert metrics.backlog_reduction_percentage == 20


def test_metrics_calculate_time_to_pr_and_completion() -> None:
    base = datetime(2026, 4, 24, 12, tzinfo=UTC)
    metrics = build_metrics(
        [
            job(1, JobStatus.COMPLETED, base, pr_after=120, completed_after=600, pr_url="https://github.com/me/superset/pull/1"),
            job(2, JobStatus.COMPLETED, base, pr_after=300, completed_after=900, pr_url="https://github.com/me/superset/pull/2"),
        ]
    )

    assert metrics.average_time_to_pr_seconds == 210
    assert metrics.median_time_to_pr_seconds == 210
    assert metrics.average_time_to_completion_seconds == 750
    assert metrics.average_remediation_cycle_time_seconds == 750
    assert metrics.throughput_jobs_per_day > 0


def test_dashboard_metric_boxes_include_hover_descriptions() -> None:
    html = render_dashboard([job(1, JobStatus.COMPLETED, datetime(2026, 4, 24, 12, tzinfo=UTC), completed_after=600)])

    assert 'class="card metric-box"' in html
    assert 'class="panel metric-box"' in html
    assert 'class="metric-help"' in html
    assert 'class="metric-tooltip" role="tooltip"' in html
    assert 'title="All security findings currently tracked by the control plane."' in html
    assert 'data-description="All security findings currently tracked by the control plane."' in html
    assert "Completed Remediations (PRs Merged)" in html
    assert 'aria-label="Completion rate:' in html


def test_dashboard_includes_manual_poll_action() -> None:
    html = render_dashboard([])

    assert 'id="poll-now"' in html
    assert "Poll Status Now" in html
    assert 'id="poll-status"' in html
    assert 'fetch("/poll", { method: "POST" })' in html
    assert "window.location.reload()" in html

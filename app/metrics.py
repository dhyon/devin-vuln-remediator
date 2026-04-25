from __future__ import annotations

from datetime import UTC, datetime
from statistics import median

from app.models import JobStatus, MetricsSummary, RemediationJob


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round_optional(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def build_metrics(
    jobs: list[RemediationJob],
    engineer_hours_per_remediation: float = 2.0,
    engineer_hourly_cost: float = 150.0,
) -> MetricsSummary:
    total = len(jobs)
    completed = [job for job in jobs if job.status == JobStatus.COMPLETED]
    failed = [job for job in jobs if job.status == JobStatus.FAILED]
    pr_closed = [job for job in jobs if job.status == JobStatus.PR_CLOSED]
    waiting = [
        job
        for job in jobs
        if job.status in {JobStatus.WAITING_FOR_USER, JobStatus.WAITING_FOR_APPROVAL}
        or job.status_detail in {"waiting_for_user", "waiting_for_approval"}
    ]
    active = [
        job
        for job in jobs
        if job.status
        in {
            JobStatus.QUEUED,
            JobStatus.SESSION_STARTED,
            JobStatus.RUNNING,
            JobStatus.PR_OPENED,
            JobStatus.WAITING_FOR_USER,
            JobStatus.WAITING_FOR_APPROVAL,
        }
    ]
    active_devin_sessions = [
        job
        for job in jobs
        if job.status
        in {
            JobStatus.SESSION_STARTED,
            JobStatus.RUNNING,
            JobStatus.WAITING_FOR_USER,
            JobStatus.WAITING_FOR_APPROVAL,
        }
    ]
    prs = [job for job in jobs if job.pr_url]
    terminal_count = len(completed) + len(failed) + len(pr_closed)
    time_to_pr = [
        (job.pr_opened_at - job.created_at).total_seconds()
        for job in jobs
        if job.pr_opened_at and job.created_at
    ]
    time_to_completion = [
        (job.completed_at - job.created_at).total_seconds()
        for job in completed + failed + pr_closed
        if job.completed_at and job.created_at
    ]
    throughput = _throughput_jobs_per_day(completed)
    engineer_hours_avoided = len(completed) * engineer_hours_per_remediation
    return MetricsSummary(
        total_jobs=total,
        active_jobs=len(active),
        active_devin_sessions=len(active_devin_sessions),
        completed_jobs=len(completed),
        failed_jobs=len(failed),
        waiting_jobs=len(waiting),
        pr_created_jobs=len(prs),
        completion_rate=round(len(completed) / total, 3) if total else 0,
        success_rate=round(len(completed) / terminal_count, 3) if terminal_count else 0,
        average_time_to_pr_seconds=_round_optional(_avg(time_to_pr)),
        median_time_to_pr_seconds=round(median(time_to_pr), 2) if time_to_pr else None,
        average_time_to_completion_seconds=_round_optional(_avg(time_to_completion)),
        total_acus_consumed=round(sum(job.acus_consumed for job in jobs), 2),
        throughput_jobs_per_day=throughput,
        engineer_hours_avoided=round(engineer_hours_avoided, 2),
        estimated_cost_avoided=round(engineer_hours_avoided * engineer_hourly_cost, 2),
        backlog_reduction_percentage=round((len(completed) / total) * 100, 1) if total else 0,
        average_remediation_cycle_time_seconds=_round_optional(_avg(time_to_completion)),
    )


def _throughput_jobs_per_day(completed_jobs: list[RemediationJob]) -> float:
    if not completed_jobs:
        return 0
    completed_at = [job.completed_at for job in completed_jobs if job.completed_at]
    if not completed_at:
        return 0
    first_created = min(job.created_at for job in completed_jobs)
    last_completed = max(completed_at)
    elapsed_days = max((last_completed - first_created).total_seconds() / 86400, 1 / 24)
    return round(len(completed_jobs) / elapsed_days, 2)

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    SESSION_STARTED = "session_started"
    RUNNING = "running"
    PR_OPENED = "pr_opened"
    WAITING_FOR_USER = "waiting_for_user"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    IGNORED = "ignored"

    NEEDS_INPUT = "waiting_for_user"


class Finding(BaseModel):
    title: str
    body: str
    severity: str = "medium"
    repository: str = "example/superset"
    issue_number: int | None = None
    scanner: str = "manual"
    metadata: dict[str, Any] = Field(default_factory=dict)


class IssueContext(BaseModel):
    repository: str
    issue_number: int
    issue_title: str
    issue_body: str = ""
    issue_url: str = ""


class GitHubIssueEvent(IssueContext):
    action: str
    label: str | None = None
    labels: list[str] = Field(default_factory=list)
    event_action: str | None = None


class DevinSession(BaseModel):
    session_id: str
    status: str
    url: str | None = None
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    repos: list[str] = Field(default_factory=list)
    acu_limit: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None


class SessionInsights(BaseModel):
    status: str
    acu_used: float = 0
    pr_url: str | None = None
    pull_requests: list[str] = Field(default_factory=list)
    needs_input: bool = False
    failure_reason: str | None = None
    summary: str | None = None
    session_id: str | None = None
    org_id: str | None = None
    url: str | None = None
    tags: list[str] = Field(default_factory=list)
    session_size: str | int | None = None
    num_devin_messages: int | None = None
    num_user_messages: int | None = None
    analysis: dict[str, Any] | str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionConsumption(BaseModel):
    session_id: str
    acus_consumed: float = 0
    date: str | None = None
    unavailable: bool = False
    unavailable_reason: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class RemediationJob(BaseModel):
    id: int
    repository: str
    issue_number: int
    issue_title: str = ""
    issue_url: str = ""
    issue_body: str = ""
    labels_json: str = "[]"
    event_action: str = ""
    status: JobStatus
    status_detail: str | None = None
    devin_session_id: str | None = None
    devin_session_url: str | None = None
    pr_url: str | None = None
    pr_state: str | None = None
    acus_consumed: float = 0
    session_size: str | None = None
    num_devin_messages: int | None = None
    num_user_messages: int | None = None
    analytics_available: int = 0
    enterprise_analytics_available: int = 0
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    pr_opened_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def acu_used(self) -> float:
        return self.acus_consumed

    @property
    def started_at(self) -> datetime | None:
        return self.created_at if self.devin_session_id else None


class MetricsSummary(BaseModel):
    total_jobs: int
    active_jobs: int
    completed_jobs: int
    failed_jobs: int
    waiting_jobs: int
    pr_created_jobs: int
    success_rate: float
    average_time_to_pr_seconds: float | None = None
    median_time_to_pr_seconds: float | None = None
    average_time_to_completion_seconds: float | None = None
    total_acus_consumed: float
    throughput_jobs_per_day: float
    engineer_hours_avoided: float
    estimated_cost_avoided: float
    backlog_reduction_percentage: float
    average_remediation_cycle_time_seconds: float | None = None

    @property
    def active_sessions(self) -> int:
        return self.active_jobs

    @property
    def completed_remediations(self) -> int:
        return self.completed_jobs

    @property
    def prs_opened(self) -> int:
        return self.pr_created_jobs

    @property
    def total_acu_used(self) -> float:
        return self.total_acus_consumed

    @property
    def throughput_24h(self) -> int:
        return int(round(self.throughput_jobs_per_day))

    @property
    def failure_rate(self) -> float:
        terminal = self.completed_jobs + self.failed_jobs
        return round(self.failed_jobs / terminal, 3) if terminal else 0

    @property
    def business_impact(self) -> str:
        return (
            f"{self.completed_jobs} remediations completed, {self.pr_created_jobs} PRs opened, "
            f"{self.engineer_hours_avoided:.1f} engineer hours avoided."
        )

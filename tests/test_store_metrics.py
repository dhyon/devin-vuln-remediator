from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import json

from app.metrics import build_metrics
from app.models import GitHubIssueEvent, JobStatus, SessionInsights
from app.store import Store


def db_path() -> str:
    path = Path("data") / f"test-{uuid4().hex}.db"
    path.parent.mkdir(exist_ok=True)
    return str(path)


def event(issue_number: int = 1) -> GitHubIssueEvent:
    return GitHubIssueEvent(
        action="labeled",
        label="devin-remediate",
        repository="me/superset",
        issue_number=issue_number,
        issue_title="Security finding",
        issue_body="Fix this finding.",
    )


def test_create_or_get_job_is_idempotent() -> None:
    store = Store(db_path())

    first = store.create_or_get_job(event())
    second = store.create_or_get_job(event())

    assert first.id == second.id
    assert len(store.list_jobs()) == 1
    assert first.status == JobStatus.QUEUED


def test_update_from_insights_tracks_pr_completion_and_acu() -> None:
    store = Store(db_path())
    job = store.create_or_get_job(event())
    job = store.attach_session(job.id, "session-1", "https://app.devin.ai/sessions/session-1")

    updated = store.update_from_insights(
        job.id,
        SessionInsights(status="completed", pr_url="https://github.com/me/superset/pull/5", acu_used=3.5),
    )

    assert updated.status == JobStatus.COMPLETED
    assert updated.pr_url == "https://github.com/me/superset/pull/5"
    assert updated.pr_opened_at is not None
    assert updated.completed_at is not None
    assert updated.acus_consumed == 3.5
    assert updated.acu_used == 3.5


def test_metrics_summarize_control_plane_outcomes() -> None:
    store = Store(db_path())
    completed = store.create_or_get_job(event(1))
    running = store.create_or_get_job(event(2))
    completed = store.attach_session(completed.id, "session-1", None)
    store.attach_session(running.id, "session-2", None)
    store.update_from_insights(
        completed.id,
        SessionInsights(status="completed", pr_url="https://github.com/me/superset/pull/7", acu_used=4),
    )

    metrics = build_metrics(store.list_jobs())

    assert metrics.active_sessions == 1
    assert metrics.completed_remediations == 1
    assert metrics.prs_opened == 1
    assert metrics.success_rate == 1
    assert metrics.total_acu_used == 4


def test_event_log_records_lifecycle() -> None:
    store = Store(db_path())
    job = store.create_or_get_job(event())

    store.record_event(job.id, "queued", "Job queued", {"issue": job.issue_number})
    store.record_event(job.id, "session_started", "Session started", {"session_id": "session-1"})

    with store.connect() as conn:
        rows = conn.execute("SELECT * FROM job_events WHERE job_id = ? ORDER BY id", (job.id,)).fetchall()

    assert [row["event_type"] for row in rows] == ["queued", "session_started"]
    assert rows[0]["message"] == "Job queued"
    assert json.loads(rows[1]["payload_json"]) == {"session_id": "session-1"}


def test_pr_opened_timestamp_only_set_once() -> None:
    store = Store(db_path())
    job = store.create_or_get_job(event())

    first = store.mark_pr_opened(job.id, "https://github.com/me/superset/pull/1", "open")
    second = store.mark_pr_opened(job.id, "https://github.com/me/superset/pull/2", "open")

    assert first.pr_opened_at == second.pr_opened_at
    assert second.pr_url == "https://github.com/me/superset/pull/2"


def test_completed_timestamp_only_set_once() -> None:
    store = Store(db_path())
    job = store.create_or_get_job(event())

    first = store.mark_completed(job.id)
    second = store.mark_completed(job.id)

    assert first.completed_at == second.completed_at


def test_list_active_jobs_excludes_completed_and_failed() -> None:
    store = Store(db_path())
    queued = store.create_or_get_job(event(1))
    running = store.create_or_get_job(event(2))
    completed = store.create_or_get_job(event(3))
    failed = store.create_or_get_job(event(4))

    store.update_job(running.id, status=JobStatus.RUNNING.value)
    store.mark_completed(completed.id)
    store.mark_failed(failed.id, "tests failed")

    active = store.list_active_jobs()

    assert {job.id for job in active} == {queued.id, running.id}

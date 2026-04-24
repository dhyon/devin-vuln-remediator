from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from app.models import GitHubIssueEvent, JobStatus, RemediationJob, SessionInsights


ACTIVE_STATUSES = (
    JobStatus.QUEUED.value,
    JobStatus.SESSION_STARTED.value,
    JobStatus.RUNNING.value,
    JobStatus.PR_OPENED.value,
    JobStatus.WAITING_FOR_USER.value,
    JobStatus.WAITING_FOR_APPROVAL.value,
)


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        init_db(self.database_path)

    def create_or_get_job(self, event: GitHubIssueEvent | None = None, **kwargs: Any) -> RemediationJob:
        if event is not None:
            values = {
                "repository": event.repository,
                "issue_number": event.issue_number,
                "issue_title": event.issue_title,
                "issue_url": event.issue_url,
                "issue_body": event.issue_body,
                "labels": event.labels,
                "event_action": event.event_action or event.action,
            }
        else:
            values = kwargs

        labels = values.get("labels", [])
        labels_json = values.get("labels_json") or json.dumps(labels)
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO remediation_jobs
                (repository, issue_number, issue_title, issue_url, issue_body, labels_json, event_action, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["repository"],
                    int(values["issue_number"]),
                    values.get("issue_title", ""),
                    values.get("issue_url", ""),
                    values.get("issue_body", ""),
                    labels_json,
                    values.get("event_action", ""),
                    values.get("status", JobStatus.QUEUED.value),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM remediation_jobs WHERE repository = ? AND issue_number = ?",
                (values["repository"], int(values["issue_number"])),
            ).fetchone()
        return self._row_to_job(row)

    def get_job(self, repository: str, issue_number: int) -> RemediationJob | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM remediation_jobs WHERE repository = ? AND issue_number = ?",
                (repository, issue_number),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def get_job_by_session(self, session_id: str) -> RemediationJob | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM remediation_jobs WHERE devin_session_id = ?",
                (session_id,),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, status: str | None = None, limit: int = 100) -> list[RemediationJob]:
        with self.connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM remediation_jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM remediation_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_job(row) for row in rows]

    def list_active_jobs(self) -> list[RemediationJob]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM remediation_jobs WHERE status IN ({placeholders}) ORDER BY updated_at ASC",
                ACTIVE_STATUSES,
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def update_job(self, job_id: int, **fields: Any) -> RemediationJob:
        if not fields:
            job = self._get_job_by_id(job_id)
            if job is None:
                raise KeyError(f"Job not found: {job_id}")
            return job

        allowed = {
            "status",
            "status_detail",
            "devin_session_id",
            "devin_session_url",
            "pr_url",
            "pr_state",
            "acus_consumed",
            "session_size",
            "num_devin_messages",
            "num_user_messages",
            "analytics_available",
            "enterprise_analytics_available",
            "failure_reason",
            "pr_opened_at",
            "completed_at",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        updates["updated_at"] = utcnow()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self.connect() as conn:
            row = conn.execute(
                f"UPDATE remediation_jobs SET {assignments} WHERE id = ? RETURNING *",
                (*updates.values(), job_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Job not found: {job_id}")
        return self._row_to_job(row)

    def record_event(self, job_id: int, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO job_events (job_id, event_type, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, event_type, message, json.dumps(payload or {}, separators=(",", ":")), utcnow()),
            )

    def list_recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT e.*, j.repository, j.issue_number
                FROM job_events e
                LEFT JOIN remediation_jobs j ON j.id = e.job_id
                ORDER BY e.created_at DESC, e.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_pr_opened(self, job_id: int, pr_url: str, pr_state: str) -> RemediationJob:
        current = self._get_job_by_id(job_id)
        if current is None:
            raise KeyError(f"Job not found: {job_id}")
        return self.update_job(
            job_id,
            status=JobStatus.PR_OPENED.value,
            pr_url=pr_url,
            pr_state=pr_state,
            pr_opened_at=current.pr_opened_at.isoformat() if current.pr_opened_at else utcnow(),
        )

    def mark_completed(self, job_id: int) -> RemediationJob:
        current = self._get_job_by_id(job_id)
        if current is None:
            raise KeyError(f"Job not found: {job_id}")
        return self.update_job(
            job_id,
            status=JobStatus.COMPLETED.value,
            completed_at=current.completed_at.isoformat() if current.completed_at else utcnow(),
        )

    def mark_failed(self, job_id: int, reason: str) -> RemediationJob:
        current = self._get_job_by_id(job_id)
        if current is None:
            raise KeyError(f"Job not found: {job_id}")
        return self.update_job(
            job_id,
            status=JobStatus.FAILED.value,
            failure_reason=reason,
            completed_at=current.completed_at.isoformat() if current.completed_at else utcnow(),
        )

    def attach_session(self, job_id: int, session_id: str, session_url: str | None) -> RemediationJob:
        job = self.update_job(
            job_id,
            status=JobStatus.SESSION_STARTED.value,
            devin_session_id=session_id,
            devin_session_url=session_url,
        )
        self.record_event(job_id, "session_started", "Devin session started", {"session_id": session_id, "url": session_url})
        return job

    def update_from_insights(self, job_id: int, insights: SessionInsights) -> RemediationJob:
        status = self._map_insight_status(insights)
        fields: dict[str, Any] = {
            "status": status.value,
            "acus_consumed": insights.acu_used,
            "session_size": str(insights.session_size) if insights.session_size is not None else None,
            "num_devin_messages": insights.num_devin_messages,
            "num_user_messages": insights.num_user_messages,
            "analytics_available": 1,
            "failure_reason": insights.failure_reason,
        }
        fields = {key: value for key, value in fields.items() if value is not None}
        job = self.update_job(job_id, **fields)
        if insights.pr_url:
            job = self.mark_pr_opened(job_id, insights.pr_url, job.pr_state or "open")
        if status == JobStatus.COMPLETED:
            job = self.mark_completed(job_id)
        if status == JobStatus.FAILED:
            job = self.mark_failed(job_id, insights.failure_reason or "Unknown failure")
        return job

    def count_jobs(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM remediation_jobs").fetchone()
        return int(row["count"])

    def list_pollable_jobs(self, limit: int = 25) -> list[RemediationJob]:
        pollable = (
            JobStatus.SESSION_STARTED.value,
            JobStatus.RUNNING.value,
            JobStatus.PR_OPENED.value,
            JobStatus.WAITING_FOR_USER.value,
            JobStatus.WAITING_FOR_APPROVAL.value,
        )
        placeholders = ",".join("?" for _ in pollable)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM remediation_jobs WHERE status IN ({placeholders}) ORDER BY updated_at ASC LIMIT ?",
                (*pollable, limit),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def seed_jobs(self, jobs: list[GitHubIssueEvent]) -> int:
        for event in jobs:
            self.create_or_get_job(event)
        return len(jobs)

    def clear(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM job_events")
            conn.execute("DELETE FROM remediation_jobs")

    def _get_job_by_id(self, job_id: int) -> RemediationJob | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM remediation_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    @staticmethod
    def _map_insight_status(insights: SessionInsights) -> JobStatus:
        if insights.failure_reason or insights.status == "failed":
            return JobStatus.FAILED
        if insights.needs_input or insights.status == "needs_input":
            return JobStatus.WAITING_FOR_USER
        if insights.status == "waiting_for_approval":
            return JobStatus.WAITING_FOR_APPROVAL
        if insights.status == "completed":
            return JobStatus.COMPLETED
        if insights.pr_url or insights.status == "pr_opened":
            return JobStatus.PR_OPENED
        return JobStatus.RUNNING

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> RemediationJob:
        data = dict(row)
        data["issue_title"] = data.get("issue_title") or ""
        data["issue_url"] = data.get("issue_url") or ""
        data["issue_body"] = data.get("issue_body") or ""
        data["labels_json"] = data.get("labels_json") or "[]"
        data["event_action"] = data.get("event_action") or ""
        data["acus_consumed"] = data.get("acus_consumed") or 0
        data["analytics_available"] = data.get("analytics_available") or 0
        data["enterprise_analytics_available"] = data.get("enterprise_analytics_available") or 0
        for key in ("created_at", "updated_at", "pr_opened_at", "completed_at"):
            if data.get(key):
                data[key] = datetime.fromisoformat(data[key])
        return RemediationJob(**data)


def init_db(database_path: str = "data/remediator.db") -> None:
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS remediation_jobs (
                id INTEGER PRIMARY KEY,
                repository TEXT NOT NULL,
                issue_number INTEGER NOT NULL,
                issue_title TEXT,
                issue_url TEXT,
                issue_body TEXT,
                labels_json TEXT,
                event_action TEXT,
                status TEXT NOT NULL,
                status_detail TEXT,
                devin_session_id TEXT,
                devin_session_url TEXT,
                pr_url TEXT,
                pr_state TEXT,
                acus_consumed REAL,
                session_size TEXT,
                num_devin_messages INTEGER,
                num_user_messages INTEGER,
                analytics_available INTEGER DEFAULT 0,
                enterprise_analytics_available INTEGER DEFAULT 0,
                failure_reason TEXT,
                created_at TEXT,
                updated_at TEXT,
                pr_opened_at TEXT,
                completed_at TEXT,
                UNIQUE(repository, issue_number)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_events (
                id INTEGER PRIMARY KEY,
                job_id INTEGER,
                event_type TEXT,
                message TEXT,
                payload_json TEXT,
                created_at TEXT
            )
            """
        )
        _ensure_columns(conn)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    required = {
        "issue_title": "TEXT",
        "issue_url": "TEXT",
        "issue_body": "TEXT",
        "labels_json": "TEXT",
        "event_action": "TEXT",
        "status_detail": "TEXT",
        "devin_session_id": "TEXT",
        "devin_session_url": "TEXT",
        "pr_url": "TEXT",
        "pr_state": "TEXT",
        "acus_consumed": "REAL",
        "session_size": "TEXT",
        "num_devin_messages": "INTEGER",
        "num_user_messages": "INTEGER",
        "analytics_available": "INTEGER DEFAULT 0",
        "enterprise_analytics_available": "INTEGER DEFAULT 0",
        "failure_reason": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
        "pr_opened_at": "TEXT",
        "completed_at": "TEXT",
    }
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(remediation_jobs)").fetchall()}
    for column, definition in required.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE remediation_jobs ADD COLUMN {column} {definition}")

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from app.analytics_client import MockAnalyticsClient
from app.devin_client import MockDevinClient
from app.github_client import MockGitHubClient
from app.models import GitHubIssueEvent, JobStatus
from app.poller import RemediationPoller
from app.store import Store


def db_path() -> str:
    path = Path("data") / f"test-{uuid4().hex}.db"
    path.parent.mkdir(exist_ok=True)
    return str(path)


def test_poller_starts_session_and_comments_then_completes() -> None:
    async def run() -> None:
        store = Store(db_path())
        devin = MockDevinClient()
        github = MockGitHubClient()
        poller = RemediationPoller(store, devin, MockAnalyticsClient(), github)
        event = GitHubIssueEvent(
            action="labeled",
            label="devin-remediate",
            repository="me/superset",
            issue_number=99,
            issue_title="Subprocess shell injection risk",
            issue_body="Remove shell=True.",
        )

        started = await poller.start_remediation(event)
        assert started.status == JobStatus.SESSION_STARTED
        assert started.devin_session_id is not None
        assert len(github.comments) == 1

        first_poll = await poller.poll_once()
        second_poll = await poller.poll_once()
        third_poll = await poller.poll_once()

        assert len(first_poll) == 1
        assert first_poll[0].status == JobStatus.RUNNING
        assert second_poll[0].status == JobStatus.PR_OPENED
        assert third_poll[0].status == JobStatus.COMPLETED
        assert third_poll[0].pr_url is not None
        assert len(github.comments) == 3
        assert "completed" in github.comments[-1][2].lower()

    asyncio.run(run())

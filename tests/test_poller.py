from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from app.analytics_client import MockAnalyticsClient
from app.devin_client import DevinApiError, MockDevinClient
from app.github_client import MockGitHubClient
from app.models import DevinSession
from app.models import GitHubIssueEvent, JobStatus, SessionConsumption, SessionInsights
from app.poller import RemediationPoller, parse_github_pull_url
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


def test_poller_marks_job_failed_when_devin_session_start_hits_capacity() -> None:
    async def run() -> None:
        store = Store(db_path())
        github = MockGitHubClient()
        poller = RemediationPoller(store, FailingDevinClient(), MockAnalyticsClient(), github)
        event = GitHubIssueEvent(
            action="labeled",
            label="devin-remediate",
            repository="me/superset",
            issue_number=100,
            issue_title="Unsafe YAML loader",
            issue_body="Use safe_load.",
        )

        job = await poller.start_remediation(event)

        assert job.status == JobStatus.FAILED
        assert job.devin_session_id is None
        assert "concurrent session limit" in (job.failure_reason or "")
        assert github.comments
        assert "Could not start Devin remediation session" in github.comments[-1][2]
        assert "org-" not in github.comments[-1][2]
        assert store.list_recent_events()[0]["event_type"] == "session_start_failed"

    asyncio.run(run())


def test_duplicate_events_do_not_create_duplicate_sessions() -> None:
    async def run() -> None:
        store = Store(db_path())
        devin = SlowCountingDevinClient()
        github = MockGitHubClient()
        poller = RemediationPoller(store, devin, MockAnalyticsClient(), github)
        event = GitHubIssueEvent(
            action="labeled",
            label="devin-remediate",
            repository="me/superset",
            issue_number=101,
            issue_title="Duplicate webhook event",
            issue_body="Only one session should be created.",
        )

        first, second = await asyncio.gather(
            poller.start_remediation(event),
            poller.start_remediation(event),
        )

        jobs = store.list_jobs()
        assert len(jobs) == 1
        assert devin.create_count == 1
        assert len(github.comments) == 1
        assert {first.id, second.id} == {jobs[0].id}
        assert jobs[0].devin_session_id == "session-1"

    asyncio.run(run())


def test_poll_starts_preexisting_queued_jobs() -> None:
    async def run() -> None:
        store = Store(db_path())
        devin = SlowCountingDevinClient()
        github = MockGitHubClient()
        poller = RemediationPoller(store, devin, MockAnalyticsClient(), github)
        store.create_or_get_job(
            GitHubIssueEvent(
                action="labeled",
                label="devin-remediate",
                repository="me/superset",
                issue_number=102,
                issue_title="Queued from earlier crash",
                issue_body="Retry me.",
            )
        )

        updated = await poller.poll_once()

        assert len(updated) == 1
        assert updated[0].status == JobStatus.SESSION_STARTED
        assert updated[0].devin_session_id == "session-1"
        assert devin.create_count == 1
        assert len(github.comments) == 1

    asyncio.run(run())


def test_poll_does_not_fail_when_github_comment_target_was_deleted() -> None:
    async def run() -> None:
        store = Store(db_path())
        poller = RemediationPoller(store, FailingDevinClient(), MockAnalyticsClient(), MissingIssueGitHubClient())
        store.create_or_get_job(
            GitHubIssueEvent(
                action="labeled",
                label="devin-remediate",
                repository="me/superset",
                issue_number=4,
                issue_title="Deleted issue",
                issue_body="The GitHub issue no longer exists.",
            )
        )

        updated = await poller.poll_once()

        assert len(updated) == 1
        assert updated[0].status == JobStatus.FAILED
        events = store.list_recent_events()
        assert events[0]["event_type"] == "github_comment_failed"
        assert events[1]["event_type"] == "session_start_failed"

    asyncio.run(run())


def test_poll_uses_enterprise_consumption_when_insights_acu_is_zero() -> None:
    async def run() -> None:
        store = Store(db_path())
        devin = MockDevinClient()
        github = MockGitHubClient()
        poller = RemediationPoller(store, devin, EnterpriseConsumptionAnalyticsClient(), github)
        event = GitHubIssueEvent(
            action="labeled",
            label="devin-remediate",
            repository="me/superset",
            issue_number=103,
            issue_title="ACU usage",
            issue_body="Track ACUs.",
        )
        started = await poller.start_remediation(event)

        updated = await poller.poll_once()

        assert len(updated) == 1
        assert updated[0].id == started.id
        assert updated[0].acus_consumed == 4.75
        assert updated[0].enterprise_analytics_available == 1

    asyncio.run(run())


def test_poll_marks_job_completed_when_linked_github_pr_is_merged() -> None:
    async def run() -> None:
        store = Store(db_path())
        devin = MockDevinClient()
        github = MergedPullRequestGitHubClient()
        poller = RemediationPoller(store, devin, OpenPrAnalyticsClient(), github)
        event = GitHubIssueEvent(
            action="labeled",
            label="devin-remediate",
            repository="me/superset",
            issue_number=104,
            issue_title="Merged PR",
            issue_body="Complete me after merge.",
        )
        await poller.start_remediation(event)

        updated = await poller.poll_once()

        assert len(updated) == 1
        assert updated[0].status == JobStatus.COMPLETED
        assert updated[0].pr_state == "merged"
        assert updated[0].completed_at is not None
        assert github.pull_requests_checked == [("me", "superset", 9)]

    asyncio.run(run())


def test_poll_marks_job_pr_closed_when_linked_github_pr_is_closed_without_merge() -> None:
    async def run() -> None:
        store = Store(db_path())
        devin = MockDevinClient()
        github = ClosedPullRequestGitHubClient()
        poller = RemediationPoller(store, devin, OpenPrAnalyticsClient(), github)
        event = GitHubIssueEvent(
            action="labeled",
            label="devin-remediate",
            repository="me/superset",
            issue_number=105,
            issue_title="Closed PR",
            issue_body="Mark me closed after the PR is manually closed.",
        )
        await poller.start_remediation(event)

        updated = await poller.poll_once()

        assert len(updated) == 1
        assert updated[0].status == JobStatus.PR_CLOSED
        assert updated[0].pr_state == "closed"
        assert updated[0].completed_at is not None
        assert github.pull_requests_checked == [("me", "superset", 9)]

    asyncio.run(run())


def test_parse_github_pull_url() -> None:
    assert parse_github_pull_url("https://github.com/me/superset/pull/9") == ("me", "superset", 9)
    assert parse_github_pull_url("https://github.com/me/superset/issues/9") is None


class FailingDevinClient:
    async def create_session(
        self,
        prompt: str,
        title: str,
        tags: list[str],
        repos: list[str] | None = None,
    ) -> DevinSession:
        raise DevinApiError(
            'Devin API POST /v3/organizations/org-secret/sessions failed with HTTP 429: {"detail":"limit"}',
            status_code=429,
        )

    async def get_session(self, session_id: str) -> DevinSession:
        raise AssertionError("get_session should not be called")

    async def send_message(self, session_id: str, message: str) -> None:
        raise AssertionError("send_message should not be called")


class MissingIssueGitHubClient:
    async def comment_on_issue(self, repository: str, issue_number: int, body: str) -> None:
        request = httpx.Request("POST", f"https://api.github.com/repos/{repository}/issues/{issue_number}/comments")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    async def post_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
        await self.comment_on_issue(f"{owner}/{repo}", issue_number, body)

    async def create_issue(self, owner: str, repo: str, title: str, body: str, labels: list[str]) -> dict:
        raise AssertionError("create_issue should not be called")

    async def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
        raise AssertionError("get_issue should not be called")


class EnterpriseConsumptionAnalyticsClient:
    async def get_session_insights(self, session_id: str) -> SessionInsights:
        return SessionInsights(status="running", acu_used=0)

    async def get_session_daily_consumption(self, session_id: str) -> SessionConsumption | None:
        return SessionConsumption(session_id=session_id, acus_consumed=4.75)


class OpenPrAnalyticsClient:
    async def get_session_insights(self, session_id: str) -> SessionInsights:
        return SessionInsights(
            status="running",
            pr_url="https://github.com/me/superset/pull/9",
            pr_state="open",
        )

    async def get_session_daily_consumption(self, session_id: str) -> SessionConsumption | None:
        return None


class MergedPullRequestGitHubClient(MockGitHubClient):
    def __init__(self) -> None:
        super().__init__()
        self.pull_requests_checked: list[tuple[str, str, int]] = []

    async def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict:
        self.pull_requests_checked.append((owner, repo, pull_number))
        return {
            "number": pull_number,
            "state": "closed",
            "merged": True,
            "html_url": f"https://github.com/{owner}/{repo}/pull/{pull_number}",
        }


class ClosedPullRequestGitHubClient(MockGitHubClient):
    def __init__(self) -> None:
        super().__init__()
        self.pull_requests_checked: list[tuple[str, str, int]] = []

    async def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict:
        self.pull_requests_checked.append((owner, repo, pull_number))
        return {
            "number": pull_number,
            "state": "closed",
            "merged": False,
            "html_url": f"https://github.com/{owner}/{repo}/pull/{pull_number}",
        }


@dataclass
class SlowCountingDevinClient:
    create_count: int = 0

    async def create_session(
        self,
        prompt: str,
        title: str,
        tags: list[str],
        repos: list[str] | None = None,
    ) -> DevinSession:
        self.create_count += 1
        await asyncio.sleep(0.01)
        return DevinSession(
            session_id=f"session-{self.create_count}",
            status="new",
            url=f"https://app.devin.ai/sessions/session-{self.create_count}",
            title=title,
            tags=tags,
            repos=repos or [],
        )

    async def get_session(self, session_id: str) -> DevinSession:
        raise AssertionError("get_session should not be called")

    async def send_message(self, session_id: str, message: str) -> None:
        raise AssertionError("send_message should not be called")

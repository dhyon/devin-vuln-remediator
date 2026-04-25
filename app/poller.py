from __future__ import annotations

import httpx
from urllib.parse import urlparse

from app.analytics_client import AnalyticsClient
from app.devin_client import DevinApiError, DevinClient
from app.github_client import GitHubClient
from app.models import GitHubIssueEvent, JobStatus, RemediationJob
from app.prompts import build_remediation_prompt
from app.store import Store


STARTED_COMMENT = "Started Devin remediation session: {url}"
START_FAILED_COMMENT = "Could not start Devin remediation session: {reason}"
PR_COMMENT = "Devin opened a remediation PR: {url}"
COMPLETED_COMMENT = "Devin remediation completed. PR: {url}"
FAILED_COMMENT = "Devin remediation failed: {reason}"
NEEDS_INPUT_COMMENT = "Devin needs input before continuing this remediation."


class RemediationPoller:
    def __init__(
        self,
        store: Store,
        devin_client: DevinClient,
        analytics_client: AnalyticsClient,
        github_client: GitHubClient,
    ) -> None:
        self.store = store
        self.devin_client = devin_client
        self.analytics_client = analytics_client
        self.github_client = github_client

    async def start_remediation(self, event: GitHubIssueEvent) -> RemediationJob:
        job = self.store.create_or_get_job(event)
        if job.devin_session_id:
            return job
        claimed_job = self.store.claim_session_start(job.id)
        if claimed_job is None:
            return self.store.get_job(job.repository, job.issue_number) or job
        job = claimed_job

        try:
            session = await self.devin_client.create_session(
                prompt=build_remediation_prompt(event, f"https://github.com/{event.repository}"),
                title=f"Remediate #{event.issue_number}: {event.issue_title}",
                tags=[
                    "vulnerability-remediation",
                    "superset",
                    "github-issue",
                    f"issue-{event.issue_number}",
                    f"repo-{event.repository.replace('/', '-')}",
                ],
                repos=[event.repository],
            )
        except DevinApiError as exc:
            reason = user_safe_devin_error(exc)
            job = self.store.mark_failed(job.id, reason)
            self.store.record_event(job.id, "session_start_failed", reason, {"status_code": exc.status_code})
            await self._safe_comment_on_issue(
                job,
                job.repository,
                job.issue_number,
                START_FAILED_COMMENT.format(reason=reason),
            )
            return job

        job = self.store.attach_session(job.id, session.session_id, session.url)
        await self._safe_comment_on_issue(
            job,
            job.repository,
            job.issue_number,
            STARTED_COMMENT.format(url=session.url or session.session_id),
        )
        return job

    async def poll_once(self, limit: int = 25) -> list[RemediationJob]:
        updated: list[RemediationJob] = []
        for job in self.store.list_queued_jobs(limit):
            started = await self.start_remediation(job_to_event(job))
            updated.append(started)
            if len(updated) >= limit:
                return updated
        if updated:
            return updated

        for job in self.store.list_pollable_jobs(limit):
            if not job.devin_session_id:
                continue
            before = job.status
            insights = await self.analytics_client.get_session_insights(job.devin_session_id)
            enterprise_analytics_available = 0
            consumption = await self.analytics_client.get_session_daily_consumption(job.devin_session_id)
            if consumption and not consumption.unavailable:
                enterprise_analytics_available = 1
                if consumption.acus_consumed > 0:
                    insights = insights.model_copy(update={"acu_used": consumption.acus_consumed})
            after = self.store.update_from_insights(job.id, insights)
            if enterprise_analytics_available:
                after = self.store.update_job(after.id, enterprise_analytics_available=1)
            after = await self._refresh_pr_state(after)
            await self._comment_for_transition(before, after)
            updated.append(after)
        return updated

    async def _refresh_pr_state(self, job: RemediationJob) -> RemediationJob:
        if not job.pr_url:
            return job
        pull_ref = parse_github_pull_url(job.pr_url)
        if pull_ref is None:
            return job
        owner, repo, pull_number = pull_ref
        try:
            pull = await self.github_client.get_pull_request(owner, repo, pull_number)
        except httpx.HTTPStatusError as exc:
            self.store.record_event(
                job.id,
                "github_pr_refresh_failed",
                f"GitHub PR refresh failed with HTTP {exc.response.status_code}",
                {"status_code": exc.response.status_code, "pr_url": job.pr_url},
            )
            return job

        pr_state = "merged" if pull.get("merged") else str(pull.get("state") or job.pr_state or "open")
        job = self.store.update_job(job.id, pr_state=pr_state)
        if pull.get("merged"):
            job = self.store.mark_completed(job.id)
        elif pr_state == "closed":
            job = self.store.mark_pr_closed(job.id)
        return job

    async def _comment_for_transition(self, before: JobStatus, job: RemediationJob) -> None:
        if before == job.status:
            return
        if job.status == JobStatus.PR_OPENED and job.pr_url:
            body = PR_COMMENT.format(url=job.pr_url)
        elif job.status == JobStatus.COMPLETED:
            body = COMPLETED_COMMENT.format(url=job.pr_url or "not available")
        elif job.status == JobStatus.FAILED:
            body = FAILED_COMMENT.format(reason=job.failure_reason or "unknown failure")
        elif job.status == JobStatus.NEEDS_INPUT:
            body = NEEDS_INPUT_COMMENT
        else:
            return
        await self._safe_comment_on_issue(job, job.repository, job.issue_number, body)

    async def _safe_comment_on_issue(
        self,
        job: RemediationJob,
        repository: str,
        issue_number: int,
        body: str,
    ) -> None:
        try:
            await self.github_client.comment_on_issue(repository, issue_number, body)
        except httpx.HTTPStatusError as exc:
            self.store.record_event(
                job.id,
                "github_comment_failed",
                f"GitHub issue comment failed with HTTP {exc.response.status_code}",
                {"status_code": exc.response.status_code, "issue_number": issue_number},
            )


def user_safe_devin_error(exc: DevinApiError) -> str:
    if exc.status_code == 429:
        return "Devin concurrent session limit reached. Put an existing Devin session to sleep or wait for capacity, then redeliver the webhook or reapply the trigger label."
    if exc.status_code in {401, 403}:
        return "Devin API authorization failed. Check DEVIN_API_KEY, DEVIN_ORG_ID, and account access."
    return f"Devin API request failed with HTTP {exc.status_code or 'unknown'}."


def job_to_event(job: RemediationJob) -> GitHubIssueEvent:
    return GitHubIssueEvent(
        action=job.event_action or "labeled",
        label=None,
        labels=[],
        repository=job.repository,
        issue_number=job.issue_number,
        issue_title=job.issue_title,
        issue_body=job.issue_body,
        issue_url=job.issue_url,
        event_action=job.event_action or "requeued",
    )


def parse_github_pull_url(url: str) -> tuple[str, str, int] | None:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4 or parts[2] != "pull":
        return None
    try:
        pull_number = int(parts[3])
    except ValueError:
        return None
    return parts[0], parts[1], pull_number

from __future__ import annotations

from app.analytics_client import AnalyticsClient
from app.devin_client import DevinClient
from app.github_client import GitHubClient
from app.models import GitHubIssueEvent, JobStatus, RemediationJob
from app.prompts import build_remediation_prompt
from app.store import Store


STARTED_COMMENT = "Started Devin remediation session: {url}"
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
        job = self.store.attach_session(job.id, session.session_id, session.url)
        await self.github_client.comment_on_issue(
            job.repository,
            job.issue_number,
            STARTED_COMMENT.format(url=session.url or session.session_id),
        )
        return job

    async def poll_once(self, limit: int = 25) -> list[RemediationJob]:
        updated: list[RemediationJob] = []
        for job in self.store.list_pollable_jobs(limit):
            if not job.devin_session_id:
                continue
            before = job.status
            insights = await self.analytics_client.get_session_insights(job.devin_session_id)
            after = self.store.update_from_insights(job.id, insights)
            await self._comment_for_transition(before, after)
            updated.append(after)
        return updated

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
        await self.github_client.comment_on_issue(job.repository, job.issue_number, body)

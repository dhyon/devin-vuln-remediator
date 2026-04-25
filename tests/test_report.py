from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app import main as app_main
from app.models import GitHubIssueEvent, JobStatus


def test_report_uses_dashboard_time_to_pr_metric() -> None:
    with TestClient(app_main.app) as client:
        app_main.store.clear()
        for issue_number, seconds_to_pr in [(1, 60), (2, 120), (3, 3600)]:
            job = app_main.store.create_or_get_job(event(issue_number))
            app_main.store.update_job(
                job.id,
                status=JobStatus.PR_OPENED.value,
                pr_url=f"https://github.com/me/superset/pull/{issue_number}",
                pr_opened_at=(job.created_at + timedelta(seconds=seconds_to_pr)).isoformat(),
            )

        dashboard_response = client.get("/dashboard")
        report_response = client.get("/report")

    assert dashboard_response.status_code == 200
    assert "Median time to PR" in dashboard_response.text
    assert "2.0m" in dashboard_response.text
    assert report_response.status_code == 200
    assert "Median time to PR: 2.0m" in report_response.text
    assert "Average time to PR" not in report_response.text


def event(issue_number: int) -> GitHubIssueEvent:
    return GitHubIssueEvent(
        action="labeled",
        label="devin-remediate",
        repository="me/superset",
        issue_number=issue_number,
        issue_title=f"Security finding {issue_number}",
        issue_body="Fix this finding.",
    )

from __future__ import annotations

import json
from pathlib import Path

from app.models import GitHubIssueEvent


def load_findings(path: str) -> list[GitHubIssueEvent]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    events: list[GitHubIssueEvent] = []
    for index, item in enumerate(data.get("findings", data), start=1):
        events.append(
            GitHubIssueEvent(
                action="labeled",
                label="devin-remediate",
                repository=item.get("repository", "demo/superset"),
                issue_number=int(item.get("issue_number", index)),
                issue_title=item["title"],
                issue_body=item.get("body", item.get("description", "")),
                issue_url=item.get("issue_url", f"https://github.com/demo/superset/issues/{index}"),
            )
        )
    return events


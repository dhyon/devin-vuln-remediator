from __future__ import annotations

import hashlib
import hmac
from typing import Any

from fastapi import HTTPException, Request

from app.models import GitHubIssueEvent


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


async def validate_github_request(request: Request, secret: str, allow_unsigned: bool = False) -> bytes:
    body = await request.body()
    if allow_unsigned:
        return body
    if not secret or not verify_signature(secret, body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")
    return body


def parse_github_issue_event(payload: dict[str, Any]) -> GitHubIssueEvent | None:
    if "issue" not in payload or "repository" not in payload:
        return None

    repo = payload["repository"]
    issue = payload["issue"]
    if issue.get("pull_request"):
        return None

    label = payload.get("label") or {}
    full_name = repo.get("full_name") or f"{repo.get('owner', {}).get('login', 'unknown')}/{repo.get('name', 'unknown')}"
    labels = [item["name"] for item in issue.get("labels", []) if item.get("name")]
    if label.get("name") and label["name"] not in labels:
        labels.append(label["name"])
    action = payload.get("action", "")

    return GitHubIssueEvent(
        action=action,
        label=label.get("name"),
        labels=labels,
        repository=full_name,
        issue_number=int(issue["number"]),
        issue_title=issue.get("title", ""),
        issue_body=issue.get("body") or "",
        issue_url=issue.get("html_url") or "",
        event_action=action,
    )


def parse_issue_label_event(payload: dict[str, Any]) -> GitHubIssueEvent | None:
    return parse_github_issue_event(payload)


def is_remediation_trigger(event: GitHubIssueEvent | None, target_label: str) -> bool:
    return bool(
        event
        and event.action in {"labeled", "opened", "edited", "reopened"}
        and target_label in event.labels
    )

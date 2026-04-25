from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app import main as app_main
from app.github_webhook import is_remediation_trigger, parse_issue_label_event, verify_signature


def test_verify_signature_accepts_valid_sha256_signature() -> None:
    body = b'{"action":"labeled"}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    assert verify_signature("secret", body, signature)


def test_verify_signature_rejects_invalid_signature() -> None:
    assert not verify_signature("secret", b"{}", "sha256=bad")


def test_parse_and_match_remediation_label_event() -> None:
    event = parse_issue_label_event(
        {
            "action": "labeled",
            "label": {"name": "devin-remediate"},
            "repository": {"full_name": "me/superset"},
            "issue": {
                "number": 42,
                "title": "Fix vulnerable package",
                "body": "Upgrade the package.",
                "html_url": "https://github.com/me/superset/issues/42",
            },
        }
    )

    assert event is not None
    assert event.repository == "me/superset"
    assert event.issue_number == 42
    assert is_remediation_trigger(event, "devin-remediate")


def test_non_matching_label_is_not_a_trigger() -> None:
    event = parse_issue_label_event(
        {
            "action": "labeled",
            "label": {"name": "triage"},
            "repository": {"full_name": "me/superset"},
            "issue": {"number": 1, "title": "Finding"},
        }
    )

    assert not is_remediation_trigger(event, "devin-remediate")


def test_pr_event_is_ignored() -> None:
    event = parse_issue_label_event(
        {
            "action": "labeled",
            "label": {"name": "devin-remediate"},
            "repository": {"full_name": "me/superset"},
            "issue": {
                "number": 3,
                "title": "PR event",
                "pull_request": {"html_url": "https://github.com/me/superset/pull/3"},
                "labels": [{"name": "devin-remediate"}],
            },
        }
    )

    assert event is None


def test_webhook_rejects_invalid_signature() -> None:
    with TestClient(app_main.app) as client:
        response = client.post("/webhooks/github", json=issue_payload(), headers={"X-Hub-Signature-256": "sha256=bad"})

    assert response.status_code == 401


def test_webhook_ignores_issue_without_trigger_label() -> None:
    with TestClient(app_main.app) as client:
        app_main.store.clear()
        reset_mocks()
        payload = issue_payload(labels=["security"], label="security")
        response = client.post(
            "/webhooks/github",
            content=json.dumps(payload),
            headers=signed_headers(payload),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is False
    assert len(app_main.devin_client.sessions) == 0


def test_duplicate_labeled_event_does_not_create_duplicate_devin_session() -> None:
    with TestClient(app_main.app) as client:
        app_main.store.clear()
        reset_mocks()
        payload = issue_payload(issue_number=444)
        first = client.post("/webhooks/github", content=json.dumps(payload), headers=signed_headers(payload))
        second = client.post("/webhooks/github", content=json.dumps(payload), headers=signed_headers(payload))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["accepted"] is True
    assert second.json()["accepted"] is True
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    assert len(app_main.devin_client.sessions) == 1
    assert len(app_main.github_client.comments) == 1


def test_github_comment_is_posted_after_session_starts() -> None:
    with TestClient(app_main.app) as client:
        app_main.store.clear()
        reset_mocks()
        payload = issue_payload(issue_number=445)
        response = client.post("/webhooks/github", content=json.dumps(payload), headers=signed_headers(payload))

    assert response.status_code == 200
    assert app_main.github_client.comments
    repository, issue_number, body = app_main.github_client.comments[-1]
    assert repository == "me/superset"
    assert issue_number == 445
    assert body.startswith("Started Devin remediation session: https://app.devin.ai/sessions/")


def test_demo_routes_are_disabled_outside_demo_mode() -> None:
    original_demo_mode = app_main.settings.demo_mode
    try:
        object.__setattr__(app_main.settings, "demo_mode", False)
        with TestClient(app_main.app) as client:
            response = client.post("/demo/simulate-webhook")
    finally:
        object.__setattr__(app_main.settings, "demo_mode", original_demo_mode)

    assert response.status_code == 404


def issue_payload(issue_number: int = 42, labels: list[str] | None = None, label: str = "devin-remediate") -> dict:
    labels = labels or ["security", "devin-remediate"]
    return {
        "action": "labeled",
        "label": {"name": label},
        "repository": {"full_name": "me/superset"},
        "issue": {
            "number": issue_number,
            "title": "Fix vulnerable package",
            "body": "Upgrade the package.",
            "html_url": f"https://github.com/me/superset/issues/{issue_number}",
            "labels": [{"name": item} for item in labels],
        },
    }


def signed_headers(payload: dict) -> dict[str, str]:
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"demo-secret", body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": signature, "Content-Type": "application/json"}


def reset_mocks() -> None:
    if hasattr(app_main.devin_client, "sessions"):
        app_main.devin_client.sessions.clear()
        app_main.devin_client.get_counts.clear()
    if hasattr(app_main.github_client, "comments"):
        app_main.github_client.comments.clear()

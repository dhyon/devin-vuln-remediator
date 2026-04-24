from __future__ import annotations

from app.models import IssueContext
from app.prompts import build_remediation_prompt


def issue() -> IssueContext:
    return IssueContext(
        repository="me/superset",
        issue_number=123,
        issue_title="Dependency vulnerability in example package",
        issue_body="Scanner reported a vulnerable package. Use the narrowest safe remediation.",
        issue_url="https://github.com/me/superset/issues/123",
    )


def test_prompt_includes_issue_title_and_body() -> None:
    prompt = build_remediation_prompt(issue(), "https://github.com/me/superset")

    assert "#123 - Dependency vulnerability in example package" in prompt
    assert "Scanner reported a vulnerable package" in prompt


def test_prompt_includes_fixes_reference() -> None:
    prompt = build_remediation_prompt(issue(), "https://github.com/me/superset")

    assert "Fixes #123" in prompt
    assert "A reviewable GitHub PR linked to issue #123." in prompt


def test_prompt_includes_non_goals() -> None:
    prompt = build_remediation_prompt(issue(), "https://github.com/me/superset")

    assert "Non-goals:" in prompt
    assert "Do not auto-merge." in prompt
    assert "Do not expand scope beyond the issue." in prompt
    assert "Do not rewrite unrelated modules." in prompt


def test_prompt_includes_dependency_and_validation_guidance() -> None:
    prompt = build_remediation_prompt(issue(), "https://github.com/me/superset")

    assert "For dependency vulnerabilities, prefer the narrowest safe version bump." in prompt
    assert "For validation issues, prefer allowlists or explicit schema checks." in prompt

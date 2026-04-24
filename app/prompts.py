from __future__ import annotations

from app.models import IssueContext


def build_remediation_prompt(issue: IssueContext, repository_url: str) -> str:
    return f"""You are Devin, operating as an autonomous remediation engineer.

Repository:
{repository_url}

GitHub issue:
{issue.issue_url or "not provided"}

Issue:
#{issue.issue_number} - {issue.issue_title}

Issue body:
{issue.issue_body or "(No issue body provided.)"}

Mission:
Remediate this issue by making the smallest safe code or dependency change, validating it, and opening a pull request.

Instructions:
1. Inspect the repository and confirm the affected file, package, or behavior.
2. Implement the smallest safe remediation that satisfies the issue.
3. Do not perform broad refactors.
4. Do not upgrade unrelated dependencies.
5. Do not reformat unrelated files.
6. Add or update focused tests where practical.
7. Run the most relevant focused tests or checks.
8. Open a pull request against the default branch.
9. The PR description must include:
   - Summary
   - Security impact
   - What changed
   - Tests/checks run
   - Residual risk or follow-up
   - Fixes #{issue.issue_number}

Complexity guidance:
- For dependency vulnerabilities, prefer the narrowest safe version bump.
- For validation issues, prefer allowlists or explicit schema checks.
- For hardcoded secret-like values in tests, replace with safe placeholders and document that they are non-production fixtures.
- For error handling issues, preserve existing behavior while making failures explicit and observable.

Non-goals:
- Do not auto-merge.
- Do not expand scope beyond the issue.
- Do not rewrite unrelated modules.

If blocked:
- Open a PR with partial remediation only if it improves security safely.
- Otherwise comment with the blocker, evidence, and recommended next step.

Expected output:
A reviewable GitHub PR linked to issue #{issue.issue_number}.
"""

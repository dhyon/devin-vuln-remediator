from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx


DEFAULT_LABELS = ["security", "devin-remediate", "demo"]
COMPLEXITY_ORDER = {"small": 1, "medium": 2, "large": 3}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create GitHub issues from curated Superset security findings.")
    parser.add_argument("--findings", default="demo/findings.json", help="Curated findings JSON path.")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY"), help="GitHub fork repo, e.g. owner/superset.")
    parser.add_argument("--limit", type=int, default=8, help="Maximum issues to create.")
    parser.add_argument("--min-complexity", default=None, help="Skip findings below this complexity: small, medium, large, or 1-3.")
    parser.add_argument("--max-complexity", default=None, help="Skip findings above this complexity: small, medium, large, or 1-3.")
    parser.add_argument("--dry-run", action="store_true", help="Print issue payloads without creating issues.")
    args = parser.parse_args()

    if not args.repo:
        raise SystemExit("GITHUB_REPOSITORY or --repo is required")

    findings = filter_findings(
        load_findings(args.findings),
        limit=args.limit,
        min_complexity=parse_complexity(args.min_complexity),
        max_complexity=parse_complexity(args.max_complexity),
    )

    if not findings:
        raise SystemExit("No findings matched the requested filters.")

    token = os.getenv("GITHUB_TOKEN")
    if not token and not args.dry_run:
        raise SystemExit("GITHUB_TOKEN is required unless --dry-run is used")

    for finding in findings:
        payload = issue_payload(finding)
        if args.dry_run:
            print(json.dumps(payload, indent=2))
            continue
        response = httpx.post(
            f"https://api.github.com/repos/{args.repo}/issues",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json=payload,
            timeout=30,
        )
        handle_github_error(response, args.repo)
        print(response.json()["html_url"])


def load_findings(path: str) -> list[dict[str, Any]]:
    findings_path = Path(path)
    if not findings_path.exists():
        raise SystemExit(f"Findings file not found: {path}. Copy demo/findings.example.json to demo/findings.json and curate it.")
    with findings_path.open(encoding="utf-8") as f:
        data = json.load(f)
    findings = data.get("findings", data)
    if not isinstance(findings, list):
        raise SystemExit("Findings JSON must be a list or an object with a 'findings' list.")
    return findings


def handle_github_error(response: httpx.Response, repo: str) -> None:
    if response.status_code < 400:
        return

    message = github_error_message(response)
    if response.status_code == 410:
        raise SystemExit(
            f"GitHub rejected issue creation for {repo}: Issues appear to be disabled for this repository.\n"
            "Enable Issues in the repository settings, then rerun this script.\n"
            f"GitHub response: {message}"
        )
    if response.status_code == 401:
        raise SystemExit(
            "GitHub rejected the token with 401 Unauthorized. Check that GITHUB_TOKEN is set, copied correctly, and not expired.\n"
            f"GitHub response: {message}"
        )
    if response.status_code == 403:
        raise SystemExit(
            f"GitHub rejected issue creation for {repo} with 403 Forbidden. "
            "For a fine-grained token, grant Issues read/write access to this repository.\n"
            f"GitHub response: {message}"
        )
    if response.status_code == 404:
        raise SystemExit(
            f"GitHub could not find {repo}, or the token cannot access it. Check GITHUB_REPOSITORY and token repository access.\n"
            f"GitHub response: {message}"
        )

    response.raise_for_status()


def github_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text.strip()[:500] or f"HTTP {response.status_code}"
    if isinstance(data, dict):
        return str(data.get("message") or data)[:500]
    return str(data)[:500]


def filter_findings(
    findings: list[dict[str, Any]],
    limit: int,
    min_complexity: int | None,
    max_complexity: int | None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for finding in findings:
        complexity = finding.get("complexity")
        if complexity is not None:
            complexity_score = parse_complexity(complexity)
            if min_complexity is not None and complexity_score < min_complexity:
                continue
            if max_complexity is not None and complexity_score > max_complexity:
                continue
        selected.append(finding)
        if len(selected) >= limit:
            break
    return selected


def parse_complexity(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in COMPLEXITY_ORDER:
        return COMPLEXITY_ORDER[text]
    try:
        score = int(text)
    except ValueError as exc:
        raise SystemExit(f"Unknown complexity value: {value}. Use small, medium, large, or 1-3.") from exc
    if score not in {1, 2, 3}:
        raise SystemExit(f"Unknown complexity value: {value}. Use small, medium, large, or 1-3.")
    return score


def issue_payload(finding: dict[str, Any]) -> dict[str, Any]:
    title = finding.get("title")
    if not title:
        title = f"{finding.get('source_tool', finding.get('scanner', 'security'))}: {finding.get('category', 'security hygiene finding')}"
    return {
        "title": title,
        "body": format_issue_body(finding),
        "labels": DEFAULT_LABELS,
    }


def format_issue_body(finding: dict[str, Any]) -> str:
    source_tool = finding.get("source", finding.get("source_tool", finding.get("scanner", "manual review")))
    finding_id = finding.get("finding_id", finding.get("id", "not provided"))
    affected = finding.get("affected_file", finding.get("affected_package", finding.get("affected", "not provided")))
    severity = finding.get("severity", "not classified")
    risk = finding.get("risk", finding.get("body", finding.get("description", "Review and remediate the finding if confirmed.")))
    acceptance = as_list(
        finding.get(
            "acceptance_criteria",
            [
                "Confirm the finding is reproducible or explain why it is a false positive.",
                "Implement the smallest safe remediation.",
                "Add or update focused tests where practical.",
            ],
        )
    )
    verification = as_list(
        finding.get(
            "suggested_verification",
            [
                "Run the relevant scanner or targeted test.",
                "Document any residual risk in the pull request.",
            ],
        )
    )
    non_goals = as_list(
        finding.get(
            "non_goals",
            [
                "Do not perform broad refactors unrelated to the finding.",
                "Do not claim a CVE unless the scanner output explicitly identifies one.",
            ],
        )
    )

    lines = [
        "## Security Finding",
        "",
        f"- Source tool: {source_tool}",
        f"- Finding ID: {finding_id}",
        f"- Affected file/package: {affected}",
        f"- Severity: {severity}",
    ]
    if "category" in finding:
        lines.append(f"- Category: {finding['category']}")
    if "complexity" in finding:
        lines.append(f"- Estimated remediation complexity: {finding['complexity']}")
    if finding.get("scanner_rule"):
        lines.append(f"- Scanner rule: {finding['scanner_rule']}")
    if finding.get("cve"):
        lines.append(f"- CVE: {finding['cve']}")
    lines.extend(
        [
            "",
            "## Risk",
            "",
            str(risk),
            "",
            "## Acceptance Criteria",
            "",
            *[f"- {item}" for item in acceptance],
            "",
            "## Suggested Verification",
            "",
            *[f"- {item}" for item in verification],
            "",
            "## Non-goals",
            "",
            *[f"- {item}" for item in non_goals],
            "",
            "_This issue was created from curated scanner or security-hygiene findings for the Devin remediation demo._",
        ]
    )
    return "\n".join(lines)


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


if __name__ == "__main__":
    main()

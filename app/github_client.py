from __future__ import annotations

from typing import Protocol

import httpx


class GitHubClient(Protocol):
    async def post_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
        ...

    async def create_issue(self, owner: str, repo: str, title: str, body: str, labels: list[str]) -> dict:
        ...

    async def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
        ...

    async def comment_on_issue(self, repository: str, issue_number: int, body: str) -> None:
        ...


class RealGitHubClient:
    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")

    async def post_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/comments",
                headers=self._headers(),
                json={"body": body},
            )
            response.raise_for_status()

    async def create_issue(self, owner: str, repo: str, title: str, body: str, labels: list[str]) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/repos/{owner}/{repo}/issues",
                headers=self._headers(),
                json={"title": title, "body": body, "labels": labels},
            )
            response.raise_for_status()
            return response.json()

    async def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}",
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def comment_on_issue(self, repository: str, issue_number: int, body: str) -> None:
        owner, repo = repository.split("/", 1)
        await self.post_issue_comment(owner, repo, issue_number, body)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }


class MockGitHubClient:
    def __init__(self) -> None:
        self.comments: list[tuple[str, int, str]] = []
        self.issues: list[dict] = []

    async def comment_on_issue(self, repository: str, issue_number: int, body: str) -> None:
        self.comments.append((repository, issue_number, body))

    async def post_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> None:
        await self.comment_on_issue(f"{owner}/{repo}", issue_number, body)

    async def create_issue(self, owner: str, repo: str, title: str, body: str, labels: list[str]) -> dict:
        issue = {
            "number": len(self.issues) + 1,
            "title": title,
            "body": body,
            "labels": [{"name": label} for label in labels],
            "html_url": f"https://github.com/{owner}/{repo}/issues/{len(self.issues) + 1}",
            "repository": f"{owner}/{repo}",
        }
        self.issues.append(issue)
        return issue

    async def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
        for issue in self.issues:
            if issue["repository"] == f"{owner}/{repo}" and issue["number"] == issue_number:
                return issue
        return {
            "number": issue_number,
            "title": "",
            "body": "",
            "labels": [],
            "html_url": f"https://github.com/{owner}/{repo}/issues/{issue_number}",
        }

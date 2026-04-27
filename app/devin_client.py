from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Protocol

import httpx

from app.models import DevinSession


class DevinApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, response_body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class DevinClient(Protocol):
    async def create_session(
        self,
        prompt: str,
        title: str,
        tags: list[str],
        repos: list[str] | None = None,
    ) -> DevinSession:
        ...

    async def get_session(self, session_id: str) -> DevinSession:
        ...

    async def send_message(self, session_id: str, message: str) -> None:
        ...


class RealDevinClient:
    def __init__(
        self,
        api_key: str,
        org_id: str,
        base_url: str = "https://api.devin.ai",
        max_acu_limit: float | None = None,
        create_as_user_id: str | None = None,
        default_repos: list[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.org_id = org_id
        self.base_url = base_url.rstrip("/")
        self.max_acu_limit = max_acu_limit
        self.create_as_user_id = create_as_user_id
        self.default_repos = default_repos or []
        self.http_client = http_client

    async def create_session(
        self,
        prompt: str,
        title: str,
        tags: list[str],
        repos: list[str] | None = None,
    ) -> DevinSession:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "title": title,
            "tags": tags,
        }
        session_repos = repos if repos is not None else self.default_repos
        if session_repos:
            payload["repos"] = session_repos
        if self.max_acu_limit is not None:
            payload["max_acu_limit"] = self.max_acu_limit
        if self.create_as_user_id:
            payload["create_as_user_id"] = self.create_as_user_id

        data = await self._request_json(
            "POST",
            f"/v3/organizations/{self.org_id}/sessions",
            json=payload,
        )
        return parse_session(data)

    async def get_session(self, session_id: str) -> DevinSession:
        data = await self._request_json("GET", f"/v3/organizations/{self.org_id}/sessions/{session_id}")
        return parse_session(data)

    async def send_message(self, session_id: str, message: str) -> None:
        await self._request_json(
            "POST",
            f"/v3/organizations/{self.org_id}/sessions/{session_id}/messages",
            json={"message": message},
        )

    async def _request_json(self, method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        client = self.http_client or httpx.AsyncClient(timeout=30)
        close_client = self.http_client is None
        try:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=json,
            )
        finally:
            if close_client:
                await client.aclose()

        if response.status_code < 200 or response.status_code >= 300:
            error_body = _safe_error_body(response)
            raise DevinApiError(
                f"Devin API {method} {path} failed with HTTP {response.status_code}: {error_body}",
                status_code=response.status_code,
                response_body=error_body,
            )
        if not response.content:
            return {}
        return response.json()


class MockDevinClient:
    def __init__(self) -> None:
        self.sessions: dict[str, DevinSession] = {}
        self.get_counts: dict[str, int] = {}
        self.messages: list[tuple[str, str]] = []

    async def create_session(
        self,
        prompt: str,
        title: str,
        tags: list[str],
        repos: list[str] | None = None,
        ) -> DevinSession:
        digest = hashlib.sha1(f"{title}:{prompt}".encode()).hexdigest()[:10]
        session = DevinSession(
            session_id=f"demo-{digest}",
            status="new",
            url=f"https://app.devin.ai/sessions/demo-{digest}",
            title=title,
            tags=tags,
            repos=repos or [],
        )
        self.sessions[session.session_id] = session
        self.get_counts[session.session_id] = 0
        return session

    async def get_session(self, session_id: str) -> DevinSession:
        session = self.sessions.get(
            session_id,
            DevinSession(session_id=session_id, status="running", url=f"https://app.devin.ai/sessions/{session_id}"),
        )
        count = self.get_counts.get(session_id, 0) + 1
        self.get_counts[session_id] = count
        status = "new"
        if count == 1:
            status = "running"
        elif count == 2:
            status = "pr_opened"
        elif count >= 3:
            status = "completed"
        updated = session.model_copy(update={"status": status})
        self.sessions[session_id] = updated
        return updated

    async def send_message(self, session_id: str, message: str) -> None:
        self.messages.append((session_id, message))


def parse_session(data: dict[str, Any]) -> DevinSession:
    parsed: dict[str, Any] = {
        "session_id": str(data.get("session_id") or data.get("id")),
        "status": str(data.get("status", "running")),
        "url": data.get("url"),
        "title": data.get("title"),
        "tags": list(data.get("tags") or []),
        "repos": list(data.get("repos") or data.get("repositories") or []),
        "acu_limit": data.get("max_acu_limit") or data.get("acu_limit"),
        "updated_at": _parse_datetime(data.get("updated_at")),
    }
    created_at = _parse_datetime(data.get("created_at"))
    if created_at:
        parsed["created_at"] = created_at
    return DevinSession(**parsed)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _safe_error_body(response: httpx.Response) -> str:
    text = response.text.strip()
    if not text:
        return "empty response body"
    return text[:500]

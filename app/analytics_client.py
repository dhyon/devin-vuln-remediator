from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from app.devin_client import DevinApiError
from app.models import SessionConsumption, SessionInsights


class AnalyticsProvider(Protocol):
    async def get_session_insights(self, session_id: str) -> SessionInsights:
        ...

    async def get_session_daily_consumption(self, session_id: str) -> SessionConsumption | None:
        ...


class AnalyticsClient:
    def __init__(
        self,
        api_key: str,
        org_id: str,
        base_url: str = "https://api.devin.ai",
        enterprise_consumption_enabled: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.org_id = org_id
        self.base_url = base_url.rstrip("/")
        self.enterprise_consumption_enabled = enterprise_consumption_enabled
        self.http_client = http_client
        self.enterprise_unavailable_reason: str | None = None

    async def get_session_insights(self, session_id: str) -> SessionInsights:
        data = await self._request_json("GET", f"/v3/organizations/{self.org_id}/sessions/{session_id}/insights")
        return parse_session_insights(data)

    async def get_session_daily_consumption(self, session_id: str) -> SessionConsumption | None:
        if not self.enterprise_consumption_enabled:
            return None
        path = f"/v3/enterprise/consumption/daily/sessions/{session_id}"
        try:
            data = await self._request_json("GET", path)
        except DevinApiError as exc:
            if exc.status_code in {401, 403}:
                self.enterprise_unavailable_reason = f"Enterprise analytics unavailable: HTTP {exc.status_code}"
                return SessionConsumption(
                    session_id=session_id,
                    unavailable=True,
                    unavailable_reason=self.enterprise_unavailable_reason,
                )
            raise
        return parse_session_consumption(session_id, data)

    async def get_insights(self, session_id: str) -> SessionInsights:
        return await self.get_session_insights(session_id)

    async def _request_json(self, method: str, path: str) -> dict[str, Any]:
        client = self.http_client or httpx.AsyncClient(timeout=30)
        close_client = self.http_client is None
        try:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
            )
        finally:
            if close_client:
                await client.aclose()

        if response.status_code < 200 or response.status_code >= 300:
            raise DevinApiError(
                f"Devin analytics API {method} {path} failed with HTTP {response.status_code}: {_safe_error_body(response)}",
                status_code=response.status_code,
            )
        if not response.content:
            return {}
        return response.json()


class MockAnalyticsClient:
    def __init__(self) -> None:
        self.enterprise_unavailable_reason: str | None = None
        self.poll_counts: dict[str, int] = {}

    async def get_session_insights(self, session_id: str) -> SessionInsights:
        if session_id.endswith("fail"):
            return SessionInsights(status="failed", acu_used=2.4, failure_reason="Demo remediation failed tests")
        count = self.poll_counts.get(session_id, 0) + 1
        self.poll_counts[session_id] = count
        pr_number = int(hashlib.sha1(session_id.encode()).hexdigest()[:6], 16) % 900 + 100
        pr_url = f"https://github.com/demo/superset/pull/{pr_number}"
        if count == 1:
            return SessionInsights(
                session_id=session_id,
                status="running",
                acu_used=1.1,
                summary="Demo session is analyzing the finding and repository context.",
                url=f"https://app.devin.ai/sessions/{session_id}",
            )
        if count == 2:
            return SessionInsights(
                session_id=session_id,
                status="running",
                acu_used=2.4,
                pr_url=pr_url,
                pull_requests=[pr_url],
                summary="Demo session opened a remediation PR.",
                url=f"https://app.devin.ai/sessions/{session_id}",
            )
        return SessionInsights(
            session_id=session_id,
            status="completed",
            acu_used=3.2,
            pr_url=pr_url,
            pull_requests=[pr_url],
            summary="Demo session opened a remediation PR and completed successfully.",
            url=f"https://app.devin.ai/sessions/{session_id}",
        )

    async def get_session_daily_consumption(self, session_id: str) -> SessionConsumption | None:
        return SessionConsumption(session_id=session_id, acus_consumed=3.2)

    async def get_insights(self, session_id: str) -> SessionInsights:
        return await self.get_session_insights(session_id)


def parse_session_insights(data: dict[str, Any]) -> SessionInsights:
    pull_requests = _pull_request_urls(data.get("pull_requests"))
    pr_state = _first_pull_request_state(data.get("pull_requests"))
    analysis = data.get("analysis")
    return SessionInsights(
        session_id=data.get("session_id"),
        org_id=data.get("org_id"),
        status=str(data.get("status", "running")),
        status_detail=data.get("status_detail"),
        acu_used=float(data.get("acus_consumed") or data.get("acu_used") or data.get("acu") or 0),
        pr_url=pull_requests[0] if pull_requests else data.get("pr_url"),
        pr_state=pr_state or data.get("pr_state"),
        pull_requests=pull_requests,
        needs_input=bool(
            data.get("needs_input")
            or data.get("status") == "needs_input"
            or data.get("status_detail") == "waiting_for_user"
        ),
        failure_reason=data.get("failure_reason"),
        summary=analysis if isinstance(analysis, str) else data.get("summary"),
        url=data.get("url"),
        tags=list(data.get("tags") or []),
        session_size=data.get("session_size"),
        num_devin_messages=data.get("num_devin_messages"),
        num_user_messages=data.get("num_user_messages"),
        analysis=analysis,
        created_at=_parse_datetime(data.get("created_at")),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def parse_session_consumption(session_id: str, data: dict[str, Any]) -> SessionConsumption:
    return SessionConsumption(
        session_id=str(data.get("session_id") or session_id),
        acus_consumed=float(data.get("acus_consumed") or data.get("acu_used") or 0),
        date=data.get("date") or data.get("day"),
        raw=data,
    )


def _pull_request_urls(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        urls: list[str] = []
        for item in value:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict):
                url = item.get("pr_url") or item.get("url") or item.get("html_url")
                if url:
                    urls.append(str(url))
        return urls
    return []


def _first_pull_request_state(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, dict) and item.get("pr_state"):
            return str(item["pr_state"])
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    return None


def _safe_error_body(response: httpx.Response) -> str:
    text = response.text.strip()
    if not text:
        return "empty response body"
    return text[:500]

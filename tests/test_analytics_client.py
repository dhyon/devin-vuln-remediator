from __future__ import annotations

import asyncio

import httpx

from app.analytics_client import AnalyticsClient


def test_session_insights_parsing() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/v3/organizations/org-1/sessions/sess-123/insights"
            return httpx.Response(
                200,
                json={
                    "acus_consumed": 4.25,
                    "created_at": "2026-04-24T12:00:00Z",
                    "updated_at": "2026-04-24T12:30:00Z",
                    "num_devin_messages": 8,
                    "num_user_messages": 2,
                    "org_id": "org-1",
                    "pull_requests": [{"url": "https://github.com/me/superset/pull/9"}],
                    "session_id": "sess-123",
                    "session_size": "medium",
                    "status": "completed",
                    "tags": ["security"],
                    "url": "https://app.devin.ai/sessions/sess-123",
                    "analysis": {"summary": "PR opened and tests passed"},
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.devin.ai")
        try:
            analytics = AnalyticsClient(api_key="secret-token", org_id="org-1", http_client=client)
            insights = await analytics.get_session_insights("sess-123")
        finally:
            await client.aclose()

        assert insights.session_id == "sess-123"
        assert insights.org_id == "org-1"
        assert insights.status == "completed"
        assert insights.acu_used == 4.25
        assert insights.pr_url == "https://github.com/me/superset/pull/9"
        assert insights.pull_requests == ["https://github.com/me/superset/pull/9"]
        assert insights.num_devin_messages == 8
        assert insights.num_user_messages == 2
        assert insights.analysis == {"summary": "PR opened and tests passed"}

    asyncio.run(run())


def test_enterprise_analytics_permission_failure_is_graceful() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v3/enterprise/consumption/daily/sessions/sess-123"
            return httpx.Response(403, json={"detail": "forbidden"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.devin.ai")
        try:
            analytics = AnalyticsClient(
                api_key="secret-token",
                org_id="org-1",
                enterprise_consumption_enabled=True,
                http_client=client,
            )
            consumption = await analytics.get_session_daily_consumption("sess-123")
        finally:
            await client.aclose()

        assert consumption is not None
        assert consumption.unavailable
        assert consumption.unavailable_reason == "Enterprise analytics unavailable: HTTP 403"
        assert analytics.enterprise_unavailable_reason == "Enterprise analytics unavailable: HTTP 403"

    asyncio.run(run())

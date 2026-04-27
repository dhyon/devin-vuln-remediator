from __future__ import annotations

import asyncio
import json

import httpx

from app.devin_client import MockDevinClient, RealDevinClient


def test_create_session_request_shape() -> None:
    async def run() -> None:
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["auth"] = request.headers["Authorization"]
            captured["payload"] = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "session_id": "sess-123",
                    "status": "running",
                    "url": "https://app.devin.ai/sessions/sess-123",
                    "tags": ["security"],
                    "repos": ["me/superset"],
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.devin.ai")
        try:
            devin = RealDevinClient(
                api_key="secret-token",
                org_id="org-1",
                max_acu_limit=10,
                create_as_user_id="user-1",
                http_client=client,
            )
            session = await devin.create_session(
                prompt="Fix the finding",
                title="Remediate issue",
                tags=["security"],
                repos=["me/superset"],
            )
        finally:
            await client.aclose()

        assert captured["method"] == "POST"
        assert captured["path"] == "/v3/organizations/org-1/sessions"
        assert captured["auth"] == "Bearer secret-token"
        assert captured["payload"] == {
            "prompt": "Fix the finding",
            "title": "Remediate issue",
            "tags": ["security"],
            "repos": ["me/superset"],
            "max_acu_limit": 10,
            "create_as_user_id": "user-1",
        }
        assert session.session_id == "sess-123"

    asyncio.run(run())


def test_get_session_parsing() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/v3/organizations/org-1/sessions/sess-123"
            return httpx.Response(
                200,
                json={
                    "session_id": "sess-123",
                    "status": "completed",
                    "url": "https://app.devin.ai/sessions/sess-123",
                    "title": "Remediate issue",
                    "tags": ["security", "devin-remediate"],
                    "created_at": "2026-04-24T12:00:00Z",
                    "updated_at": "2026-04-24T12:30:00Z",
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.devin.ai")
        try:
            devin = RealDevinClient(api_key="secret-token", org_id="org-1", http_client=client)
            session = await devin.get_session("sess-123")
        finally:
            await client.aclose()

        assert session.session_id == "sess-123"
        assert session.status == "completed"
        assert session.title == "Remediate issue"
        assert session.tags == ["security", "devin-remediate"]
        assert session.updated_at is not None

    asyncio.run(run())


def test_mock_client_returns_deterministic_lifecycle_states() -> None:
    async def run() -> None:
        devin = MockDevinClient()
        session = await devin.create_session("prompt", "title", ["tag"], ["repo"])

        first = await devin.get_session(session.session_id)
        second = await devin.get_session(session.session_id)
        third = await devin.get_session(session.session_id)

        assert session.session_id == "demo-8c6976c26b"
        assert session.status == "new"
        assert first.status == "running"
        assert second.status == "pr_opened"
        assert third.status == "completed"

    asyncio.run(run())

from __future__ import annotations

import pytest

from app.config import ConfigurationError, Settings


ENV_KEYS = [
    "APP_MODE",
    "DEMO_MODE",
    "DEVIN_MODE",
    "GITHUB_MODE",
    "DEVIN_API_KEY",
    "DEVIN_ORG_ID",
    "GITHUB_TOKEN",
    "GITHUB_WEBHOOK_SECRET",
    "DATABASE_PATH",
    "TRIGGER_LABEL",
    "TARGET_LABEL",
]


def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_demo_mode_does_not_require_real_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_env(monkeypatch)
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("DEVIN_MODE", "mock")
    monkeypatch.setenv("GITHUB_MODE", "mock")
    monkeypatch.setenv("DATABASE_PATH", "/data/remediation.db")
    monkeypatch.setenv("TRIGGER_LABEL", "devin-remediate")

    settings = Settings.from_env()

    assert settings.demo_mode
    assert settings.devin_mode == "mock"
    assert settings.github_mode == "mock"
    assert settings.database_path == "/data/remediation.db"
    assert settings.target_label == "devin-remediate"
    assert settings.devin_api_key is None
    assert settings.github_token is None


def test_real_mode_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_env(monkeypatch)
    monkeypatch.setenv("APP_MODE", "real")
    monkeypatch.setenv("DEVIN_MODE", "real")
    monkeypatch.setenv("GITHUB_MODE", "real")

    with pytest.raises(ConfigurationError) as exc:
        Settings.from_env()

    message = str(exc.value)
    assert "DEVIN_API_KEY" in message
    assert "DEVIN_ORG_ID" in message
    assert "GITHUB_TOKEN" in message
    assert "GITHUB_WEBHOOK_SECRET" in message


def test_real_mode_accepts_required_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_env(monkeypatch)
    monkeypatch.setenv("APP_MODE", "real")
    monkeypatch.setenv("DEVIN_MODE", "real")
    monkeypatch.setenv("GITHUB_MODE", "real")
    monkeypatch.setenv("DEVIN_API_KEY", "devin-token")
    monkeypatch.setenv("DEVIN_ORG_ID", "org-1")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "webhook-secret")

    settings = Settings.from_env()

    assert not settings.demo_mode
    assert settings.devin_api_key == "devin-token"
    assert settings.devin_org_id == "org-1"
    assert settings.github_token == "github-token"

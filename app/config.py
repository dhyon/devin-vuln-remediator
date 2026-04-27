from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    app_name: str = "Devin Vulnerability Remediator"
    app_mode: str = "demo"
    demo_mode: bool = True
    database_path: str = "data/remediator.db"
    github_webhook_secret: str = "demo-secret"
    github_mode: str = "mock"
    allow_unsigned_github_webhooks: bool = False
    github_token: str | None = None
    github_api_base_url: str = "https://api.github.com"
    devin_api_key: str | None = None
    devin_org_id: str | None = None
    devin_api_base_url: str = "https://api.devin.ai"
    devin_mode: str = "mock"
    devin_max_acu_limit: float | None = None
    devin_create_as_user_id: str | None = None
    devin_repos: tuple[str, ...] = ()
    devin_enterprise_analytics: bool = False
    target_label: str = "devin-remediate"
    poll_limit: int = 25
    engineer_hours_per_remediation: float = 2.0
    engineer_hourly_cost: float = 150.0

    @classmethod
    def from_env(cls) -> "Settings":
        app_mode = os.getenv("APP_MODE", os.getenv("DEMO_MODE", "demo")).lower()
        if app_mode in {"1", "true", "yes", "on"}:
            app_mode = "demo"
        if app_mode in {"0", "false", "no", "off"}:
            app_mode = "real"
        devin_mode = os.getenv("DEVIN_MODE", "mock" if app_mode == "demo" else "real").lower()
        github_mode = os.getenv("GITHUB_MODE", "mock" if app_mode == "demo" else "real").lower()
        demo_mode = app_mode == "demo"
        max_acu = os.getenv("DEVIN_MAX_ACU_LIMIT")
        repos = tuple(repo.strip() for repo in os.getenv("DEVIN_REPOS", "").split(",") if repo.strip())
        webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
        settings = cls(
            app_mode=app_mode,
            demo_mode=demo_mode,
            database_path=os.getenv("DATABASE_PATH", cls.database_path),
            github_webhook_secret=webhook_secret or (cls.github_webhook_secret if demo_mode else ""),
            github_mode=github_mode,
            allow_unsigned_github_webhooks=os.getenv("ALLOW_UNSIGNED_GITHUB_WEBHOOKS", "false").lower() in {"1", "true", "yes", "on"},
            github_token=os.getenv("GITHUB_TOKEN"),
            github_api_base_url=os.getenv("GITHUB_API_BASE_URL", cls.github_api_base_url),
            devin_api_key=os.getenv("DEVIN_API_KEY"),
            devin_org_id=os.getenv("DEVIN_ORG_ID"),
            devin_api_base_url=os.getenv("DEVIN_BASE_URL", os.getenv("DEVIN_API_BASE_URL", cls.devin_api_base_url)),
            devin_mode=devin_mode,
            devin_max_acu_limit=float(max_acu) if max_acu else None,
            devin_create_as_user_id=os.getenv("DEVIN_CREATE_AS_USER_ID"),
            devin_repos=repos,
            devin_enterprise_analytics=os.getenv("DEVIN_ENTERPRISE_ANALYTICS", "false").lower() in {"1", "true", "yes", "on"},
            target_label=os.getenv("TRIGGER_LABEL", os.getenv("TARGET_LABEL", cls.target_label)),
            poll_limit=int(os.getenv("POLL_LIMIT", str(cls.poll_limit))),
            engineer_hours_per_remediation=float(os.getenv("ENGINEER_HOURS_PER_REMEDIATION", str(cls.engineer_hours_per_remediation))),
            engineer_hourly_cost=float(os.getenv("ENGINEER_HOURLY_COST", str(cls.engineer_hourly_cost))),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.app_mode not in {"demo", "real"}:
            raise ConfigurationError("APP_MODE must be either 'demo' or 'real'")
        if self.devin_mode not in {"mock", "real"}:
            raise ConfigurationError("DEVIN_MODE must be either 'mock' or 'real'")
        if self.github_mode not in {"mock", "real"}:
            raise ConfigurationError("GITHUB_MODE must be either 'mock' or 'real'")
        if self.poll_limit < 1:
            raise ConfigurationError("POLL_LIMIT must be at least 1")
        if self.engineer_hours_per_remediation < 0:
            raise ConfigurationError("ENGINEER_HOURS_PER_REMEDIATION must be non-negative")
        if self.engineer_hourly_cost < 0:
            raise ConfigurationError("ENGINEER_HOURLY_COST must be non-negative")
        if self.demo_mode:
            return
        missing: list[str] = []
        if self.devin_mode == "real":
            if not self.devin_api_key:
                missing.append("DEVIN_API_KEY")
            if not self.devin_org_id:
                missing.append("DEVIN_ORG_ID")
        if self.github_mode == "real" and not self.github_token:
            missing.append("GITHUB_TOKEN")
        if not self.github_webhook_secret:
            missing.append("GITHUB_WEBHOOK_SECRET")
        if missing:
            raise ConfigurationError(f"Missing required real-mode environment variables: {', '.join(missing)}")

    def ensure_paths(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)


settings = Settings.from_env()

"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, populated from env vars or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "feature-flag-service"
    env: str = "local"

    # Logging
    log_level: str = "INFO"
    log_json: bool = True

    # Database (async SQLAlchemy URL)
    database_url: str = "postgresql+asyncpg://flags:flags@localhost:5432/flags"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Cache
    cache_ttl_seconds: float = 30.0

    # Admin
    # Shared secret required (via the `x-admin-token` header) to reach the
    # /admin/* endpoints. When unset the admin endpoints are disabled entirely.
    admin_token: str | None = None

    # Evaluation
    # Safe result served when the database is unavailable and no cached snapshot
    # exists. Defaults to OFF so a degraded backend never silently enables flags.
    evaluation_fallback_enabled: bool = False

    # OpenTelemetry
    otel_enabled: bool = False
    otel_service_name: str = "feature-flag-service"
    otel_exporter_otlp_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()

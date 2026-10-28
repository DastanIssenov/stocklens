"""Application settings loaded from environment variables / `.env` (pydantic-settings).

Secrets are `SecretStr` so they never end up in logs or reprs.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_DIR = _BACKEND_DIR.parent

DISCLAIMER = "Educational project. Predictions and reviews are not investment advice."
DEV_JWT_SECRET = "dev-only-change-me-please-32-bytes-min"  # noqa: S105 - refused in prod by the validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_REPO_DIR / ".env"), str(_BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- app ---
    app_name: str = "Stock Platform API"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = False
    cors_origins: str = "http://localhost:3000,http://localhost"

    # --- infrastructure ---
    database_url: str = "postgresql+asyncpg://stock:stock@localhost:5432/stock"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None

    # --- auth ---
    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    # --- external data (names match TASK.md §0.7) ---
    alpaca_key: SecretStr | None = None
    alpaca_secret: SecretStr | None = None
    alpaca_endpoint: str | None = None
    alpaca_data_url: str = "https://data.alpaca.markets"
    finnhub_key: SecretStr | None = None
    fred_key: SecretStr | None = None
    sec_user_agent: str | None = None
    tradernet_url: str = "https://tradernet.com/api/"
    tradernet_min_interval_s: float = 5.0
    http_timeout_s: float = 30.0

    # --- ML providers: switching mock -> real is a config change only ---
    prediction_provider: Literal["mock", "mlflow"] = "mock"
    trade_reviewer: Literal["auto", "mock", "llm"] = "auto"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_timeout_s: float = 30.0
    mlflow_tracking_uri: str | None = None

    # --- paper trading ---
    starting_cash_usd: Decimal = Decimal("100000")
    starting_cash_kzt: Decimal = Decimal("50000000")
    fallback_usdkzt: Decimal = Decimal("450")
    fee_rate_us: Decimal = Decimal("0.0005")
    fee_min_us: Decimal = Decimal("1")
    fee_rate_kase: Decimal = Decimal("0.0015")
    fee_min_kase: Decimal = Decimal("300")
    fee_rate_lse: Decimal = Decimal("0.001")
    fee_min_lse: Decimal = Decimal("3")
    max_position_weight_warn: float = 0.25

    # --- rate limiting (requests per minute) ---
    rate_limit_enabled: bool = True
    rate_limit_default: int = 120
    rate_limit_auth: int = 10
    rate_limit_trades: int = 30

    # --- cache TTLs (seconds) ---
    cache_ttl_prices: int = 600
    cache_ttl_quote: int = 60
    cache_ttl_overview: int = 60
    cache_ttl_predictions: int = 3600
    cache_ttl_news: int = 300

    # --- background jobs ---
    data_updates_enabled: bool = True

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        # docker / Heroku style URLs -> asyncpg driver
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://") :]
        return v

    @model_validator(mode="after")
    def _prod_needs_real_secret(self) -> Settings:
        if self.environment == "prod" and self.jwt_secret.get_secret_value() == DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET must be set in production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def alpaca_configured(self) -> bool:
        return bool(self.alpaca_key and self.alpaca_secret)

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()

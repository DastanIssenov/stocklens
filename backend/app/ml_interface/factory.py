"""Builds ML providers from settings. Switching mock → real happens here, driven by `.env` only."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.ml_interface.base import PredictionProvider, TradeReviewer
from app.ml_interface.mock import MockPredictionProvider, MockTradeReviewer
from app.ml_interface.openai_compat import OpenAICompatibleTradeReviewer

log = get_logger(__name__)


def build_prediction_provider(settings: Settings) -> PredictionProvider:
    if settings.prediction_provider == "mlflow":
        # GPU phase: `MLflowPredictionProvider` (docs/GPU_PLAN.md §8). Until it exists we fall back.
        log.warning("mlflow_provider_not_available_using_mock")
    return MockPredictionProvider()


def build_trade_reviewer(settings: Settings) -> TradeReviewer:
    want_llm = settings.trade_reviewer == "llm" or (
        settings.trade_reviewer == "auto" and settings.llm_configured
    )
    if want_llm:
        if not settings.llm_configured:
            log.warning("llm_reviewer_requested_but_not_configured_using_mock")
            return MockTradeReviewer()
        assert settings.llm_base_url and settings.llm_api_key and settings.llm_model
        return OpenAICompatibleTradeReviewer(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
            model=settings.llm_model,
            timeout_s=settings.llm_timeout_s,
        )
    return MockTradeReviewer()


@lru_cache
def get_prediction_provider() -> PredictionProvider:
    return build_prediction_provider(get_settings())


@lru_cache
def get_trade_reviewer() -> TradeReviewer:
    return build_trade_reviewer(get_settings())


def get_fallback_reviewer() -> TradeReviewer:
    return MockTradeReviewer()

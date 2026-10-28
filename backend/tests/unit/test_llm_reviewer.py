import json

import httpx
import pytest

from app.core.config import Settings
from app.ml_interface.factory import build_trade_reviewer
from app.ml_interface.mock import MockTradeReviewer
from app.ml_interface.openai_compat import OpenAICompatibleTradeReviewer, _extract_json
from tests.unit.test_ml_mocks import _ctx

GOOD = {
    "verdict": "reasonable",
    "score": 7,
    "summary": "ok",
    "reasons": ["r1", "r2", "r3"],
    "risks": ["x"],
    "what_to_watch": ["w"],
}


def _transport(contents: list[str], seen: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"auth": request.headers.get("authorization"), "body": body, "url": str(request.url)})
        content = contents[min(len(seen) - 1, len(contents) - 1)]
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler)


async def test_llm_reviewer_parses_strict_json() -> None:
    seen: list[dict] = []
    r = OpenAICompatibleTradeReviewer(
        "http://llm/v1/", "k", "m", transport=_transport([json.dumps(GOOD)], seen)
    )
    out = await r.review(_ctx(), lang="ru")
    assert out.verdict == "reasonable" and out.score == 7
    assert seen[0]["url"] == "http://llm/v1/chat/completions"
    assert seen[0]["auth"] == "Bearer k"
    assert seen[0]["body"]["response_format"] == {"type": "json_object"}
    assert "Russian" in seen[0]["body"]["messages"][1]["content"]


async def test_llm_reviewer_retries_once_then_fails() -> None:
    seen: list[dict] = []
    bad = json.dumps({**GOOD, "score": 99})
    r = OpenAICompatibleTradeReviewer(
        "http://llm/v1", "k", "m", transport=_transport([bad, json.dumps(GOOD)], seen)
    )
    assert (await r.review(_ctx())).score == 7
    assert len(seen) == 2
    seen2: list[dict] = []
    r2 = OpenAICompatibleTradeReviewer("http://llm/v1", "k", "m", transport=_transport([bad], seen2))
    with pytest.raises(ValueError):
        await r2.review(_ctx())


def test_extract_json_variants() -> None:
    assert json.loads(_extract_json('```json\n{"a": 1}\n```')) == {"a": 1}
    assert json.loads(_extract_json('Sure! {"a": 2} hope this helps')) == {"a": 2}


def test_factory_selects_reviewer_by_config_only() -> None:
    assert isinstance(
        build_trade_reviewer(Settings(_env_file=None, trade_reviewer="auto")), MockTradeReviewer
    )
    llm = Settings(
        _env_file=None, trade_reviewer="auto", llm_base_url="http://x/v1", llm_api_key="k", llm_model="qwen"
    )
    assert isinstance(build_trade_reviewer(llm), OpenAICompatibleTradeReviewer)
    forced_mock = Settings(
        _env_file=None, trade_reviewer="mock", llm_base_url="http://x", llm_api_key="k", llm_model="q"
    )
    assert isinstance(build_trade_reviewer(forced_mock), MockTradeReviewer)
    misconfigured = Settings(_env_file=None, trade_reviewer="llm")
    assert isinstance(build_trade_reviewer(misconfigured), MockTradeReviewer)

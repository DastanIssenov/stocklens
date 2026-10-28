"""Trade reviewer backed by any OpenAI-compatible `/chat/completions` endpoint.

Works with hosted APIs and with vLLM / llama.cpp / Ollama servers (GPU phase: vLLM on the RTX 5090).
Used only when LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are set.
"""

from __future__ import annotations

import json
import re

import httpx
from pydantic import ValidationError

from app.core.logging import get_logger
from app.ml_interface.base import TradeContext, TradeReviewer, TradeReviewOutput

log = get_logger(__name__)

_LANG_NAMES = {"en": "English", "ru": "Russian", "kk": "Kazakh"}

SYSTEM_PROMPT = """You are a cautious trading coach inside an EDUCATIONAL paper-trading simulator.
You review one simulated trade. You never give investment advice, never promise returns and never tell
the user what to buy. Judge only risk management and reasoning quality, using ONLY the facts given.

Reply with ONE JSON object and nothing else, exactly with these keys:
{
  "verdict": "reasonable" | "risky" | "poor",
  "score": integer 1-10 (10 = very sensible risk management),
  "summary": one sentence,
  "reasons": 3 to 5 short strings explaining the verdict with numbers from the facts,
  "risks": 1 to 5 short strings,
  "what_to_watch": 1 to 5 short strings
}
Demo model predictions (prediction_is_demo = true) are random placeholders: mention them at most once
and never rely on them."""


def _extract_json(text: str) -> str:
    """Accept bare JSON or JSON wrapped in ```json fences / extra prose."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


class OpenAICompatibleTradeReviewer(TradeReviewer):
    name = "llm"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self._transport = transport

    async def _complete(self, client: httpx.AsyncClient, messages: list[dict[str, str]]) -> str:
        resp = await client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 700,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        return str(resp.json()["choices"][0]["message"]["content"])

    async def review(self, ctx: TradeContext, lang: str = "en") -> TradeReviewOutput:
        facts = ctx.model_dump(mode="json")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Write all text values in {_LANG_NAMES.get(lang, 'English')}.\n"
                f"Trade facts (JSON):\n{json.dumps(facts, ensure_ascii=False)}",
            },
        ]
        async with httpx.AsyncClient(timeout=self.timeout_s, transport=self._transport) as client:
            last_error: Exception | None = None
            for attempt in range(2):  # one retry with the validation error fed back
                content = await self._complete(client, messages)
                try:
                    return TradeReviewOutput.model_validate_json(_extract_json(content))
                except ValidationError as e:
                    last_error = e
                    log.warning("llm_review_invalid_json", attempt=attempt, errors=e.error_count())
                    messages += [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": "Your JSON did not match the schema: "
                            f"{e.errors(include_url=False, include_input=False)}. "
                            "Reply with corrected JSON only.",
                        },
                    ]
        raise ValueError(f"LLM returned invalid review JSON: {last_error}")

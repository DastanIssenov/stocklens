"""Polite HTTP: one client per source, per-source rate limit, retries with back-off on 429/5xx."""

from __future__ import annotations

import time
from typing import Any

import httpx

from data_pipeline.config import RATE, USER_AGENT


class SourceError(RuntimeError):
    pass


class Polite:
    def __init__(self, source: str, headers: dict[str, str] | None = None, timeout: float = 60) -> None:
        self.source = source
        self.min_interval = 1.0 / RATE[source]
        self._last = 0.0
        self.client = httpx.Client(
            timeout=timeout, headers={"User-Agent": USER_AGENT, **(headers or {})}, follow_redirects=True
        )
        self.calls = 0

    def get(self, url: str, params: dict[str, Any] | None = None, retries: int = 4) -> httpx.Response:
        for attempt in range(retries + 1):
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.calls += 1
            try:
                r = self.client.get(url, params=params)
            except httpx.TransportError as e:
                if attempt == retries:
                    raise SourceError(f"{self.source}: {type(e).__name__}") from e
                time.sleep(2**attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == retries:
                    raise SourceError(f"{self.source}: HTTP {r.status_code}")
                time.sleep(float(r.headers.get("Retry-After") or 2**attempt))
                continue
            return r
        raise SourceError(f"{self.source}: retries exhausted")  # pragma: no cover

    def close(self) -> None:
        self.client.close()

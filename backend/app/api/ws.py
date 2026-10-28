"""WebSocket `/ws/prices`: pushes live quotes published by workers on the Redis `prices` channel."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.core.redis import PRICES_CHANNEL, get_redis
from app.services.market import quote_key

log = get_logger(__name__)
router = APIRouter()

MAX_SYMBOLS = 50


class PriceHub:
    """One Redis subscription per process, fanned out to all connected sockets."""

    def __init__(self) -> None:
        self.clients: dict[WebSocket, set[str]] = {}
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen(), name="price-hub")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _listen(self) -> None:
        while True:
            pubsub = get_redis().pubsub()
            try:
                await pubsub.subscribe(PRICES_CHANNEL)
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    await self.broadcast(json.loads(msg["data"]))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # reconnect after Redis hiccups
                log.warning("price_hub_error", error=str(e))
                await asyncio.sleep(2)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()

    async def broadcast(self, quote: dict[str, Any]) -> None:
        sym = quote.get("symbol")
        dead = []
        for ws, symbols in list(self.clients.items()):
            if symbols and sym not in symbols:
                continue
            try:
                await ws.send_json({"type": "quote", **quote})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.pop(ws, None)


hub = PriceHub()


@router.websocket("/ws/prices")
async def ws_prices(websocket: WebSocket) -> None:
    await websocket.accept()
    raw = websocket.query_params.get("symbols", "")
    symbols = {s.strip().upper() for s in raw.split(",") if s.strip()}
    if len(symbols) > MAX_SYMBOLS:
        await websocket.close(code=1008, reason="too many symbols")
        return
    hub.clients[websocket] = symbols
    try:
        # initial snapshot of whatever live quotes exist
        if symbols:
            vals = await get_redis().mget([quote_key(s) for s in symbols])
            for v in vals:
                if v:
                    await websocket.send_json({"type": "quote", **json.loads(v)})
        while True:  # keep the connection open; clients may send pings / new symbol lists
            msg = await websocket.receive_text()
            if msg.startswith("subscribe:"):
                new = {s.strip().upper() for s in msg[len("subscribe:") :].split(",") if s.strip()}
                hub.clients[websocket] = set(list(new)[:MAX_SYMBOLS])
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.pop(websocket, None)

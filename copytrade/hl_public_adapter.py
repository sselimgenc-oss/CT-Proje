"""Explicitly invoked, public-only Hyperliquid fills adapter.

No connections are opened at import or construction time. The adapter exposes
only the public userFills websocket subscription and read-only info backfill.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable
from urllib.request import Request, urlopen


DEFAULT_WS_URL = "wss://api.hyperliquid.xyz/ws"
DEFAULT_INFO_URL = "https://api.hyperliquid.xyz/info"


class HyperliquidPublicAdapter:
    """Runtime adapter using injectable websocket and HTTP transports."""

    def __init__(self, *, ws_url: str = DEFAULT_WS_URL, info_url: str = DEFAULT_INFO_URL,
                 ws_connect: Callable[..., Any] | None = None,
                 http_post: Callable[[str, dict[str, Any], float], Any] | None = None,
                 request_timeout_seconds: float = 20.0) -> None:
        if not ws_url.startswith("wss://") or not info_url.startswith("https://"):
            raise ValueError("yalnız güvenli public wss/https uçları desteklenir")
        self.ws_url, self.info_url = ws_url, info_url
        self._ws_connect = ws_connect
        self._http_post = http_post or self._post_json
        self.request_timeout_seconds = request_timeout_seconds
        self._socket = None

    @staticmethod
    def _post_json(url: str, payload: dict[str, Any], timeout: float) -> Any:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    async def connect(self, addresses: tuple[str, ...]) -> None:
        if not addresses or any(not isinstance(a, str) or not a.strip() for a in addresses):
            raise ValueError("açık public adres abonelikleri gerekli")
        if self._socket is not None:
            raise RuntimeError("adapter zaten bağlı")
        connector = self._ws_connect
        if connector is None:
            try:
                from websockets.asyncio.client import connect as connector
            except ImportError as exc:
                raise RuntimeError("WebSocket için websockets paketi kurulmalı") from exc
        self._socket = await connector(self.ws_url, open_timeout=self.request_timeout_seconds,
                                       ping_interval=20, ping_timeout=20)
        try:
            for address in addresses:
                await self._socket.send(json.dumps({"method": "subscribe", "subscription": {
                    "type": "userFills", "user": address}}, separators=(",", ":")))
        except Exception:
            await self.close()
            raise

    async def receive(self, timeout_seconds: float) -> Any | None:
        if self._socket is None:
            raise RuntimeError("adapter bağlı değil")
        while True:
            try:
                raw = await asyncio.wait_for(self._socket.recv(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            message = json.loads(raw)
            if isinstance(message, dict) and message.get("channel") == "userFills":
                return message
            # Subscription acknowledgements and server control frames are not fills.

    async def backfill(self, plan: dict[str, Any], addresses: tuple[str, ...]) -> list[Any]:
        if plan.get("kind") != "read_only_backfill_request":
            raise ValueError("read-only backfill plan bekleniyordu")
        start_ms, end_ms = plan.get("start_ms"), plan.get("end_ms")
        if not isinstance(start_ms, int) or not isinstance(end_ms, int) or start_ms < 0 or end_ms < start_ms:
            raise ValueError("backfill zaman aralığı geçersiz")
        messages: list[Any] = []
        for address in addresses:
            payload = {"type": "userFillsByTime", "user": address,
                       "startTime": start_ms, "endTime": end_ms}
            # The transport is deliberately injectable; urllib is the dependency
            # free default. Avoid implicit executor creation in hosts that disable
            # thread pools, while callers needing nonblocking HTTP can inject an
            # async-aware wrapper separately in a future protocol revision.
            result = self._http_post(self.info_url, payload, self.request_timeout_seconds)
            if not isinstance(result, list):
                raise ValueError("userFillsByTime yanıtı liste olmalı")
            messages.append({"channel": "userFills", "data": {"user": address, "fills": result}})
        return messages

    async def close(self) -> None:
        socket, self._socket = self._socket, None
        if socket is not None:
            await socket.close()

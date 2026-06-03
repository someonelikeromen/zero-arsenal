"""
用途: IP 级别速率限制中间件（02-system-architecture.md §6 rate_limit.py）
用法: app.add_middleware(RateLimitMiddleware, requests_per_minute=60, burst=10)
环境变量:
    ZERO_ARSENAL_RATE_LIMIT  — 每分钟允许的请求数（默认 60）
    ZERO_ARSENAL_RATE_BURST  — 突发允许额度（默认 10）
    ZERO_ARSENAL_RATE_ENABLED — "0" 禁用（默认 "1" 启用）
MCP集成: 不适用（ASGI 中间件）
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

_DEFAULT_RPM  = int(os.getenv("ZERO_ARSENAL_RATE_LIMIT", "60"))
_DEFAULT_BURST = int(os.getenv("ZERO_ARSENAL_RATE_BURST", "10"))
_ENABLED = os.getenv("ZERO_ARSENAL_RATE_ENABLED", "1") != "0"

# SSE 流式端点豁免（长连接，不应被 RPM 限制）
_SSE_PATH_PREFIXES = ("/api/sessions/",)
_SSE_PATH_SUFFIXES = ("/events", "/stream")


def _is_sse_path(path: str) -> bool:
    return any(path.endswith(s) for s in _SSE_PATH_SUFFIXES)


class _TokenBucket:
    """令牌桶算法：支持 burst 突发 + RPM 平滑限速。"""

    __slots__ = ("tokens", "last_refill", "capacity", "refill_rate")

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self.capacity = float(capacity)
        self.refill_rate = refill_rate   # tokens per second

    def consume(self, amount: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    基于令牌桶的 IP 级别速率限制。
    SSE 长连接路径自动豁免，OPTIONS/HEAD 请求豁免。
    """

    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int = _DEFAULT_RPM,
        burst: int = _DEFAULT_BURST,
    ) -> None:
        super().__init__(app)
        self._rpm = requests_per_minute
        self._burst = burst
        self._refill_rate = requests_per_minute / 60.0
        # client_ip → TokenBucket（内存状态；单进程单机适用）
        self._buckets: dict[str, _TokenBucket] = defaultdict(
            lambda: _TokenBucket(self._burst, self._refill_rate)
        )
        self._enabled = _ENABLED

    def _get_client_ip(self, request: Request) -> str:
        # 尊重反向代理头
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._enabled:
            return await call_next(request)

        # 豁免 OPTIONS/HEAD
        if request.method in ("OPTIONS", "HEAD"):
            return await call_next(request)

        # 豁免 SSE 流式端点
        if _is_sse_path(request.url.path):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        bucket = self._buckets[client_ip]

        if not bucket.consume():
            logger.warning("[RateLimit] %s throttled on %s", client_ip, request.url.path)
            return JSONResponse(
                status_code=429,
                content={
                    "ok": False,
                    "error_code": "rate_limited",
                    "message": f"Too Many Requests. Limit: {self._rpm} req/min.",
                    "retry_after_seconds": round(1.0 / self._refill_rate, 1),
                },
                headers={"Retry-After": str(round(1.0 / self._refill_rate))},
            )

        return await call_next(request)

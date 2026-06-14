"""
用途: IP 级别速率限制中间件（02-system-architecture.md §6 rate_limit.py）
用法: app.add_middleware(RateLimitMiddleware, requests_per_minute=60, burst=10)
环境变量:
    ZERO_ARSENAL_RATE_LIMIT  — 每分钟允许的请求数（默认 60）
    ZERO_ARSENAL_RATE_BURST  — 突发允许额度（默认 10）
    ZERO_ARSENAL_RATE_ENABLED — "1" 启用（默认 "0" 禁用，本地开发不限流）
MCP集成: 不适用（ASGI 中间件）
"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

_DEFAULT_RPM  = int(os.getenv("ZERO_ARSENAL_RATE_LIMIT", "60"))
_DEFAULT_BURST = int(os.getenv("ZERO_ARSENAL_RATE_BURST", "10"))
_ENABLED = os.getenv("ZERO_ARSENAL_RATE_ENABLED", "0") != "0"

# NEW-C7-02：仅信任来自受信反向代理的 X-Forwarded-For。
# ZERO_ARSENAL_TRUSTED_PROXIES：逗号分隔的可信代理对端 IP（如 "127.0.0.1,10.0.0.1"）。
# 为空时不信任任何 XFF（直接用 request.client.host），杜绝伪造 IP 绕过限速。
_TRUSTED_PROXIES = frozenset(
    p.strip() for p in os.getenv("ZERO_ARSENAL_TRUSTED_PROXIES", "").split(",") if p.strip()
)

# NEW-C7-01：令牌桶淘汰参数（防止伪造 IP 撑爆内存）。
_BUCKET_IDLE_TTL = float(os.getenv("ZERO_ARSENAL_RATE_BUCKET_TTL", "300"))  # 空闲桶存活秒数
_BUCKET_SWEEP_INTERVAL = 60.0  # 两次清扫的最小间隔（秒）
_BUCKET_MAX_ENTRIES = int(os.getenv("ZERO_ARSENAL_RATE_BUCKET_MAX", "10000"))  # 硬上限

# SSE 流式端点豁免（长连接 / LLM 生成流，不应被 RPM 限制）
_SSE_PATH_SUFFIXES = ("/events", "/stream")
_SSE_PATH_EXACT = (
    "/api/characters/generate",
    "/api/characters/generate/questions",
)


def _is_sse_path(path: str) -> bool:
    if path in _SSE_PATH_EXACT:
        return True
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
        # 不再用 defaultdict（避免读取即建桶），改为显式 get-or-create，便于淘汰统计。
        self._buckets: dict[str, _TokenBucket] = {}
        self._last_sweep = time.monotonic()
        self._enabled = _ENABLED

    def _get_client_ip(self, request: Request) -> str:
        # NEW-C7-02：仅当直接对端是受信代理时，才采信 X-Forwarded-For 首段。
        peer = request.client.host if request.client else "unknown"
        if peer in _TRUSTED_PROXIES:
            xff = request.headers.get("X-Forwarded-For", "")
            if xff:
                return xff.split(",")[0].strip()
        return peer

    def _get_bucket(self, client_ip: str) -> _TokenBucket:
        bucket = self._buckets.get(client_ip)
        if bucket is None:
            bucket = _TokenBucket(self._burst, self._refill_rate)
            self._buckets[client_ip] = bucket
        return bucket

    def _sweep_idle_buckets(self) -> None:
        """NEW-C7-01：淘汰空闲（已满且久未活动）的令牌桶，限制内存增长。"""
        now = time.monotonic()
        if now - self._last_sweep < _BUCKET_SWEEP_INTERVAL:
            return
        self._last_sweep = now
        stale = [
            ip for ip, b in self._buckets.items()
            if (now - b.last_refill) > _BUCKET_IDLE_TTL and b.tokens >= b.capacity
        ]
        for ip in stale:
            self._buckets.pop(ip, None)
        # 硬上限保护：仍超限时，淘汰最久未活动的条目
        if len(self._buckets) > _BUCKET_MAX_ENTRIES:
            overflow = sorted(self._buckets.items(), key=lambda kv: kv[1].last_refill)
            for ip, _ in overflow[: len(self._buckets) - _BUCKET_MAX_ENTRIES]:
                self._buckets.pop(ip, None)
        if stale:
            logger.debug("[RateLimit] swept %d idle buckets (total=%d)",
                         len(stale), len(self._buckets))

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._enabled:
            return await call_next(request)

        # 豁免 OPTIONS/HEAD
        if request.method in ("OPTIONS", "HEAD"):
            return await call_next(request)

        # 豁免 SSE 流式端点
        if _is_sse_path(request.url.path):
            return await call_next(request)

        self._sweep_idle_buckets()
        client_ip = self._get_client_ip(request)
        bucket = self._get_bucket(client_ip)

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

"""
Bearer Token 校验中间件。

启用方式（backend/main.py）：
    from backend.api.middleware import AuthMiddleware
    app.add_middleware(AuthMiddleware)

环境变量：
    ZERO_ARSENAL_API_TOKEN — 若设置，则所有 /api/* 请求必须携带
                             `Authorization: Bearer <token>` 头；SSE /events
                             也可用 access_token query 参数（EventSource 限制）。
                             未设置时仅放行本地回环，远程 403。

排除路径（无论 token 是否配置，均不校验）：
    /docs、/redoc、/openapi.json、/api/openapi.json、/health
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)
_SKIP_PREFIXES = ("/docs", "/redoc", "/openapi", "/health")


class AuthMiddleware(BaseHTTPMiddleware):
    """可选 Bearer Token 校验中间件。"""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._token: str = os.environ.get("ZERO_ARSENAL_API_TOKEN", "").strip()
        if not self._token:
            logger.warning(
                "\n"
                "╔══════════════════════════════════════════════════════════════╗\n"
                "║  ⚠️  ZERO_ARSENAL_API_TOKEN 未设置（fail-closed）：           ║\n"
                "║  仅放行本地回环（127.0.0.1/::1）的 /api 请求，远程一律 403。 ║\n"
                "║  生产部署请设置环境变量 ZERO_ARSENAL_API_TOKEN=<secret>      ║\n"
                "╚══════════════════════════════════════════════════════════════╝"
            )

    @staticmethod
    def _is_loopback(request: Request) -> bool:
        client_host = request.client.host if request.client else ""
        return client_host in ("127.0.0.1", "::1", "localhost")

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path

        # 跳过文档 / 健康检查路径，且仅拦截 /api/*
        if any(path.startswith(skip) for skip in _SKIP_PREFIXES) or not path.startswith("/api"):
            return await call_next(request)

        # token 未配置 → fail-closed：仅放行本地回环请求，远程拒绝（D4）
        if not self._token:
            if self._is_loopback(request):
                return await call_next(request)
            return JSONResponse(
                status_code=403,
                content={
                    "error": "forbidden",
                    "message": "API token not configured; remote access denied (fail-closed)",
                },
            )

        auth_header = request.headers.get("Authorization", "")
        query_token = request.query_params.get("access_token", "") if path.endswith("/events") else ""
        if not auth_header.startswith("Bearer ") and not query_token:
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "Missing Bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        provided_token = query_token or auth_header.removeprefix("Bearer ").strip()
        # 常量时间比较，避免计时侧信道（NEW-C7-03）
        if not hmac.compare_digest(provided_token, self._token):
            return JSONResponse(
                status_code=403,
                content={"error": "forbidden", "message": "Invalid API token"},
            )

        return await call_next(request)

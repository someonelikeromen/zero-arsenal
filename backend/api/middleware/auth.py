"""
Bearer Token 校验中间件。

启用方式（backend/main.py）：
    from backend.api.middleware import AuthMiddleware
    app.add_middleware(AuthMiddleware)

环境变量：
    ZERO_ARSENAL_API_TOKEN — 若设置，则所有 /api/* 请求必须携带
                             `Authorization: Bearer <token>` 头；
                             未设置时中间件直接放行（开发模式）。

排除路径（无论 token 是否配置，均不校验）：
    /docs、/redoc、/openapi.json、/api/openapi.json、/health
"""
from __future__ import annotations

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
                "║  ⚠️  ZERO_ARSENAL_API_TOKEN 未设置，API 处于完全开放状态！   ║\n"
                "║  生产部署时请设置环境变量 ZERO_ARSENAL_API_TOKEN=<secret>    ║\n"
                "╚══════════════════════════════════════════════════════════════╝"
            )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # token 未配置 → 开发模式，直接放行
        if not self._token:
            return await call_next(request)

        path = request.url.path

        # 跳过文档 / 健康检查路径
        if any(path.startswith(skip) for skip in _SKIP_PREFIXES):
            return await call_next(request)

        # 只拦截 /api/* 路径
        if not path.startswith("/api"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "Missing Bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        provided_token = auth_header.removeprefix("Bearer ").strip()
        if provided_token != self._token:
            return JSONResponse(
                status_code=403,
                content={"error": "forbidden", "message": "Invalid API token"},
            )

        return await call_next(request)

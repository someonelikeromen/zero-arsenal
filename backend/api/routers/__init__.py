"""
API 子路由包。
从此处导入各功能模块的 router，由 api/routes.py 聚合挂载。
"""
from .sessions import router as sessions_router
from .stream import router as stream_router
from .engine import router as engine_router
from .config import router as config_router

__all__ = ["sessions_router", "stream_router", "engine_router", "config_router"]

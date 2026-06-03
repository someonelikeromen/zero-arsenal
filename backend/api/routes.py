"""
API 路由聚合器。

将各功能模块的子路由挂载到统一的 /api 前缀下：
  - sessions   : 会话 CRUD、角色卡、章节、记忆、NPC、统计等
  - stream     : 消息发送 + SSE 事件流
  - engine     : 骰子、技能、扩展、Agent Profile、工具
  - config     : WorldPlugin、MCP、LLM 路由、API Keys、系统信息
  - worlds     : 全局世界模板 CRUD + SSE 提炼
  - characters : 全局人物模板 CRUD + SSE 生成
  - assets     : 全局 NPC/物品模板 CRUD
  - prompts    : 全局提示词模板 CRUD

对外只暴露 `router`，由 backend/main.py 的 `app.include_router(router)` 挂载。
"""
from fastapi import APIRouter

from .routers.sessions import router as _sessions
from .routers.stream import router as _stream
from .routers.engine import router as _engine
from .routers.config import router as _config
from .routers.worlds import router as _worlds
from .routers.characters import router as _characters
from .routers.assets import router as _assets
from .routers.prompts import router as _prompts

router = APIRouter(prefix="/api")
router.include_router(_sessions)
router.include_router(_stream)
router.include_router(_engine)
router.include_router(_config)
router.include_router(_worlds)
router.include_router(_characters)
router.include_router(_assets)
router.include_router(_prompts)

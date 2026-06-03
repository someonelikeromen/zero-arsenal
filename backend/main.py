"""
零度武库 (ZeroArsenal) — FastAPI 主入口
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

import sys
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


def _log(msg: str) -> None:
    """跨平台安全 print（避免 Windows GBK 编码错误）。"""
    print(msg, flush=True, file=sys.stderr)

from .db import init_db, set_db_path
from .engine import set_archive_dir
from .api import router
from .api.middleware import AuthMiddleware
from .api.middleware.rate_limit import RateLimitMiddleware
from .tools import skill_registry

# ── 配置 ─────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH  = DATA_DIR / "zero_arsenal.db"
DICE_ARCHIVE_DIR = DATA_DIR / "dice-archive"
SKILLS_DIR = BASE_DIR / "skills"

# 扩展技能目录（自动发现 extensions/*/skills/）
EXTENSION_DIRS = list((BASE_DIR / "extensions").glob("*/skills")) if (BASE_DIR / "extensions").exists() else []


# ── 生命周期 ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    set_db_path(DB_PATH)
    await init_db()
    set_archive_dir(DICE_ARCHIVE_DIR)

    # 初始化记忆子系统 DB 路径
    from .memory.adapter import set_memory_db_path, memory_adapter
    set_memory_db_path(str(DB_PATH))
    _log(f"[Memory] full_mode={memory_adapter.is_full_mode}")

    # 启动记忆提取队列（后台 worker 消费 enqueue_extraction 任务）
    try:
        from .memory.extract_queue import extract_queue
        await extract_queue.start()
        _log("[Memory] ExtractQueue started")
    except Exception as _eq_err:
        _log(f"[Memory] ExtractQueue start failed: {_eq_err}")

    # 技能发现：内置 → 用户级 → 项目级（E3 三级目录扫描，04-extension-system.md §2）
    skill_registry.add_skill_dir(SKILLS_DIR)
    # 用户级技能目录（~/.zero-arsenal/skills/）
    _user_skills_dir = Path.home() / ".zero-arsenal" / "skills"
    if _user_skills_dir.exists():
        skill_registry.add_skill_dir(_user_skills_dir)
        _log(f"[Skills] user skill dir: {_user_skills_dir}")
    # 项目级技能目录（.zero-arsenal/skills/，最高优先级）
    _proj_skills_dir = Path(".zero-arsenal") / "skills"
    if _proj_skills_dir.exists():
        skill_registry.add_skill_dir(_proj_skills_dir)
        _log(f"[Skills] project skill dir: {_proj_skills_dir}")
    for ext_skill_dir in EXTENSION_DIRS:
        skill_registry.add_skill_dir(ext_skill_dir)
    skill_registry.discover()

    # 注册文风库技能
    from .skills.writing_styles import init_writing_style_skills
    style_count = init_writing_style_skills()
    _log(f"[Skills] writing styles registered: {style_count}")
    _log(f"[Skills] found {len(skill_registry.list_skills())} skills total")
    _log(f"[DB] SQLite ready: {DB_PATH}")
    _log(f"[Dice] archive: {DICE_ARCHIVE_DIR}")
    # 初始化 MCP 桥接（动态发现工具 schema 后注册）
    try:
        from .tools.mcp_bridge import MCPToolBridge
        from .tools import tool_registry
        mcp_config = BASE_DIR / "data" / "sys_config" / "mcp.json"
        _mcp_bridge = MCPToolBridge(str(mcp_config))
        # 先动态拉取工具 schema（discover 是 async），再注册到 registry
        await _mcp_bridge.discover()
        registered = _mcp_bridge.register_to_registry(tool_registry)
        _log(f"[MCP] bridge initialized, {registered} tools registered")
    except Exception as _mcp_err:
        _log(f"[MCP] bridge init skipped: {_mcp_err}")

    # 加载全部扩展（三级目录扫描，工具/节点/Hooks/WorldPlugin 注入到对应 Registry）
    try:
        from .extensions.extension_loader import load_all_extensions
        from .extensions import plugin_registry as _plugin_reg
        from .tools import tool_registry
        from .agents.agent_node import register_node as _register_agent_node
        from .hooks import hook_manager as _hm
        _loaded_exts = load_all_extensions()
        for _ext in _loaded_exts:
            # 注册扩展工具
            for _tool in _ext.tools:
                try:
                    tool_registry.register(_tool)
                except Exception:
                    pass
            # 注册扩展 AgentNode
            for _node in _ext.agent_nodes:
                try:
                    _register_agent_node(_node)
                except Exception:
                    pass
            # 注册扩展 Hooks（E1 修复：HookManager.register_extension_hooks）
            if _ext.hooks:
                try:
                    _ext_key = getattr(_ext, "key", "") or getattr(_ext.hooks, "__module__", "")
                    _hm.register_extension_hooks(_ext.hooks, ext_key=str(_ext_key))
                except Exception as _hook_err:
                    _log(f"[ExtLoader] Hook registration failed: {_hook_err}")
            # 注册 WorldPlugin 到 plugin_registry（E2 修复）
            if _ext.world_plugin is not None:
                try:
                    from .extensions.plugin import WorldPlugin as _WP
                    if isinstance(_ext.world_plugin, _WP):
                        _plugin_reg.register(_ext.world_plugin)
                        _log(f"[ExtLoader] WorldPlugin '{_ext.world_plugin.key}' registered")
                    else:
                        _log(f"[ExtLoader] WorldPlugin skipped (not WorldPlugin dataclass): {type(_ext.world_plugin)}")
                except Exception as _wp_err:
                    _log(f"[ExtLoader] WorldPlugin register failed: {_wp_err}")
        # 注册扩展 prompt_fragments → PromptRegistry（E6 修复）
        _ext_frag_count = 0
        try:
            from .prompts.template_loader import load_prompt_fragment_file
            from .prompts.registry import registry as _pr
            for _ext in _loaded_exts:
                for _frag_path in (_ext.prompt_fragments or []):
                    try:
                        _frag = load_prompt_fragment_file(_frag_path)
                        if _frag:
                            _pr.register(_frag)
                            _ext_frag_count += 1
                    except Exception as _fp_err:
                        _log(f"[ExtLoader] Fragment {_frag_path} register failed: {_fp_err}")
        except Exception as _pf_err:
            _log(f"[ExtLoader] prompt_fragments batch registration failed: {_pf_err}")
        _log(f"[ExtLoader] {len(_loaded_exts)} extensions loaded via load_all_extensions(); {_ext_frag_count} ext fragments registered")
    except Exception as _ext_err:
        _log(f"[ExtLoader] load_all_extensions failed: {_ext_err}")

    # 初始化 Hook 系统（触发内置 Hook 注册）
    from .hooks import hook_manager
    _log(f"[Hooks] {len(hook_manager.list_hooks())} hooks registered")

    # 加载 agents/*.md 系统提示片段（P4 修复：Layer 1 文件化）
    try:
        from .prompts.template_loader import load_agent_prompts
        _ap_count = load_agent_prompts()
        _log(f"[Prompts] {_ap_count} agent prompts loaded from agents/*.md")
    except Exception as e:
        _log(f"[Prompts] agent prompt loading failed: {e}")

    # 加载扩展规则（Track C）
    try:
        from .extensions.rules_loader import rule_registry as _rule_reg
        _log(f"[Startup] Extension rules loaded: {len(_rule_reg.list_rules())} rules")
    except Exception as e:
        _log(f"[Startup] rules_loader init failed: {e}")

    # 发现并注册扩展 Hook（Track C）
    try:
        from .extensions.hook_protocol import discover_and_register_hooks
        _hook_count = discover_and_register_hooks()
        _log(f"[Startup] Extension hooks registered: {_hook_count}")
    except Exception as e:
        _log(f"[Startup] hook_protocol init failed: {e}")

    # 扩展热加载（开发模式自动激活，04-extension-system.md §1.1）
    # 控制：ZERO_ARSENAL_HOT_RELOAD=1 强制启用，ZERO_ARSENAL_NO_HOT_RELOAD=1 强制禁用
    import asyncio as _asyncio
    from .skills.watcher import start_extension_watcher as _start_watcher
    _watcher_task = await _start_watcher()
    if _watcher_task:
        _log("[HotReload] 扩展热加载监视器已启动（watchfiles）")

    # 构建扩展注册表 __registry__.json（三级目录扫描）
    try:
        from .extensions.registry_builder import build_registry
        ext_reg = build_registry(BASE_DIR / "extensions")
        _log(f"[ExtRegistry] {len(ext_reg.get('extensions', []))} extensions discovered")
    except Exception as _reg_err:
        _log(f"[ExtRegistry] build skipped: {_reg_err}")

    # WorldPlugin 权限覆盖
    try:
        from .extensions.plugin import plugin_registry as _plugin_reg
        from .agents.permission import profile_registry as _profile_reg
        for _plugin_info in _plugin_reg.list_plugins():
            _plugin_obj = _plugin_reg.get(_plugin_info["key"])
            if _plugin_obj:
                for _pname in ("play", "plan", "review"):
                    _plugin_obj.apply_permission_overlay(_pname, _profile_reg)
        _log("[Permissions] WorldPlugin overlays applied")
    except Exception as _overlay_err:
        _log(f"[Permissions] overlay skipped: {_overlay_err}")

    # ── 记忆重要度每日衰减调度器（importance *= 0.98，凌晨3点触发） ──────────────
    import asyncio as _asyncio
    import datetime as _datetime

    async def _importance_decay_loop():
        """后台无限循环：每天凌晨 3:00 对所有 memory_entries 执行 importance 衰减。"""
        while True:
            try:
                now = _datetime.datetime.now()
                # 计算到明天凌晨 3:00 的秒数
                target = now.replace(hour=3, minute=0, second=0, microsecond=0)
                if target <= now:
                    target += _datetime.timedelta(days=1)
                sleep_secs = (target - now).total_seconds()
                await _asyncio.sleep(sleep_secs)

                # 执行衰减
                from .db import get_db as _get_db
                async with _get_db() as _db:
                    await _db.execute(
                        "UPDATE memory_entries SET importance = importance * 0.98 "
                        "WHERE importance > 0.01"
                    )
                    await _db.commit()
                _log("[Memory] 每日 importance 衰减完成（×0.98）")
            except _asyncio.CancelledError:
                break
            except Exception as _decay_err:
                _log(f"[Memory] importance 衰减失败: {_decay_err}")
                await _asyncio.sleep(3600)  # 失败后 1 小时重试

    _decay_task = _asyncio.ensure_future(_importance_decay_loop())
    _log("[Memory] importance 衰减调度器已启动（每天凌晨3:00）")

    # ── event_log 7 天清理调度器 ──────────────────────────────────────────────

    async def _event_log_cleanup_loop():
        """后台循环：每天凌晨 4:00 删除 7 天前的 event_log 记录。"""
        while True:
            try:
                now = _datetime.datetime.now()
                target = now.replace(hour=4, minute=0, second=0, microsecond=0)
                if target <= now:
                    target += _datetime.timedelta(days=1)
                await _asyncio.sleep((target - now).total_seconds())

                cutoff = (
                    _datetime.datetime.now() - _datetime.timedelta(days=7)
                ).timestamp()
                from .db import get_db as _get_db
                async with _get_db() as _db:
                    await _db.execute(
                        "DELETE FROM event_log WHERE created_at < ?", (cutoff,)
                    )
                    await _db.commit()
                _log("[EventBus] event_log 7天清理完成")
            except _asyncio.CancelledError:
                break
            except Exception as _clean_err:
                _log(f"[EventBus] event_log 清理失败: {_clean_err}")
                await _asyncio.sleep(3600)

    _cleanup_task = _asyncio.ensure_future(_event_log_cleanup_loop())
    _log("[EventBus] event_log 清理调度器已启动（每天凌晨4:00，保留7天）")

    _log("[ZeroArsenal] backend started")
    yield

    # 关闭时：停止热加载监视器、ExtractQueue、衰减调度器和清理调度器
    from .skills.watcher import stop_extension_watcher as _stop_watcher
    await _stop_watcher()

    _decay_task.cancel()
    _cleanup_task.cancel()
    try:
        await _decay_task
    except Exception:
        pass
    try:
        await _cleanup_task
    except Exception:
        pass
    try:
        from .memory.extract_queue import extract_queue
        await extract_queue.stop()
        _log("[Memory] ExtractQueue stopped")
    except Exception:
        pass


# ── FastAPI 应用 ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="零度武库 API",
    description="AI 跑团小说工具统合后端",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bearer Token 可选鉴权（设置环境变量 ZERO_ARSENAL_API_TOKEN 后生效）
app.add_middleware(AuthMiddleware)
# IP 级别速率限制（02-system-architecture.md §6，ZERO_ARSENAL_RATE_LIMIT=60/min）
app.add_middleware(RateLimitMiddleware)

app.include_router(router)


# ── 统一错误响应格式（11-api-design.md §1.3） ─────────────────────────────────

_STATUS_TO_ERROR_CODE: dict[int, str] = {
    400: "invalid_request",
    401: "unauthorized",
    403: "permission_denied",
    404: "not_found",
    409: "conflict",
    410: "gone",
    422: "validation_error",
    429: "rate_limited",
    500: "agent_error",
    503: "llm_unavailable",
}

_MSG_FRAGMENT_TO_CODE: list[tuple[str, str]] = [
    ("session not found", "session_not_found"),
    ("message not found", "message_not_found"),
    ("chapter not found", "chapter_not_found"),
    ("session_id", "session_not_found"),
    ("invalid mode", "invalid_mode"),
    ("invalid message_type", "invalid_message_type"),
    ("already consolidated", "chapter_already_consolidated"),
    ("processing", "session_processing"),
    ("confirm must be true", "confirm_required"),
    ("deleted", "session_deleted"),
]


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """将所有 HTTP 异常转换为统一 JSON 格式（11-api-design.md §9）。"""
    detail = exc.detail
    # 若 detail 已是含 error/message 的 dict，直接使用
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)

    message = str(detail)
    # 尝试语义化错误码
    error_code = _STATUS_TO_ERROR_CODE.get(exc.status_code, f"http_{exc.status_code}")
    msg_lower = message.lower()
    for fragment, code in _MSG_FRAGMENT_TO_CODE:
        if fragment in msg_lower:
            error_code = code
            break

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": error_code,
            "message": message,
            "details": {},
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic 校验失败 → 422 统一格式。"""
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "请求参数校验失败",
            "details": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """未捕获的服务端异常 → 500 统一格式（不暴露堆栈到响应）。"""
    _log(f"[ERROR] Unhandled exception: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "服务器内部错误，请稍后重试",
            "details": {},
        },
    )


@app.get("/")
async def root():
    return {
        "name": "零度武库",
        "version": "0.1.0",
        "docs": "/docs",
        "status": "running"
    }


@app.get("/health")
async def health():
    from .memory.adapter import get_engine_status
    return {"status": "ok", "memory": get_engine_status()}


# ── 启动入口 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(BASE_DIR)],
    )

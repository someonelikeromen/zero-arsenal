"""
ToolRegistry — 工具注册与执行系统。
Agent 通过工具与游戏世界和数据库交互，而不是直接操作。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional, Union, Type

# 分级超时常量（D19 / 设计 07 §7.2）
try:
    from timeouts import GLOBAL_TOOL_TIMEOUT
except ImportError:  # cwd=repo root
    from backend.timeouts import GLOBAL_TOOL_TIMEOUT

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """工具执行上下文，由 Agent 传入，工具 handler 可选消费。"""
    session_id: str = ""
    message_id: str = ""
    agent_name: str = ""
    profile_name: str = "play"
    turn_index: int = 0
    metadata: dict = field(default_factory=dict)
    # 弱引用到当前轮次的 TurnContext（供 draw_gacha 等写状态工具传播结果）
    turn_ctx: Optional[object] = field(default=None, repr=False, compare=False)
    # 事件总线引用（工具可直接发布 SSE 事件；None = 不发布）
    bus: Optional[object] = field(default=None, repr=False, compare=False)
    # 取消信号：外部设置后工具应尽早中止并抛出 asyncio.CancelledError
    abort_signal: Optional[object] = field(default=None, repr=False, compare=False)

    @property
    def state_snapshot(self) -> dict:
        """
        当前 TurnContext 的不可变状态快照（设计文档 04-extension-system.md §2.1）。
        实现通过 turn_ctx 提供完整访问（turn_ctx 是 state_snapshot 的超集）。
        若 turn_ctx 为 None，返回空字典。
        """
        if self.turn_ctx is None:
            return {}
        # TurnContext 是 dataclass，asdict 提供不可变快照
        try:
            from dataclasses import asdict
            return asdict(self.turn_ctx)   # type: ignore[arg-type]
        except Exception:
            # 非 dataclass 场景：尽力返回 __dict__
            return dict(getattr(self.turn_ctx, "__dict__", {}))


@dataclass
class ToolResult:
    """
    工具执行结果的标准化契约（07-tool-registry.md §1.2）。

    工具 handler 可以：
      - 返回纯 dict（向后兼容，绝大多数内置工具走此路径）；
      - 返回 ToolResult 实例（推荐，结构化契约）。
    `ToolRegistry.execute` 会通过 `normalize_result()` 把任意返回统一成 dict，
    确保上层 tool_loop 始终拿到一致结构（含 `ok`/`error` 字段）。
    """
    content: str = ""                               # 返回给 LLM 的文本
    data: dict = field(default_factory=dict)        # 结构化数据
    part_type: str = ""                             # 触发 Part 的类型（空=不触发）
    should_memorize: bool = False
    needs_continuation: bool = False
    error: str = ""                                 # 非空表示失败

    def to_dict(self) -> dict:
        """序列化为标准 dict 契约。"""
        return {
            "ok": not self.error,
            "content": self.content,
            "data": self.data,
            "part_type": self.part_type,
            "should_memorize": self.should_memorize,
            "needs_continuation": self.needs_continuation,
            "error": self.error,
        }


def normalize_result(result) -> dict:
    """
    把工具 handler 的任意返回值规整为标准 dict 契约。
    - ToolResult        → result.to_dict()
    - dict              → 原样返回（补 ok 字段，若缺失）
    - 其他（str/None）  → 包装进 {"ok": True, "result": ...}
    """
    if isinstance(result, ToolResult):
        return result.to_dict()
    if isinstance(result, dict):
        if "ok" not in result:
            # 约定：含非空 error 字段视为失败
            result = {**result, "ok": not result.get("error")}
        return result
    return {"ok": True, "result": result}


@dataclass
class ToolDef:
    name: str
    description: str
    # parameters 支持两种格式（07-tool-registry.md）：
    #   - dict：直接是 JSON Schema（向后兼容，当前所有内置工具使用此格式）
    #   - type[BaseModel]：Pydantic v2 模型类，运行时自动转换为 JSON Schema
    #     新工具推荐使用此格式，获得运行时参数校验 + 自动生成 schema 的优势
    parameters: Union[dict, Type]
    handler: Callable         # async function
    permission_required: str = "allow"   # allow | ask | deny
    tags: list[str] = field(default_factory=list)  # ["read", "write", "dice", "memory"]
    timeout_seconds: float = GLOBAL_TOOL_TIMEOUT    # 工具执行超时（秒，D19 全局默认 30s）
    group: str = "general"                          # engine | narrative | character | economy | chapter
    requires_permission: bool = False               # 是否需要权限检查
    execution_mode: str = "parallel"                # parallel（幂等，可并发）| sequential（副作用，串行）
    # 扩展工具元数据（backend/extensions/*/tools.py 在构造 ToolDef 时会传入这些 kwargs）：
    #   display_name —— UI 展示名（可选，留空时回落到 name）
    #   plugin_key —— 工具所属世界插件键（如 "muv_luv" / "gundam_seed"；空=通用）
    # 历史上 ToolDef 不接受这两个字段，导致 extensions/*/tools.py 在 import 阶段抛
    #   TypeError: ToolDef.__init__() got an unexpected keyword argument 'plugin_key'/'display_name'
    # 这里显式声明字段以兼容扩展工具加载（conf_b07）。
    display_name: str = ""
    plugin_key: str = ""
    # 工具级别中间件钩子（优先于全局 HookEvent，仅对此工具生效）
    # before_hooks: list of async(args: dict, ctx: ToolContext) -> dict | None
    #   返回 dict 时替换 args；返回 None 时使用原始 args
    # after_hooks:  list of async(args: dict, result: dict, ctx: ToolContext) -> dict | None
    #   返回 dict 时替换 result；返回 None 时使用原始 result
    before_hooks: list = field(default_factory=list)
    after_hooks: list = field(default_factory=list)

    def schema(self) -> dict:
        """
        返回 OpenAI function calling 兼容的 JSON Schema。
        - parameters 为 dict：直接返回
        - parameters 为 Pydantic BaseModel 类：自动转换（需要 pydantic v2）
        """
        if isinstance(self.parameters, dict):
            return self.parameters
        # Pydantic BaseModel 路径
        try:
            return self.parameters.model_json_schema()  # pydantic v2
        except AttributeError:
            try:
                return self.parameters.schema()  # pydantic v1 fallback
            except Exception:
                pass
        # 最后兜底：返回空 schema
        return {"type": "object", "properties": {}}

    def validate_args(self, args: dict) -> dict:
        """
        若 parameters 为 Pydantic BaseModel 类，则对 args 做运行时类型校验，
        返回校验后的 dict；校验失败时原样返回（不抛出，避免破坏现有工具）。
        dict 格式 parameters 不做校验（JSON Schema 格式由 LLM 保证）。
        """
        if isinstance(self.parameters, dict):
            return args
        try:
            model_instance = self.parameters(**args)
            return model_instance.model_dump()  # pydantic v2
        except Exception:
            return args


class ToolRegistry:
    """工具注册中心，支持按标签过滤和 OpenAI function calling 格式导出。"""

    _instance: Optional["ToolRegistry"] = None

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        """返回全局单例（与模块级 tool_registry 同一对象）。"""
        if cls._instance is None:
            # 延迟绑定：模块加载完成后，tool_registry 全局变量已存在
            import sys
            _mod = sys.modules[cls.__module__]
            cls._instance = getattr(_mod, "tool_registry", None)
        return cls._instance  # type: ignore[return-value]

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        """注册一个工具。"""
        self._tools[tool.name] = tool
        logger.debug(f"Tool registered: {tool.name}")

    def unregister(self, name: str) -> bool:
        """
        注销一个工具（07-tool-registry.md §6，用于 MCP 服务断开 / 热卸载）。
        返回 True 表示确实移除了一个已注册工具，False 表示该工具不存在。
        """
        if name in self._tools:
            del self._tools[name]
            logger.debug(f"Tool unregistered: {name}")
            return True
        return False

    def get(self, name: str) -> Optional[ToolDef]:
        """获取工具定义，不存在时返回 None。"""
        return self._tools.get(name)

    def list_tools(self, tags: list[str] | None = None) -> list[dict]:
        """
        列出所有工具，可按标签过滤（满足任意一个标签即返回）。
        返回格式：[{name, description, tags, permission_required}]
        """
        tools = list(self._tools.values())
        if tags:
            tools = [t for t in tools if any(tag in t.tags for tag in tags)]
        return [
            {
                "name": t.name,
                "description": t.description,
                "tags": t.tags,
                "permission_required": t.permission_required,
            }
            for t in tools
        ]

    async def execute(
        self,
        name: str,
        args: dict,
        ctx: Optional[ToolContext] = None,
        session_id: str = "",
    ) -> dict:
        """
        执行工具，含权限检查（AgentProfile ask/deny）和超时控制。

        权限流程（设计文档 07 §3 + 10 §2）：
          deny  → 直接拒绝，不执行
          ask   → 发布 permission.ask 事件，等待前端确认（超时视为 deny，fail-closed）
          allow → 直接执行
        """
        tool = self._tools.get(name)
        if tool is None:
            return {"error": "tool not found", "tool_name": name}

        # ── 权限检查 ────────────────────────────────────────────────────────
        effective_ctx = ctx or ToolContext()
        permission = self._resolve_permission(tool, effective_ctx.profile_name)

        if permission == "deny":
            logger.info(f"Tool '{name}' denied by profile '{effective_ctx.profile_name}'")
            return {"error": f"tool denied by profile '{effective_ctx.profile_name}'", "tool_name": name}

        if permission == "ask":
            allowed = await self._wait_for_permission(
                tool_name=name,
                args=args,
                ctx=effective_ctx,
                session_id=effective_ctx.session_id or session_id,
            )
            if not allowed:
                return {"error": "tool denied by user", "tool_name": name}

        # ── 执行 ────────────────────────────────────────────────────────────
        # Pydantic BaseModel 参数校验（dict 格式工具跳过）
        import inspect as _inspect
        call_args = tool.validate_args(dict(args))
        try:
            sig = _inspect.signature(tool.handler)
            if "viewer_agent" in sig.parameters and "viewer_agent" not in call_args:
                call_args["viewer_agent"] = effective_ctx.agent_name or "narrator"
            # 始终用 context 中的真实 session_id 覆盖（防止 LLM 幻觉传错 session_id）
            if "session_id" in sig.parameters:
                call_args["session_id"] = effective_ctx.session_id or session_id or call_args.get("session_id", "")
        except Exception:
            call_args = dict(args)

        try:
            result = await asyncio.wait_for(
                tool.handler(**call_args),
                timeout=tool.timeout_seconds,
            )
            # 标准化返回契约（ToolResult / dict / 其他 → 统一 dict，含 ok 字段）
            return normalize_result(result)
        except asyncio.TimeoutError:
            logger.warning(f"Tool {name} timed out after {tool.timeout_seconds}s")
            return {"error": f"tool timeout after {tool.timeout_seconds}s", "tool_name": name}
        except Exception as exc:
            logger.warning(f"Tool {name} raised: {exc}")
            return {"error": str(exc), "tool_name": name}

    def _resolve_permission(self, tool: ToolDef, profile_name: str) -> str:
        """
        依照 AgentProfile 权限规则解析工具的实际权限。
        优先级：profile 规则 > tool.permission_required 默认值。
        """
        try:
            from ..agents.permission import profile_registry
            profile = profile_registry.get(profile_name)
            if profile:
                action = profile.resolve(tool.name)
                return action.value  # PermissionAction.allow/ask/deny → str
        except Exception as e:
            # D-16 fail-closed：profile 解析异常时不回落到工具默认（可能是 allow），
            # 一律降级为 ask 交人确认（无前端时 ask 超时 → deny）。
            logger.warning(
                "[registry] _resolve_permission 异常，fail-closed 降级为 ask: %s", e
            )
            return "ask"
        return tool.permission_required

    async def _wait_for_permission(
        self,
        tool_name: str,
        args: dict,
        ctx: ToolContext,
        session_id: str,
        timeout_seconds: float = 60.0,
    ) -> bool:
        """
        委托 ask_handler.check_permission_and_ask 完成 ask 交互。
        超时/异常视为 deny（fail-closed）：ask_handler 的 PendingAsk.wait()
        超时返回 deny，本函数异常分支亦 return False。
        """
        try:
            from ..agents.ask_handler import check_permission_and_ask
            return await check_permission_and_ask(
                session_id=session_id,
                tool_name=tool_name,
                tool_args=args,
                profile_name=ctx.profile_name,
                reason=f"Agent '{ctx.agent_name}' 请求执行工具 '{tool_name}'",
            )
        except Exception as e:
            logger.warning(f"permission ask failed, defaulting to deny (fail-closed): {e}")
            return False  # fail-closed

    @staticmethod
    def _strip_ctx_params(schema: dict) -> dict:
        """
        从工具 schema 中移除由 context 自动注入的参数（session_id / viewer_agent），
        避免 LLM 幻觉提供错误值。运行时 execute() 会始终从 ToolContext 注入正确值。
        """
        import copy
        schema = copy.deepcopy(schema)
        props: dict = schema.get("properties", {})
        required: list = schema.get("required", [])
        for key in ("session_id", "viewer_agent"):
            props.pop(key, None)
            if key in required:
                required.remove(key)
        schema["properties"] = props
        if required != schema.get("required", []):
            schema["required"] = required
        return schema

    def to_openai_functions(self, names: Optional[list[str]] = None) -> list[dict]:
        """
        转为 OpenAI function calling 格式：
        [{"type": "function", "function": {"name", "description", "parameters"}}]
        names — 不传则返回所有；传入时只返回指定工具。
        parameters 支持 dict（JSON Schema）和 Pydantic BaseModel 类（自动转换）。
        context 注入参数（session_id / viewer_agent）从 schema 中剥离，防止 LLM 幻觉。
        """
        tools = list(self._tools.values())
        if names is not None:
            name_set = set(names)
            tools = [t for t in tools if t.name in name_set]
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": f"{t.description} [group:{t.group}]",
                    "parameters": self._strip_ctx_params(t.schema()),
                },
            }
            for t in tools
        ]


# 全局单例
tool_registry = ToolRegistry()

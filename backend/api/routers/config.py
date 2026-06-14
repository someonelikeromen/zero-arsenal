"""
配置管理路由：WorldPlugin、AgentProfile、文风、MCP、LLM 路由、API Keys、系统信息。
对应设计文档 11-api-design.md §5 / §7
"""
from __future__ import annotations
import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...bus import bus, BusEvent, EventType

logger = logging.getLogger(__name__)
router = APIRouter()

_SUPPORTED_PROVIDERS = ("deepseek", "openai", "anthropic", "cohere", "groq")
_KEY_ENV_MAP = {
    "deepseek":  "DEEPSEEK_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "cohere":    "COHERE_API_KEY",
    "groq":      "GROQ_API_KEY",
}
_SYS_CONFIG_DIR = Path(__file__).parent.parent.parent / "data" / "sys_config"


# ── Hook 管理 ─────────────────────────────────────────────────────────────────

@router.get("/hooks")
async def list_hooks(event: Optional[str] = None):
    """列出所有已注册的 Hook（可按事件类型过滤）。"""
    from ...hooks import hook_manager, HookEvent
    evt = HookEvent(event) if event else None
    return {"hooks": hook_manager.list_hooks(evt), "count": len(hook_manager.list_hooks(evt))}


# ── 系统信息 ──────────────────────────────────────────────────────────────────

@router.get("/system/info")
async def system_info():
    """系统信息总览（调试用）。"""
    from ...tools import tool_registry, skill_registry
    from ...extensions import plugin_registry
    from ...agents.permission import profile_registry
    from ...hooks import hook_manager
    from ...memory.adapter import memory_adapter

    return {
        "version": "0.1.0",
        "memory_mode": "full" if memory_adapter.is_full_mode else "fallback",
        "tools": len(tool_registry.list_tools()),
        "skills": len(skill_registry.list_skills()),
        "plugins": len(plugin_registry.list_plugins()),
        "profiles": len(profile_registry.list_profiles()),
        "hooks": len(hook_manager.list_hooks()),
        "graph_nodes": ["rules", "dm_gate", "dice", "npc", "world", "narrator", "style", "var", "chronicler"],
    }


@router.get("/system/memory-health")
async def memory_health():
    """记忆子系统健康状态（full / fallback 模式 + 各组件可用性）。"""
    from ...memory.adapter import memory_adapter
    details: dict = {}
    try:
        details["is_full_mode"] = memory_adapter.is_full_mode
        details["mode"] = "full" if memory_adapter.is_full_mode else "fallback"
        # 检测各子组件
        for comp in ("engine", "consolidator", "extractor", "retriever", "rollback"):
            try:
                mod = __import__(f"backend.memory.{comp}", fromlist=[comp])
                details[comp] = "available"
            except ImportError as e:
                details[comp] = f"unavailable: {e}"
        # 嵌入模型
        try:
            from ...utils.llm_client import get_embedding_client
            ec = get_embedding_client()
            details["embedding_client"] = "available" if ec is not None else "unavailable"
        except Exception as e:
            details["embedding_client"] = f"error: {e}"
    except Exception as e:
        details["error"] = str(e)
    return {"ok": True, "memory": details}


# ── WorldPlugin / AgentProfile / 文风 ────────────────────────────────────────

@router.get("/config/world-plugins")
async def list_plugin_keys(ext_type: str = "plugin"):
    """列出已注册的插件。ext_type=plugin 只返回行为包；ext_type=all 返回全部。"""
    from ...extensions import plugin_registry
    plugins = plugin_registry.list_plugins()
    if ext_type != "all":
        plugins = [p for p in plugins if p.get("ext_type", "plugin") == ext_type]
    result = []
    for info in plugins:
        plug = plugin_registry.get(info["key"])
        entry = dict(info)
        if plug:
            entry["extra_attributes"] = plug.extra_attributes
            entry["skills_dir"] = plug.skills_dir or ""
            # 动态检测：插件类是否真正覆写了任意生命周期方法
            from ...extensions.plugin import WorldPlugin as _BasePlugin
            _lifecycle_methods = ("on_session_init", "on_turn_start", "on_turn_end")
            entry["has_lifecycle_hooks"] = any(
                type(plug).__dict__.get(m) is not None and
                type(plug).__dict__[m] is not _BasePlugin.__dict__.get(m)
                for m in _lifecycle_methods
            )
        result.append(entry)
    return {"plugins": result, "total": len(result)}


@router.get("/config/agent-profiles")
async def list_agent_profiles():
    """列出所有 AgentProfile（权限模式）。"""
    from ...agents.permission import profile_registry
    profiles = profile_registry.list_profiles()
    result = []
    for p in profiles:
        profile = profile_registry.get(p["name"])
        entry = dict(p)
        if profile:
            entry["permissions"] = [
                {"pattern": perm.tool_pattern, "action": perm.action.value}
                for perm in profile.permissions
            ]
        result.append(entry)
    return {"profiles": result, "total": len(result)}


@router.get("/config/writing-styles")
async def list_writing_styles():
    """列出所有已注册的文风技能。"""
    from ...tools import skill_registry
    skills = skill_registry.list_skills()
    styles = [
        s for s in skills
        if "writing" in s.get("name", "").lower()
        or "style" in s.get("name", "").lower()
        or "文风" in s.get("name", "")
        or "style" in " ".join(s.get("phases", [])).lower()
    ]
    return {"styles": styles, "total": len(styles)}


# ── MCP 管理 ──────────────────────────────────────────────────────────────────

class MCPConnectRequest(BaseModel):
    server_id: str
    command: str
    args: list[str] = []
    env: dict = {}
    enabled: bool = True


@router.get("/mcp/servers")
async def list_mcp_servers():
    """列出 MCP 配置文件中的所有服务器。"""
    import json
    config_path = _SYS_CONFIG_DIR / "mcp.json"
    if not config_path.exists():
        return {"servers": [], "total": 0}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        servers = data.get("servers", [])
        return {"servers": servers, "total": len(servers)}
    except Exception as e:
        raise HTTPException(500, f"MCP config load failed: {e}")


@router.post("/mcp/connect")
async def mcp_connect(req: MCPConnectRequest):
    """动态注册一个 MCP 服务器工具到 ToolRegistry。"""
    import json, tempfile, pathlib
    try:
        from ...tools.mcp_bridge import MCPToolBridge
        from ...tools import tool_registry

        cfg = {"servers": [{"id": req.server_id, "command": req.command,
                            "args": req.args, "env": req.env, "enabled": req.enabled}]}
        tmp = pathlib.Path(tempfile.mktemp(suffix=".json"))
        tmp.write_text(json.dumps(cfg), encoding="utf-8")

        bridge = MCPToolBridge(str(tmp))
        count = bridge.register_to_registry(tool_registry)
        tmp.unlink(missing_ok=True)
        return {"registered": count, "server_id": req.server_id}
    except Exception as e:
        raise HTTPException(500, f"MCP connect failed: {e}")


@router.delete("/mcp/{server_id}")
async def mcp_disconnect(server_id: str):
    """从 ToolRegistry 注销指定 MCP 服务器的所有工具。"""
    from ...tools import tool_registry
    removed = []
    for name, tool in list(tool_registry._tools.items()):
        if server_id in tool.tags:
            del tool_registry._tools[name]
            removed.append(name)
    if not removed:
        raise HTTPException(404, f"No tools found for MCP server '{server_id}'")
    return {"removed_tools": removed, "count": len(removed)}


# ── LLM 路由配置 ──────────────────────────────────────────────────────────────

class LLMRouteUpdate(BaseModel):
    agent: str
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@router.get("/config/llm-routes")
async def get_llm_routes():
    """获取当前 LLM 路由配置（agents.json）。"""
    import json
    agents_cfg = _SYS_CONFIG_DIR / "agents.json"
    if not agents_cfg.exists():
        return {"routes": {}, "source": "default"}
    try:
        data = json.loads(agents_cfg.read_text(encoding="utf-8"))
        return {"routes": data.get("agents", data), "source": str(agents_cfg)}
    except Exception as e:
        raise HTTPException(500, f"agents.json load failed: {e}")


@router.put("/config/llm-routes")
async def update_llm_route(req: LLMRouteUpdate):
    """在线更新指定 agent 的 LLM 路由配置，写入 agents.json。"""
    import json
    agents_cfg_path = _SYS_CONFIG_DIR / "agents.json"
    agents_cfg_path.parent.mkdir(parents=True, exist_ok=True)

    config: dict = {}
    if agents_cfg_path.exists():
        try:
            config = json.loads(agents_cfg_path.read_text(encoding="utf-8"))
        except Exception:
            config = {}

    agents_node = config.setdefault("agents", {})
    agent_cfg = agents_node.setdefault(req.agent, {})
    agent_cfg["provider"] = req.provider
    agent_cfg["model"] = req.model
    if req.temperature is not None:
        agent_cfg["temperature"] = req.temperature
    if req.max_tokens is not None:
        agent_cfg["max_tokens"] = req.max_tokens

    agents_cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "agent": req.agent, "config": agent_cfg}


# ── API Key 管理 ──────────────────────────────────────────────────────────────

class ApiKeyUpdateRequest(BaseModel):
    provider: str
    api_key: str


@router.get("/config/api-keys")
async def get_api_keys():
    """返回各 Provider 的 API Key 状态（脱敏）。"""
    result: dict = {}
    for provider, env_var in _KEY_ENV_MAP.items():
        key_val = os.environ.get(env_var, "")
        result[provider] = {
            "configured": bool(key_val),
            "preview": key_val[:8] + "..." if len(key_val) > 8 else ("(未设置)" if not key_val else key_val),
        }
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    return {"keys": result, "env_file": str(env_path)}


# ── Wiki 候选 URL 模式管理 ────────────────────────────────────────────────────

class WikiPatternItem(BaseModel):
    source: str
    pattern: str
    slug_transform: Optional[str] = None
    enabled: bool = True
    notes: str = ""


@router.get("/config/wiki-patterns")
async def get_wiki_patterns():
    """返回当前所有 wiki 候选 URL 模式（含禁用的）。"""
    from ...utils.web_scraper import list_wiki_patterns
    return {"patterns": list_wiki_patterns(), "total": len(list_wiki_patterns())}


@router.put("/config/wiki-patterns")
async def replace_wiki_patterns(patterns: list[WikiPatternItem]):
    """整体替换 wiki 模式列表（PUT 覆盖）。"""
    from ...utils.web_scraper import save_wiki_patterns
    data = [p.model_dump() for p in patterns]
    ok = save_wiki_patterns(data)
    if not ok:
        raise HTTPException(500, "wiki_patterns.json 写入失败")
    return {"ok": True, "total": len(data)}


@router.post("/config/wiki-patterns")
async def add_wiki_pattern(item: WikiPatternItem):
    """追加一条 wiki 模式。若同 source 已存在则更新。"""
    from ...utils.web_scraper import list_wiki_patterns, save_wiki_patterns
    patterns = list_wiki_patterns()
    existing = next((p for p in patterns if p.get("source") == item.source), None)
    new_item = item.model_dump()
    if existing:
        existing.update(new_item)
        action = "updated"
    else:
        patterns.append(new_item)
        action = "added"
    ok = save_wiki_patterns(patterns)
    if not ok:
        raise HTTPException(500, "wiki_patterns.json 写入失败")
    return {"ok": True, "action": action, "source": item.source}


@router.delete("/config/wiki-patterns/{source}")
async def delete_wiki_pattern(source: str):
    """按 source 名称删除（或禁用）一条 wiki 模式。"""
    from ...utils.web_scraper import list_wiki_patterns, save_wiki_patterns
    patterns = list_wiki_patterns()
    before = len(patterns)
    patterns = [p for p in patterns if p.get("source") != source]
    if len(patterns) == before:
        raise HTTPException(404, f"未找到 source='{source}' 的 wiki 模式")
    ok = save_wiki_patterns(patterns)
    if not ok:
        raise HTTPException(500, "wiki_patterns.json 写入失败")
    return {"ok": True, "deleted": source}


# ─────────────────────────────────────────────────────────────────────────────

@router.put("/config/api-keys")
async def update_api_key(req: ApiKeyUpdateRequest):
    """更新指定 Provider 的 API Key（进程环境变量 + .env 文件）。"""
    provider = req.provider.lower()
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(400, f"不支持的 provider: {provider}。支持：{list(_SUPPORTED_PROVIDERS)}")
    if not req.api_key.strip():
        raise HTTPException(400, "api_key 不能为空")

    env_var = _KEY_ENV_MAP[provider]
    os.environ[env_var] = req.api_key.strip()

    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    try:
        lines: list[str] = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{env_var}="):
                lines[i] = f"{env_var}={req.api_key.strip()}"
                updated = True
                break
        if not updated:
            lines.append(f"{env_var}={req.api_key.strip()}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        return {"ok": True, "provider": provider, "warning": f".env 写入失败: {e}"}

    return {"ok": True, "provider": provider, "env_var": env_var}

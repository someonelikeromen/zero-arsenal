"""
MCPToolBridge — 将外部 MCP (Model Context Protocol) 服务的工具桥接进 ToolRegistry。
参考设计文档 07-tool-registry.md §4 MCPToolBridge
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import aiohttp
    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False

if TYPE_CHECKING:
    from .registry import ToolRegistry

from .registry import ToolDef

logger = logging.getLogger(__name__)

_DEFAULT_MCP_CONFIG = Path(__file__).parent.parent / "data" / "sys_config" / "mcp.json"


class MCPToolBridge:
    """
    MCP 工具桥接器。
    从 mcp.json 加载 MCP 服务配置，将其工具注册到 ToolRegistry。
    """

    def __init__(self, mcp_config_path: str = "") -> None:
        config_path = Path(mcp_config_path) if mcp_config_path else _DEFAULT_MCP_CONFIG
        self._config: dict = {}
        self._servers: list[dict] = []
        self._timeout: int = 10
        # 动态发现的工具 schema 缓存：server_name -> [{name, description, inputSchema}]
        self._dynamic_tools: dict[str, list[dict]] = {}

        if config_path.exists():
            try:
                self._config = json.loads(config_path.read_text(encoding="utf-8"))
                self._servers = self._config.get("servers", [])
                self._timeout = self._config.get("timeout_seconds", 10)
                logger.debug(f"MCPToolBridge: 加载配置 {config_path}，共 {len(self._servers)} 个服务")
            except Exception as e:
                logger.warning(f"MCPToolBridge: 解析 mcp.json 失败 — {e}")
        else:
            logger.debug(f"MCPToolBridge: mcp.json 不存在于 {config_path}，跳过加载")

    async def fetch_tool_list(self, server_url: str) -> list[dict]:
        """
        从 MCP 服务动态获取工具列表。
        标准 MCP HTTP 协议：GET {server_url}/tools/list
        返回 [{"name": str, "description": str, "inputSchema": dict}, ...]
        失败时返回空列表（调用方应回落到静态配置）。
        """
        if not _HAS_AIOHTTP:
            return []
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            ) as session:
                async with session.get(f"{server_url.rstrip('/')}/tools/list") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tools = data.get("tools", data if isinstance(data, list) else [])
                        return [t for t in tools if isinstance(t, dict) and t.get("name")]
        except Exception as e:
            logger.debug(f"[MCPToolBridge] fetch_tool_list {server_url} failed: {e}")
        return []

    async def discover(self) -> list[str]:
        """
        发现所有已启用的 MCP 服务的工具列表。
        先尝试动态获取（GET /tools/list），失败则回落到 mcp.json 静态配置。
        动态获取成功时，工具 schema 缓存在 self._dynamic_tools 供注册使用。
        返回格式：["mcp_{server_name}_{tool_name}", ...]
        """
        result: list[str] = []
        for server in self._servers:
            if not server.get("enabled", False):
                continue
            server_name = server.get("name", "unknown")
            server_url = server.get("url", "")

            dynamic_tools: list[dict] = []
            if server_url:
                dynamic_tools = await self.fetch_tool_list(server_url)

            if dynamic_tools:
                self._dynamic_tools[server_name] = dynamic_tools
                for tool in dynamic_tools:
                    result.append(f"mcp_{server_name}_{tool['name']}")
            else:
                for tool_name in server.get("tools", []):
                    result.append(f"mcp_{server_name}_{tool_name}")
        return result

    async def call_tool(self, server_name: str, tool_name: str, args: dict) -> dict:
        """
        调用指定 MCP 服务器上的工具（HTTP POST）。
        失败时返回 {"error": str(e), "mcp_server": server_name}
        """
        server = next((s for s in self._servers if s.get("name") == server_name), None)
        if server is None:
            return {"error": f"MCP 服务器 '{server_name}' 未找到", "mcp_server": server_name}

        url = server.get("url", "")
        if not url:
            return {"error": "MCP 服务器 URL 为空", "mcp_server": server_name}

        payload = {"tool": tool_name, "arguments": args}

        if not _HAS_AIOHTTP:
            return {"error": "aiohttp 未安装，无法调用 MCP 工具", "mcp_server": server_name}

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout)
            ) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    text = await resp.text()
                    return {
                        "error": f"HTTP {resp.status}: {text[:200]}",
                        "mcp_server": server_name,
                    }
        except Exception as e:
            logger.warning(f"MCPToolBridge: 调用 {server_name}/{tool_name} 失败 — {e}")
            return {"error": str(e), "mcp_server": server_name}

    def register_to_registry(self, registry: "ToolRegistry") -> int:
        """
        将所有已启用 MCP 服务的工具注册到 ToolRegistry。
        返回注册成功的工具数量。
        """
        count = 0
        for server in self._servers:
            if not server.get("enabled", False):
                continue
            server_name = server.get("name", "unknown")
            description_prefix = server.get("description", f"MCP 服务 {server_name}")

            for tool_name in server.get("tools", []):
                full_name = f"mcp_{server_name}_{tool_name}"

                # 使用闭包捕获变量
                def make_handler(sn: str, tn: str):
                    async def handler(**args: dict) -> dict:
                        return await self.call_tool(sn, tn, args)
                    return handler

                tool_def = ToolDef(
                    name=full_name,
                    description=f"[MCP] {description_prefix} → {tool_name}",
                    parameters={
                        "type": "object",
                        "properties": {
                            "args": {
                                "type": "object",
                                "description": "传递给 MCP 工具的参数",
                            }
                        },
                        "required": [],
                    },
                    handler=make_handler(server_name, tool_name),
                    permission_required="ask",
                    tags=["mcp", server_name],
                )
                registry.register(tool_def)
                count += 1
                logger.debug(f"MCPToolBridge: 已注册工具 {full_name}")

        return count

    async def register_plugin_mcp_servers(
        self, plugin_key: str, mcp_servers: list[dict]
    ) -> int:
        """
        为 WorldPlugin 的自定义 MCP 服务注册工具。
        工具名格式：{plugin_key}_{server_name}_{tool_name}
        返回成功注册的工具数。
        """
        from .registry import tool_registry

        count = 0
        for server_cfg in mcp_servers:
            if not server_cfg.get("enabled", True):
                continue
            server_url = server_cfg.get("url", "")
            server_name = server_cfg.get("name", "custom")
            if not server_url:
                continue

            tools = await self.fetch_tool_list(server_url)
            for tool in tools:
                raw_name = tool["name"]
                full_name = f"{plugin_key}_{server_name}_{raw_name}"

                def make_handler(url: str, tn: str):
                    async def handler(**args: dict) -> dict:
                        if not _HAS_AIOHTTP:
                            return {"error": "aiohttp 未安装，无法调用 MCP 工具"}
                        try:
                            async with aiohttp.ClientSession(
                                timeout=aiohttp.ClientTimeout(total=self._timeout)
                            ) as session:
                                async with session.post(
                                    url, json={"tool": tn, "arguments": args}
                                ) as resp:
                                    if resp.status == 200:
                                        return await resp.json()
                                    text = await resp.text()
                                    return {"error": f"HTTP {resp.status}: {text[:200]}"}
                        except Exception as exc:
                            return {"error": str(exc)}
                    return handler

                input_schema = tool.get("inputSchema") or {
                    "type": "object",
                    "properties": {},
                    "required": [],
                }

                tool_def = ToolDef(
                    name=full_name,
                    description=f"[MCP:{plugin_key}] {tool.get('description', raw_name)}",
                    parameters=input_schema,
                    handler=make_handler(server_url, raw_name),
                    permission_required="ask",
                    tags=["mcp", "plugin", plugin_key, server_name],
                )
                tool_registry.register(tool_def)
                count += 1
                logger.debug(f"MCPToolBridge: 已注册插件工具 {full_name}")

        return count


# 全局单例
mcp_bridge = MCPToolBridge()

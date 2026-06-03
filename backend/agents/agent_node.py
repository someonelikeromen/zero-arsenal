"""
AgentNode ABC — 扩展 Agent 节点的抽象基类。
设计文档 03-agent-system.md §7、04-extension-system.md §2.2

用法（扩展开发者）：
    from backend.agents.agent_node import AgentNode, register_node
    from backend.agents.state import TurnContext

    class MyCustomNode(AgentNode):
        name = "my_node"
        display_name = "我的自定义节点"
        insert_after = "narrator"   # 插在 narrator→style 之间

        async def execute(self, ctx: TurnContext) -> TurnContext:
            # ... 自定义逻辑 ...
            return ctx

    register_node(MyCustomNode())

然后 build_graph() 调用 inject_registered_nodes(builder) 即可自动注入图。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
import logging

from .state import TurnContext

_log = logging.getLogger(__name__)

# 全局注册表：所有通过 register_node 注册的扩展节点
_REGISTERED_NODES: list["AgentNode"] = []


class AgentNode(ABC):
    """
    扩展 Agent 节点抽象基类。

    扩展开发者继承此类，实现 execute() 方法，
    并通过 insert_after 或 replace 声明图注入位置。
    """

    name: str = ""
    """唯一节点名，如 'my_combat_judge'。"""

    display_name: str = ""
    """用于日志和 UI 展示的可读名称。"""

    insert_after: Optional[str] = None
    """
    在哪个已有节点之后插入本节点。
    如 'narrator' 表示插入在 narrator→style 之间。
    若为 None，则不自动注入（需手动调用 builder.add_node）。
    """

    replace: Optional[str] = None
    """
    替换哪个已有节点。
    如 'style' 表示用本节点完全替换 StyleAgent。
    replace 优先于 insert_after。
    """

    tools: list = []
    """本节点所用的 ToolDef 列表（可空）。"""

    @abstractmethod
    async def execute(self, ctx: TurnContext) -> TurnContext:
        """节点主逻辑，接收 TurnContext 返回修改后的 TurnContext。"""
        ...

    async def __call__(self, ctx: TurnContext) -> TurnContext:
        """使节点可以作为 LangGraph 节点函数直接调用。"""
        return await self.execute(ctx)


def register_node(node: AgentNode) -> None:
    """注册一个扩展 AgentNode 实例到全局注册表。"""
    if not node.name:
        raise ValueError(f"AgentNode {type(node).__name__} must define a non-empty 'name'")
    # 去重：同名节点后注册的覆盖先注册的
    global _REGISTERED_NODES
    _REGISTERED_NODES = [n for n in _REGISTERED_NODES if n.name != node.name]
    _REGISTERED_NODES.append(node)
    _log.info("[AgentNode] registered: %s (insert_after=%s, replace=%s)",
              node.name, node.insert_after, node.replace)


def list_registered_nodes() -> list[AgentNode]:
    """返回当前所有注册的扩展节点。"""
    return list(_REGISTERED_NODES)


def inject_registered_nodes(builder, edge_map: dict[str, str]) -> dict[str, str]:
    """
    将已注册的扩展节点注入到 LangGraph StateGraph 中。

    参数：
        builder: StateGraph 实例（add_node / add_edge 接口）
        edge_map: 当前图的 {from_node: to_node} 有向边映射（可变，函数内更新）

    返回：
        更新后的 edge_map。

    注入规则：
    - replace: 用新节点替换旧节点（旧节点的入边和出边接给新节点）
    - insert_after: 在 edge_map[insert_after] → X 之间插入新节点，
                    变为 edge_map[insert_after] → new → X
    """
    for node in _REGISTERED_NODES:
        try:
            if node.replace:
                # 替换：旧节点的出边移给新节点，新节点接受旧节点的入边
                old_name = node.replace
                builder.add_node(node.name, node)
                # 找旧节点出边目标
                old_next = edge_map.get(old_name)
                if old_next:
                    builder.add_edge(node.name, old_next)
                    edge_map[node.name] = old_next
                # 将指向旧节点的边重定向到新节点
                for src, dst in list(edge_map.items()):
                    if dst == old_name:
                        edge_map[src] = node.name
                if old_name in edge_map:
                    del edge_map[old_name]
                _log.info("[AgentNode] replaced '%s' with '%s'", old_name, node.name)

            elif node.insert_after:
                # 插入：在 insert_after → next 之间插入
                after = node.insert_after
                next_node = edge_map.get(after)
                if next_node is None:
                    _log.warning("[AgentNode] insert_after target '%s' not in edge_map, skipping '%s'",
                                 after, node.name)
                    continue
                builder.add_node(node.name, node)
                builder.add_edge(after, node.name)
                builder.add_edge(node.name, next_node)
                edge_map[after] = node.name
                edge_map[node.name] = next_node
                _log.info("[AgentNode] inserted '%s' after '%s' (before '%s')",
                          node.name, after, next_node)

        except Exception as exc:
            _log.error("[AgentNode] failed to inject '%s': %s", node.name, exc)

    return edge_map

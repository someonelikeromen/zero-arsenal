"""
WorldPlugin 扩展系统 — 世界插件接口与注册表。
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..prompts.registry import PromptRegistry


@dataclass
class AttributeDef:
    """
    属性维度定义（04-extension-system.md §2.4）。
    扩展开发者通过 WorldPlugin.attribute_schema 声明本世界的属性体系。
    """
    display: str                        # 用户可见名称，如 "力量"
    min: int = 1
    max: int = 999
    default: int = 10
    description: str = ""              # 属性说明（注入 system prompt）
    unit: str = ""                     # 单位（如 "点"、"级"）


@dataclass
class ItemType:
    """
    物品类型定义（04-extension-system.md §2.4）。
    扩展开发者通过 WorldPlugin.item_types 声明可用的物品分类。
    """
    key: str                            # 唯一键，如 "weapon"、"technique"
    display_name: str                   # 用户可见名称
    stackable: bool = False
    max_stack: Optional[int] = None
    rarity_tiers: list[str] = field(default_factory=list)
    custom_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class EconomyConfig:
    """
    经济配置（04-extension-system.md §2.4）。
    扩展开发者通过 WorldPlugin.economy_config 声明本世界的货币与汇率。
    """
    primary_currency: str = "积分"                     # 主货币名
    secondary_currencies: list[str] = field(default_factory=list)
    starting_balance: dict[str, int] = field(default_factory=dict)
    exchange_rates: dict[str, float] = field(default_factory=dict)


@dataclass
class WorldPlugin:
    """
    世界插件基类（对齐 04-extension-system.md §2.4）。

    生命周期钩子：
      on_session_init  — 会话创建时调用，可在角色卡/世界状态写入初始值
      on_turn_start    — 每轮 RulesAgent 之前调用，可注入临时状态
      on_turn_end      — 每轮 ChroniclerAgent 之后调用，可触发跨轮持久化

    属性/物品/经济字段说明：
      attribute_schema — 声明本世界的属性维度（AttributeDef 字典）
      item_types       — 声明本世界的物品分类（ItemType 列表）
      economy_config   — 声明本世界的货币与汇率（EconomyConfig，None=使用全局默认）
      extra_attributes — 向后兼容的简单属性名列表（优先使用 attribute_schema）
    """
    key: str
    name: str
    description: str
    system_prompt_fragments: list[dict] = field(default_factory=list)
    agent_profile: str = "play"

    # ── 属性体系（04-extension-system.md §2.4，向后兼容：extra_attributes 仍有效）──
    # attribute_schema 优先；未提供时退化为 extra_attributes 列表
    attribute_schema: dict[str, AttributeDef] = field(default_factory=dict)
    # 向后兼容的简单属性名列表（当 attribute_schema 为空时使用）
    extra_attributes: list[str] = field(default_factory=list)

    # ── 物品体系 ────────────────────────────────────────────────────────────────
    item_types: list[ItemType] = field(default_factory=list)

    # ── 经济配置 ────────────────────────────────────────────────────────────────
    economy_config: Optional[EconomyConfig] = None

    # ── 其他配置 ────────────────────────────────────────────────────────────────
    skills_dir: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    # 权限覆盖规则：{"play": [{"pattern": "roll_*", "action": "allow"}], ...}
    permission_overlay: dict = field(default_factory=dict)
    # 插件附带的自定义 MCP 服务列表
    # 格式：[{"name": "my_mcp", "url": "http://localhost:8100", "enabled": True}]
    mcp_servers: list = field(default_factory=list)

    def get_effective_attributes(self) -> dict[str, AttributeDef]:
        """
        返回实际生效的属性字典。
        优先使用 attribute_schema；若为空则将 extra_attributes 列表转换为简单 AttributeDef。
        """
        if self.attribute_schema:
            return self.attribute_schema
        return {
            attr: AttributeDef(display=attr)
            for attr in self.extra_attributes
        }

    # ── 生命周期钩子（可在子类/实例中覆盖） ─────────────────────────────────

    def on_session_init(self, state: dict) -> dict:
        """
        会话初始化时调用（CREATE /sessions 之后）。
        state: AgentState 的 dict 快照（character_data, world_plugin, mode ...）
        返回修改后的 state dict。
        """
        return state

    def on_turn_start(self, state: dict) -> dict:
        """
        每轮 RulesAgent 之前调用。
        可注入临时上下文（如战斗计时器、天气效果等）。
        """
        return state

    def on_turn_end(self, state: dict) -> dict:
        """
        每轮 ChroniclerAgent 之后调用。
        可触发跨轮持久化（如日/周期效果结算）。
        """
        return state

    def get_rules_skills(self) -> list[str]:
        """返回本世界的 SKILL 路径列表（在会话初始化时自动激活）。"""
        return []

    def get_character_template(self) -> dict:
        """返回角色卡初始模板（JSON 可序列化）。"""
        return {}

    def apply_to_registry(self, prompt_reg: "PromptRegistry") -> None:
        """将插件的提示词片段注入 PromptRegistry world 层。"""
        from ..prompts.registry import PromptFragment
        for i, frag_data in enumerate(self.system_prompt_fragments):
            if isinstance(frag_data, PromptFragment):
                # 已经是 PromptFragment 对象（muv_luv/gundam_seed 等插件传入），直接注册
                prompt_reg.register(frag_data)
            else:
                # dict 格式兼容路径
                phase_val = frag_data.get("phase", "all")
                phase_list = phase_val if isinstance(phase_val, list) else [phase_val]
                frag = PromptFragment(
                    id=f"world.{self.key}.{i}",
                    layer="world",
                    phase=phase_list,
                    content=frag_data["content"],
                    priority=200 + i,
                    inject_as=frag_data.get("inject_as", "system"),
                )
                prompt_reg.register(frag)

    def apply_permission_overlay(self, profile_name: str, profile_registry) -> None:
        """
        将插件的权限覆盖规则应用到对应的 AgentProfile。

        D3：此前实现直接 `profile.permissions.insert(0, ...)` 修改 profile_registry
        返回的对象 —— 但该对象往往是模块级单例（PLAY_PROFILE 等），就地修改会
        永久污染全局基础 Profile，且多个世界插件叠加时规则会累积串台。
        现改为：深拷贝基础 Profile → 在副本上插入 overlay 规则 → 重新注册副本，
        全局基础 Profile 保持纯净。失败时静默跳过（不影响启动）。
        """
        import copy
        if not self.permission_overlay:
            return
        overlay_rules = self.permission_overlay.get(profile_name, [])
        if not overlay_rules:
            return
        try:
            from ..agents.permission import PermissionAction, ToolPermission
            base = profile_registry.get(profile_name)
            if not base:
                return
            cloned = copy.deepcopy(base)
            overlay_perms = []
            for rule in overlay_rules:
                pattern = rule.get("pattern", "*")
                action_str = rule.get("action", "allow")
                try:
                    action = PermissionAction(action_str)
                except ValueError:
                    continue
                overlay_perms.append(ToolPermission(tool_pattern=pattern, action=action))
            # overlay 规则置于列表最前（优先级最高，允许放宽 deny）
            cloned.permissions = overlay_perms + list(cloned.permissions)
            profile_registry.register(cloned)
        except Exception:
            pass


class WorldPluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, WorldPlugin] = {}

    def register(self, plugin: WorldPlugin) -> None:
        self._plugins[plugin.key] = plugin
        if getattr(plugin, "mcp_servers", None):
            try:
                import asyncio
                from ..tools.mcp_bridge import mcp_bridge
                asyncio.ensure_future(
                    mcp_bridge.register_plugin_mcp_servers(plugin.key, plugin.mcp_servers)
                )
            except Exception as e:
                logger.warning(f"[plugin_registry] MCP registration failed for {plugin.key}: {e}")

    def get(self, key: str) -> Optional[WorldPlugin]:
        return self._plugins.get(key)

    def list_plugins(self) -> list[dict]:
        return [
            {"key": p.key, "name": p.name, "description": p.description,
             "agent_profile": p.agent_profile}
            for p in self._plugins.values()
        ]

    def apply_to_prompt_registry(self, plugin_key: str, prompt_reg: "PromptRegistry") -> None:
        plugin = self.get(plugin_key)
        if plugin:
            plugin.apply_to_registry(prompt_reg)


plugin_registry = WorldPluginRegistry()

"""
AgentProfile 权限系统 — play/plan/review 三种模式。
参考 opencode Permission Ruleset 设计。

YAML 配置优先：agents/profiles/*.yaml 存在时自动覆盖内置 Profile。
"""
from __future__ import annotations
import fnmatch
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


class PermissionAction(str, Enum):
    ALLOW = "allow"
    ASK   = "ask"
    DENY  = "deny"


@dataclass
class ToolPermission:
    tool_pattern: str           # glob 通配，如 "write_*" / "*" / "read_*"
    action: PermissionAction

    def matches(self, tool_name: str) -> bool:
        return fnmatch.fnmatch(tool_name, self.tool_pattern)


@dataclass
class AgentProfile:
    name: str
    description: str
    permissions: list[ToolPermission] = field(default_factory=list)
    visible_part_types: list[str] = field(default_factory=list)
    max_tokens_per_turn: int = 2048
    active_tools: Optional[list[str]] = None  # None=全量；列表=仅注入这些工具给 LLM
    # group 级白名单（07-tool-registry.md §3 allowed_groups）：None=不限；非空=只允许这些 group
    allowed_groups: Optional[list[str]] = None
    # 权限列表无匹配时的默认行为（设计 §10 default_permission）
    default_permission: PermissionAction = PermissionAction.DENY
    # ── D11 多模型角色映射（设计 §7.2 AgentProfile.llm_role）────────────────────
    # llm_role：该 Profile 默认使用的 agents.json 角色键（None=由调用方按 agent_name 解析）
    # llm_overrides：直接覆盖 provider/model/temperature/max_tokens（None=不覆盖，用单模型默认）
    llm_role: Optional[str] = None
    llm_overrides: Optional[dict] = None

    def resolve_llm(self, agent_name: Optional[str] = None) -> dict:
        """
        解析该 Profile 的有效 LLM 配置（D11）。
        优先级：llm_overrides > agents.json[llm_role 或 agent_name] > 统一默认 > 硬编码。
        未设置任何多模型字段时，等价于按 agent_name 走单模型默认（向后兼容）。
        """
        from .llm import load_agent_config
        role = self.llm_role or agent_name or self.name
        cfg = dict(load_agent_config(role))
        if isinstance(self.llm_overrides, dict):
            cfg.update(self.llm_overrides)
        return cfg

    def check_tool(self, tool_name: str) -> PermissionAction:
        """
        按顺序匹配权限规则，返回第一个匹配的 action；
        无规则匹配时返回 default_permission（而非硬编码 DENY）。
        """
        for perm in self.permissions:
            if perm.matches(tool_name):
                return perm.action
        return self.default_permission

    def resolve(self, tool_name: str) -> PermissionAction:
        """check_tool 的别名（供 ToolRegistry 调用）。"""
        return self.check_tool(tool_name)

    def filter_tools(self, tool_names: list[str]) -> list[str]:
        """
        按 active_tools 白名单 + allowed_groups + permissions 三重过滤工具名列表。
        - active_tools=None：不限制名称
        - allowed_groups=None：不限制 group
        - permissions DENY：无论其他条件均排除
        """
        # 解析 group 过滤（07-tool-registry.md §3 allowed_groups）
        _group_filter: Optional[set] = None
        if self.allowed_groups is not None:
            _group_filter = set(self.allowed_groups)
            try:
                from ..tools import tool_registry as _tr
                _tool_groups = {t.name: t.group for t in _tr._tools.values()}  # type: ignore[attr-defined]
            except Exception:
                _tool_groups = {}
        else:
            _tool_groups = {}

        result = []
        for t in tool_names:
            if self.check_tool(t) == PermissionAction.DENY:
                continue
            if self.active_tools is not None and t not in self.active_tools:
                continue
            if _group_filter is not None:
                t_group = _tool_groups.get(t, "general")
                if t_group not in _group_filter:
                    continue
            result.append(t)
        return result


# ── 内置 Profile ──────────────────────────────────────────────────────────────

PLAY_PROFILE = AgentProfile(
    name="play",
    description="玩家模式：专注叙事体验，隐藏系统细节",
    default_permission=PermissionAction.ALLOW,
    permissions=[
        # 读操作：始终允许（不打扰玩家）
        ToolPermission("read_*",   PermissionAction.ALLOW),
        ToolPermission("get_*",    PermissionAction.ALLOW),
        ToolPermission("list_*",   PermissionAction.ALLOW),
        ToolPermission("search_*", PermissionAction.ALLOW),
        # 骰子 / 记忆写入：自动允许（游戏必需）
        ToolPermission("roll_*",   PermissionAction.ALLOW),
        ToolPermission("add_memory", PermissionAction.ALLOW),
        # 角色状态写入：允许（叙事流程需要）
        ToolPermission("update_character_state", PermissionAction.ALLOW),
        # 危险写入操作：ask 确认（在 play 模式下静默询问，60s 超时视为 deny，fail-closed）
        ToolPermission("delete_*", PermissionAction.ASK),
        ToolPermission("reset_*",  PermissionAction.ASK),
        # 其余：允许（play 模式尽量不打扰）
        ToolPermission("*",        PermissionAction.ALLOW),
    ],
    visible_part_types=["narrative", "dice_roll", "state_patch", "npc_action", "world_event", "chapter_end"],
    max_tokens_per_turn=2048,
)

PLAN_PROFILE = AgentProfile(
    name="plan",
    description="规划模式：显示 DM 注释和技能加载信息；写操作需 ask 确认",
    # plan 模式限制 LLM 可见工具（写操作需确认，危险操作不可见）
    active_tools=[
        "read_character", "get_world_state", "search_memory", "search_lore",
        "get_chapter_summaries", "query_world_rules", "check_skill_trigger",
        "roll_check", "generate_action_options", "load_skill",
        "update_character_state", "add_memory",
        # plan 专用工具
        "read_chapter", "outline_chapter",
    ],
    default_permission=PermissionAction.ASK,
    permissions=[
        # 读操作白名单：始终允许
        ToolPermission("read_*",    PermissionAction.ALLOW),
        ToolPermission("get_*",     PermissionAction.ALLOW),
        ToolPermission("list_*",    PermissionAction.ALLOW),
        ToolPermission("search_*",  PermissionAction.ALLOW),
        ToolPermission("check_*",   PermissionAction.ALLOW),
        ToolPermission("query_*",   PermissionAction.ALLOW),
        ToolPermission("roll_*",    PermissionAction.ALLOW),   # 骰子允许
        # 写操作需确认
        ToolPermission("write_*",   PermissionAction.ASK),
        ToolPermission("update_*",  PermissionAction.ASK),
        ToolPermission("add_*",     PermissionAction.ASK),
        ToolPermission("earn_*",    PermissionAction.ASK),
        ToolPermission("purchase_*", PermissionAction.ASK),
        # 危险操作拒绝
        ToolPermission("delete_*",  PermissionAction.DENY),
        ToolPermission("reset_*",   PermissionAction.DENY),
        # 其余写操作 ask
        ToolPermission("*",         PermissionAction.ASK),
    ],
    visible_part_types=["narrative", "dice_roll", "state_patch", "npc_action", "world_event",
                        "chapter_end", "dm_note", "skill_load", "compaction", "action_options"],
    max_tokens_per_turn=2048,
)

REVIEW_PROFILE = AgentProfile(
    name="review",
    description="审阅模式：严格只读，显示所有内部信息；写操作全部拒绝",
    # review 模式只允许 LLM 调用只读工具
    active_tools=[
        "read_character", "get_world_state", "search_memory", "search_lore",
        "get_chapter_summaries", "query_world_rules", "check_skill_trigger",
        "generate_action_options",
        # review 专用工具
        "read_chapter", "style_check", "purity_check",
    ],
    default_permission=PermissionAction.DENY,
    permissions=[
        # 仅允许纯读操作
        ToolPermission("read_*",       PermissionAction.ALLOW),
        ToolPermission("get_*",        PermissionAction.ALLOW),
        ToolPermission("list_*",       PermissionAction.ALLOW),
        ToolPermission("search_*",     PermissionAction.ALLOW),
        ToolPermission("query_*",      PermissionAction.ALLOW),
        ToolPermission("check_*",      PermissionAction.ALLOW),
        ToolPermission("generate_action_options", PermissionAction.ALLOW),  # review 允许看选项
        # review 专用审校工具（只读，NEW-B10-01：此前落入 * → DENY 被误拒）
        ToolPermission("style_check",  PermissionAction.ALLOW),
        ToolPermission("purity_check", PermissionAction.ALLOW),
        # 所有写操作拒绝（严格只读）
        ToolPermission("*",            PermissionAction.DENY),
    ],
    visible_part_types=["narrative", "dice_roll", "state_patch", "npc_action", "world_event",
                        "chapter_end", "dm_note", "skill_load", "compaction",
                        "permission_ask", "system_grant", "action_options"],
    max_tokens_per_turn=4096,
)


# ── YAML 加载器 ──────────────────────────────────────────────────────────────

_PROFILES_DIR = Path(__file__).parent / "profiles"


def _load_profile_from_yaml(yaml_path: Path) -> Optional[AgentProfile]:
    """
    从 YAML 文件加载 AgentProfile。
    yaml 格式见 agents/profiles/play.yaml。
    """
    try:
        import yaml  # pyyaml
    except ImportError:
        _log.warning("[Permission] PyYAML 未安装，跳过 YAML profile 加载：%s", yaml_path)
        return None
    try:
        data: dict = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        perms = [
            ToolPermission(
                tool_pattern=p["pattern"],
                action=PermissionAction(p["action"]),
            )
            for p in data.get("permissions", [])
        ]
        default_perm_str = data.get("default_permission", "deny")
        try:
            default_perm = PermissionAction(default_perm_str)
        except ValueError:
            _log.warning("[Permission] 未知 default_permission 值 '%s'，使用 DENY", default_perm_str)
            default_perm = PermissionAction.DENY
        return AgentProfile(
            name=data["name"],
            description=data.get("description", ""),
            permissions=perms,
            visible_part_types=data.get("visible_part_types", []),
            max_tokens_per_turn=int(data.get("max_tokens_per_turn", 2048)),
            active_tools=data.get("active_tools"),
            allowed_groups=data.get("allowed_groups"),  # 07-tool-registry.md §3
            default_permission=default_perm,
            llm_role=data.get("llm_role"),            # D11 多模型角色映射
            llm_overrides=data.get("llm_overrides"),
        )
    except Exception as e:
        _log.warning("[Permission] 解析 %s 失败: %s", yaml_path, e)
        return None


def _load_profiles_from_dir(profiles_dir: Path) -> dict[str, AgentProfile]:
    """扫描 profiles/ 目录，返回 {name: AgentProfile}。"""
    result: dict[str, AgentProfile] = {}
    if not profiles_dir.exists():
        return result
    for yaml_file in profiles_dir.glob("*.yaml"):
        profile = _load_profile_from_yaml(yaml_file)
        if profile:
            result[profile.name] = profile
            _log.debug("[Permission] 从 YAML 加载 profile: %s", profile.name)
    return result


# ── 注册表 ────────────────────────────────────────────────────────────────────

class ProfileRegistry:
    def __init__(self) -> None:
        self._profiles: dict[str, AgentProfile] = {}
        # 会话级 profile 缓存：用于 WorldPlugin overlay 注入后的有效 Profile
        # key: session_id, value: 经叠加后的 AgentProfile 副本
        self._session_profiles: dict[str, AgentProfile] = {}

    def register(self, profile: AgentProfile) -> None:
        self._profiles[profile.name] = profile

    def get(self, name: str) -> AgentProfile:
        return self._profiles.get(name, PLAY_PROFILE)

    def check_tool(self, profile_name: str, tool_name: str) -> PermissionAction:
        return self.get(profile_name).check_tool(tool_name)

    def list_profiles(self) -> list[dict]:
        return [
            {"name": p.name, "description": p.description,
             "visible_parts": p.visible_part_types}
            for p in self._profiles.values()
        ]

    # ── 会话级 Profile（WorldPlugin overlay 支持）──────────────────────────────

    def set_session_profile(self, session_id: str, profile: AgentProfile) -> None:
        """存储会话级有效 Profile（含 WorldPlugin overlay 的副本）。"""
        self._session_profiles[session_id] = profile

    def get_session_profile(self, session_id: str, fallback_name: str = "play") -> AgentProfile:
        """
        获取会话级有效 Profile。
        存在会话级缓存时优先返回；否则返回全局注册的基础 Profile。
        """
        return self._session_profiles.get(session_id) or self.get(fallback_name)

    def clear_session_profile(self, session_id: str) -> None:
        """清除会话级 Profile 缓存（会话结束或重置时调用）。"""
        self._session_profiles.pop(session_id, None)


profile_registry = ProfileRegistry()
# 优先注册内置 Python Profile（作为 fallback）
profile_registry.register(PLAY_PROFILE)
profile_registry.register(PLAN_PROFILE)
profile_registry.register(REVIEW_PROFILE)
# 再加载 YAML（覆盖内置，允许用户自定义）
for _yaml_profile in _load_profiles_from_dir(_PROFILES_DIR).values():
    profile_registry.register(_yaml_profile)
    _log.info("[Permission] YAML profile '%s' 覆盖内置 profile", _yaml_profile.name)


def get_profile(name: str) -> AgentProfile:
    """便捷函数：从默认注册表获取 AgentProfile（name 不存在时返回 PLAY_PROFILE）。"""
    return profile_registry.get(name)


def apply_plugin_overlay(profile: AgentProfile, overlay: dict[str, PermissionAction]) -> AgentProfile:
    """
    将 WorldPlugin 的权限覆盖层注入到 AgentProfile 的 permissions 列表前端，
    返回新的独立副本（不修改全局注册表中的原 Profile）。

    overlay 格式：{"tool_pattern": PermissionAction, ...}
    注入规则优先级最高（在现有规则列表之前匹配）。
    """
    import copy
    cloned = copy.deepcopy(profile)
    # 将 overlay 规则插入到列表头部（最高优先级）
    overlay_perms = [
        ToolPermission(tool_pattern=pat, action=act)
        for pat, act in overlay.items()
    ]
    cloned.permissions = overlay_perms + cloned.permissions
    return cloned

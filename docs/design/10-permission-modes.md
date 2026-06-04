# 10 · Permission Modes（权限模式系统）

> **来源灵感**：opencode `agent/agent.ts` 的 Permission Ruleset 设计——plan / build / explore Agent 各持不同权限集合，不写 if/else 而是用规则表（ruleset）驱动权限决策。
>
> 注：本文档已于 2026-06 对齐实现（D0 以代码为准）。
>
> **基准裁定（2026-06）**：本文档历史上 §2「设计草案 vs 实现差异对照」与 §3「原始设计意图」自相矛盾。现按 D0 裁定：
> - **数据结构 / 算法形态** 一律以实现为准（§2 的 list[ToolPermission] + glob + `apply_plugin_overlay` 深拷贝模型生效，详见 §2/§4 修订注）。
> - **`play` 默认权限** 以实现为准：**`default_permission=ALLOW` + 末位 `*→allow`**（产品取向「尽量不打扰」，属有意为之）。§3.1 已据此修订。
> - **`plan` 允许 `roll_*` 掷骰** 与 **`review` 的 `style_check`/`purity_check` 被 `*→deny` 误拒**（NEW-B10-01）**不属于良性偏离，而是待修复的实现缺陷**。本文档保留 §3.2/§3.3 的原始设计意图作为「应然」目标，**不**将其改写为现状（见对应小节的 ⚠️ 注与 `docs/review/fix_report_docs.md`）。
> - **`ask` 超时语义** 以设计/实现一致的 **deny（fail-closed）** 为准；代码注释中「60s 默认允许 / fail-open」为陈旧误导注释，应以 deny 为准。

---

## 1. 设计动机

传统权限控制常见两种反模式：

| 反模式 | 问题 |
|--------|------|
| 硬编码 if/else 分支 | 增加新模式时需要散改多处代码，维护成本高 |
| 单一全能 Agent | 无法在"策划分析"阶段阻止 Agent 意外写入数据库 |

**规则表驱动**的优势：

- 每个模式（Mode）对应一份 `AgentProfile`，独立声明哪些工具可用
- 权限变更只需修改数据，不需要改逻辑代码
- 支持世界插件（WorldPlugin）在运行时叠加覆盖默认规则
- `ask` 权限将控制权交还给用户，构成人机协作的安全阀

---

## 2. `AgentProfile` 数据结构

> **⚠️ 设计草案 vs 实现差异对照**（`backend/agents/permission.py`）：
>
> | 设计草案 | 实现 | 差异说明 |
> |---------|------|---------|
> | `tool_permissions: dict[str, PermissionValue]` | `permissions: list[ToolPermission]` | 结构从字典改为有序列表；`ToolPermission(tool_pattern, action)` 支持 glob 通配，按顺序首次匹配 |
> | 通配符 `'*'` 作为字典键 | `ToolPermission("*", action)` 列表末尾兜底条目 | 语义等价，但实现用顺序优先级而非字典查找 |
> | `_overlay: dict[str, PermissionValue]` | `apply_plugin_overlay(profile, overlay)` 函数 | 不在实例上存储 overlay；改为创建深拷贝并插入额外 ToolPermission，避免污染全局 Profile |
> | 无 `visible_part_types` | `visible_part_types: list[str]` | 实现新增；控制该模式下哪些 Part 类型对玩家可见 |
> | 无 `max_tokens_per_turn` | `max_tokens_per_turn: int = 2048` | 实现新增；模式级 token 预算上限 |
> | 无 `allowed_groups` | `allowed_groups: list[str] \| None` | 实现新增；按工具 group 批量放行（07-tool-registry §3 配套使用） |
>
> YAML Profile 文件（`agents/profiles/*.yaml`）优先级高于内置 Python Profile，可在不改代码的情况下覆盖。

```python
# backend/agents/permission.py（实际实现）
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import fnmatch


class PermissionAction(str, Enum):
    ALLOW = "allow"
    ASK   = "ask"
    DENY  = "deny"


@dataclass
class ToolPermission:
    """单条权限规则。tool_pattern 支持 fnmatch glob（如 "write_*" / "*"）。"""
    tool_pattern: str
    action: PermissionAction

    def matches(self, tool_name: str) -> bool:
        return fnmatch.fnmatch(tool_name, self.tool_pattern)


@dataclass
class AgentProfile:
    name: str
    """模式标识符，如 'play' / 'plan' / 'review'"""

    description: str
    """人类可读说明，显示在 UI 模式切换处"""

    permissions: list[ToolPermission] = field(default_factory=list)
    """
    有序权限规则列表（替代草案中的 tool_permissions dict）。
    check_tool() 按顺序找第一个匹配的 ToolPermission，无匹配则退到 default_permission。
    支持 glob 通配：ToolPermission("write_*", DENY) 匹配所有 write_ 开头的工具。
    """

    default_permission: PermissionAction = PermissionAction.DENY
    """无规则匹配时的兜底权限。play 模式建议 ALLOW，review 模式建议 DENY。"""

    active_tools: Optional[list[str]] = None
    """
    该模式下激活的工具白名单。
    None  → 不限制（但仍受 permissions 过滤）
    list  → 仅注入列表中的工具描述给 LLM（减少 token 消耗）
    """

    visible_part_types: list[str] = field(default_factory=list)
    """该模式下哪些 Part 类型对玩家可见（空=全可见）。实现扩展字段。"""

    max_tokens_per_turn: int = 2048
    """单回合最大 token 预算。实现扩展字段。"""

    # 注意：草案中的 _overlay 字段不在实例上；
    # WorldPlugin overlay 通过 apply_plugin_overlay(profile, overlay) 函数处理：
    # 它创建 profile 的深拷贝，在 permissions 列表头部插入 overlay 规则，
    # 再用 ProfileRegistry.set_session_profile() 存入会话级缓存。
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 模式唯一标识，用于 API `PATCH /api/sessions/{id}/mode` |
| `description` | `str` | 前端模式切换 tooltip 显示文案 |
| `permissions` | `list[ToolPermission]` | 核心规则列表，按顺序首次匹配；替代草案 `tool_permissions dict` |
| `default_permission` | `PermissionAction` | 兜底策略，play=ALLOW，plan=ASK，review=DENY |
| `active_tools` | `list \| None` | 控制传入 LLM 的工具描述列表（减少 token 消耗），None=不限制 |
| `visible_part_types` | `list[str]` | 该模式下对玩家可见的 Part 类型（实现扩展字段） |
| `max_tokens_per_turn` | `int` | 单回合 token 上限（实现扩展字段） |
| `allowed_groups` | `list[str] \| None` | 按工具 group 批量放行（实现扩展字段） |

---

## 3. 三种内置模式

### 3.1 `play` 模式（正常跑团）

**实现现状（2026-06 对齐，以代码为准）**：`play` 采用 **`default_permission=ALLOW` + 末位 `*→allow`** 的「尽量不打扰」产品取向（`backend/agents/permission.py` / `agents/profiles/play.yaml`）。**消费/写入类工具（`purchase_*`、`update_character_state`、`earn_*`/`award_*`、`fork_chapter`、`consolidate_chapter`、`mcp_*`）在 play 下均为 `allow`**，不再弹 `ask`；play 模式下唯一保留 `ask` 的是 `delete_*` / `reset_*` / `draw_gacha`。

> 早期设计意图（仅历史参考）：对「角色大改 / 道具购买」等消费行为保留 `ask` 确认。该意图已被产品决策放弃；如未来需恢复消费确认，应在 play.yaml 显式为 `purchase_*`/`update_character_state` 等加 `ask` 规则。

```python
# 【过时草案：消费类 ask 版本，保留供对照；实际 play 见 play.yaml（allow-by-default）】
PLAY_PROFILE = AgentProfile(
    name="play",
    description="正常跑团模式——Agent 可自由写叙事、掷骰、生成 NPC，"
                "消费类操作需玩家确认",
    tool_permissions={
        # ── 叙事核心 ──────────────────────────────────────────────
        "roll_check":       "allow",   # 骰点判定，全自动
        "write_narrative":  "allow",   # 写正文，全自动
        "fork_chapter":     "allow",   # 开分支章节，全自动
        "spawn_npc":        "allow",   # 即兴生成 NPC，全自动

        # ── 信息查询 ──────────────────────────────────────────────
        "search_lore":      "allow",   # 查世界设定，只读
        "query_character":  "allow",   # 查角色档案，只读
        "load_skill":       "allow",   # 加载 Skill 文件，只读

        # ── 角色状态写入 ───────────────────────────────────────────
        "edit_character":   "ask",     # 大幅改属性需玩家确认（防意外覆写）

        # ── 奖励与商店 ────────────────────────────────────────────
        "earn_reward":      "allow",   # 战斗奖励自动结算
        "open_shop":        "allow",   # 打开商店界面，无消费副作用
        "evaluate_item":    "allow",   # 评估物品价值，只读
        "purchase_item":    "ask",     # 花费资源，需玩家确认
    },
    default_permission="ask",
    active_tools="all",
)
```

**权限决策快查表（play 模式）**：

| 操作 | 权限 | 理由 |
|------|------|------|
| 掷骰 | allow | 叙事核心，频繁打断体验差 |
| 写正文 | allow | Agent 主要职责 |
| 角色大改 | ask | 不可逆操作，需人工确认 |
| 购买道具 | ask | 消耗玩家资源，需知情同意 |
| 查世界设定 | allow | 只读，无副作用 |

---

### 3.2 `plan` 模式（策划 / 只读分析）

**设计意图**：来自 opencode plan Agent 的思路——此阶段 Agent 只应阅读、分析、
撰写**计划文本**，绝不能写入正文、触发骰点或消费资源。
用 `"*": "deny"` 作为默认阻断，再逐一开放白名单工具。

> ⚠️ **实现偏离（缺陷，非良性，待修复）**：当前 `plan.yaml` 实际 `default_permission=ask`、末位 `*→ask`（非设计的 deny 双保险），且 **`roll_* → allow` 并把 `roll_check` 放进 `active_tools`，违反「绝不能触发骰点」**。本小节保留为「应然」设计目标，**不**按现状改写；修复方向：plan 改回 deny-by-default 白名单并移除 `roll_*` allow（见 `docs/review/fix_report_docs.md`）。

```python
PLAN_PROFILE = AgentProfile(
    name="plan",
    description="策划分析模式——只读查询 + 撰写大纲计划，"
                "完全禁止写入正文或消费任何资源",
    tool_permissions={
        "*":               "deny",    # 默认拒绝所有工具（白名单策略）

        # ── 只读白名单 ────────────────────────────────────────────
        "search_lore":     "allow",   # 查世界设定
        "query_character": "allow",   # 查角色档案
        "load_skill":      "allow",   # 加载 Skill 文档（只读）

        # ── 计划写入（不产生正式章节） ────────────────────────────
        "outline_chapter": "allow",   # 写章节大纲，存入 plan_drafts 而非 chapters
    },
    default_permission="deny",        # 兜底也是 deny，双重保险
    active_tools=[
        "search_lore",
        "query_character",
        "load_skill",
        "outline_chapter",
    ],
)
```

> **注意**：`active_tools` 缩减了工具列表，LLM system prompt 中不会出现
> `write_narrative` / `roll_check` 等工具描述，从根源上杜绝 Agent 尝试调用。

---

### 3.3 `review` 模式（审校）

**设计意图**：人工或 AI 审校已生成的章节内容，检查文风一致性与 AI 纯净度，
不允许任何写入操作。

> ⚠️ **实现缺陷 NEW-B10-01（非良性，待修复）**：`review.yaml` 的 allow pattern 为 `check_*`，而 `style_check`/`purity_check` 以 `style`/`purity` 开头**不匹配**，落到末位 `*→deny` 被静默拒绝；且 `review.yaml` 的 `active_tools` 未包含这两项。结果 review 模式两个核心审校工具反被自身规则禁掉，与本节设计直接冲突。本小节保留为「应然」设计目标，**不**按现状改写；修复方向：review permissions 显式加 `style_check → allow`、`purity_check → allow`，并在 `review.yaml` 的 active_tools 补回 `read_chapter/style_check/purity_check`。

```python
REVIEW_PROFILE = AgentProfile(
    name="review",
    description="审校模式——对已有章节进行文风审查和纯净度检查，"
                "所有写入操作均被禁止",
    tool_permissions={
        "*":              "deny",    # 白名单策略

        # ── 只读审校工具 ──────────────────────────────────────────
        "read_chapter":   "allow",   # 读取章节内容
        "style_check":    "allow",   # 文风规则检查（03-writing-style.mdc）
        "purity_check":   "allow",   # AI 套路纯净度检查（12-anti-llm-cliche.mdc）
    },
    default_permission="deny",
    active_tools=["read_chapter", "style_check", "purity_check"],
)
```

---

### 3.4 内置模式注册表

> **实现差异（2026-06）**：实际为 `ProfileRegistry` 实例（非 ClassVar 类方法），注册 play/plan/review 后再用 YAML 覆盖。`get(name)` 对**未注册名返回 `PLAY_PROFILE` 兜底**（非草案的 `raise KeyError`）——容错优先，但可能掩盖错误模式名；模式切换 API 另有 400 校验把关（见 §7.4）。

```python
# profiles/registry.py（草案；实际 get 改为 fallback 到 play，见上注）
from typing import ClassVar

class AgentProfileRegistry:
    _profiles: ClassVar[dict[str, AgentProfile]] = {}

    @classmethod
    def register(cls, profile: AgentProfile) -> None:
        cls._profiles[profile.name] = profile

    @classmethod
    def get(cls, name: str) -> AgentProfile:
        if name not in cls._profiles:
            raise KeyError(f"AgentProfile '{name}' not registered")
        return cls._profiles[name]

    @classmethod
    def list_names(cls) -> list[str]:
        return list(cls._profiles.keys())


# 注册内置模式
AgentProfileRegistry.register(PLAY_PROFILE)
AgentProfileRegistry.register(PLAN_PROFILE)
AgentProfileRegistry.register(REVIEW_PROFILE)
```

---

## 4. 权限匹配算法

> **实现差异（2026-06，以代码为准）**：
> - 实际 `check_tool` 按 `permissions` **列表顺序首次匹配**（glob），无显式「精确优先于通配」分级——靠把具体规则排在 `*` 之前来近似（YAML 顺序写错会失效）。
> - overlay 经 `apply_plugin_overlay` **插入列表头部 = 最高优先级**（高于一切，含精确规则），与下方草案「overlay 低于精确匹配」相反。最终优先级实为：**overlay（置顶）> 列表顺序首次匹配 > default_permission**。
> - `check_and_gate` 对 `deny` **返回 error dict**（`{"error": ...}`，由 `tools/registry.py` 处理）而非抛 `PermissionDeniedError`；行为等价但不符下方草案的异常契约。
> - **`deny 不可被 overlay 上调为 allow` 的安全底线当前未强制**（`extensions/plugin.py` 的 overlay 可覆盖 deny）——属待补实现的安全加固项，非文档滞后。

### 4.1 匹配优先级（精确 > 通配符 > 默认）

来自 opencode 权限系统的 merge 逻辑，规则如下：

```
resolve_permission(tool_name, profile):
  1. 精确匹配：tool_permissions[tool_name]           → 直接返回
  2. 通配符：  tool_permissions["*"]                 → 返回通配符值
  3. 兜底：    profile.default_permission             → 返回默认值
  4. 叠加层：  在步骤 1-3 之前，先检查 _overlay[tool_name]
```

### 4.2 完整算法实现

```python
def resolve_permission(
    tool_name: str,
    profile: AgentProfile,
) -> PermissionValue:
    """
    权限解析：精确匹配 > 叠加层 > 通配符 > default_permission

    叠加层（_overlay）由 WorldPlugin 在会话初始化时注入，
    优先级高于 Profile 自身规则，但低于精确匹配。
    """
    # 步骤 1：精确匹配（最高优先级）
    if tool_name in profile.tool_permissions:
        return profile.tool_permissions[tool_name]

    # 步骤 2：叠加层（WorldPlugin 覆盖）
    if tool_name in profile._overlay:
        return profile._overlay[tool_name]

    # 步骤 3：通配符匹配
    if "*" in profile.tool_permissions:
        return profile.tool_permissions["*"]

    # 步骤 4：默认权限（兜底）
    return profile.default_permission


def check_and_gate(
    tool_name: str,
    profile: AgentProfile,
    event_bus,          # BusEventEmitter
) -> bool:
    """
    执行权限门控：
    - allow → 返回 True，工具继续执行
    - deny  → 返回 False，工具调用被静默丢弃（或抛出 PermissionDeniedError）
    - ask   → 发布 permission.ask 事件，挂起等待用户响应
    """
    perm = resolve_permission(tool_name, profile)

    if perm == "allow":
        return True

    if perm == "deny":
        raise PermissionDeniedError(
            tool=tool_name,
            profile=profile.name,
            message=f"工具 '{tool_name}' 在 '{profile.name}' 模式下被禁止",
        )

    if perm == "ask":
        # 挂起当前 Agent 步骤，等待前端用户确认
        # 详见第 6 节「ask 权限交互流程」
        event_bus.emit("permission.ask", {
            "tool": tool_name,
            "profile": profile.name,
            "description": _get_tool_description(tool_name),
        })
        return False  # 暂时挂起，由回调恢复
```

### 4.3 通配符示例

| `tool_permissions` 配置 | `resolve_permission("roll_check")` | `resolve_permission("unknown_tool")` |
|------------------------|--------------------------------------|----------------------------------------|
| `{"roll_check": "allow", "*": "deny"}` | `allow`（精确匹配） | `deny`（通配符） |
| `{"*": "deny"}` | `deny`（通配符） | `deny`（通配符） |
| `{}` + `default="ask"` | `ask`（默认） | `ask`（默认） |
| `{"roll_check": "deny"}` + `default="allow"` | `deny`（精确匹配） | `allow`（默认） |

---

## 5. WorldPlugin 自定义 AgentProfile

### 5.1 设计原则

WorldPlugin 不直接替换整个 AgentProfile，而是通过**叠加层（overlay）**
在运行时动态覆盖部分权限，保持基础 Profile 不变、易于复用。

```python
@dataclass
class WorldPlugin:
    world_key: str
    display_name: str

    # 叠加到 AgentProfile._overlay 的额外权限规则
    permission_overlay: dict[str, dict[str, PermissionValue]] = field(default_factory=dict)
    # 格式：{ "profile_name": { "tool_name": permission_value } }

    def apply_to_profile(self, profile: AgentProfile) -> None:
        """将本插件的覆盖规则注入到 profile._overlay"""
        overlay = self.permission_overlay.get(profile.name, {})
        profile._overlay.update(overlay)
```

### 5.2 武侠世界插件示例

```python
WUXIA_PLUGIN = WorldPlugin(
    world_key="wuxia_cn",
    display_name="中华武侠",
    permission_overlay={
        "play": {
            # 武侠世界无 SP 经济体系，关闭击杀获取 SP
            "earn_sp_by_kill":  "deny",
            # 内功心法传授需要专门确认（特殊师徒关系）
            "teach_inner_art":  "ask",
            # 开放武功传承系统
            "inherit_martial_art": "allow",
        },
    },
)
```

### 5.3 无限流世界插件示例

```python
INFINITE_FLOW_PLUGIN = WorldPlugin(
    world_key="infinite_flow",
    display_name="无限流副本",
    permission_overlay={
        "play": {
            # 跨世界传送机制，默认世界不开启
            "multi_world_transfer": "allow",
            # 副本主神积分系统
            "exchange_main_god_points": "ask",
            # 开启副本强制任务系统
            "assign_main_quest": "allow",
        },
        "plan": {
            # plan 模式额外开放副本架构分析工具
            "analyze_dungeon_structure": "allow",
        },
    },
)
```

### 5.4 权限叠加顺序

```
最终权限 = 精确匹配（Profile.tool_permissions）
         > WorldPlugin Overlay（profile._overlay）
         > 通配符（Profile.tool_permissions["*"]）
         > default_permission
```

---

## 6. `ask` 权限的交互流程

### 6.1 完整生命周期

```
Agent 调用 tool(name="purchase_item", ...)
        │
        ▼
check_and_gate("purchase_item", profile) → perm == "ask"
        │
        ▼
发布 BusEvent: permission.ask
{
  "id": "perm-uuid-001",
  "type": "permission.ask",
  "data": {
    "tool": "purchase_item",
    "profile": "play",
    "description": "购买道具「凤凰翎」，消耗 500 金币",
    "args": { "item_id": "phoenix_feather", "cost": 500 }
  }
}
        │
        ▼ SSE 推送到前端
前端弹出确认对话框（PermissionDialog 组件）
        │
        ├─ 用户点击「允许」─────────────────────────────────────────
        │                                                          │
        ▼                                                          ▼
POST /api/sessions/{id}/asks/{ask_id}                         用户点击「拒绝」
{ "decision": "allow" }                                          │
        │                                                          ▼
        ▼                                              后端收到 "deny" 决策
后端 PermissionGate 收到 allow 回调                    Agent 步骤抛出 ToolAbortedError
恢复 Agent 挂起步骤，继续执行                           工具调用被取消，写入 dm_note Part
```

### 6.2 BusEvent 结构

```python
@dataclass
class PermissionAskEvent:
    id: str                  # UUID，用于前端回调时携带
    type: Literal["permission.ask"]
    session_id: str
    data: PermissionAskData

@dataclass
class PermissionAskData:
    tool: str                # 被拦截的工具名
    profile: str             # 当前模式名
    description: str         # 人类可读描述（LLM 生成或工具预设）
    args: dict               # 工具调用参数（脱敏后）
    timeout_seconds: int = 60  # 超时后自动 deny
```

### 6.3 超时处理

> **权威语义（2026-06）**：`ask` 超时 = **deny（fail-closed）**。实现 `backend/agents/ask_handler.py`（`ASK_TIMEOUT_SECONDS = 60`）超时后 `_decision = "deny"`。
> ⚠️ 代码中 `tools/registry.py` 与 `play.yaml` 残留的「超时后默认允许 / 60s 自动允许（fail-open）」注释**为陈旧误导注释**，与实际 deny 行为矛盾，以本节 deny 为准（应清理注释）。

```python
async def wait_for_permission_decision(
    event_id: str,
    timeout: float = 60.0,
) -> Literal["allow", "deny"]:
    """等待前端用户决策，超时自动返回 deny"""
    try:
        decision = await asyncio.wait_for(
            permission_gate.wait(event_id),
            timeout=timeout,
        )
        return decision
    except asyncio.TimeoutError:
        logger.warning(f"Permission ask {event_id} timed out, defaulting to deny")
        return "deny"
```

---

## 7. 模式切换 API

### 7.1 接口定义

```
PATCH /api/sessions/{session_id}/mode
```

> **实现说明**：实际接口使用 `PATCH`（语义为局部更新），而非 `POST`。

#### 权限询问接口（ask 模式）

```
GET  /api/sessions/{session_id}/asks            # 获取当前待决策的权限询问列表
POST /api/sessions/{session_id}/asks/{ask_id}   # 提交决策（allow / deny）
```

**POST 请求体**：
```json
{ "decision": "allow" }
```

**GET 响应示例**：
```json
[
  {
    "ask_id": "perm-uuid-001",
    "tool_name": "purchase_item",
    "tool_args": { "item_id": "sword_01", "quantity": 1 },
    "reason": "购买物品需要确认",
    "created_at": 1748796000.0
  }
]
```

**请求体**：
```json
{
  "mode": "plan"
}
```

**响应**（200 OK）：
```json
{
  "session_id": "sess-001",
  "previous_mode": "play",
  "current_mode": "plan",
  "active_tools": ["search_lore", "query_character", "load_skill", "outline_chapter"],
  "switched_at": "2026-05-31T23:00:00+08:00"
}
```

### 7.2 切换语义

- **不影响消息历史**：已有 `messages` 表记录不变
- **不影响 Part 数据**：已渲染的 Part 保持不变
- **立即生效**：下一次 Agent 调用工具时使用新 Profile
- **WorldPlugin 叠加保持**：模式切换后，WorldPlugin overlay 重新应用到新 Profile

### 7.3 切换实现

```python
async def switch_mode(session_id: str, new_mode: str) -> dict:
    session = await session_repo.get(session_id)
    old_mode = session.current_mode

    # 从注册表获取新 Profile
    new_profile = AgentProfileRegistry.get(new_mode)

    # 重新应用 WorldPlugin overlay
    world_plugin = WorldPluginRegistry.get(session.world_key)
    world_plugin.apply_to_profile(new_profile)

    # 持久化
    await session_repo.update_mode(session_id, new_mode)

    # 发布模式切换事件（前端 UI 更新）
    event_bus.emit("session.mode_changed", {
        "session_id": session_id,
        "previous_mode": old_mode,
        "current_mode": new_mode,
        "active_tools": (
            new_profile.active_tools
            if new_profile.active_tools != "all"
            else "all"
        ),
    })

    return {
        "session_id": session_id,
        "previous_mode": old_mode,
        "current_mode": new_mode,
        "active_tools": new_profile.active_tools,
    }
```

### 7.4 合法模式值

| 模式名 | 描述 |
|--------|------|
| `play` | 正常跑团，大多数工具 allow |
| `plan` | 只读分析 + 大纲撰写 |
| `review` | 审校检查，完全只读 |

非注册模式名返回 `400 Bad Request`：
```json
{
  "error": "invalid_mode",
  "message": "Mode 'debug' is not registered",
  "details": { "available_modes": ["play", "plan", "review"] }
}
```

> **实现差异（2026-06）**：当前校验为硬编码字面量 `req.mode not in ("play","plan","review")`，返回 400 但 body 为纯文本 `detail`（缺结构化 `details.available_modes`），且新增 YAML 自定义模式无法通过校验。上方为「应然」结构化错误体；修复方向：改为查 `profile_registry.list_profiles()` 校验并返回结构化 body。

---

## 8. 扩展：自定义 AgentProfile

WorldPlugin 开发者可以注册完全自定义的模式：

```python
# worlds/cyberpunk/profiles.py

HACK_PROFILE = AgentProfile(
    name="hack",
    description="赛博朋克黑客模式——开启网络渗透工具，关闭物理战斗工具",
    tool_permissions={
        "*":                  "deny",
        "network_intrusion":  "allow",
        "data_extraction":    "allow",
        "trace_evasion":      "allow",
        "search_lore":        "allow",
        "query_character":    "allow",
        "combat_action":      "deny",   # 显式关闭（与通配符 deny 一致，但语义更清晰）
    },
    default_permission="deny",
    active_tools=[
        "network_intrusion",
        "data_extraction",
        "trace_evasion",
        "search_lore",
        "query_character",
    ],
)

# 在插件加载时注册
AgentProfileRegistry.register(HACK_PROFILE)
```

---

## 附录：权限枚举值说明

| 值 | 行为 | 适用场景 |
|----|------|---------|
| `allow` | 直接执行，无任何提示 | 频繁调用、低风险、只读操作 |
| `ask` | 挂起 → 弹出确认框 → 等待用户决策 | 有副作用、消耗资源、不可逆操作 |
| `deny` | 立即拒绝，抛出 `PermissionDeniedError` | 该模式下完全禁止的操作 |

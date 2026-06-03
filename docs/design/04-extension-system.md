# 04 — 统一扩展体系完整设计

> **版本**：0.1.0 · **最后更新**：2026-05-31  
> **关联文件**：`01-architecture-overview.md`、`03-agent-system.md`

---

## 目录

1. [设计目标](#1-设计目标)
2. [八类扩展类型详解](#2-八类扩展类型详解)
3. [扩展发现机制](#3-扩展发现机制)
4. [内置扩展目录](#4-内置扩展目录)
5. [Hook 点全览](#5-hook-点全览)
6. [扩展开发指南](#6-扩展开发指南)

---

## 1. 设计目标

### 1.1 核心承诺

> **核心代码零修改即可扩展新世界观、新工具、新 Agent。**

扩展体系遵循以下四个原则：

| 原则 | 含义 |
|------|------|
| **零侵入** | 添加新扩展不需要修改 `core/` 目录中的任何文件 |
| **声明式** | 扩展通过配置文件（YAML/JSON/SKILL.md）声明能力，不依赖运行时猴补丁 |
| **三级覆盖** | 内置 < 用户级 < 项目级，高优先级同名扩展自动覆盖低优先级 |
| **可热加载** | 开发模式下，修改扩展文件后无需重启服务（生产模式需重启） |

### 1.2 优先级三级目录

参考来源：opencode Plugin Hooks、pi Extension 系统、Cursor rules 三级、superpowers SKILL.md。

```
优先级（高 → 低）

③ 项目级    .zero-arsenal/extensions/         当前项目专属，最高优先级
② 用户级    ~/.zero-arsenal/extensions/        跨项目共享，中等优先级
① 内置级    zero_arsenal/extensions/           随包发布，最低优先级（可被覆盖）
```

**同名冲突处理规则**：

- 同类扩展同 `id`：高优先级完全替换低优先级（不做合并）。
- WorldPlugin 同 `name`：高优先级覆盖，但 `data/` 目录做**合并**（内置数据 + 项目数据共存）。
- SKILL.md 同 `id`：高优先级替换，但 `inject_as` 为 `append` 时追加而非替换。

### 1.3 目录结构总览

```
extensions/
├── crossover/              # 内置：综漫无限流世界插件
├── wuxia/                  # 内置：武侠江湖世界插件
├── infinite_arsenal/       # 内置：无限武库世界插件
└── __registry__.json       # 扩展注册表（自动生成，勿手动编辑）

~/.zero-arsenal/extensions/
└── my_custom_world/        # 用户级扩展示例

.zero-arsenal/extensions/
└── project_override/       # 项目级覆盖示例
```

---

## 2. 八类扩展类型详解

### 2.1 工具扩展（Tool Extension）

**文件位置**：`extensions/<name>/tools.py`（或 `tools/` 子目录）

**接口定义（实现版）**：

> ⚠️ **字段名对照表**（设计草案 vs 实际实现 `backend/tools/registry.py`）：
>
> | 本文档（草案名） | 实现字段名 | 说明 |
> |---|---|---|
> | `id` | `name` | 工具唯一标识符 |
> | `execute` | `handler` | 工具处理函数（async） |
> | `default_permission` | `permission_required` | 默认权限（allow/ask/deny） |
> | `state_snapshot` | `turn_ctx`（弱引用） | TurnContext 引用，功能超集 |
>
> 编写扩展工具时请使用**实现字段名**。

```python
# backend/tools/registry.py（实际实现）
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional, Union, Type


@dataclass
class ToolContext:
    """工具执行时的运行时上下文。"""
    session_id: str = ""
    message_id: str = ""
    agent_name: str = ""
    profile_name: str = "play"          # 当前 AgentProfile 名称
    turn_index: int = 0
    metadata: dict = field(default_factory=dict)
    turn_ctx: Optional[object] = None   # 弱引用到 TurnContext（替代 state_snapshot）
    bus: Optional[object] = None        # EventBus 引用（可发布 SSE 事件）
    abort_signal: Optional[object] = None  # 取消信号


@dataclass
class ToolResult:
    """工具执行结果。"""
    content: str = ""                   # 返回给 LLM 的文本
    data: dict = field(default_factory=dict)
    part_type: str = ""                 # 触发 Part 的类型（空=不触发）
    should_memorize: bool = False
    needs_continuation: bool = False
    error: str = ""                     # 非空表示失败


@dataclass
class ToolDef:
    name: str                           # 全局唯一标识（草案字段名：id）
    description: str                    # LLM 可见的触发描述
    parameters: Union[dict, Type]       # dict（JSON Schema）或 Pydantic BaseModel 类
    handler: Callable                   # async function（草案字段名：execute）
    permission_required: str = "allow"  # allow/ask/deny（草案字段名：default_permission）
    execution_mode: str = "parallel"    # parallel | sequential
    tags: list[str] = field(default_factory=list)
    group: str = "general"              # engine | narrative | character | economy | chapter
    timeout_seconds: float = 15.0
    before_hooks: list = field(default_factory=list)  # 工具级前置钩子
    after_hooks: list = field(default_factory=list)   # 工具级后置钩子
```

**加载时机**：服务启动时扫描所有扩展，所有 `ToolDef` 统一注册到 `ToolRegistry`。LangGraph 节点按 `agent_profile` 过滤可用工具列表。

**注册方式**：

```python
# extensions/crossover/tools.py（使用实现字段名）
from backend.tools.registry import ToolDef, ToolContext, ToolResult

async def _earn_sp_by_kill(session_id: str, enemy_key: str,
                            enemy_tier: int, enemy_tier_sub: str,
                            killed: bool) -> dict:
    sp_table = {1: 50, 2: 200, 3: 800, 4: 3200, 5: 12800}
    base_sp = sp_table.get(enemy_tier, 50)
    multiplier = {"L": 0.8, "M": 1.0, "U": 1.3}[enemy_tier_sub]
    total = int(base_sp * multiplier * (1.5 if killed else 1.0))
    # 直接返回 dict，registry.execute() 会包装为 {"result": ...}
    return {"sp_gained": total, "enemy": enemy_key}

TOOLS = [
    ToolDef(
        name="earn_sp_by_kill",         # 注意：字段名为 name，不是 id
        description="根据敌人星级计算并发放击杀 SP 奖励。在战斗结束后由 VarAgent 调用。",
        parameters={                    # dict 格式（JSON Schema）
            "type": "object",
            "properties": {
                "enemy_key": {"type": "string"},
                "enemy_tier": {"type": "integer"},
                "enemy_tier_sub": {"type": "string", "enum": ["L", "M", "U"]},
                "killed": {"type": "boolean"},
            },
            "required": ["enemy_key", "enemy_tier", "enemy_tier_sub", "killed"],
        },
        handler=_earn_sp_by_kill,       # 注意：字段名为 handler，不是 execute
        permission_required="allow",    # 注意：字段名为 permission_required
        execution_mode="sequential",
        tags=["economy", "combat", "crossover"],
        group="economy",
    )
]
```

---

### 2.2 Agent 节点扩展（Agent Extension）

**文件位置**：`extensions/<name>/agents.py`

> **⚠️ 实现差异**（`backend/agents/agent_node.py`）：
>
> | 草案字段 | 实现 | 说明 |
> |---------|------|------|
> | `system_prompt_id: str` | 无 | 实现中 Agent 节点不绑定提示词 ID；提示词由 PromptRegistry 按 agent_filter 自动匹配 |
> | `profile: AgentProfile` | 无 | 实现中节点不持有独立 Profile；共用会话级 effective_profile（通过 profile_registry 管理） |
> | `execute(state: AgentState)` | `execute(ctx: TurnContext)` | AgentState 已重命名为 TurnContext |
> | `AGENT_NODES` 列表 | `register_node(MyNode())` | 实现用模块级注册函数；`extension_loader` 导入 `agents.py` 时副作用注册 |

**接口定义**（`backend/agents/agent_node.py` 实际实现）：

```python
class AgentNode(ABC):
    name: str                         # 唯一节点名
    display_name: str                 # 日志和 UI 可读名称
    insert_after: str | None = None   # 注入位置（如 "narrator"、"var"）
    replace: str | None = None        # 替换现有节点（如 "style"）
    tools: list = []                  # 本节点可用工具（ToolDef 列表）

    @abstractmethod
    async def execute(self, ctx: TurnContext) -> TurnContext: ...
```

**注册方式**（导入 agents.py 时自动触发）：

```python
from backend.agents.agent_node import AgentNode, register_node
from backend.agents.state import TurnContext

class MyCustomNode(AgentNode):
    name = "my_node"
    display_name = "我的自定义节点"
    insert_after = "narrator"

    async def execute(self, ctx: TurnContext) -> TurnContext:
        # ... 自定义逻辑 ...
        return ctx

register_node(MyCustomNode())  # 模块级副作用注册
```

**加载时机**：服务启动时，扩展加载器扫描所有 `agents.py`，导入时 `register_node()` 副作用触发注册，`inject_registered_nodes(builder)` 修改图结构。

**图注入规则**：

```
insert_after="narrator"  → 在 narrator → style 边中间插入新节点
replace="style"          → 用新节点完全替换 StyleAgent（style 节点从图中移除）
insert_after=None        → 不自动注入，需要在 plugin.py 中手动调用 graph_builder
```

---

### 2.3 技能扩展（Skill Extension）

**文件位置**：`extensions/<name>/skills/*.md`（或用户级 `~/.zero-arsenal/skills/`）

**SKILL.md frontmatter 完整字段**：

```yaml
---
id: "world-rules-crossover"            # 全局唯一 ID
version: "1.2.0"
display_name: "综漫无限流世界规则"

# 触发模式
trigger: "always"                      # always | on_demand | auto
# always:    每次会话强制注入
# on_demand: 玩家/DM 手动激活
# auto:      满足 condition 时自动激活

condition: null                        # trigger=auto 时的激活条件（Python 表达式）
# 示例：'state["mode"] == "combat" and "crossover" in state["world_plugin"]["name"]'

# 注入目标
inject_as: "system_prompt_append"      # system_prompt_prepend | system_prompt_append |
                                       # tool_context | before_hook | after_hook | replace
# system_prompt_append: 追加到 Agent 的 System Prompt 末尾
# tool_context:         作为工具调用时的上下文注入

# 作用阶段（哪些 Agent 节点会收到此 SKILL）
phases:
  - "rules"
  - "dm"
  # 留空表示所有 Agent

priority: 100                          # 数字越大越先注入（影响 System Prompt 顺序）

# 适用世界（空列表=所有世界）
applicable_worlds:
  - "crossover"

# 文件依赖（本 SKILL 依赖的其他 SKILL id）
requires: []

# 元数据
author: "built-in"
description: "综漫无限流的骰子协议、战力星级、SP 经济规则。"
---

<!-- 以下是实际注入到 System Prompt 的内容 -->

## 综漫无限流世界规则

### 骰子协议
...（详细内容）...
```

**加载时机**：会话初始化时，根据 `trigger` 和 `condition` 决定是否激活。`always` 类 SKILL 在 `AgentState.active_skills` 中预填充；`auto` 类在每轮开始时动态评估。

---

### 2.4 世界插件扩展（WorldPlugin）

**文件位置**：`extensions/<name>/plugin.py`

**实际实现**（`backend/extensions/plugin.py`，已对齐）：

```python
# backend/extensions/plugin.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AttributeDef:
    """属性维度定义。通过 WorldPlugin.attribute_schema 声明本世界的属性体系。"""
    display: str              # 用户可见名称，如 "力量"
    min: int = 1
    max: int = 999
    default: int = 10
    description: str = ""
    unit: str = ""            # 单位，如 "点"、"级"


@dataclass
class ItemType:
    """物品类型定义。通过 WorldPlugin.item_types 声明可用物品分类。"""
    key: str
    display_name: str
    stackable: bool = False
    max_stack: Optional[int] = None
    rarity_tiers: list[str] = field(default_factory=list)
    custom_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class EconomyConfig:
    """经济配置。通过 WorldPlugin.economy_config 声明货币与汇率。"""
    primary_currency: str = "积分"
    secondary_currencies: list[str] = field(default_factory=list)
    starting_balance: dict[str, int] = field(default_factory=dict)
    exchange_rates: dict[str, float] = field(default_factory=dict)


@dataclass
class WorldPlugin:
    """
    世界插件基类（backend/extensions/plugin.py）。
    每个 WorldPlugin 定义一个完整的世界观体系：
    属性维度、物品类型、经济配置、Agent 权限、MCP 服务。

    必填字段：key、name、description
    """
    key: str                               # 唯一标识，如 "crossover"
    name: str                              # 用户可见名称，如 "综漫无限流"
    description: str = ""
    system_prompt_fragments: list[dict] = field(default_factory=list)
    agent_profile: str = "play"

    # ── 属性体系 ─────────────────────────────────────────────────────────────
    # attribute_schema 优先；未提供时退化为 extra_attributes 简单列表
    attribute_schema: dict[str, AttributeDef] = field(default_factory=dict)
    # 示例：{"STR": AttributeDef(display="力量", min=1, max=999, default=10)}
    extra_attributes: list[str] = field(default_factory=list)  # 向后兼容

    # ── 物品体系 ─────────────────────────────────────────────────────────────
    item_types: list[ItemType] = field(default_factory=list)

    # ── 经济配置 ─────────────────────────────────────────────────────────────
    economy_config: Optional[EconomyConfig] = None

    # ── 权限覆盖 ─────────────────────────────────────────────────────────────
    # 格式：{"play": [{"pattern": "roll_*", "action": "allow"}], ...}
    permission_overlay: dict = field(default_factory=dict)

    # ── MCP 服务 ─────────────────────────────────────────────────────────────
    # 格式：[{"name": "my_mcp", "url": "http://localhost:8100", "enabled": True}]
    mcp_servers: list = field(default_factory=list)

    # ── 其他配置 ─────────────────────────────────────────────────────────────
    skills_dir: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    # ── 生命周期钩子 ─────────────────────────────────────────────────────────
    def on_session_init(self, state: dict) -> dict:
        """会话创建后调用，state 为 TurnContext dict 快照，返回修改后的 state。"""
        return state

    def on_turn_start(self, state: dict) -> dict:
        """每轮 RulesAgent 之前调用。"""
        return state

    def on_turn_end(self, state: dict) -> dict:
        """每轮 ChroniclerAgent 之后调用。"""
        return state

    def get_rules_skills(self) -> list[str]:
        """返回本世界的 SKILL 路径列表（会话初始化时自动激活）。"""
        return []

    def get_character_template(self) -> dict:
        """返回角色卡初始模板（JSON 可序列化）。"""
        return {}

    def get_effective_attributes(self) -> dict[str, AttributeDef]:
        """返回实际生效的属性字典（attribute_schema 优先，否则从 extra_attributes 转换）。"""
        if self.attribute_schema:
            return self.attribute_schema
        return {attr: AttributeDef(display=attr) for attr in self.extra_attributes}
```

**最小扩展示例**：

```python
# extensions/my_world/plugin.py
from backend.extensions.plugin import WorldPlugin, AttributeDef, ItemType, EconomyConfig

plugin = WorldPlugin(
    key="my_world",
    name="我的世界",
    description="自定义世界观",
    attribute_schema={
        "STR": AttributeDef(display="力量", min=1, max=100, default=10),
        "INT": AttributeDef(display="智力", min=1, max=100, default=10),
    },
    item_types=[
        ItemType(key="weapon", display_name="武器", stackable=False),
        ItemType(key="consumable", display_name="消耗品", stackable=True, max_stack=99),
    ],
    economy_config=EconomyConfig(
        primary_currency="金币",
        starting_balance={"金币": 100},
    ),
    system_prompt_fragments=[
        {"phase": "all", "content": "你正在一个剑与魔法的世界中..."}
    ],
)
```

---

### 2.5 提示词片段扩展（PromptFragment）

**文件位置**：`extensions/<name>/prompts/` 或 `prompts/fragments/`

**文件格式**：普通 Markdown 文件，frontmatter 指定注入目标。

```yaml
---
fragment_id: "crossover_combat_reminder"
inject_into: ["narrator", "dm"]        # 注入到哪些 Agent 的 System Prompt
position: "after_world_rules"          # before_start | after_world_rules | before_end
condition: 'state["mode"] == "combat"' # 仅在战斗模式下注入
priority: 50
---

## 战斗模式提醒（综漫世界）

当前处于战斗模式。请注意：
- 骰子结果已在 RulesAgent 阶段固化，**禁止在叙事中修改骰子结果**。
- 战力差距 ≥ 2 星时，弱方不能正面击败强方（除非使用系统兑换能力）。
- 每次使用能力必须注明其来源（已兑换清单 or 天生特质）。
```

---

### 2.6 MCP 服务扩展

**文件位置**：`extensions/<name>/mcp_server.py`（或外部服务 URL）

**配置格式**（在 `plugin.py` 的 `mcp_servers` 字段中声明）：

```python
mcp_servers = [
    MCPConfig(
        server_id="crossover_db",
        command="python",
        args=["-m", "extensions.crossover.mcp_server", "--stdio"],
        env={"NOVEL_DB": "${NOVEL_DB}"},   # 支持环境变量插值
    )
]
```

**MCP 服务工具自动注册**：加载 WorldPlugin 时，系统自动启动 `mcp_servers` 列表中的所有 MCP 服务，并将其暴露的工具合并到 `ToolRegistry`，权限继承 `plugin.agent_profile.tool_permissions`。

---

### 2.7 规则扩展（Rules Extension）

**文件位置**：`extensions/<name>/rules/*.md`（对标 Cursor `.mdc` 风格）

**文件格式**：

```yaml
---
rule_id: "dice-protocol"
trigger: "always"                      # always | on_demand（对标 cursor alwaysApply/agentRequested）
applicable_agents: ["rules", "dm"]     # 限定作用 Agent
priority: 200                          # 数字越大越高优先级
description: "骰子判定协议：何时投骰、DC 计算方式、暴击规则。"
---

# 骰子判定协议

## 何时需要投骰
凡行动存在不确定性且后果影响剧情，均需投骰...

## DC 计算
基础 DC = 敌方能力值 × 难度系数...
```

**三级触发**（与 SKILL.md 触发模式对应）：

| trigger | 含义 | 实现 |
|---------|------|------|
| `always` | 每轮强制注入 | 预置到 `active_skills` |
| `on_demand` | DM/玩家手动激活 | API `activate_rule(rule_id)` |

---

### 2.8 Hook 扩展

**文件位置**：`extensions/<name>/hooks.py`

**完整 Hook 接口**：

```python
# core/extension_hooks.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class ExtensionHooks(Protocol):
    """
    扩展可实现的所有 Hook 方法。
    所有方法均为可选（Protocol 不强制实现）。
    执行顺序：内置 Hook → 用户级 Hook → 项目级 Hook（按优先级排序）。
    """

    # ── 工具调用 Hook（来自 pi agent-loop） ──────────────────────
    async def before_tool_call(
        self, tool_call: ToolCall, state: AgentState, agent_name: str
    ) -> BeforeToolAction:
        """工具调用前，可 block/modify 工具调用。"""
        ...

    async def after_tool_call(
        self, tool_call: ToolCall, result: ToolResult, state: AgentState
    ) -> AfterToolAction:
        """工具调用后，可替换结果或终止循环。"""
        ...

    # ── LangGraph 图节点 Hook（来自 opencode Plugin Hooks）───────
    async def before_agent_node(
        self, agent_name: str, state: AgentState
    ) -> AgentState:
        """每个 LangGraph 节点执行前调用。"""
        ...

    async def after_agent_node(
        self, agent_name: str, state: AgentState
    ) -> AgentState:
        """每个 LangGraph 节点执行后调用。"""
        ...

    # ── 会话生命周期 Hook ─────────────────────────────────────────
    async def on_session_start(self, state: AgentState) -> AgentState:
        """会话创建时（首次 turn）调用。"""
        ...

    async def on_session_end(self, state: AgentState) -> None:
        """会话正常结束时调用（归档完成后）。"""
        ...

    async def on_session_error(self, error: Exception, state: AgentState) -> None:
        """管线抛出异常时调用。"""
        ...

    # ── 变量结算 Hook（来自 pi Extension 系统）──────────────────
    async def before_var_update(
        self, update: VarUpdate, state: AgentState
    ) -> VarUpdate | None:
        """变量结算前，返回 None 表示跳过此条更新。"""
        ...

    async def after_var_update(
        self, update: VarUpdate, state: AgentState
    ) -> None:
        """变量结算后，可触发副作用（如成就检查）。"""
        ...

    # ── NPC Hook ──────────────────────────────────────────────────
    async def before_npc_response(
        self, npc_key: str, state: AgentState
    ) -> AgentState:
        """NPC 子 Session 启动前调用。"""
        ...

    async def after_npc_response(
        self, npc_key: str, response: NPCResponse, state: AgentState
    ) -> NPCResponse:
        """NPC 响应生成后调用，可修改响应内容。"""
        ...

    # ── 叙事 Hook ─────────────────────────────────────────────────
    async def after_narrative_generated(
        self, narrative: str, state: AgentState
    ) -> str:
        """NarratorAgent P3 完成后，StyleAgent 之前调用。可预处理叙事文本。"""
        ...

    async def after_style_applied(
        self, narrative: str, purity_score: float, state: AgentState
    ) -> str:
        """StyleAgent 完成后调用。可追加世界特定的格式化。"""
        ...

    # ── 记忆压缩 Hook ─────────────────────────────────────────────
    async def before_memory_compress(
        self, turns_to_compress: list[dict], state: AgentState
    ) -> list[dict]:
        """记忆压缩前调用，可过滤或标记重要事件。"""
        ...
```

**Hook 注册示例**：

```python
# extensions/crossover/hooks.py

class CrossoverHooks:
    async def before_var_update(self, update: VarUpdate, state: AgentState) -> VarUpdate | None:
        """综漫世界特有：属性超过当前进化阶段上限时，自动触发进化。"""
        if update.update_type == "UpdateAttribute" and update.target == "STR":
            current_evo = state["memory_context"].get("evolution_stage", 1)
            cap = EVOLUTION_CAPS[current_evo]
            if update.after > cap:
                # 触发进化事件而不是直接裁减
                await get_bus().emit(EvolutionTriggerPart(
                    character=update.target,
                    from_stage=current_evo,
                ))
                return None  # 跳过此次直接赋值，让进化逻辑处理
        return update

HOOKS = CrossoverHooks()
```

---

## 3. 扩展发现机制

### 3.1 目录扫描算法

```python
# core/extension_loader.py
import importlib
import json
from pathlib import Path
from typing import Any

EXTENSION_SEARCH_PATHS = [
    Path("zero_arsenal/extensions"),           # ① 内置级（随包）
    Path.home() / ".zero-arsenal/extensions", # ② 用户级
    Path(".zero-arsenal/extensions"),          # ③ 项目级（最高优先级）
]

def discover_extensions() -> dict[str, ExtensionBundle]:
    """
    扫描三级目录，按优先级合并扩展。
    返回：{extension_id: ExtensionBundle}
    """
    registry: dict[str, list[tuple[int, Path]]] = {}  # id → [(priority, path)]

    for priority, base_path in enumerate(EXTENSION_SEARCH_PATHS):
        if not base_path.exists():
            continue
        for ext_dir in sorted(base_path.iterdir()):
            if not ext_dir.is_dir():
                continue
            manifest_path = ext_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            ext_id = manifest["id"]
            registry.setdefault(ext_id, []).append((priority, ext_dir))

    bundles: dict[str, ExtensionBundle] = {}
    for ext_id, candidates in registry.items():
        # 按优先级排序（高优先级在后，最终取最高）
        candidates.sort(key=lambda x: x[0])
        winner_priority, winner_path = candidates[-1]

        bundles[ext_id] = ExtensionBundle(
            ext_id=ext_id,
            path=winner_path,
            priority=winner_priority,
            shadowed_by=winner_path if len(candidates) > 1 else None,
        )
    return bundles


def load_extension(bundle: ExtensionBundle) -> LoadedExtension:
    """
    加载单个扩展包，返回所有可注册的组件。
    """
    loaded = LoadedExtension(ext_id=bundle.ext_id, path=bundle.path)

    # 加载 plugin.py（WorldPlugin）
    plugin_path = bundle.path / "plugin.py"
    if plugin_path.exists():
        module = importlib.import_module_from_path(plugin_path)
        loaded.world_plugin = getattr(module, "PLUGIN", None)

    # 加载 tools.py（ToolDef 列表）
    tools_path = bundle.path / "tools.py"
    if tools_path.exists():
        module = importlib.import_module_from_path(tools_path)
        loaded.tools = getattr(module, "TOOLS", [])

    # 加载 agents.py（AgentNode 列表）
    agents_path = bundle.path / "agents.py"
    if agents_path.exists():
        module = importlib.import_module_from_path(agents_path)
        loaded.agent_nodes = getattr(module, "AGENT_NODES", [])

    # 加载 hooks.py
    hooks_path = bundle.path / "hooks.py"
    if hooks_path.exists():
        module = importlib.import_module_from_path(hooks_path)
        loaded.hooks = getattr(module, "HOOKS", None)

    # 扫描 skills/ 目录
    skills_dir = bundle.path / "skills"
    if skills_dir.exists():
        loaded.skills = list(skills_dir.glob("*.md"))

    # 扫描 rules/ 目录
    rules_dir = bundle.path / "rules"
    if rules_dir.exists():
        loaded.rules = list(rules_dir.glob("*.md"))

    # 扫描 prompts/ 目录
    prompts_dir = bundle.path / "prompts"
    if prompts_dir.exists():
        loaded.prompt_fragments = list(prompts_dir.glob("**/*.md"))

    return loaded
```

### 3.2 冲突解决规则

```
同类扩展冲突解决顺序：

1. ToolDef 同 id：
   高优先级完全替换。注册表中保留替换记录（可追溯）。

2. AgentNode 同 name：
   高优先级替换。图结构按高优先级的 insert_after/replace 重建。

3. WorldPlugin 同 name：
   高优先级的 plugin.py 替换低优先级。
   但 data/ 目录做合并（内置数据作为 fallback，项目数据优先查找）。

4. SKILL.md 同 id：
   - inject_as == "replace"：高优先级完全替换。
   - inject_as == "append"：两者都注入，高优先级在后。

5. Rules 同 rule_id：
   高优先级完全替换。
```

---

## 4. 内置扩展目录

### 4.1 crossover — 综漫无限流

```
extensions/crossover/
├── manifest.json              # 扩展元数据
├── plugin.py                  # WorldPlugin 实现
├── tools.py                   # 扩展工具
├── agents.py                  # 可选扩展 Agent 节点
├── hooks.py                   # Hook 实现
├── skills/
│   ├── world-rules.md         # trigger: always — 综漫世界核心规则
│   ├── dice-protocol.md       # trigger: always — 骰子判定协议
│   ├── shop-evaluation.md     # trigger: on_demand — 商店物品定价指南
│   ├── combat-tactics.md      # trigger: auto (mode==combat) — 战斗战术提示
│   └── purity-check.md        # trigger: always — AI纯净度自核查
├── rules/
│   ├── dice-protocol.md       # trigger: always
│   ├── combat-tactics.md      # trigger: on_demand
│   └── capability-realism.md  # trigger: always
└── data/
    ├── character-template.json  # 角色卡初始模板
    ├── shop-catalog.json        # 汪吧商品目录（种子数据）
    └── world-registry.json      # 已注册世界列表
```

**属性体系（10 维）**：

```python
# extensions/crossover/plugin.py（属性部分）
attribute_schema = {
    "STR": AttributeDef(display="力量", min=1, max=9999, default=10,
                        description="物理攻击力、搬运能力、近战破坏力"),
    "DUR": AttributeDef(display="耐久", min=1, max=9999, default=10,
                        description="受到伤害的抵抗能力、血量上限"),
    "VIT": AttributeDef(display="活力", min=1, max=9999, default=10,
                        description="恢复速度、毒素抗性、持续战斗能力"),
    "SPD": AttributeDef(display="速度", min=1, max=9999, default=10,
                        description="移动速度、反应时间、行动次序"),
    "AGI": AttributeDef(display="敏捷", min=1, max=9999, default=10,
                        description="闪避率、精准度、连击能力"),
    "INT": AttributeDef(display="智力", min=1, max=9999, default=10,
                        description="学习能力、魔力量、技术领域"),
    "MND": AttributeDef(display="心智", min=1, max=9999, default=10,
                        description="精神抗性、异能适应、意志力"),
    "PER": AttributeDef(display="感知", min=1, max=9999, default=10,
                        description="战场感知、情报收集、预判能力"),
    "CHA": AttributeDef(display="魅力", min=1, max=9999, default=10,
                        description="NPC 好感度加成、社交技能、领导力"),
    "LCK": AttributeDef(display="幸运", min=1, max=9999, default=10,
                        description="暴击率、掉落率、被选中概率"),
}
```

**经济体系（汪吧经济）**：

```python
economy_config = EconomyConfig(
    primary_currency="SP",                # 主货币：积分（Skill Points）
    secondary_currencies=["汪吧点", "战功", "声望"],
    starting_balance={"SP": 1000, "汪吧点": 0, "战功": 0, "声望": 0},
    exchange_rates={"汪吧点": 0.1, "战功": 5.0, "声望": 0.0},
    # 声望不可换算，纯叙事影响
)
```

---

### 4.2 wuxia — 武侠江湖

```
extensions/wuxia/
├── manifest.json
├── plugin.py
├── tools.py                   # 工具：inner_power_circulate, spar_challenge 等
├── skills/
│   ├── world-rules.md         # 武侠世界核心设定规则
│   ├── cultivation-system.md  # 修炼体系（炼体/筑基/金丹...）
│   └── social-protocol.md    # 江湖社交规则（拜师/挑战/恩怨）
├── rules/
│   ├── cultivation-caps.md    # 修炼上限验证规则
│   └── faction-politics.md   # 门派政治规则
└── data/
    ├── character-template.json
    ├── sects-catalog.json     # 门派目录（少林/武当/峨眉等）
    └── techniques-catalog.json # 武学目录（种子数据）
```

**属性体系（8 维·修炼维度）**：

```python
attribute_schema = {
    "FLESH":   AttributeDef(display="肉身", min=1, max=9999, default=10,
                            description="体质强度、物理防御、受毒抗性"),
    "SPIRIT":  AttributeDef(display="神魂", min=1, max=9999, default=10,
                            description="精神力、灵魂强韧度、异术抵抗"),
    "INNER":   AttributeDef(display="内力", min=0, max=9999, default=0,
                            description="内功深度、技能耗用基础、续航"),
    "SWORD":   AttributeDef(display="剑道", min=1, max=999, default=1,
                            description="剑法造诣，影响剑系技能威力"),
    "FIST":    AttributeDef(display="拳意", min=1, max=999, default=1,
                            description="拳掌功夫造诣"),
    "LIGHT":   AttributeDef(display="轻功", min=1, max=999, default=1,
                            description="身法速度、飞跃距离"),
    "CHARM":   AttributeDef(display="江湖名望", min=0, max=9999, default=0,
                            description="在江湖中的声誉，影响 NPC 态度"),
    "FORTUNE": AttributeDef(display="气运", min=1, max=100, default=50,
                            description="奇遇触发率、危机化解概率"),
}
```

---

### 4.3 infinite_arsenal — 无限武库

```
extensions/infinite_arsenal/
├── manifest.json
├── plugin.py
├── tools.py                   # 工具：draw_gacha, earn_battle_rewards 等
├── agents.py                  # GachaAgent：专用抽卡 Agent 节点
├── skills/
│   ├── world-rules.md         # 无限武库核心规则（主神空间）
│   ├── anti-feat-rating.md    # Anti-Feat 星级评定协议
│   └── shop-evaluation.md     # 三轮定价评估协议（来自02-exchange-evaluation）
├── rules/
│   ├── gacha-protocol.md      # 抽卡双轨协议
│   ├── capability-realism.md  # 能力现实性验证（来自08）
│   └── physical-strip.md      # 物理剥离规则
└── data/
    ├── character-template.json  # 无限武库角色卡结构（主神空间格式）
    ├── pool-catalog.json        # 卡池目录（综合池/战术池/战略池）
    └── acg-source-registry.json # 已收录 ACG 作品来源注册表
```

---

## 5. Hook 点全览

```python
# core/extension_hooks.py — 完整实现

class HookRegistry:
    """
    全局 Hook 注册表。
    加载扩展时自动注册，按优先级排序执行。
    """
    _hooks: list[tuple[int, ExtensionHooks]] = []  # [(priority, hook_impl)]

    def register(self, hooks: ExtensionHooks, priority: int) -> None:
        self._hooks.append((priority, hooks))
        self._hooks.sort(key=lambda x: x[0])

    async def run_before_tool_call(
        self, tool_call: ToolCall, state: AgentState, agent_name: str
    ) -> BeforeToolAction:
        """
        执行顺序：优先级从低到高（内置→用户→项目）。
        一旦某个 Hook 返回 block=True，立即停止后续 Hook。
        """
        for _, hook in self._hooks:
            if not hasattr(hook, "before_tool_call"):
                continue
            action = await hook.before_tool_call(tool_call, state, agent_name)
            if action.block:
                return action
            if action.modified_args:
                tool_call = tool_call.with_args(action.modified_args)
        return BeforeToolAction(block=False)

    async def run_after_tool_call(
        self, tool_call: ToolCall, result: ToolResult, state: AgentState
    ) -> AfterToolAction:
        """执行顺序：优先级从低到高。一旦 terminate=True 立即停止。"""
        for _, hook in self._hooks:
            if not hasattr(hook, "after_tool_call"):
                continue
            action = await hook.after_tool_call(tool_call, result, state)
            if action.replace_result:
                result = action.replace_result
            if action.terminate:
                return AfterToolAction(replace_result=result, terminate=True)
        return AfterToolAction(replace_result=result)

    async def run_before_agent_node(
        self, agent_name: str, state: AgentState
    ) -> AgentState:
        for _, hook in self._hooks:
            if hasattr(hook, "before_agent_node"):
                state = await hook.before_agent_node(agent_name, state)
        return state

    async def run_after_agent_node(
        self, agent_name: str, state: AgentState
    ) -> AgentState:
        for _, hook in self._hooks:
            if hasattr(hook, "after_agent_node"):
                state = await hook.after_agent_node(agent_name, state)
        return state

    async def run_before_var_update(
        self, update: VarUpdate, state: AgentState
    ) -> VarUpdate | None:
        """返回 None 表示跳过此次更新。"""
        current = update
        for _, hook in self._hooks:
            if hasattr(hook, "before_var_update"):
                current = await hook.before_var_update(current, state)
                if current is None:
                    return None
        return current

    async def run_after_narrative_generated(
        self, narrative: str, state: AgentState
    ) -> str:
        for _, hook in self._hooks:
            if hasattr(hook, "after_narrative_generated"):
                narrative = await hook.after_narrative_generated(narrative, state)
        return narrative

    # ... 其余 run_* 方法类同 ...
```

**Hook 执行顺序总表**：

| Hook 方法 | 来源 | 执行位置 | 可修改内容 | 可终止流程 |
|-----------|------|----------|-----------|-----------|
| `before_tool_call` | pi agent-loop | tool_loop 内，工具执行前 | 工具参数 | ✅（block） |
| `after_tool_call` | pi agent-loop | tool_loop 内，工具执行后 | 工具结果 | ✅（terminate） |
| `before_agent_node` | opencode Plugin | LangGraph 节点前 | AgentState | ❌ |
| `after_agent_node` | opencode Plugin | LangGraph 节点后 | AgentState | ❌ |
| `on_session_start` | opencode Plugin | 首轮 RulesAgent 前 | AgentState | ❌ |
| `on_session_end` | opencode Plugin | ChroniclerAgent 后 | 无（只读） | ❌ |
| `on_session_error` | opencode Plugin | 管线异常时 | 无（只读） | ❌ |
| `before_var_update` | pi Extension | VarAgent 每条结算前 | VarUpdate | ✅（返回 None） |
| `after_var_update` | pi Extension | VarAgent 每条结算后 | 无（副作用） | ❌ |
| `before_npc_response` | 本项目原创 | NPCAgent 子 Session 前 | AgentState | ❌ |
| `after_npc_response` | 本项目原创 | NPCAgent 子 Session 后 | NPCResponse | ❌ |
| `after_narrative_generated` | 本项目原创 | NarratorAgent P3 后 | 叙事文本 | ❌ |
| `after_style_applied` | 本项目原创 | StyleAgent 后 | 最终叙事 | ❌ |
| `before_memory_compress` | 本项目原创 | ChroniclerAgent 压缩前 | 待压缩轮次 | ❌ |

---

## 6. 扩展开发指南

### 6.1 最小化示例：新建"现代都市"WorldPlugin

以下是创建一个新世界插件所需的**最少代码**，满足系统要求的同时保持最小体积。

**目录结构**：

```
.zero-arsenal/extensions/modern_city/
├── manifest.json
├── plugin.py
└── skills/
    └── world-rules.md
```

**Step 1：`manifest.json`**

```json
{
  "id": "modern_city",
  "display_name": "现代都市",
  "version": "1.0.0",
  "description": "现代都市异能世界，ESPer 与科学的对决。",
  "type": "world_plugin",
  "min_engine_version": "0.1.0",
  "author": "your-name"
}
```

**Step 2：`plugin.py`**

```python
"""
用途: 现代都市 WorldPlugin — 最小化实现示例
用法: 放置于 .zero-arsenal/extensions/modern_city/plugin.py
"""
from core.world_plugin import WorldPlugin, AttributeDef, EconomyConfig

class ModernCityPlugin(WorldPlugin):
    name = "modern_city"
    display_name = "现代都市"
    version = "1.0.0"

    # ── 属性体系（7 维） ────────────────────────────────────────────
    attribute_schema = {
        "PHY": AttributeDef(display="体能", min=1, max=9999, default=10,
                            description="基础体能、力量、耐久度"),
        "PSY": AttributeDef(display="ESP 强度", min=0, max=9999, default=0,
                            description="异能功率，0 表示未觉醒"),
        "INT": AttributeDef(display="智力", min=1, max=9999, default=10,
                            description="学习速度、情报分析、科技理解"),
        "SOC": AttributeDef(display="社交", min=1, max=999, default=10,
                            description="NPC 好感度、谎言检测、人际关系"),
        "STL": AttributeDef(display="潜行", min=1, max=999, default=5,
                            description="隐蔽行动、监控规避、信息渗透"),
        "TEC": AttributeDef(display="技术", min=1, max=999, default=5,
                            description="黑客、机械、电子设备操作"),
        "LCK": AttributeDef(display="幸运", min=1, max=100, default=50,
                            description="随机事件的倾向性"),
    }

    # ── 经济体系 ─────────────────────────────────────────────────────
    economy_config = EconomyConfig(
        primary_currency="学园币",
        secondary_currencies=["暗网点数", "人情"],
        starting_balance={"学园币": 5000, "暗网点数": 0, "人情": 0},
        exchange_rates={"暗网点数": 2.5, "人情": 0.0},
    )

    # ── 样式配置 ──────────────────────────────────────────────────────
    style_config = {
        "default_scene_type": "daily_grind",
        "writing_style": "网文",
        "tone": "light_sci_fi",
    }

    def on_session_init(self, state):
        """初始化时确保 ESP 强度从 0 开始（未觉醒状态）。"""
        if "PSY" not in state.get("memory_context", {}).get("attributes", {}):
            state.setdefault("memory_context", {})
            state["memory_context"].setdefault("attributes", {})["PSY"] = 0
        return state

    def get_rules_skills(self):
        return ["skills/world-rules.md"]

    def get_character_template(self):
        return {
            "esper_level": 0,            # 0: 无能力者, 1-5: Level 1-5
            "ability_name": None,         # 觉醒后填写
            "ability_description": None,
            "organization": "学园都市第七学区",
            "faction": "neutral",
        }

    def validate_attribute_update(self, key, current, delta, state):
        if key == "PSY":
            esper_level = state["memory_context"].get("esper_level", 0)
            max_psy = {0: 0, 1: 100, 2: 500, 3: 2000, 4: 8000, 5: 99999}[esper_level]
            if isinstance(delta, (int, float)) and current + delta > max_psy:
                return False, f"PSY 超出 Level {esper_level} 上限 {max_psy}"
        return True, ""


PLUGIN = ModernCityPlugin()
```

**Step 3：`skills/world-rules.md`**

```yaml
---
id: "modern-city-world-rules"
version: "1.0.0"
display_name: "现代都市世界规则"
trigger: "always"
inject_as: "system_prompt_append"
phases: ["rules", "dm", "narrator"]
priority: 100
applicable_worlds: ["modern_city"]
---

## 现代都市世界设定

### 基础设定
- 时代背景：近未来，科学超越魔法的世界
- 核心矛盾：能力者（ESP）与非能力者、学园都市与外界
- 技术水平：比现实先进约 20-30 年（纳米机械、心理学武器、反重力原型）

### ESP 能力规则
- 每人只能有一种 ESP 能力（绝对唯一）
- Level 0（无能力者）和 Level 5（超能力者）之间隔着巨大鸿沟
- PSY 属性 0 = 未觉醒，觉醒需要特殊触发条件（骰子 DC 20）
- 强行使用超过自身 Level 的能力会导致脑损伤（PSY 临时 -20%）

### 行动规则
- 学园都市内：禁止明面冲突（警备员 Anti-Skill 巡逻）
- 暗网交易：需要暗网点数，追踪风险随每次交易累积
- 现金交易：超过 10 万学园币的单笔交易触发自动上报
```

### 6.2 添加自定义工具（可选）

```python
# .zero-arsenal/extensions/modern_city/tools.py
from core.tool_def import ToolDef, ToolContext, ToolResult
from pydantic import BaseModel

class HackSystemParams(BaseModel):
    target_system: str           # "traffic_cam" | "school_db" | "bank_transfer"
    method: str                  # "brute_force" | "social_engineering" | "zero_day"
    stealth_mode: bool = True

async def _hack_system(params: HackSystemParams, ctx: ToolContext) -> ToolResult:
    tec_score = ctx.state_snapshot.get("memory_context", {}).get(
        "attributes", {}
    ).get("TEC", 5)

    success_chance = min(0.9, tec_score / 100)
    import random
    success = random.random() < success_chance

    return ToolResult(
        content={
            "success": success,
            "target": params.target_system,
            "trace_added": 0.05 if not params.stealth_mode else 0.01,
        },
        display=f"{'成功' if success else '失败'}入侵 {params.target_system}",
    )

TOOLS = [
    ToolDef(
        id="hack_system",
        description="入侵电子系统（监控、数据库、转账系统等）。需要 TEC 属性支撑。",
        parameters=HackSystemParams,
        execute=_hack_system,
        default_permission="ask",     # 危险操作，执行前询问
        execution_mode="sequential",
        tags=["tech", "modern_city", "stealth"],
    )
]
```

### 6.3 检查清单

新建 WorldPlugin 发布前，逐项确认：

```
[ ] manifest.json 中 id 全局唯一（未与其他扩展冲突）
[ ] plugin.py 中所有必填字段已实现（name, display_name, attribute_schema）
[ ] attribute_schema 每个维度有 min/max/default/description
[ ] economy_config 的 starting_balance 覆盖所有 secondary_currencies
[ ] get_character_template() 返回 JSON 可序列化的 dict
[ ] validate_attribute_update() 覆盖所有有上限约束的属性
[ ] skills/world-rules.md frontmatter 格式正确，trigger 已设置
[ ] 自定义 ToolDef 的 default_permission 已按危险程度设置
[ ] 无硬编码绝对路径（遵循 06-script-generalization.mdc）
[ ] 在 README 或注释中说明该世界的核心规则来源（原著/原创）
```

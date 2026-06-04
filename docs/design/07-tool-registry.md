# 07 — 工具注册表设计（Tool Registry）

> **版本**：v1.1（2026-06 对齐实现）  
> **参考来源**：opencode `tool/tool.ts`（Effect Schema + ctx.ask）、pi TypeBox `registerTool`、MCP 动态工具规范  
> **状态**：已实现（部分偏离）——核心机制（注册、按 Agent 过滤、execution_mode 并发、权限 ask SSE、MCP 桥接、内置/扩展工具清单）全部落地，工具数远超本草案。
>
> 注：本文档已于 2026-06 对齐实现（D0 以代码为准）。原「设计稿，待实现」已撤销。下文 §3.3/§3.6 的「实现名称对照表」与「补录」维护良好；§1/§2/§4/§5/§7 的接口/流程/常量按下列「实现对齐总览」修正：
>
> **实现对齐总览（2026-06）**
> - **§1.1 ToolContext**：实际字段 `session_id/message_id/agent_name/profile_name/turn_index/metadata/turn_ctx/bus/abort_signal`。**无 `ctx.ask_permission` 回调**——权限交互改由 `ToolRegistry._wait_for_permission` + `ask_handler` 集中处理；`turn_id→turn_index(int)`、`extra→metadata`、`state` 由 `turn_ctx`+`state_snapshot` 替代。
> - **§1.2 ToolResult**：结构存在但**形同虚设**——所有 handler 返回**纯 dict**，`ToolRegistry.execute` 也返回 dict，`part_type/should_memorize/needs_continuation` 实际由 handler 自行发 Part。实际为「dict 返回 + handler 自发 Part」模型；`metadata→data`，且 `should_memorize`/`needs_continuation` 默认值实现为 **False**（草案为 True）。
> - **§1.3 ToolDef**：`id→name`、`parameters` 放宽为 `Union[dict, Type]`（内置工具用 dict=JSON Schema 直传）、`default_permission→permission_required: str`（无 Literal 约束）、`execute→handler`（签名 `handler(**args)->dict`）、`timeout_seconds` 默认 **15.0**；另有未消费的死字段 `requires_permission`。
> - **§1.4 AgentProfile**：实际见 `backend/agents/permission.py`——用 glob 模式 `list[ToolPermission]` + `default_permission` + `active_tools` + `visible_part_types` + `max_tokens_per_turn` + `allowed_groups`，替代草案的 `permission_overrides` dict（详见 10-permission-modes §2）。
> - **§2.1 执行链**：拆在 `tool_loop._execute_one` + `ToolRegistry.execute` 两处；`registry.execute` **先权限后验证**（与草案相反），且 tool_loop 已先门控一次 → 存在双重权限检查；before/after_hooks 在 tool_loop 跑（非 registry 内）。
> - **§5.1 权限矩阵**：**play 模式系统性放宽为 allow**（`default=ALLOW` + 末位 `*→allow`，`edit/earn/purchase/fork/consolidate/mcp_*` 均 allow）——属「尽量不打扰」产品取向（D0 已采纳为现状，见 10-permission-modes §3.1）；plan/review 与设计基本吻合（但 review 的 style/purity 误 deny 为缺陷，见 10 §3.3）。`deny 不可被 overlay 上调为 allow` 的安全底线当前未强制（待补）。
> - **§3.6+ 额外工具**：实现另有 `fetch_web_lore`、`list_scraper_rules`（group="lore"）及扩展自动发现 `_discover_extension_tools`（扫描 `extensions/*/tools.py` 的 `TOOLS`），本草案 §3 未列。
> - **§4.1 MCPBridge**：实际为**配置驱动**（读 `data/sys_config/mcp.json`）、用 **aiohttp**、`fetch_tool_list` 用 **GET**、工具名 `mcp_{server}_{tool}`（下划线）、无 `_jsonschema_to_pydantic`（直传 inputSchema dict）、用 `register_to_registry()/discover()/register_plugin_mcp_servers()` 替代 `get_tool_defs()/close()`。**MCP 重试指数退避未实现**。
> - **§6 ToolRegistry**：单例为 `ToolRegistry.get_instance()` + 模块级 `tool_registry`；`to_llm_schema→to_openai_functions`；**无 `unregister`**（MCP 热卸载待补）。
> - **§7.2 超时常量**：实际 ToolDef 默认 15s、MCP 10s、ASK 60s、fetch_tool_list 5s——与草案 GLOBAL=30/LONG_RUNNING=120/MCP=15/PERMISSION_ASK=300 全部不符，且无集中分级超时常量（待统一）。
> - **§8 测试**：本分片范围内未见工具链单测/集成测试（待补）。

---

## 目录

1. [核心数据结构](#1-核心数据结构)
2. [工具执行链（完整流程）](#2-工具执行链完整流程)
3. [内置工具完整清单](#3-内置工具完整清单)
4. [MCP 工具桥接](#4-mcp-工具桥接)
5. [工具权限矩阵](#5-工具权限矩阵)
6. [ToolRegistry 类](#6-toolregistry-类)
7. [错误处理与超时策略](#7-错误处理与超时策略)
8. [测试策略](#8-测试策略)

---

## 1. 核心数据结构

### 1.1 ToolContext

工具执行时的完整上下文，由 AgentRunner 在每次 tool_call 前构造并注入。

```python
from dataclasses import dataclass, field
from typing import Callable, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from zero_arsenal.core.agent_state import AgentState
    from zero_arsenal.core.event_bus import EventBus


@dataclass
class ToolContext:
    """工具执行上下文，每次 tool_call 创建一个新实例。"""

    # 会话与消息标识
    session_id: str
    message_id: str           # 当前 LLM 消息的 ID，用于关联 Part
    turn_id: str              # 当前对话轮次 ID

    # 执行主体
    agent_name: str           # 触发此工具的 Agent 名称（dm/npc/narrator/world）

    # 状态与总线（只读引用，不可在工具内直接 mutate）
    state: "AgentState"
    bus: "EventBus"

    # 权限回调：返回 True=用户授权，False=拒绝
    ask_permission: Callable[[str, str, dict], bool]

    # 中止信号：工具应定期检查并 raise ToolAbortedError
    abort_signal: Any         # asyncio.Event 或等价对象

    # 附加元数据（可选，工具自定义）
    extra: dict = field(default_factory=dict)
```

**说明**：

- `ask_permission(tool_id, reason, args)` 会通过 EventBus 推送 `permission.ask` 事件，前端弹出确认对话框，等待用户确认后回调。
- `abort_signal` 在用户点击"停止"或超时时被 set，工具应在长循环中调用 `abort_signal.is_set()` 检查。

---

### 1.2 ToolResult

工具执行完毕后的标准返回值。

```python
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """工具执行结果，最终写入 message_parts 表。"""

    # 主体内容：文本 Part 使用 str，结构化 Part 使用 dict
    content: str | dict

    # 附加元数据（不进向量记忆，只存结构化 DB）
    metadata: dict

    # Part 类型标识（对应 message_parts.part_type）
    part_type: str            # "tool_result" | "narrative" | "state_patch" | "roll_result" | ...

    # 错误信息（None 表示执行成功）
    error: str | None = None

    # 是否应触发记忆写入
    should_memorize: bool = True

    # 是否需要触发下一轮 LLM 推理（默认 True）
    needs_continuation: bool = True
```

---

### 1.3 ToolDef

工具的完整定义结构，注册时传入 `ToolRegistry`。

```python
from pydantic import BaseModel
from dataclasses import dataclass, field
from typing import Callable, Literal, Any, Awaitable


@dataclass
class ToolDef:
    """工具定义，描述一个可被 LLM 调用的原子操作。"""

    # 工具唯一标识（全局唯一，命名风格：snake_case）
    id: str

    # LLM 可见的描述（影响 LLM 工具选择质量，务必清晰）
    description: str

    # 参数 Schema（Pydantic BaseModel 子类）
    parameters: type[BaseModel]

    # 默认权限级别
    # allow  = 直接执行，无需询问
    # ask    = 执行前弹出权限确认（涉及写操作或外部调用）
    # deny   = 当前模式下禁用此工具
    default_permission: Literal["allow", "ask", "deny"]

    # 执行模式：parallel=可与其他工具并发执行，sequential=需独占执行
    execution_mode: Literal["parallel", "sequential"]

    # 执行前钩子列表：签名 async def hook(args: dict, ctx: ToolContext) -> dict
    # 返回值会合并回 args（可用于参数预处理/验证/注入）
    before_hooks: list[Callable] = field(default_factory=list)

    # 执行后钩子列表：签名 async def hook(result: ToolResult, ctx: ToolContext) -> ToolResult
    after_hooks: list[Callable] = field(default_factory=list)

    # 主执行函数：签名 async def execute(args: dict, ctx: ToolContext) -> ToolResult
    execute: Callable[[dict, "ToolContext"], Awaitable[ToolResult]] = None

    # 所属工具组（用于按 Agent 过滤）
    group: str = "general"    # "engine" | "narrative" | "character" | "economy" | "chapter" | "general"

    # 超时秒数（None = 使用全局默认 30s）
    timeout_seconds: float | None = None

    # 标签（用于权限矩阵覆盖和日志分类）
    tags: list[str] = field(default_factory=list)
```

---

### 1.4 AgentProfile

每个 Agent 实例携带的配置，决定哪些工具可用及权限覆盖。

```python
@dataclass
class AgentProfile:
    agent_name: str
    mode: Literal["play", "plan", "review"]
    # 工具组白名单（None 表示全部可用）
    allowed_groups: list[str] | None = None
    # 单工具权限覆盖：{"tool_id": "allow"/"ask"/"deny"}
    permission_overrides: dict[str, str] = field(default_factory=dict)
```

---

## 2. 工具执行链（完整流程）

### 2.1 流程总览

```
LLM 输出 tool_call JSON
        │
        ▼
[1] 参数解析与验证
    pydantic.model_validate(args) → 失败则返回 ToolResult(error=...)
        │
        ▼
[2] 权限检查
    获取有效权限 = permission_overrides.get(tool_id) ?? default_permission
    ├─ allow  → 直接进入 [3]
    ├─ ask    → 推送 permission.ask 事件 → 等待用户响应
    │           ├─ granted → 进入 [3]
    │           └─ denied  → 返回 ToolResult(error="用户拒绝授权")
    └─ deny   → 直接返回 ToolResult(error="当前模式禁用此工具")
        │
        ▼
[3] before_hooks（顺序执行）
    for hook in tool.before_hooks:
        args = await hook(args, ctx)
    任一 hook 抛出异常 → 中止，返回 ToolResult(error=hook_error)
        │
        ▼
[4] execute（带超时）
    result = await asyncio.wait_for(
        tool.execute(args, ctx),
        timeout=tool.timeout_seconds or GLOBAL_TIMEOUT
    )
        │
        ▼
[5] after_hooks（顺序执行）
    for hook in tool.after_hooks:
        result = await hook(result, ctx)
        │
        ▼
[6] DB 写入
    ├─ INSERT INTO message_parts (message_id, part_type, content, metadata)
    └─ 若 result.should_memorize: 触发 MemoryEngine.write()
        │
        ▼
[7] EventBus 发布
    await bus.publish(session_id, BusEvent(
        type="part.created",
        data={"part_type": result.part_type, "content": result.content, ...}
    ))
        │
        ▼
[8] 返回给 AgentRunner
    runner 将 ToolResult 追加到 conversation_history
    若 needs_continuation=True → 继续下一轮 LLM 推理
```

### 2.2 并发执行策略

当 LLM 在同一条消息中输出多个 `tool_call` 时：

```python
async def execute_tool_calls(tool_calls: list[dict], ctx: ToolContext) -> list[ToolResult]:
    # 按 execution_mode 分组
    parallel_calls = [tc for tc in tool_calls if registry.get(tc["id"]).execution_mode == "parallel"]
    sequential_calls = [tc for tc in tool_calls if registry.get(tc["id"]).execution_mode == "sequential"]

    results = []

    # 并行工具一起跑
    if parallel_calls:
        parallel_results = await asyncio.gather(
            *[execute_single(tc, ctx) for tc in parallel_calls],
            return_exceptions=True
        )
        results.extend(parallel_results)

    # 顺序工具按序执行
    for tc in sequential_calls:
        result = await execute_single(tc, ctx)
        results.append(result)

    return results
```

### 2.3 权限询问的 SSE 流程

```
AgentRunner                  EventBus             前端 SSEClient
    │                           │                      │
    │ publish(permission.ask)   │                      │
    ├──────────────────────────►│                      │
    │                           │ event: permission.ask│
    │                           ├─────────────────────►│
    │                           │                      │ 弹出确认对话框
    │                           │                      │ 用户点击 Allow
    │                           │ POST /permission/grant│
    │◄──────────────────────────┼──────────────────────┤
    │ ask_permission() 返回 True│                      │
    │                           │                      │
```

---

## 3. 内置工具完整清单

### 3.1 引擎工具（group="engine"）

#### `roll_check`

| 字段 | 值 |
|---|---|
| **id** | `roll_check` |
| **描述** | 执行技能/属性检定骰（d20/d100/自定义面数），返回骰点结果、成功等级、叙事描述 |
| **default_permission** | `allow` |
| **execution_mode** | `parallel` |
| **产出 Part 类型** | `roll_result` |

**参数 Schema**：

```python
class RollCheckParams(BaseModel):
    dice: str                        # 骰型，如 "1d20", "2d6", "1d100"
    attribute: str                   # 检定属性键，如 "STR", "DEX", "pilot_skill"
    difficulty: int                  # 难度值（目标数）
    modifier: int = 0                # 额外加减值
    advantage: bool = False          # True=取两骰高值
    disadvantage: bool = False       # True=取两骰低值
    reason: str                      # 骰子原因（记录到 metadata）
    character_id: str | None = None  # None=主角
```

**实现说明**：

1. 从 `ctx.state` 读取 `character_id` 对应角色的 `attribute` 当前值。
2. 调用 `random.randint` 生成骰点（服务端生成，保证可重现）。
3. 计算 `final = dice_result + attribute_value + modifier`，与 `difficulty` 比较。
4. 生成成功等级：`critical_success / success / failure / critical_failure`。
5. **骰点结果不进向量记忆**，直接以 `state_patch` 格式写入结构化 DB（见 §3.1 说明）。
6. 返回 `ToolResult(content=roll_detail_dict, part_type="roll_result", should_memorize=False)`。

---

#### `load_skill`

| 字段 | 值 |
|---|---|
| **id** | `load_skill` |
| **描述** | 从技能库加载指定技能的完整数据，供叙事工具或 LLM 后续推理使用 |
| **default_permission** | `allow` |
| **execution_mode** | `parallel` |
| **产出 Part 类型** | `tool_result` |

**参数 Schema**：

```python
class LoadSkillParams(BaseModel):
    skill_id: str           # 技能唯一键，如 "second_impact_impact_kick"
    include_payload: bool = True   # 是否包含完整 payload（默认 True）
```

**实现说明**：

1. 查询 `owned_items` 表，验证主角确实拥有此技能。
2. 从 `item_catalog` 表读取完整 `payload` JSON。
3. 将技能数据注入 `ctx.state.active_skills`，供当前对话轮次使用。
4. 返回技能完整描述，让 LLM 可以在后续叙事工具中引用具体效果。

---

#### `search_lore`

| 字段 | 值 |
|---|---|
| **id** | `search_lore` |
| **描述** | 在原著/世界设定知识库中执行混合召回，返回最相关的设定条目 |
| **default_permission** | `allow` |
| **execution_mode** | `parallel` |
| **产出 Part 类型** | `tool_result` |

**参数 Schema**：

```python
class SearchLoreParams(BaseModel):
    query: str              # 搜索查询文本
    world_key: str          # 世界键（如 "muv_luv_alternative"）
    top_k: int = 5          # 返回条目数
    content_types: list[str] = []  # 过滤类型，空=全部
```

**实现说明**：

1. 调用 `MemoryEngine.recall()` 但指定 `viewer_agent="world"`（客观全知视角）。
2. 向量相似度 + Bigram 混合召回（见文档 08）。
3. 返回去重后的设定条目列表，每条含 `title`、`content`、`relevance_score`。

---

### 3.2 叙事工具（group="narrative"）

#### `write_narrative`

| 字段 | 值 |
|---|---|
| **id** | `write_narrative` |
| **描述** | 输出一段叙事正文（场景描写、对话、动作等），这是最核心的叙事产出工具 |
| **default_permission** | `allow` |
| **execution_mode** | `sequential` |
| **产出 Part 类型** | `narrative` |

**参数 Schema**：

```python
class WriteNarrativeParams(BaseModel):
    content: str            # 叙事正文（Markdown 格式）
    scene_type: str         # 场景类型（对应文风规则）
    # "daily_grind" | "action" | "emotional" | "setup" | "exploration"
    # "montage" | "transition" | "prologue" | "epilogue"
    pov_character: str      # 叙事视角角色 ID
    word_count_target: int = 0    # 0=不限制
    chapter_id: str | None = None # 所属章节（None=当前章节）
```

**实现说明**：

1. 对 `content` 执行文风检查（禁词过滤，见 `03-writing-style.mdc`）。
2. 写入 `message_parts(part_type="narrative")`。
3. `should_memorize=True`，触发 MemoryEngine 写入（向量化并建图节点）。
4. 流式推送 `part.created` + 每个 token 的 `part.updated` 事件（差分渲染）。

---

#### `spawn_npc`

| 字段 | 值 |
|---|---|
| **id** | `spawn_npc` |
| **描述** | 在当前场景中引入一个 NPC，初始化其状态并建立对话连接 |
| **default_permission** | `ask` |
| **execution_mode** | `sequential` |
| **产出 Part 类型** | `state_patch` |

**参数 Schema**：

```python
class SpawnNPCParams(BaseModel):
    npc_key: str            # NPC 键（对应 npc_profiles 表）
    location: str           # 出场地点描述
    mood: str = "neutral"   # 初始情绪状态
    intent: str = ""        # NPC 当前意图（可选，供 npc agent 使用）
    is_hostile: bool = False
```

**实现说明**：

1. 从 `npc_profiles` 读取 NPC 完整档案（包括 `psyche_model_json`）。
2. 在 `ctx.state.active_npcs` 中注册此 NPC。
3. 推送 `state_patch`，前端更新场景面板中的 NPC 列表。
4. 权限为 `ask`：因为引入 NPC 会影响叙事走向，需 DM 确认（play 模式自动 allow）。

---

#### `generate_action_options`

| 字段 | 值 |
|---|---|
| **id** | `generate_action_options` |
| **描述** | 生成当前场景下主角可选行动列表（3-5 个选项），前端渲染为选择按钮 |
| **default_permission** | `allow` |
| **execution_mode** | `sequential` |
| **产出 Part 类型** | `action_options` |

**参数 Schema**：

```python
class GenerateActionOptionsParams(BaseModel):
    options: list[ActionOption]  # 选项列表
    context_summary: str         # 简短场景摘要（用于前端显示）
    expires_after_seconds: int = 300  # 选项过期时间

class ActionOption(BaseModel):
    id: str                      # 选项唯一 ID
    label: str                   # 显示文本（≤20字）
    description: str             # 详细描述（≤80字）
    risk_level: Literal["safe", "normal", "risky", "critical"]
    required_skill: str | None = None  # 前置技能（None=无需要求）
```

---

### 3.3 角色工具（group="character"）

> **⚠️ 工具名称对照表（设计稿 vs 实现）**
>
> 设计文档使用的工具名与 `builtin_tools.py` 中注册的实际名称存在差异：
>
> | 设计名称 | 实现名称 | 说明 |
> |---------|---------|------|
> | `query_character` | `read_character` + `query_character_summary` | 拆为完整读取（read_character）和摘要查询（query_character_summary）两个工具 |
> | `edit_character` | `update_character_state` | 重命名，参数格式改为 TavernCommand patches |
>
> 扩展开发者调用时请使用**实现名称**；以下文档中的设计名称仅供理解语义用。

#### `query_character`（实现名：`read_character` / `query_character_summary`）

| 字段 | 值 |
|---|---|
| **id（实现）** | `read_character`（完整）/ `query_character_summary`（摘要） |
| **描述** | `read_character`: 读取角色卡完整 JSON；`query_character_summary`: 返回简洁摘要（属性/心理/道具），适合 DM 快速决策 |
| **default_permission** | `allow` |
| **execution_mode** | `parallel` |
| **产出 Part 类型** | `tool_result` |

**参数 Schema（read_character）**：

```python
class QueryCharacterParams(BaseModel):
    character_id: str       # 角色 ID（"protagonist" 表示主角）
    fields: list[str] = []  # 空=返回全部字段
    # 可选字段："stats" | "inventory" | "skills" | "relationships" | "psyche" | "history"
```

---

#### `edit_character`（实现名：`update_character_state`）

| 字段 | 值 |
|---|---|
| **id** | `edit_character` |
| **描述** | 修改角色属性（HP、SP、属性值、情绪状态等），生成 state_patch |
| **default_permission** | `ask` |
| **execution_mode** | `sequential` |
| **产出 Part 类型** | `state_patch` |

**参数 Schema**：

```python
class EditCharacterParams(BaseModel):
    character_id: str
    patches: list[StatPatch]
    reason: str             # 变更原因（记录到审计日志）

class StatPatch(BaseModel):
    field: str              # 如 "HP", "DEX", "relationship.alice"
    op: Literal["set", "add", "sub", "mul"]
    value: float | str | bool
```

**实现说明**：

1. 验证 `patches` 不超出属性上下限。
2. 在事务中写入 `character_state_history`（可回滚）。
3. 更新 `ctx.state` 中对应角色的内存快照。
4. 生成 `state_patch` Part，前端更新角色面板数值。

---

#### `earn_reward`

| 字段 | 值 |
|---|---|
| **id** | `earn_reward` |
| **描述** | 给予主角奖励（经验、积分、物品、技能），触发抽卡/兑换流程 |
| **default_permission** | `ask` |
| **execution_mode** | `sequential` |
| **产出 Part 类型** | `reward_result` |

**参数 Schema**：

```python
class EarnRewardParams(BaseModel):
    reward_type: Literal["exp", "points", "item", "skill", "gacha"]
    amount: float | None = None     # exp / points 的数量
    item_key: str | None = None     # 直接发物品时的键
    gacha_pool: str | None = None   # 抽卡时的池名
    gacha_count: int = 1
    reason: str                     # 奖励来源描述
```

---

### 3.4 经济工具（group="economy"）

#### `open_shop`

| 字段 | 值 |
|---|---|
| **id** | `open_shop` |
| **描述** | 打开商店面板，展示当前可购买物品列表 |
| **default_permission** | `allow` |
| **execution_mode** | `sequential` |
| **产出 Part 类型** | `shop_catalog` |

**参数 Schema**：

```python
class OpenShopParams(BaseModel):
    shop_id: str            # 商店标识（如 "system_shop", "black_market"）
    filter_type: str = ""   # 过滤物品类型（空=全部）
    sort_by: Literal["price_asc", "price_desc", "tier_desc"] = "tier_desc"
```

---

#### `evaluate_item`

| 字段 | 值 |
|---|---|
| **id** | `evaluate_item` |
| **描述** | 对物品/能力执行三轮物理定星评估（见 `02-exchange-evaluation.mdc`） |
| **default_permission** | `allow` |
| **execution_mode** | `parallel` |
| **产出 Part 类型** | `evaluation_result` |

**参数 Schema**：

```python
class EvaluateItemParams(BaseModel):
    item_name: str          # 物品名称
    acg_source: str         # ACG 来源（如 "海贼王·六式·剃"）
    raw_tier: int           # 初始星级估计
    capability_count: int   # 功能维度数量（用于降级算法）
    hax_type: str = ""      # Hax 类型（空=无）
```

---

#### `purchase_item`

| 字段 | 值 |
|---|---|
| **id** | `purchase_item` |
| **描述** | 扣除积分，将物品/技能写入主角背包 |
| **default_permission** | `ask` |
| **execution_mode** | `sequential` |
| **产出 Part 类型** | `purchase_result` |

**参数 Schema**：

```python
class PurchaseItemParams(BaseModel):
    item_key: str           # 物品键
    quantity: int = 1
    price: int              # 本次购买价格（用于校验防止篡改）
    use_discount_code: str = ""
```

---

### 3.5 章节工具（group="chapter"）

#### `fork_chapter`

| 字段 | 值 |
|---|---|
| **id** | `fork_chapter` |
| **描述** | 创建当前章节的分支（用于多结局/存档点） |
| **default_permission** | `ask` |
| **execution_mode** | `sequential` |
| **产出 Part 类型** | `chapter_fork` |

**参数 Schema**：

```python
class ForkChapterParams(BaseModel):
    fork_name: str          # 分支名称（如 "好感线-A路线"）
    description: str        # 分支说明
    snapshot_state: bool = True   # 是否快照当前完整 state
```

---

#### `consolidate_chapter`

| 字段 | 值 |
|---|---|
| **id** | `consolidate_chapter` |
| **描述** | 执行章节固化：压缩当前章节记忆、生成摘要、更新 chapter_anchors |
| **default_permission** | `ask` |
| **execution_mode** | `sequential` |
| **产出 Part 类型** | `consolidation_result` |

**参数 Schema**：

```python
class ConsolidateChapterParams(BaseModel):
    chapter_id: str
    force: bool = False     # True=跳过"章节未完成"检查
    summary_length: int = 500  # 目标摘要字数
```

---

### 3.6 超出设计的扩展工具清单（第二十八轮补录）

> 以下工具均已在 `backend/tools/builtin_tools.py` 中注册，但原设计草案（§3.1–3.5）未涵盖。部分为设计工具的**改名实现**，部分为**正向扩展**。按 group 分类如下：

**⚠️ 设计名 → 实现名 映射（另见 §3.3 对照表）**：

| 设计名 | 实现名 | 说明 |
|---|---|---|
| `query_character` | `read_character` | 读取完整角色卡 JSON |
| `edit_character` | `update_character_state` | TavernCommand patches 格式更新 |
| `evaluate_item`（三轮定星） | `evaluate_item`（市价评估） | 设计与实现语义不同；设计版=定星算法；实现版=商品市价 |

**group="character"（角色相关）**：

| 工具名 | 说明 | permission |
|---|---|---|
| `query_character_summary` | 角色简洁摘要（身份/属性/心理/道具），适合 DM 快速决策 | `allow` |
| `check_skill_trigger` | 检查玩家行动是否触发技能特效，返回应激活技能列表 | `allow` |

**group="memory"（记忆相关）**：

| 工具名 | 说明 | permission |
|---|---|---|
| `search_memory` | 语义搜索会话记忆（混合向量+词法召回）| `allow` |
| `get_chapter_summaries` | 获取最近 N 个已固化章节摘要 | `allow` |
| `write_journal` | 写入 `tier=core` 的永久日志记忆节点 | `allow` |

**group="world"（世界状态）**：

| 工具名 | 说明 | permission |
|---|---|---|
| `get_world_state` | 获取当前会话 `state_json` 世界状态快照 | `allow` |
| `update_world_state` | TavernCommand patches 更新世界状态 | `allow` |
| `query_world_rules` | 查询世界档案中的硬性规则条目 | `allow` |

**group="npc"（NPC 管理）**：

| 工具名 | 说明 | permission |
|---|---|---|
| `spawn_npc` | 生成并持久化 NPC profile | `allow` |
| `edit_npc_state` | TavernCommand patches 修改 NPC profile_json | `allow` |
| `query_npc_profile` | 查询指定 NPC 完整档案 | `allow` |
| `get_npc_knowledge_scope` | 查询 NPC 知识边界（已知/不知道列表）| `allow` |
| `update_npc_state` | 更新 NPC 状态字段并写入世界档案 | `allow` |

**group="narrative"（叙事辅助）**：

| 工具名 | 说明 | permission |
|---|---|---|
| `generate_action_options` | 为玩家生成 3~4 个可选行动 (A/B/C) | `allow` |
| `earn_reward` | 给角色 inventory 添加道具并写入日志记忆 | `allow` |
| `write_narrative` | 将文本作为 `narrative` Part 直接注入消息流 | `allow` |
| `style_check` | 文风纯净度检查（程序化，无 LLM 调用），返回 score 和 warnings | `allow` |
| `purity_check` | 对会话最新 narrative Part 执行文风检查（review 模式专用）| `allow` |

**group="chapter"（章节操作，含设计草案已有工具的实现差异）**：

| 工具名 | 说明 | permission | 备注 |
|---|---|---|---|
| `read_chapter` | 读取最近 N 章摘要和关键事件 | `allow` | review/plan 模式专用 |
| `outline_chapter` | 为下一章节生成 N 个故事节拍大纲（不写叙事）| `allow` | plan 模式专用 |
| `fork_chapter` | 创建分支章节（实现参数与设计不同，见实现）| `ask` | §3.5 已有设计，但 schema 已变 |
| `consolidate_chapter` | 触发章节记忆固化（实现参数与设计不同）| `allow` | §3.5 已有设计，但 schema 已变 |

**group="dice"（骰子）**：

| 工具名 | 说明 | permission |
|---|---|---|
| `roll_dice` | 原始 d10 骰池判定（无角色卡依赖，直接传 pool/threshold）| `allow` |

**group="economy"（经济）**：

| 工具名 | 说明 | permission |
|---|---|---|
| `open_shop` | 为场景生成商店货架（shop_type: weapon/potion/misc）| `allow` |
| `evaluate_item` | 评估物品市价（价格区间，单位：铜/银/金币）| `allow` |
| `purchase_item` | 执行购买（扣金币 + 写 inventory）| `allow` |

**group="combat"（战斗）**：

| 工具名 | 说明 | permission |
|---|---|---|
| `apply_damage` | 对角色指定部位施加伤害，返回减免后实际伤害和新增状态 | `allow` |
| `apply_heal` | 治疗指定部位，可移除状态效果 | `allow` |
| `get_combat_status` | 获取战斗状态摘要（各部位 HP + 状态效果）| `allow` |
| `roll_hit_location` | 随机生成命中部位（bias: upper/lower/head/none）| `allow` |

---

## 4. MCP 工具桥接

### 4.1 MCPToolBridge 类

将远程 MCP 服务器提供的工具自动转换为本地 `ToolDef`，使 LLM 无需感知工具来源。

```python
import httpx
import json
from typing import Any
from zero_arsenal.tools.base import ToolDef, ToolResult, ToolContext
from pydantic import create_model


class MCPToolBridge:
    """
    将 MCP 服务器的工具自动适配为本地 ToolDef。

    MCP 工具规范参考：https://spec.modelcontextprotocol.io/specification/server/tools/
    """

    def __init__(self, mcp_server_url: str, auth_token: str | None = None):
        self.mcp_server_url = mcp_server_url.rstrip("/")
        self.auth_token = auth_token
        self._http = httpx.AsyncClient(
            base_url=self.mcp_server_url,
            headers={"Authorization": f"Bearer {auth_token}"} if auth_token else {},
            timeout=30.0,
        )

    async def fetch_tool_list(self) -> list[dict]:
        """从 MCP 服务器获取工具列表（tools/list）。"""
        response = await self._http.post("/tools/list", json={})
        response.raise_for_status()
        return response.json().get("tools", [])

    def _jsonschema_to_pydantic(self, schema: dict, tool_id: str) -> type:
        """将 JSON Schema 转换为 Pydantic 模型（简化版，覆盖常用类型）。"""
        from pydantic import Field

        fields = {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        type_map = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        for prop_name, prop_schema in properties.items():
            python_type = type_map.get(prop_schema.get("type", "string"), Any)
            default = ... if prop_name in required else prop_schema.get("default", None)
            description = prop_schema.get("description", "")
            fields[prop_name] = (python_type, Field(default, description=description))

        model_name = f"MCPParams_{tool_id.replace('.', '_')}"
        return create_model(model_name, **fields)

    def _build_execute_fn(self, mcp_tool_name: str):
        """为指定 MCP 工具名创建异步执行函数。"""

        async def execute(args: dict, ctx: ToolContext) -> ToolResult:
            # 检查中止信号
            if ctx.abort_signal and ctx.abort_signal.is_set():
                return ToolResult(
                    content="",
                    metadata={},
                    part_type="tool_result",
                    error="操作已中止",
                )

            try:
                response = await self._http.post(
                    "/tools/call",
                    json={
                        "name": mcp_tool_name,
                        "arguments": args,
                    },
                )
                response.raise_for_status()
                data = response.json()

                # MCP 返回格式：{"content": [{"type": "text", "text": "..."}], "isError": false}
                is_error = data.get("isError", False)
                content_parts = data.get("content", [])

                # 提取文本内容
                text_content = "\n".join(
                    part.get("text", "") for part in content_parts if part.get("type") == "text"
                )

                return ToolResult(
                    content=text_content,
                    metadata={
                        "mcp_tool": mcp_tool_name,
                        "mcp_server": self.mcp_server_url,
                        "raw_response": data,
                    },
                    part_type="tool_result",
                    error=text_content if is_error else None,
                )

            except httpx.HTTPError as e:
                return ToolResult(
                    content="",
                    metadata={"mcp_tool": mcp_tool_name},
                    part_type="tool_result",
                    error=f"MCP 调用失败: {e}",
                )

        return execute

    async def get_tool_defs(self) -> list[ToolDef]:
        """
        拉取 MCP 工具列表并转换为 ToolDef 列表。

        调用示例：
            bridge = MCPToolBridge("http://localhost:8765", token)
            tools = await bridge.get_tool_defs()
            for tool in tools:
                registry.register(tool)
        """
        raw_tools = await self.fetch_tool_list()
        tool_defs = []

        for raw in raw_tools:
            tool_id = f"mcp.{raw['name']}"
            params_model = self._jsonschema_to_pydantic(
                raw.get("inputSchema", {}), raw["name"]
            )

            tool_def = ToolDef(
                id=tool_id,
                description=raw.get("description", f"MCP 工具: {raw['name']}"),
                parameters=params_model,
                default_permission="ask",   # MCP 工具默认需要询问（外部调用）
                execution_mode="sequential",
                execute=self._build_execute_fn(raw["name"]),
                group="mcp",
                tags=["mcp", "external"],
            )
            tool_defs.append(tool_def)

        return tool_defs

    async def close(self):
        await self._http.aclose()
```

### 4.2 MCP 工具注册流程

```python
# 启动时注册 MCP 工具
async def setup_mcp_tools(registry: "ToolRegistry"):
    # 注册多个 MCP 服务器
    mcp_servers = [
        ("http://localhost:8765", None),        # novel_system MCP
        ("http://localhost:8766", "token_xxx"), # 外部 wiki MCP
    ]

    for url, token in mcp_servers:
        bridge = MCPToolBridge(url, token)
        try:
            tool_defs = await bridge.get_tool_defs()
            for tool_def in tool_defs:
                registry.register(tool_def)
            print(f"已从 {url} 注册 {len(tool_defs)} 个 MCP 工具")
        except Exception as e:
            print(f"MCP 服务器 {url} 连接失败: {e}，跳过")
        # 注意：bridge 应在应用关闭时 close()
```

---

## 5. 工具权限矩阵

| 工具 ID | play 模式 | plan 模式 | review 模式 | 说明 |
|---|---|---|---|---|
| `roll_check` | allow | allow | deny | review 模式禁止掷骰（只读） |
| `load_skill` | allow | allow | allow | 纯读取，全模式允许 |
| `search_lore` | allow | allow | allow | 纯读取，全模式允许 |
| `write_narrative` | allow | ask | deny | plan 模式需确认，review 禁止写入 |
| `spawn_npc` | allow | ask | deny | play 模式 DM 可直接引入 NPC |
| `generate_action_options` | allow | allow | deny | review 模式禁止生成选项 |
| `query_character` | allow | allow | allow | 纯读取，全模式允许 |
| `edit_character` | ask | ask | deny | 属性修改始终需确认 |
| `earn_reward` | ask | ask | deny | 奖励发放始终需确认 |
| `open_shop` | allow | allow | deny | review 模式禁止商店 |
| `evaluate_item` | allow | allow | allow | 纯评估，不修改状态 |
| `purchase_item` | ask | ask | deny | 消费积分始终需确认 |
| `fork_chapter` | ask | allow | deny | plan 模式可自由分支 |
| `consolidate_chapter` | ask | ask | deny | 固化操作始终需确认 |
| `mcp.*` | ask | ask | deny | 所有 MCP 工具默认 ask |

**权限优先级规则**：

1. `AgentProfile.permission_overrides` 的单工具覆盖 > 模式全局设置 > `ToolDef.default_permission`
2. `deny` 是最高优先级，无法被覆盖为 `allow`（安全底线）

---

## 6. ToolRegistry 类

```python
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zero_arsenal.core.agent_profile import AgentProfile

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    全局工具注册表，管理所有 ToolDef 的生命周期与执行。

    使用单例模式，通过 get_registry() 获取全局实例。
    """

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}
        self._global_timeout: float = 30.0

    # ─── 注册 ─────────────────────────────────────────────

    def register(self, tool: ToolDef) -> None:
        """注册一个工具。重复 ID 会覆盖（热重载 MCP 工具时使用）。"""
        if tool.id in self._tools:
            logger.warning("工具 %s 已存在，将被覆盖", tool.id)
        self._tools[tool.id] = tool
        logger.debug("已注册工具: %s [group=%s]", tool.id, tool.group)

    def unregister(self, tool_id: str) -> None:
        """注销工具（MCP 服务器断开时调用）。"""
        self._tools.pop(tool_id, None)

    def get(self, tool_id: str) -> ToolDef | None:
        return self._tools.get(tool_id)

    # ─── 按 Agent 过滤 ────────────────────────────────────

    def get_tools_for_agent(self, agent: str, profile: "AgentProfile") -> list[ToolDef]:
        """
        返回指定 Agent 在当前 profile 下可用的工具列表。

        - 根据 allowed_groups 过滤工具组
        - 排除有效权限为 "deny" 的工具
        """
        result = []
        for tool in self._tools.values():
            # 工具组过滤
            if profile.allowed_groups and tool.group not in profile.allowed_groups:
                continue

            # 计算有效权限
            effective_perm = self._get_effective_permission(tool, profile)
            if effective_perm == "deny":
                continue

            result.append(tool)
        return result

    def _get_effective_permission(self, tool: ToolDef, profile: "AgentProfile") -> str:
        """计算工具在指定 profile 下的有效权限。"""
        # 单工具覆盖最高优先级
        if tool.id in profile.permission_overrides:
            return profile.permission_overrides[tool.id]

        # 模式全局规则
        mode_rules = {
            "play": {},      # 使用 ToolDef.default_permission
            "plan": {        # plan 模式：write 类工具升级为 ask
                "write_narrative": "ask",
                "spawn_npc": "ask",
                "edit_character": "ask",
                "earn_reward": "ask",
                "purchase_item": "ask",
                "fork_chapter": "allow",
            },
            "review": {      # review 模式：所有写入类工具 deny
                "write_narrative": "deny",
                "spawn_npc": "deny",
                "generate_action_options": "deny",
                "edit_character": "deny",
                "earn_reward": "deny",
                "open_shop": "deny",
                "purchase_item": "deny",
                "fork_chapter": "deny",
                "consolidate_chapter": "deny",
                "roll_check": "deny",
            },
        }

        mode_override = mode_rules.get(profile.mode, {}).get(tool.id)
        if mode_override:
            return mode_override

        return tool.default_permission

    # ─── LLM Schema 序列化 ────────────────────────────────

    def to_llm_schema(self, tools: list[ToolDef]) -> list[dict]:
        """
        将 ToolDef 列表序列化为 OpenAI 兼容的 JSON Schema 工具列表。

        返回格式：
        [
            {
                "type": "function",
                "function": {
                    "name": "tool_id",
                    "description": "...",
                    "parameters": { JSON Schema }
                }
            },
            ...
        ]
        """
        result = []
        for tool in tools:
            schema = tool.parameters.model_json_schema()
            # 清理 Pydantic 在 schema 中注入的 $defs（LLM 通常不需要）
            schema.pop("$defs", None)
            schema.pop("title", None)

            result.append({
                "type": "function",
                "function": {
                    "name": tool.id,
                    "description": tool.description,
                    "parameters": schema,
                },
            })
        return result

    # ─── 执行 ─────────────────────────────────────────────

    async def execute(
        self,
        tool_id: str,
        args: dict,
        ctx: ToolContext,
        profile: "AgentProfile | None" = None,
    ) -> ToolResult:
        """
        执行工具的完整链路（权限检查 → hooks → execute → hooks → DB/Bus）。
        """
        tool = self._tools.get(tool_id)
        if not tool:
            return ToolResult(
                content="",
                metadata={"tool_id": tool_id},
                part_type="tool_result",
                error=f"未知工具: {tool_id}",
            )

        # [1] 参数验证
        try:
            validated_args = tool.parameters.model_validate(args).model_dump()
        except Exception as e:
            return ToolResult(
                content="",
                metadata={"tool_id": tool_id, "raw_args": args},
                part_type="tool_result",
                error=f"参数验证失败: {e}",
            )

        # [2] 权限检查
        if profile:
            effective_perm = self._get_effective_permission(tool, profile)
        else:
            effective_perm = tool.default_permission

        if effective_perm == "deny":
            return ToolResult(
                content="",
                metadata={"tool_id": tool_id},
                part_type="tool_result",
                error="当前模式禁用此工具",
            )

        if effective_perm == "ask":
            granted = await ctx.ask_permission(
                tool_id,
                f"Agent {ctx.agent_name} 请求执行工具 {tool_id}",
                validated_args,
            )
            if not granted:
                return ToolResult(
                    content="",
                    metadata={"tool_id": tool_id},
                    part_type="tool_result",
                    error="用户拒绝授权",
                )

        # [3] before_hooks
        for hook in tool.before_hooks:
            try:
                validated_args = await hook(validated_args, ctx)
            except Exception as e:
                logger.error("before_hook 执行失败 [tool=%s]: %s", tool_id, e)
                return ToolResult(
                    content="",
                    metadata={"tool_id": tool_id},
                    part_type="tool_result",
                    error=f"前置钩子失败: {e}",
                )

        # [4] execute（带超时）
        timeout = tool.timeout_seconds or self._global_timeout
        try:
            result = await asyncio.wait_for(
                tool.execute(validated_args, ctx),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                content="",
                metadata={"tool_id": tool_id},
                part_type="tool_result",
                error=f"工具执行超时（{timeout}s）",
            )
        except Exception as e:
            logger.exception("工具执行异常 [tool=%s]", tool_id)
            return ToolResult(
                content="",
                metadata={"tool_id": tool_id},
                part_type="tool_result",
                error=f"工具执行异常: {e}",
            )

        # [5] after_hooks
        for hook in tool.after_hooks:
            try:
                result = await hook(result, ctx)
            except Exception as e:
                logger.error("after_hook 执行失败 [tool=%s]: %s", tool_id, e)
                # after_hook 失败不中止，但记录错误
                result.metadata["after_hook_error"] = str(e)

        # [6] DB 写入（由调用方 AgentRunner 统一处理，Registry 不直接访问 DB）
        # [7] EventBus 发布（同上）
        # 返回结果，由 AgentRunner 完成持久化和 SSE 推送

        return result


# ─── 全局单例 ─────────────────────────────────────────────

_registry_instance: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ToolRegistry()
    return _registry_instance
```

---

## 7. 错误处理与超时策略

### 7.1 错误分级

| 错误类型 | 处理策略 | 是否重试 |
|---|---|---|
| 参数验证失败 | 直接返回错误给 LLM，让 LLM 修正参数 | 否 |
| 权限拒绝 | 返回错误，停止当前工具调用链 | 否 |
| before_hook 失败 | 中止执行，返回错误 | 否 |
| 执行超时 | 返回超时错误，记录到日志 | 可选（最多1次） |
| 执行异常 | 记录完整 traceback，返回错误摘要 | 否 |
| after_hook 失败 | 记录到 metadata，不中止 | 否 |
| MCP 网络错误 | 返回错误，标记 MCP 服务不可用 | 是（最多3次，指数退避） |

### 7.2 全局超时配置

```python
GLOBAL_TOOL_TIMEOUT = 30.0          # 默认超时
LONG_RUNNING_TIMEOUT = 120.0        # 耗时工具（如 consolidate_chapter）
MCP_CALL_TIMEOUT = 15.0             # MCP 调用超时
PERMISSION_ASK_TIMEOUT = 300.0      # 等待用户确认超时（5分钟）
```

---

## 8. 测试策略

### 8.1 单元测试框架

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_roll_check_tool():
    """验证骰子工具不进向量记忆且返回 roll_result Part。"""
    registry = ToolRegistry()
    # 注册 roll_check 工具
    from zero_arsenal.tools.engine import create_roll_check_tool
    registry.register(create_roll_check_tool())

    ctx = ToolContext(
        session_id="test-session",
        message_id="msg-001",
        turn_id="turn-001",
        agent_name="dm",
        state=MagicMock(),
        bus=AsyncMock(),
        ask_permission=AsyncMock(return_value=True),
        abort_signal=MagicMock(is_set=MagicMock(return_value=False)),
    )

    result = await registry.execute(
        "roll_check",
        {"dice": "1d20", "attribute": "STR", "difficulty": 15, "reason": "测试"},
        ctx,
    )

    assert result.error is None
    assert result.part_type == "roll_result"
    assert result.should_memorize is False     # 骰点结果不进向量记忆
```

### 8.2 集成测试要点

- 验证 `sequential` 工具在并发场景下确实顺序执行（使用锁检查）
- 验证 `permission.ask` 事件通过 SSE 正确到达前端
- 验证 MCP 桥接在服务器不可用时优雅降级
- 验证 `review` 模式下所有写入工具均返回 `deny` 错误

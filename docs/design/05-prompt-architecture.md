# 提示词架构完整设计文档

**文档版本**：v1.1（2026-06 对齐实现）  
**创建日期**：2026-05-31  
**归属系统**：zero-arsenal / AI-VN 互动叙事引擎  

> 注：本文档已于 2026-06 对齐实现（D0 以代码为准）。Layer4 BackendDataStream（18 轴）逐字落地、Registry 字段/过滤/runtime/审计核心机制齐备、Layer0 Core HARD-GATE 内容完整；下列 priority 区间/字段/相位枚举按实现修正（本文档 §2.1 已建立「差异对照」惯例，此处延伸覆盖）。
>
> **实现对齐总览（2026-06，`backend/prompts/` + `backend/engine/`）**
> - **priority 区间**：实现实际区间为 **core 0–29 / agent 100–199 / world 200–299 / runtime 400+**（`registry.py`），统一以此为准；§3 各层小节仍写的旧区间（0-9/10-19/20-49/50-79/80-99）已作废，按差异表口径理解。
> - **§2.1b token_estimate**：Fragment **无 `token_estimate` 字段**，裁剪改为运行时对 `content` 现场估算（`TokenBudget.estimate_tokens`）。
> - **§2.2 AgentState**：实现**无 `AgentState` 数据类**，condition 求值直接接收普通 `dict`（约定 `state[...]` 访问）。
> - **§4.1 相位枚举**：实现相位混用 agent 名与阶段名（`dm/rules/style/narrator` + `p1/p3/p4`），`VALID_PHASES=("all","p1","p2","p3","p4","dm")`；设计的「P1=DM 单一规划阶段」实际拆为 rules/dm/p1 多节点。
> - **§3.2/§3.3 机制**：Agent 片段用 `phase` 区分（非 `agent_filter` + trigger=always）；WorldPlugin 接口名为 `get_rules_skills()`（非 `get_rules_fragments()`），规则经 `system_prompt_fragments` 注入，WorldPlugin 为 `@dataclass`（非 ABC）。
> - **§5.3 组装主路径**：主链路走 `build_system_prompt()`（str）+ `assemble_with_data_stream()`（system+user 两条消息），`registry.build()`（按 inject_as 分组）近乎死代码；prefix/standalone/append 组合未落地。
> - **§3.5b 文风层**：作为 Skill（`SkillMeta`）经 `on_demand` 注入（非独立 Registry 层 / trigger=always），无 `agent_filter`。
>
> 🔴 **待修复缺陷 / 真缺口（非文档滞后，登记于 `docs/review/fix_report_docs.md`）**
> 1. **§2.3 condition AST 白名单沙箱未实现**：`registry.py`/`skill_loader.py` 为裸 `eval(__builtins__={})`，无 `_ALLOWED_AST_NODES`，存在表达式注入风险。
> 2. **§5.1/§5.2 SKILL.md 格式严重简化**：解析器键为 `name`（非 `id`），缺 `id/role/source/version/requires/conflicts/tags`；正文五节结构（决策图/铁律/执行流程/集成/禁词）无任何文件遵循。
> 3. **§3.4 设计预置 8 个 Skill 目录不存在**，`backend/skills/` 无任何 SKILL.md（实际技能在 `extensions/*/skills/`）。

---

## 目录

1. [设计背景与参考](#1-设计背景与参考)
2. [PromptFragment Registry](#2-promptfragment-registry)
3. [五层提示词架构](#3-五层提示词架构)
4. [Phase 过滤详解](#4-phase-过滤详解)
5. [SKILL.md 完整格式规范](#5-skillmd-完整格式规范)
6. [Backend Data Stream 格式](#6-backend-data-stream-格式)
7. [Token 预算分配](#7-token-预算分配)
8. [提示词版本管理](#8-提示词版本管理)

---

## 1. 设计背景与参考

本架构综合参考了六个已有系统的核心设计思路，取其精华，形成统一的分层注入体系。

### 1.1 参考系统概述

#### ai-vn-game-system
- **机制**：SillyTavern preset 配合 worldbook 分 phase 注入
- **Phase 分段**：P1（规划）/ P3（叙事）/ P4（变量结算）三个关键阶段，不同片段仅在对应 Phase 可见
- **学到的**：Phase 隔离防止叙事上下文污染规划逻辑；37 个文风 `.md` 文件按需激活而非全量注入
- **问题**：worldbook 管理分散，优先级冲突难以调试

#### MoRanJiangHu
- **机制**：132 个 TypeScript 提示词模块 + `systemPromptBuilder` 1800+ 行 + 功能开关系统
- **学到的**：模块化程度极高，功能开关（feature flags）可动态启用/禁用单个规则块
- **问题**：TypeScript 强类型导致修改需要重新编译；builder 函数过于中心化，难以热更新
- **本系统采用**：Python dataclass + YAML frontmatter 替代 TS 类型，保留功能开关概念

#### pi（Anthropic 官方 agentic IDE）
- **机制**：`SKILL.md` frontmatter + XML 目录注入 + `read` 工具加载全文
- **学到的**：Skill 不在会话开始时全量注入，而是通过工具按需加载；frontmatter 驱动元数据（触发条件、优先级）
- **本系统采用**：完全照搬 SKILL.md 格式规范，作为 Layer 3 的基础单元

#### opencode（Sourcegraph 开源工具）
- **机制**：skill 工具按需加载；system/user 消息严格分开注入
- **学到的**：system 消息只放不变的角色定义，动态内容通过 user 消息注入，避免 system 消息冗余
- **本系统采用**：Layer 0-2 注入为 system，Layer 3-5 注入为 user 消息前缀

#### cursor（Cursor IDE 规则系统）
- **机制**：`alwaysApply` / `autoApply` / `agentRequestable` 三级规则，`.cursor/rules/*.mdc`
- **学到的**：三级触发机制比单一"总是注入"更节省 token；`alwaysApply` 对应最核心的约束
- **本系统采用**：`trigger: "always" | "auto" | "on_demand"` 字段复刻三级机制

#### superpowers（社区扩展）
- **机制**：`SKILL.md` 决策图（Mermaid）+ `HARD-GATE` 强制检查点 + **user 消息前缀注入**（非 system）
- **关键发现**：避免在同一对话中出现多个 system 消息（部分模型对多 system 支持差）；将动态规则注入为 user 消息首行可规避此限制
- **本系统采用**：Layer 3/4/5 的 `inject_as: "user"` 设计源于此

### 1.2 设计目标

| 目标 | 实现方式 |
|------|----------|
| **Token 效率** | 按 Phase 过滤 + 按需加载，避免全量注入 |
| **热更新** | 提示词以 `.md` 文件存储，不改代码即可修改 |
| **可审计** | 每次组装结果写入 `prompt_log.jsonl`，可回放 |
| **多 Agent 隔离** | `agent_filter` 字段确保内容只注入指定 Agent |
| **规则防冲突** | `priority` + Phase 过滤 + condition 求值，有明确解析顺序 |

---

## 2. PromptFragment Registry

### 2.1 PromptFragment Dataclass

> **⚠️ 设计草案 vs 实现差异对照**（`backend/prompts/registry.py`）：
>
> | 设计草案字段名 | 实现字段名 | 差异说明 |
> |--------------|------------|---------|
> | `phases` | `phase` | 单数形式；实现为 `list[str]`，无 Literal 类型约束 |
> | `role: "system"\|"user"` | `inject_as: str = "system"` | 语义合并：实现用 `inject_as` 承担"注入为 system 还是 user 消息"的职责 |
> | `inject_as: "prefix"\|"standalone"\|"append"` | （无对应字段） | 组合方式字段在实现中未独立拆出；`inject_as` 已用于 system/user 切换 |
> | `source: str` | （无显式字段） | 来源由 `id` 前缀约定推断（如 `core.xxx` → source=core） |
> | Layer 0(0-9)..Layer 5(100+) | core(0-99)/agent(100-199)/world(200-299)/skill(300-399)/runtime(400+) | 层级数量从 6 层压缩为 5 层，优先级区间重新划分 |
> | `content: str \| Callable` | `content: str` | 实现仅支持静态字符串；动态内容通过 `register_runtime()` 注入 |
>
> 编写扩展片段时请以**实现字段名**为准。

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Literal


@dataclass
class PromptFragment:
    """
    单个提示词片段的完整描述。

    所有 Fragment 注册到 PromptFragmentRegistry，由其负责
    过滤、排序、条件求值、最终组装成 LLM 消息列表。

    实现字段名：phase（非 phases）、inject_as（system/user，非 prefix/standalone/append）
    实现层级：core/agent/world/skill/runtime（5 层，优先级区间见实现注释）
    """

    id: str
    """唯一标识符，格式：<source>.<category>.<name>，如 core.format.json_output"""

    content: str | Callable[["AgentState"], str]
    """
    静态字符串，或接受 AgentState 返回字符串的动态函数。
    动态函数在每次 build() 调用时执行，用于运行时数据注入。
    实现中 content 仅支持 str；动态数据通过 register_runtime() 添加 runtime 层片段。
    """

    phases: list[Literal["p1", "p3", "p4"]] | Literal["all"]
    """
    该 Fragment 在哪些 Phase 可见。（实现字段名：phase，list[str]）
    - "p1": 规划/工具调用阶段（DM Agent）
    - "p3": 叙事生成阶段（Narrator Agent）
    - "p4": 变量结算阶段（Calibrator Agent）
    - "all": 所有阶段均可见
    """

    trigger: Literal["always", "auto", "on_demand"]
    """
    触发机制（仿 cursor 三级规则）：
    - "always"   : 始终注入，对应 cursor alwaysApply
    - "auto"     : 满足 condition 时自动注入，对应 cursor autoApply
    - "on_demand": 需要 Agent 显式调用 load_skill 工具，对应 cursor agentRequestable
    """

    condition: str | None = None
    """
    Python 表达式字符串，对 AgentState 的 dict 表示求值，结果为 bool。
    仅在 trigger="auto" 时生效。
    示例：'state["combat"]["active"] == True'
    """

    priority: int = 100
    """
    注入优先级，越小越靠前（仿 SillyTavern worldbook insertion_order）。
    草案：Layer 0(0-9), Layer 1(10-19), Layer 2(20-49), Layer 3(50-79), Layer 4(80-99), Layer 5(100+)。
    实现：core(0-99), agent(100-199), world(200-299), skill(300-399), runtime(400+)。
    """

    role: Literal["system", "user"] = "system"
    """
    注入为哪种消息角色。（实现字段名：inject_as，值 "system"|"user"）
    Layer 0-2 默认 "system"，Layer 3-5 默认 "user"（规避多 system 问题）。
    """

    depth: int = 0
    """
    注入到历史消息的哪个位置（距最新消息的轮数）。
    0 = 最新（追加到末尾）；n = 插入到倒数第 n 轮之前。
    仿 SillyTavern worldbook position 概念。
    """

    source: str = "core"
    """
    来源扩展 ID，如 'core' / 'crossover' / 'wuxia' / 'infinite_arsenal'。
    实现中无此字段，由 id 前缀约定推断。
    """

    agent_filter: list[str] | None = None
    """
    仅对列表中的 Agent 注入（通过 Agent.id 匹配）。
    None = 对所有 Agent 可见。
    示例：["dm_agent", "narrator_agent"]
    实现字段名同：agent_filter: list[str]（空列表=全匹配）。
    """

    inject_as: Literal["prefix", "standalone", "append"] = "standalone"
    """
    在同 role 消息中的组合方式（草案字段；实现中 inject_as 已被 system/user 语义占用）：
    - "prefix"    : 拼接在该 role 的首条消息开头
    - "standalone": 作为独立的一条消息
    - "append"    : 拼接在该 role 的最后一条消息末尾
    """

    enabled: bool = True
    """功能开关（仿 MoRanJiangHu feature flags），False 时跳过注入"""

    token_estimate: int = 0
    """预估 token 数，用于预算控制。0 表示未估算。"""
```

### 2.2 AgentState 结构（供 condition 求值）

```python
@dataclass
class AgentState:
    """
    传入 PromptFragment.condition 和动态 content 函数的运行时状态。
    作为 dict 快照传入，避免循环引用。
    """

    session_id: str
    agent_id: str
    phase: Literal["p1", "p3", "p4"]

    # 角色卡核心字段（来自 character card v4）
    character: dict  # 完整角色卡 JSON
    hp_ratio: float  # 当前HP / 最大HP，方便 condition 快速访问
    energy_ratio: float

    # 世界状态
    world: dict       # 世界档案快照
    location: str
    world_time: str   # "1998-04-15 14:30"

    # 战斗状态
    combat: dict      # {"active": bool, "round": int, "enemies": [...]}

    # 记忆召回结果（已在 P2 RAG 阶段获取）
    recalled_memories: list[dict]

    # NPC 快照
    active_npcs: list[dict]

    # 会话配置
    active_skills: list[str]   # 已加载的 skill ID 列表
    writing_style: list[str]   # 激活的文风文件名列表
    enabled_plugins: list[str] # 激活的 WorldPlugin 列表

    def to_dict(self) -> dict:
        """序列化为 condition 求值用的字典"""
        import dataclasses
        return dataclasses.asdict(self)
```

### 2.3 PromptFragmentRegistry 类

```python
import re
import ast
import logging
from collections import defaultdict
from typing import Iterator

logger = logging.getLogger(__name__)


class PromptFragmentRegistry:
    """
    所有 PromptFragment 的中央注册表。

    职责：
    1. 注册与去重（同 ID 覆盖，source 更新时记录变更）
    2. 按 Phase 过滤
    3. 按 Agent 过滤
    4. condition 求值（沙箱 eval，白名单 AST 检查）
    5. 按 priority 排序
    6. Token 预算控制
    7. 组装最终 LLM 消息列表
    """

    # condition 表达式允许使用的 AST 节点白名单
    _ALLOWED_AST_NODES = (
        ast.Expression, ast.BoolOp, ast.Compare, ast.BinOp,
        ast.UnaryOp, ast.Constant, ast.Name, ast.Attribute,
        ast.Subscript, ast.Index, ast.And, ast.Or, ast.Not,
        ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        ast.In, ast.NotIn, ast.Is, ast.IsNot, ast.Load,
    )

    def __init__(self, token_budget: int = 8000):
        self._fragments: dict[str, PromptFragment] = {}
        self._token_budget = token_budget

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(self, fragment: PromptFragment) -> None:
        """注册单个 Fragment。同 ID 后注册覆盖前者。"""
        if fragment.id in self._fragments:
            logger.debug("覆盖已有 Fragment: %s (来自 %s)", fragment.id, fragment.source)
        self._fragments[fragment.id] = fragment

    def register_many(self, fragments: list[PromptFragment]) -> None:
        for f in fragments:
            self.register(f)

    def unregister(self, fragment_id: str) -> None:
        self._fragments.pop(fragment_id, None)

    def set_enabled(self, fragment_id: str, enabled: bool) -> None:
        """功能开关：动态启用/禁用某个 Fragment"""
        if fragment_id in self._fragments:
            self._fragments[fragment_id].enabled = enabled

    # ------------------------------------------------------------------
    # 过滤流水线
    # ------------------------------------------------------------------

    def _iter_candidates(
        self,
        phase: Literal["p1", "p3", "p4"],
        agent_id: str,
        state: AgentState,
    ) -> Iterator[PromptFragment]:
        """按顺序过滤，返回候选 Fragment 的迭代器"""

        for frag in sorted(self._fragments.values(), key=lambda f: f.priority):
            # 1. 功能开关
            if not frag.enabled:
                continue

            # 2. Phase 过滤
            if frag.phases != "all" and phase not in frag.phases:
                continue

            # 3. Agent 过滤
            if frag.agent_filter is not None and agent_id not in frag.agent_filter:
                continue

            # 4. trigger 过滤
            if frag.trigger == "on_demand":
                if frag.id not in state.active_skills:
                    continue
            elif frag.trigger == "auto":
                if not self._eval_condition(frag, state):
                    continue
            # trigger == "always" → 无需检查 condition

            yield frag

    def _eval_condition(self, frag: PromptFragment, state: AgentState) -> bool:
        """
        在受限沙箱中对 condition 表达式求值。
        仅允许白名单 AST 节点，防止任意代码执行。
        """
        if frag.condition is None:
            return True

        try:
            tree = ast.parse(frag.condition, mode='eval')
            for node in ast.walk(tree):
                if not isinstance(node, self._ALLOWED_AST_NODES):
                    logger.warning(
                        "Fragment %s 的 condition 含不允许的 AST 节点 %s，跳过",
                        frag.id, type(node).__name__
                    )
                    return False

            result = eval(  # noqa: S307
                compile(tree, "<condition>", "eval"),
                {"__builtins__": {}},
                state.to_dict(),
            )
            return bool(result)

        except Exception as exc:
            logger.warning("Fragment %s 的 condition 求值失败: %s", frag.id, exc)
            return False

    def _resolve_content(self, frag: PromptFragment, state: AgentState) -> str:
        """解析 content：静态字符串直接返回，动态函数调用后返回"""
        if callable(frag.content):
            try:
                return frag.content(state)
            except Exception as exc:
                logger.error("Fragment %s 动态 content 生成失败: %s", frag.id, exc)
                return f"[Fragment {frag.id} 生成错误: {exc}]"
        return frag.content

    # ------------------------------------------------------------------
    # 组装
    # ------------------------------------------------------------------

    def build(
        self,
        phase: Literal["p1", "p3", "p4"],
        agent_id: str,
        state: AgentState,
        base_messages: list[dict] | None = None,
    ) -> list[dict]:
        """
        组装最终 LLM 消息列表。

        Args:
            phase: 当前执行阶段
            agent_id: 当前 Agent 的 ID
            state: 运行时状态快照
            base_messages: 历史对话消息（已有上下文），Fragment 将注入其中

        Returns:
            完整的消息列表，可直接传入 LLM API
        """
        base_messages = base_messages or []
        candidates = list(self._iter_candidates(phase, agent_id, state))

        # Token 预算控制：超出预算的低优先级 Fragment 跳过
        used_tokens = 0
        selected: list[PromptFragment] = []
        for frag in candidates:
            if frag.token_estimate > 0:
                if used_tokens + frag.token_estimate > self._token_budget:
                    logger.warning(
                        "Token 预算不足，跳过 Fragment %s (估算 %d tokens)",
                        frag.id, frag.token_estimate
                    )
                    continue
                used_tokens += frag.token_estimate
            selected.append(frag)

        # 按 role 分组，再按 inject_as 合并
        system_prefixes: list[str] = []
        system_standalones: list[dict] = []
        system_appends: list[str] = []
        user_prefixes: list[str] = []
        user_standalones: list[dict] = []

        for frag in selected:
            content = self._resolve_content(frag, state)

            if frag.role == "system":
                if frag.inject_as == "prefix":
                    system_prefixes.append(content)
                elif frag.inject_as == "append":
                    system_appends.append(content)
                else:
                    system_standalones.append({"role": "system", "content": content})
            else:  # user
                if frag.inject_as == "prefix":
                    user_prefixes.append(content)
                else:
                    user_standalones.append({"role": "user", "content": content})

        # 组装最终消息列表
        messages: list[dict] = []

        # System 消息（合并 prefix + standalone + append）
        system_parts = []
        if system_prefixes:
            system_parts.append("\n\n".join(system_prefixes))
        if system_standalones:
            # 多条 system standalone 合并为一条（避免多 system 问题）
            system_parts.extend(m["content"] for m in system_standalones)
        if system_appends:
            system_parts.append("\n\n".join(system_appends))

        if system_parts:
            messages.append({"role": "system", "content": "\n\n---\n\n".join(system_parts)})

        # 历史消息
        messages.extend(base_messages)

        # User 前缀注入（追加到最后一条 user 消息之前）
        if user_prefixes:
            prefix_content = "\n\n".join(user_prefixes)
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] = prefix_content + "\n\n" + messages[-1]["content"]
            else:
                messages.append({"role": "user", "content": prefix_content})

        # User standalone（skill 全文注入）
        for msg in user_standalones:
            messages.append(msg)

        return messages

    def debug_summary(self, phase: str, agent_id: str) -> str:
        """返回当前注册状态的调试摘要"""
        lines = [f"Registry 摘要 | Phase={phase} | Agent={agent_id}"]
        lines.append(f"总 Fragment 数: {len(self._fragments)}")
        by_trigger = defaultdict(int)
        for f in self._fragments.values():
            by_trigger[f.trigger] += 1
        for trigger, count in by_trigger.items():
            lines.append(f"  {trigger}: {count} 个")
        return "\n".join(lines)
```

---

## 3. 五层提示词架构

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 5: Writing Style        文风层（user消息，37+个.md文件）   │
├─────────────────────────────────────────────────────────────────┤
│  Layer 4: Runtime Dynamic      运行时动态层（每回合重建）          │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3: Skills               技能按需层（load_skill工具触发）    │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: WorldPlugin Rules    世界规则层（会话激活时加载）         │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1: Agent System Prompt  Agent固定层（节点初始化时加载）      │
├─────────────────────────────────────────────────────────────────┤
│  Layer 0: Core                 核心约束层（始终注入）              │
└─────────────────────────────────────────────────────────────────┘
```

### Layer 0: Core（始终注入）

**设计来源**：cursor `alwaysApply` 规则思路  
**角色**：`system`  
**trigger**：`always`  
**priority**：0–9  
**预估 token**：~500 tokens  

Core 层包含任何情况下都必须生效的约束，不随世界、Agent、会话配置变化。

#### 0.1 输出格式协议

```markdown
## 输出格式协议 [HARD-GATE]

你的所有输出必须严格遵循以下规范，违反任一条即为格式错误：

### JSON 输出规范
- 需要结构化数据时，使用 ```json ... ``` 代码块包裹
- JSON 键名使用 snake_case
- 不得在 JSON 中包含注释
- 必须是合法的 JSON（不得截断）

### XML 标签规范
- 叙事内容：<narrative>...</narrative>
- DM 注记（玩家不可见）：<dm_note>...</dm_note>
- 骰子请求：<dice_roll>...</dice_roll>
- 状态变更：<state_patch>...</state_patch>
- 章节结束信号：<chapter_end reason="..." />

### 严禁事项
- 严禁混用 JSON 和 XML 格式（只能用其中之一）
- 严禁在 <narrative> 外输出叙事内容
- 严禁在未包含 <dice_roll> 标签时引用骰子结果
```

#### 0.2 CoT 起手模板

```markdown
## 思维链协议

在输出任何叙事或判定之前，必须先在 <think>...</think> 块中完成以下检查：

1. **信息核验**：当前场景的 NPC 知道什么？不知道什么？
2. **能力边界**：角色使用的能力是否在已解锁清单内？
3. **时间轴核验**：当前时间点是否允许该事件发生？
4. **叙事逻辑**：上一轮的行动结果是否已被承接？

完成检查后，输出正式内容。<think> 块不出现在最终回复中。
```

#### 0.3 骰子引用格式（不可篡改）

```markdown
## 骰子系统约束 [HARD-GATE]

**你不能决定骰子结果**。骰子由系统独立计算后注入，你只能引用结果。

### 引用格式
```xml
<dice_roll id="roll_abc123" />
```

引用该标签时，系统会自动展示骰子详情。

### 禁止行为
- ❌ 在未收到骰子结果前描述成功或失败
- ❌ 修改或忽略系统注入的骰子结果
- ❌ 凭空写"他投出了6点"等数字

### 正确流程
1. 发出 <dice_roll> 请求
2. 等待系统注入 `<dice_result>` 片段
3. 根据 verdict 字段（success/failure/botch/critical）撰写叙事
```

#### 0.4 禁止 OOC 约束

```markdown
## 角色扮演边界 [HARD-GATE]

- 严禁跳出叙事视角发表元评论（OOC：Out of Character）
- 严禁向玩家解释"作为AI我..."
- 严禁主动破坏第四堵墙（除非剧情明确要求且有 permission_ask 确认）
- 如有内容安全顾虑，在 <dm_note> 中记录，不影响叙事流
```

---

### Layer 1: Agent System Prompt（每 Agent 固定）

**设计来源**：ai-vn-system-backend 静态 prompt + ai-vn-game-system promptBuilder  
**角色**：`system`  
**trigger**：`always`（仅对对应 Agent）  
**priority**：10–19  
**加载时机**：节点初始化时，不随回合变化  

每个 Agent 有独立的 system prompt 文件，定义其角色定位、职责边界、输出格式期望。

#### 文件路径规范

```
prompts/
└── agents/
    ├── dm_system.md          # DM Agent（P1 规划 + 工具调用）
    ├── narrator_system.md    # Narrator Agent（P3 叙事生成）
    ├── calibrator_system.md  # Calibrator Agent（P4 变量结算）
    ├── chronicler_system.md  # Chronicler Agent（章节摘要）
    └── shopkeeper_system.md  # 商店 Agent（经济系统）
```

#### DM Agent System Prompt 示例（`dm_system.md`）

```markdown
# DM Agent — 系统定义

你是本互动叙事引擎的主裁判（DM）。

## 核心职责
- **P1 阶段**：解析玩家意图，规划叙事走向，决定是否触发骰子
- **工具调用**：你有权调用以下工具：
  - `load_skill(skill_id)` — 加载战斗/商店等专项规则
  - `recall_memory(query)` — 召回相关记忆
  - `roll_dice(pool, difficulty)` — 发起骰子判定
  - `query_npc(npc_id)` — 查询 NPC 档案
- **决策文档**：每次规划在 <dm_note> 中记录推理过程

## 职责边界
- 你**不负责**生成叙事正文（由 Narrator Agent 完成）
- 你**不负责**结算数值变化（由 Calibrator Agent 完成）
- 你的输出主要是结构化决策 JSON，不是散文

## 输出格式
\`\`\`json
{
  "intent": "玩家意图摘要",
  "plan": "叙事规划",
  "dice_required": true/false,
  "skills_to_load": ["skill_id_1"],
  "narrative_hints": "给 Narrator 的提示"
}
\`\`\`
```

---

### Layer 2: WorldPlugin Rules（会话激活的世界规则）

**设计来源**：crossover/wuxia/infinite_arsenal 扩展  
**角色**：`system`  
**trigger**：`always`（session 内常驻）  
**priority**：20–49  
**加载时机**：`session_init` 时，由 `WorldPlugin.get_rules_skills()` 指定  

每个 WorldPlugin 声明自己的规则集，在会话开始时加载到 Registry。

#### WorldPlugin 接口

```python
from abc import ABC, abstractmethod


class WorldPlugin(ABC):
    """世界插件基类，定义该世界的规则注入策略"""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """插件唯一 ID，如 'wuxia_jianghu'"""
        ...

    @abstractmethod
    def get_rules_fragments(self) -> list[PromptFragment]:
        """返回该世界的规则 Fragment 列表，在 session_init 时注册"""
        ...

    @abstractmethod
    def get_skills_catalog(self) -> list[str]:
        """返回该世界可用的 SKILL.md 文件路径列表（Layer 3）"""
        ...

    def get_backend_data_schema(self) -> dict:
        """返回 Backend Data Stream 的扩展字段（Layer 4）"""
        return {}


# 示例：武侠江湖世界插件
class WuxiaJianghuPlugin(WorldPlugin):

    @property
    def plugin_id(self) -> str:
        return "wuxia_jianghu"

    def get_rules_fragments(self) -> list[PromptFragment]:
        return [
            PromptFragment(
                id="wuxia.rules.internal_energy",
                content="""## 内功体系规则

- 内力（Qi）是武侠世界的核心能量，影响技能威力和恢复速度
- 内力值 < 20% 时，所有武技威力降低 50%，且无法使用轻功
- 内力耗尽（0%）时，角色陷入"气竭"状态，持续 3 轮
- 境界等级（炼气/筑基/金丹/元婴）影响内力上限和恢复速率
""",
                phases=["p1", "p3", "p4"],
                trigger="always",
                priority=20,
                role="system",
                source="wuxia_jianghu",
            ),
            PromptFragment(
                id="wuxia.rules.honor_system",
                content="""## 江湖声望系统

- 声望（Honor）范围：-100（臭名昭著）到 +100（万古留名）
- 声望影响 NPC 初始态度（每 10 点声望 = 1 级态度偏移）
- 声望 < -50 时，正道门派 NPC 默认敌对
- 声望 > 80 时，可解锁隐藏 NPC 对话和特殊任务
""",
                phases=["p1", "p3"],
                trigger="always",
                priority=25,
                role="system",
                source="wuxia_jianghu",
            ),
        ]

    def get_skills_catalog(self) -> list[str]:
        return [
            "skills/wuxia/combat-narration.md",
            "skills/wuxia/shop-evaluation.md",
            "skills/wuxia/cultivation-breakthrough.md",
            "skills/wuxia/jianghu-encounter.md",
        ]
```

---

### Layer 3: Skills（按需加载）

**设计来源**：pi SKILL.md 格式 + opencode 按需加载 + superpowers user 消息前缀注入  
**角色**：`user`（inject_as: "prefix"）  
**trigger**：`on_demand`（通过 `load_skill` 工具触发）  
**priority**：50–79  
**加载时机**：P1 规划阶段，DM Agent 根据场景判断需要哪些 Skill  

Skills 是功能性规则的原子单元，格式见第 5 节。

#### load_skill 工具定义

```python
@tool
async def load_skill(skill_id: str, agent_state: AgentState) -> str:
    """
    按需加载 SKILL.md 文件到当前 Registry。

    DM Agent 在规划阶段调用此工具，告知系统当前场景需要
    哪些专项规则（如战斗叙事、商店评估、章节开篇等）。

    Args:
        skill_id: Skill 的 ID，对应 skills/ 目录下的文件名（不含 .md）

    Returns:
        加载成功/失败信息
    """
    skill_path = Path(f"skills/{skill_id}.md")
    if not skill_path.exists():
        return f"错误：找不到 Skill 文件 {skill_path}"

    # 解析 frontmatter 和正文
    fragment = SkillLoader.load(skill_path, agent_state.session_id)

    # 注册到 Registry（标记为已加载）
    registry.register(fragment)
    agent_state.active_skills.append(skill_id)

    return f"已加载 Skill: {fragment.id}（{fragment.token_estimate} tokens）"
```

#### 预置 Skill 目录

| Skill ID | 文件 | 适用场景 | Agent |
|----------|------|----------|-------|
| `combat-narration` | `skills/combat/combat-narration.md` | 战斗场景叙事 | Narrator |
| `shop-evaluation` | `skills/economy/shop-evaluation.md` | 商店购买/出售 | DM |
| `chapter-opening` | `skills/narrative/chapter-opening.md` | 章节开篇 | Narrator |
| `npc-dialogue` | `skills/narrative/npc-dialogue.md` | NPC 深度对话 | Narrator |
| `breakthrough` | `skills/cultivation/breakthrough.md` | 突破境界 | DM + Narrator |
| `world-transition` | `skills/meta/world-transition.md` | 穿越/跨界 | DM |
| `item-appraisal` | `skills/economy/item-appraisal.md` | 物品鉴定 | DM |
| `gacha-resolution` | `skills/system/gacha-resolution.md` | 抽卡结算 | DM |

---

### Layer 4: Runtime Dynamic（每回合动态注入）

**设计来源**：ai-vn-game-system 18 轴 DM 参考层  
**角色**：`user`（inject_as: "prefix"）  
**trigger**：`always`（每回合重建）  
**priority**：80–99  
**特性**：内容每回合重新生成，由动态 content 函数产生  

详见第 6 节 Backend Data Stream 格式。

```python
def _build_runtime_fragment(state: AgentState) -> PromptFragment:
    """构建运行时动态 Fragment（每回合调用一次）"""

    def content_fn(s: AgentState) -> str:
        return RuntimeDataStreamBuilder.build(s)

    return PromptFragment(
        id="runtime.dynamic.data_stream",
        content=content_fn,
        phases=["p1", "p3", "p4"],
        trigger="always",
        priority=80,
        role="user",
        inject_as="prefix",
        source="runtime",
        agent_filter=["dm_agent", "narrator_agent"],  # 玩家不可见
        token_estimate=0,  # 动态，每回合不同
    )
```

---

### Layer 5: Writing Style（文风层）

**设计来源**：ai-vn-game-system 37+ 个文风 `.md` 文件  
**角色**：`user`（inject_as: "standalone"）  
**trigger**：`always`（会话配置决定）  
**priority**：100+  
**优先级最低**：不影响规则约束，只影响叙事风格  

#### 文风文件目录（`writing-styles/`）

```
writing-styles/
├── 骨架层/
│   ├── 网文.md
│   ├── 小此说故事-零度写作.md
│   ├── 江南式.md
│   └── ...（共 8 个骨架层文件）
├── 节奏层/
│   ├── 小此爽写-中文.md
│   ├── 节奏大师.md
│   ├── 异世界战斗-Elainades.md
│   └── ...（共 4 个节奏层文件）
├── 心理层/
│   ├── 伏见司式.md
│   ├── 入间人间式.md
│   └── ...（共 5 个心理层文件）
└── 温度层/
    ├── 鲁迅式.md
    ├── 王小波式.md
    └── ...（共 3 个温度层文件）
```

#### 文风加载逻辑

```python
def load_writing_styles(
    style_ids: list[str],
    base_priority: int = 100,
) -> list[PromptFragment]:
    """
    根据会话配置加载文风 Fragment。
    多个文风各自作为独立 Fragment，priority 递增。
    """
    fragments = []
    for i, style_id in enumerate(style_ids):
        style_path = Path(f"writing-styles/{style_id}.md")
        content = style_path.read_text(encoding="utf-8")

        fragments.append(PromptFragment(
            id=f"style.{style_id.replace('/', '.').replace('.md', '')}",
            content=content,
            phases=["p3"],  # 只在叙事阶段注入
            trigger="always",
            priority=base_priority + i * 10,
            role="user",
            inject_as="standalone",
            source="writing_style_system",
            agent_filter=["narrator_agent"],  # 只注入叙事 Agent
        ))

    return fragments
```

---

## 4. Phase 过滤详解

### 4.1 四阶段定义

| Phase | 名称 | 执行 Agent | 职责 |
|-------|------|-----------|------|
| **P1** | 规划阶段 | DM Agent | 解析意图、调用工具、骰子判定、技能加载 |
| **P2** | RAG 阶段 | 记忆系统（非 LLM） | 向量召回、BM25 检索，结果注入 P3 |
| **P3** | 叙事阶段 | Narrator Agent | 生成叙事正文、NPC 对话、世界描述 |
| **P4** | 结算阶段 | Calibrator Agent | 数值变更、状态更新、成就检查 |

P2 为纯计算阶段，不涉及 LLM 调用，不需要提示词注入。

### 4.2 各层在不同 Phase 的可见性

| Fragment 类型 | P1 规划 | P2 RAG | P3 叙事 | P4 结算 |
|--------------|:-------:|:------:|:-------:|:-------:|
| **Layer 0 Core** | ✅ | — | ✅ | ✅ |
| **Layer 1 Agent System** | ✅ DM | — | ✅ Narrator | ✅ Calibrator |
| **Layer 2 WorldPlugin Rules** | ✅ | — | ✅ | ✅ |
| **Layer 3 Skills（combat）** | ✅（加载） | — | ✅（使用） | ❌ |
| **Layer 3 Skills（economy）** | ✅（加载） | — | ✅（使用） | ✅（结算） |
| **Layer 4 Runtime Data** | ✅（DM参考） | — | ✅（Narrator参考） | ✅ |
| **Layer 5 Writing Style** | ❌ | — | ✅ | ❌ |

### 4.3 Phase 过滤实现示例

```python
# P1 阶段构建
p1_messages = registry.build(
    phase="p1",
    agent_id="dm_agent",
    state=current_state,
    base_messages=conversation_history,
)

# P3 阶段构建（在 P1 结束、P2 RAG 完成后）
p3_messages = registry.build(
    phase="p3",
    agent_id="narrator_agent",
    state=enriched_state,  # 已包含 P2 召回结果
    base_messages=conversation_history,
)
```

### 4.4 Phase 间数据传递

```python
@dataclass
class PhaseContext:
    """在各 Phase 间传递的上下文数据"""

    # P1 → P2
    dm_decisions: dict          # DM 的规划决策
    dice_results: list[dict]    # 骰子结果
    skills_loaded: list[str]    # 已加载的 Skill ID

    # P2 → P3
    recalled_memories: list[dict]  # RAG 召回结果
    active_npcs: list[dict]        # 相关 NPC 档案

    # P3 → P4
    narrative_text: str         # 生成的叙事正文
    state_patches: list[dict]   # Narrator 建议的状态变更
    chapter_end: bool           # 是否触发章节结束
```

---

## 5. SKILL.md 完整格式规范

### 5.1 Frontmatter 字段定义

```yaml
---
# ===== 必填字段 =====
id: "combat-narration"
# Skill 唯一 ID，用于 load_skill 工具调用和 active_skills 跟踪

name: "战斗叙事专项规则"
# 人类可读名称

phases: ["p3"]
# 可选值：p1 / p3 / p4 / all（或列表）

trigger: "on_demand"
# always / auto / on_demand

priority: 60
# 50-79 范围内（Layer 3）

role: "user"
# system / user

inject_as: "prefix"
# prefix / standalone / append

source: "zero-arsenal-core"
# 来源插件/扩展 ID

# ===== 选填字段 =====
condition: null
# Python 表达式，trigger=auto 时生效

agent_filter: ["narrator_agent"]
# 只对指定 Agent 注入，null 表示全部

token_estimate: 800
# 预估 token 数（用于预算控制）

version: "1.2.0"
# Skill 版本，用于变更追踪

description: "为战斗场景提供叙事规范、禁词表和节奏控制策略"
# 简短描述，用于 UI 展示和调试日志

requires: []
# 依赖的其他 Skill ID（加载本 Skill 前先加载这些）

conflicts: ["daily-narration"]
# 与本 Skill 互斥的其他 Skill ID

tags: ["combat", "narration", "rhythm"]
# 标签，用于搜索和分类
---
```

### 5.2 正文结构规范

SKILL.md 正文分为五个标准节：

```markdown
# [Skill 名称]

## 决策图（Decision Gate）

决策树，用 Mermaid 语法绘制，明确本 Skill 的启用条件和分支：

\`\`\`mermaid
flowchart TD
    A[场景判断] --> B{战斗是否激活?}
    B -->|是| C[加载战斗叙事规则]
    B -->|否| D[跳过本 Skill]
    C --> E{敌人星级}
    E -->|≥4★| F[激活碾压型文风]
    E -->|<4★| G[激活紧绷型文风]
\`\`\`

## 铁律 [HARD-GATE]

本节列出绝对不可违反的规则。违反任一条必须停止并重写。

- [ ] 骰子结果未收到前，不得描述胜负
- [ ] 能力使用不得超出角色已解锁清单
- [ ] 敌人不无故失误（禁止主角光环）
- [ ] 心理活动不超过正文 15%

## 执行流程

Step-by-step 的执行说明：

1. **确认战力差距**：对照角色卡与敌人档案，标注星级差距
2. **选择战斗节奏**：快速收割 / 胶着拉锯 / 战略撤退 / 消耗为主 / 奇谋逆转
3. **设计关键节点**：开场手段 → 转折点 → 终结手段
4. **生成叙事**：按选定文风原子输出

## 集成说明

说明与其他系统的集成点：

- **骰子系统**：战斗判定使用 `<dice_roll>` 标签，结果由系统注入
- **状态系统**：HP/能量变化通过 `<state_patch>` 标签输出，由 Calibrator 结算
- **记忆系统**：战斗结束后，关键事件自动写入 episodic 记忆层

## 禁词与风格约束

本 Skill 激活期间额外生效的禁词（在全局禁词基础上叠加）：

**战斗场景额外禁词**：
- 浴血奋战（太套路）
- 势如破竹（排比感过强）
- 一招制敌（无聊）
- 强如斩断（万能动词，禁止）

**推荐替代表达**：
- 用具体动作代替形容（不写"剑法精妙"，写"剑尖走了个弧线，从肘关节内侧切入"）
```

### 5.3 完整示例：combat-narration.md

```markdown
---
id: "combat-narration"
name: "战斗叙事专项规则"
phases: ["p3"]
trigger: "on_demand"
priority: 60
role: "user"
inject_as: "prefix"
source: "zero-arsenal-core"
agent_filter: ["narrator_agent"]
token_estimate: 850
version: "1.3.0"
description: "为战斗场景提供星级差距评估、节奏控制、文风规范和骰子引用规则"
requires: []
conflicts: ["daily-narration"]
tags: ["combat", "narration", "rhythm", "dice"]
---

# 战斗叙事专项规则

## 决策图

\`\`\`mermaid
flowchart TD
    A[接收叙事指令] --> B{state.combat.active?}
    B -->|false| SKIP[退出：非战斗场景]
    B -->|true| C[读取战力差距]
    C --> D{星级差}
    D -->|≥2★优势| CRUSH[碾压型：余裕节奏]
    D -->|均衡±1★| TENSE[紧绷型：简洁动作]
    D -->|≥2★劣势| ESCAPE[求生型：碎片感知]
    CRUSH & TENSE & ESCAPE --> E[检查骰子结果]
    E --> F{verdict}
    F -->|critical| EPIC[史诗化处理]
    F -->|success| NORMAL[正常叙事]
    F -->|failure| SETBACK[挫折叙事]
    F -->|botch| DISASTER[灾难叙事]
\`\`\`

## 铁律 [HARD-GATE]

以下规则在每段叙事生成后必须逐一核查，违反任一条必须重写：

- [ ] **骰子先行**：描述伤害/成败前，骰子结果必须已收到（有 `<dice_result>` 注入）
- [ ] **能力边界**：角色使用的技能必须在 `character.loadout.application_techniques` 清单内
- [ ] **敌人主体性**：敌人有自己的战术逻辑，不因剧情需要而无故失误
- [ ] **心理比例**：内心独白字数 ≤ 正文 15%（意识流文风章节除外）
- [ ] **伤害对等**：主角受伤时，描写程度与 HP 损失比例相符
- [ ] **禁止主角光环**：劣势情况下不得出现"最后关头对手手滑"的描写

## 执行流程

### Step 1：战力差距确认

从 `<dm_note>` 中读取 DM 的战力评估，或自行计算：

\`\`\`
我方：[角色名] [anti_feat_tier]★[tier_sub]
敌方：[敌人名] [anti_feat_tier]★[tier_sub]
差距：[+/-N]★
\`\`\`

### Step 2：选定战斗节奏原子

根据差距选择节奏：

| 差距 | 节奏原子 | 文风特征 |
|------|----------|----------|
| 碾压（≥+2★） | 余裕型 | 长句，有余暇观察，细节丰富 |
| 均衡（±1★） | 紧绷型 | 短句，动作碎片，读者喘不过气 |
| 劣势（≥-2★） | 碎片感知型 | 意识流，感官分裂，时间扭曲 |
| 临界逃脱 | 极限型 | 混合以上，节奏突变 |

### Step 3：关键节点设计

在 `<think>` 块中规划：
- **开场手段**：第一个动作是什么？
- **转折点**：骰子 verdict 决定的关键翻转
- **终结手段**：本轮战斗结束点（不一定是死亡）

### Step 4：骰子结果引用

收到 `<dice_result>` 后，按 verdict 处理：

- **critical**：同等字数内，加入史诗感（环境呼应、慢镜头处理），但不夸张
- **success**：正常推进，角色获得预期结果
- **failure**：挫折，但不崩溃。写角色如何调整
- **botch**：灾难性失误。严重后果，不得轻描淡写

### Step 5：输出格式

\`\`\`xml
<narrative>
[叙事正文，500-1500字]
</narrative>

<state_patch>
{"hp_delta": -15, "energy_delta": -20, "status_add": ["bleeding"]}
</state_patch>

<dm_note>
[本轮战斗内部记录：战术选择、NPC 意图、下轮伏笔]
</dm_note>
\`\`\`

## 集成说明

- **骰子系统**：使用 `<dice_roll pool="N" difficulty="D" />` 发起判定
- **状态系统**：HP/能量/状态变化通过 `<state_patch>` 输出，由 Calibrator P4 结算
- **记忆系统**：战斗关键事件（首次重伤、首次杀敌、绝境逆转）自动标记为 episodic 记忆
- **成就系统**：Calibrator 检查 `earn_battle_rewards` 触发条件

## 禁词与风格约束

**额外禁词**（在全局禁词基础上叠加，战斗叙事期间生效）：

```
浴血奋战  势如破竹  一招制敌  强如斩断  虎虎生威
以一当百  天下无敌  无懈可击  举重若轻  游刃有余
只见       但见       但听       话说      却说
```

**数字"3"限制**（战斗场景同样适用）：
- 禁止三连动作排比
- 禁止三段情绪递进，选最强的一个
- 例外：客观计数（"三刀"）不受限

**Show Don't Tell（战斗强化版）**：
- ❌ 他感到非常危险
- ✅ 颈椎的汗毛立了起来，眼角捕捉到侧面的黑影
```

---

## 6. Backend Data Stream 格式

### 6.1 设计原则

Backend Data Stream（后端数据流）是注入给 DM Agent 和 Narrator Agent 的结构化参考层：

- **仅 Agent 可见**，玩家不可见（包裹在 `<dm_note>` 风格的隐藏标签中）
- 每回合重建，反映最新游戏状态
- 来源：角色卡 v4 + 世界档案 + 骰子日志

### 6.2 18 轴数据结构

```python
@dataclass
class BackendDataStream:
    """
    18 轴 DM 参考层数据结构。
    每回合由 RuntimeDataStreamBuilder 从 AgentState 生成，
    序列化为 Markdown 注入为 user 消息前缀。
    """

    # 轴 1-3：生命与能量
    hp_status: HPStatus           # 各部位 HP 状态
    energy_pools: list[EnergyPool]  # 所有能量池状态
    passive_abilities: list[str]   # 当前激活的被动技能

    # 轴 4-6：装备与技能
    equipped_items: list[dict]     # 已装备物品
    application_techniques: list[dict]  # 可用主动技能
    power_sources: list[dict]      # 能量来源（内功/魔力/科技）

    # 轴 7-9：心理状态
    emotion_state: str             # 当前情绪标签（平静/愤怒/恐惧等）
    stress_level: int              # 压力值 0-100
    morale: int                    # 士气 0-100
    clarity: int                   # 神志清醒度 0-100

    # 轴 10-11：关系网络
    active_relationships: list[RelationshipSnapshot]  # 当前场景 NPC 关系
    trust_matrix: dict[str, int]   # NPC 信任度快照

    # 轴 12-13：世界状态
    world_time: str                # "1998-04-15 14:30"
    current_location: str          # 当前地点描述

    # 轴 14-15：任务进度
    active_quests: list[QuestSnapshot]   # 当前进行中的任务
    active_hooks: list[HookSnapshot]     # 悬而未决的叙事钩子

    # 轴 16：经济状态
    economy: EconomySnapshot       # 积分/徽章/tier

    # 轴 17：战斗状态
    combat: CombatSnapshot         # 战斗详情（非战斗时为 null）

    # 轴 18：记忆召回结果
    recalled_memories: list[MemorySnippet]  # P2 RAG 召回的相关记忆


@dataclass
class HPStatus:
    head: BodyPartHP
    torso: BodyPartHP
    left_arm: BodyPartHP
    right_arm: BodyPartHP
    left_leg: BodyPartHP
    right_leg: BodyPartHP
    overall_ratio: float       # 全身平均 HP%
    critical_parts: list[str]  # HP < 20% 的部位名称


@dataclass
class BodyPartHP:
    current: int
    max: int
    armor: int
    status_effects: list[str]  # ["bleeding", "fractured", ...]


@dataclass
class EnergyPool:
    name: str        # "内力" / "魔力" / "体力"
    current: int
    max: int
    regen_per_turn: int
    type: str        # "qi" / "mana" / "stamina" / "tech_charge"


@dataclass
class RelationshipSnapshot:
    npc_id: str
    name: str
    affinity: int        # -100 到 +100
    relationship_type: str  # "ally" / "neutral" / "hostile"
    is_present: bool     # 是否在当前场景


@dataclass
class CombatSnapshot:
    active: bool
    round: int
    initiative_order: list[str]  # 行动顺序
    enemies: list[EnemySnapshot]
    environment_effects: list[str]  # ["darkness", "rain", "fire"]


@dataclass
class EnemySnapshot:
    id: str
    name: str
    tier: int
    tier_sub: str
    hp_ratio: float
    known_abilities: list[str]
    status_effects: list[str]
    intent: str         # DM 已规划的敌人意图


@dataclass
class MemorySnippet:
    content: str
    relevance_score: float
    tier: str           # "episodic" / "semantic" / "core"
    created_at: str
```

### 6.3 序列化为 Markdown

```python
class RuntimeDataStreamBuilder:
    """将 BackendDataStream 序列化为 Markdown 格式的提示词文本"""

    @staticmethod
    def build(state: AgentState) -> str:
        stream = RuntimeDataStreamBuilder._extract_stream(state)
        return RuntimeDataStreamBuilder._render(stream)

    @staticmethod
    def _render(s: BackendDataStream) -> str:
        lines = ["<backend_data_stream>", "<!-- 以下内容仅 Agent 可见，不展示给玩家 -->", ""]

        # === 轴 1-3：生命与能量 ===
        lines.append("## 生命状态")
        lines.append(f"- 综合HP：{s.hp_status.overall_ratio:.0%}")
        if s.hp_status.critical_parts:
            lines.append(f"- ⚠️ 危急部位：{', '.join(s.hp_status.critical_parts)}")
        for pool in s.energy_pools:
            pct = pool.current / pool.max if pool.max > 0 else 0
            lines.append(f"- {pool.name}：{pool.current}/{pool.max}（{pct:.0%}），回复{pool.regen_per_turn}/轮")

        # === 轴 7-9：心理状态 ===
        lines.append("")
        lines.append("## 心理状态")
        lines.append(f"- 情绪：{s.emotion_state}")
        lines.append(f"- 压力：{s.stress_level}/100 | 士气：{s.morale}/100 | 神志：{s.clarity}/100")

        # === 轴 10-11：关系 ===
        present_npcs = [r for r in s.active_relationships if r.is_present]
        if present_npcs:
            lines.append("")
            lines.append("## 当前场景NPC")
            for npc in present_npcs:
                sign = "+" if npc.affinity >= 0 else ""
                lines.append(f"- {npc.name}（{npc.relationship_type}，好感度{sign}{npc.affinity}）")

        # === 轴 12-13：世界状态 ===
        lines.append("")
        lines.append("## 世界状态")
        lines.append(f"- 时间：{s.world_time}")
        lines.append(f"- 位置：{s.current_location}")

        # === 轴 17：战斗状态 ===
        if s.combat and s.combat.active:
            lines.append("")
            lines.append("## 战斗状态 ⚔️")
            lines.append(f"- 当前轮：第 {s.combat.round} 轮")
            lines.append(f"- 行动顺序：{' → '.join(s.combat.initiative_order)}")
            for enemy in s.combat.enemies:
                lines.append(
                    f"- 敌方 {enemy.name}（{enemy.tier}★{enemy.tier_sub}）"
                    f"HP {enemy.hp_ratio:.0%}，意图：{enemy.intent}"
                )
            if s.combat.environment_effects:
                lines.append(f"- 环境效果：{', '.join(s.combat.environment_effects)}")

        # === 轴 18：记忆召回 ===
        if s.recalled_memories:
            lines.append("")
            lines.append("## 相关记忆")
            for mem in s.recalled_memories[:3]:  # 最多展示3条
                lines.append(f"- [{mem.tier}|{mem.relevance_score:.2f}] {mem.content[:100]}...")

        lines.append("")
        lines.append("</backend_data_stream>")
        return "\n".join(lines)
```

---

## 7. Token 预算分配

### 7.1 各层估算 Token 数

| 层 | 内容 | 估算 Token | 备注 |
|----|------|-----------|------|
| **Layer 0 Core** | 格式协议 + CoT + 骰子约束 + OOC | ~500 | 固定，不随配置变化 |
| **Layer 1 Agent System** | 单个 Agent 的 system prompt | ~300–600 | 每 Agent 不同 |
| **Layer 2 WorldPlugin** | 激活的世界规则（通常 2–5 条） | ~400–800 | 随世界插件变化 |
| **Layer 3 Skills** | 每个 Skill 平均 ~800 tokens | ~800–2400 | 加载数量 1–3 个 |
| **Layer 4 Runtime** | Backend Data Stream | ~300–600 | 随游戏状态变化 |
| **Layer 5 Writing Style** | 每个文风文件约 ~500 tokens | ~500–1500 | 激活 1–3 个文风 |
| **历史对话** | 最近 N 轮对话 | ~2000–4000 | 动态压缩 |
| **当前用户消息** | 玩家输入 | ~50–200 | — |
| **总计** | | **~4850–10600** | 目标控制在 8000 以内 |

### 7.2 预算控制策略

```python
class TokenBudgetManager:
    """
    Token 预算管理器。
    当总估算超出预算时，按优先级从低到高裁剪。
    """

    HARD_BUDGET = 8000      # 总 token 预算（不含输出）
    RESERVED_OUTPUT = 2000  # 为输出预留的 token
    HISTORY_MAX = 4000      # 历史对话最大 token 数

    @classmethod
    def trim_history(cls, messages: list[dict]) -> list[dict]:
        """
        当历史消息超出预算时，从中间裁剪（保留最新和最早的部分）。
        仿 SillyTavern 的 Context Sliding 机制。
        """
        # 简化实现：保留最新 20 轮
        if len(messages) > 40:  # 大约 20 轮（每轮 2 条）
            return messages[:2] + messages[-38:]  # 保留最早 1 轮 + 最新 19 轮
        return messages

    @classmethod
    def prioritize_skills(cls, skills: list[str], budget: int) -> list[str]:
        """当 Skill 数量过多时，只保留最重要的"""
        # 战斗 Skill 优先级最高，其他按加载顺序
        priority_order = ["combat-narration", "gacha-resolution"]
        result = []
        remaining = budget
        for skill_id in priority_order + [s for s in skills if s not in priority_order]:
            skill_tokens = SKILL_TOKEN_ESTIMATES.get(skill_id, 800)
            if remaining >= skill_tokens:
                result.append(skill_id)
                remaining -= skill_tokens
        return result
```

### 7.3 上下文压缩（Compaction）

当历史消息超出预算时，触发 Chronicler Agent 压缩。

> ⚠️ **实现差异（第二十九轮补录）**：设计草案的函数签名与实现不符，以下为**实际实现版本**。

```python
# 实际实现（backend/agents/compaction.py）
COMPACT_THRESHOLD = 3000   # 估算 token 超过此值才触发

async def maybe_compact(ctx: TurnContext) -> TurnContext:
    """
    检查当前上下文 token 估算量，超阈值时压缩历史叙事并更新 ctx.memory_context。
    失败时静默返回原始 ctx（不抛异常）。
    """
    total_text = (ctx.memory_context or "") + (ctx.narrative_text or "") + session_notes
    estimated = token_budget.estimate_tokens(total_text)
    if estimated < COMPACT_THRESHOLD:
        return ctx

    # 从 DB 取最近 20 条 narrative Parts 文本（而非 messages 列表参数）
    narrative_texts = await _fetch_recent_narratives(ctx.session_id, limit=20)
    summary = await _summarize("\n\n".join(narrative_texts))   # 调用 chronicler LLM

    # 将摘要注入 memory_context 前缀（而非作为 system message 插入 list）
    ctx.memory_context = f"[历史摘要]\n{summary}\n\n" + ctx.memory_context

    # 写 compaction Part 到 DB 并发布 Bus 事件
    await _write_compaction_part(ctx, summary)
    return ctx
```

**设计草案与实现的核心差异对照**：

| 维度 | 设计草案 | 实际实现 |
|---|---|---|
| 函数签名 | `(session_id, messages: list[dict])` | `(ctx: TurnContext)` |
| 返回值 | `list[dict]`（消息列表） | `TurnContext` |
| Token 估算源 | `estimate_tokens(messages)` | `memory_context + narrative_text + session_notes` 拼接字符串 |
| 历史来源 | `messages[:-10]` 参数 | DB 查 `message_parts WHERE type='narrative'` |
| 压缩阈值 | `TOKEN_BUDGET_MANAGER.HISTORY_MAX` | `COMPACT_THRESHOLD = 3000` |
| 结果注入方式 | 返回含 `<compaction>` role=system 的 list | 前缀注入 `ctx.memory_context` 字符串 |
| 错误处理 | 不处理（异常传播） | `try/except` 静默返回原始 `ctx` |

---

## 8. 提示词版本管理

### 8.1 文件路径规范

```
zero-arsenal/
├── prompts/                          # 提示词根目录
│   ├── agents/                       # Layer 1：Agent System Prompts
│   │   ├── dm_system.md
│   │   ├── narrator_system.md
│   │   ├── calibrator_system.md
│   │   └── chronicler_system.md
│   └── core/                         # Layer 0：Core 约束
│       ├── format_protocol.md
│       ├── cot_template.md
│       ├── dice_protocol.md
│       └── ooc_constraint.md
├── skills/                           # Layer 3：Skills（按需加载）
│   ├── combat/
│   │   └── combat-narration.md
│   ├── economy/
│   │   ├── shop-evaluation.md
│   │   └── item-appraisal.md
│   ├── narrative/
│   │   ├── chapter-opening.md
│   │   └── npc-dialogue.md
│   └── system/
│       └── gacha-resolution.md
├── writing-styles/                   # Layer 5：文风文件
│   ├── 网文.md
│   ├── 小此爽写-中文.md
│   └── ...（37+ 文件）
└── plugins/                          # WorldPlugin 规则片段
    ├── wuxia/
    ├── crossover/
    └── infinite_arsenal/
```

### 8.2 提示词热更新机制

所有提示词以 `.md` 文件存储，修改文件即可更新，**无需改代码或重启**：

```python
class PromptFileLoader:
    """
    带缓存的提示词文件加载器。
    文件修改时间变化时自动失效缓存，实现热更新。
    """

    def __init__(self, watch_interval: float = 5.0):
        self._cache: dict[str, tuple[float, str]] = {}  # path → (mtime, content)
        self._watch_interval = watch_interval

    def load(self, path: str | Path) -> str:
        path = Path(path)
        mtime = path.stat().st_mtime

        if path in self._cache:
            cached_mtime, cached_content = self._cache[path]
            if cached_mtime == mtime:
                return cached_content

        content = path.read_text(encoding="utf-8")
        self._cache[path] = (mtime, content)
        return content

    def load_skill(self, skill_path: str | Path) -> PromptFragment:
        """解析 SKILL.md 的 frontmatter + 正文，返回 PromptFragment"""
        import yaml

        content = self.load(skill_path)

        # 分割 frontmatter 和正文
        if content.startswith("---"):
            _, front, body = content.split("---", 2)
            meta = yaml.safe_load(front)
        else:
            meta = {}
            body = content

        return PromptFragment(
            id=meta.get("id", Path(skill_path).stem),
            content=body.strip(),
            phases=meta.get("phases", "all"),
            trigger=meta.get("trigger", "on_demand"),
            condition=meta.get("condition"),
            priority=meta.get("priority", 60),
            role=meta.get("role", "user"),
            inject_as=meta.get("inject_as", "standalone"),
            source=meta.get("source", "unknown"),
            agent_filter=meta.get("agent_filter"),
            token_estimate=meta.get("token_estimate", 0),
            enabled=meta.get("enabled", True),
        )


# 全局单例
_loader = PromptFileLoader()
```

### 8.3 版本追踪与变更日志

每个 SKILL.md 文件的 frontmatter 中包含 `version` 字段，遵循语义化版本：

- `MAJOR.MINOR.PATCH`
- **MAJOR**：破坏性变更（更改了 HARD-GATE 规则、删除字段）
- **MINOR**：新增规则或示例，向后兼容
- **PATCH**：措辞修正、格式整理

版本变更记录在各 Skill 文件末尾的 `## 变更历史` 节：

```markdown
## 变更历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| 1.3.0 | 2026-05-31 | 新增碎片感知型节奏原子；更新禁词表 |
| 1.2.0 | 2026-04-10 | HARD-GATE 添加伤害对等检查 |
| 1.1.0 | 2026-03-01 | 集成骰子系统 v2 引用格式 |
| 1.0.0 | 2026-02-01 | 初始版本 |
```

### 8.4 提示词审计日志

每次 `registry.build()` 调用，将组装结果写入审计日志：

```python
@dataclass
class PromptBuildLog:
    """提示词组装的审计记录"""
    session_id: str
    turn_index: int
    phase: str
    agent_id: str
    fragments_used: list[str]        # Fragment ID 列表
    fragments_skipped: list[str]     # 被跳过的 Fragment ID（含原因）
    total_token_estimate: int
    built_at: float                  # Unix 时间戳

# 写入审计文件
async def log_build(log: PromptBuildLog, log_dir: Path) -> None:
    import json
    log_file = log_dir / f"prompt_log_{log.session_id}.jsonl"
    async with aiofiles.open(log_file, mode='a', encoding='utf-8') as f:
        await f.write(json.dumps(dataclasses.asdict(log), ensure_ascii=False) + "\n")
```

---

*文档结束。最后更新：2026-05-31*

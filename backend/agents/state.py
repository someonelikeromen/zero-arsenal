"""
AgentState — LangGraph 全局状态，贯穿整个 Agent 图。
参考 03-agent-system.md 设计。

设计文档中的不可变数据类（§4）：
  DiceResult / DMDecision / NPCResponse / WorldEvent / TavernCommand / VarUpdate

TurnContext 是 dataclass 实现（替代 TypedDict），字段覆盖设计文档 AgentState §4 全集。
字段命名差异说明：
  design: player_input  → impl: user_input  (别名属性兼容)
  design: dm_decision   → impl: dm_verdict + dm_note + roll_request (分拆更细粒度)
  design: npc_responses → impl: npc_reactions (语义一致，命名差异)
  design: memory_context: dict → impl: memory_context: str (精简表示)
"""
from __future__ import annotations
from typing import Annotated, Optional, Any, Literal
from dataclasses import dataclass, field
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage

# LangGraph 1.x 要求所有非 list 字段在有条件分支时声明 reducer，否则会触发
# INVALID_CONCURRENT_GRAPH_UPDATE。_keep_last 即 "最后写入者胜" 语义。
def _keep_last(a: Any, b: Any) -> Any:  # noqa: E302
    """通用 last-writer-wins reducer：后写的值覆盖前写的值。"""
    return b


# ── 设计文档 §4 不可变数据类 ──────────────────────────────────────────────────

@dataclass(frozen=True)
class DiceResult:
    """骰子结果不可变（frozen=True），一经产生禁止修改。"""
    dice_type: str                        # "d20", "2d6" 等
    raw_rolls: tuple[int, ...]            # 原始点数
    modifier: int                         # 属性加成
    total: int                            # 最终结果
    success: bool                         # 是否成功（对照 DC）
    critical: bool                        # 是否暴击/大失败
    triggered_by_skill: str | None = None  # 触发该骰的 SKILL.md id


@dataclass
class DMDecision:
    """DM 对行动合法性的结构化判定。"""
    verdict: Literal["pass", "reject", "modify"] = "pass"
    reason: str = ""                      # 中文说明（reject 时展示给玩家）
    modified_action: str | None = None    # modify 时的调整后行动描述
    involved_npcs: list[str] = field(default_factory=list)
    consequence_preview: str | None = None


@dataclass
class NPCResponse:
    """单个 NPC 的本轮反应。"""
    npc_key: str = ""
    dialogue: str | None = None           # 对话文本
    action: str | None = None             # 行动描述
    emotion_delta: dict[str, float] = field(default_factory=dict)
    knowledge_gained: list[str] = field(default_factory=list)


@dataclass
class WorldEvent:
    """世界层面的事件（经济/派系/环境等）。"""
    event_type: str = ""
    impact_scope: Literal["local", "regional", "global"] = "local"
    description: str = ""
    variable_deltas_preview: dict[str, Any] = field(default_factory=dict)


@dataclass
class TavernCommand:
    """NarratorAgent P4 阶段生成的结构化指令。"""
    command_type: Literal[
        "UpdateAttribute", "GrantItem", "RemoveItem",
        "UpdateRelationship", "CreditPoints", "TriggerEvent",
        "RegisterHook"
    ] = "UpdateAttribute"
    target: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class VarUpdate:
    """变量变更记录。"""
    update_type: str = ""
    target: str = ""
    before: Any = None
    after: Any = None
    source: str = ""                      # "narrator_p4" | "world_event" | "dm_modify"


@dataclass
class TurnContext:
    """单轮上下文，在 Agent 图中流转。

    字段对齐 03-agent-system.md §4 AgentState 设计，用 dataclass 替代 TypedDict
    以获得 LangGraph 兼容性和更好的 IDE 支持。

    LangGraph 1.x 兼容性：所有基础字段使用 Annotated[T, _keep_last] 声明 reducer，
    防止含条件分支至 END 的图触发 INVALID_CONCURRENT_GRAPH_UPDATE 错误。
    """
    session_id: Annotated[str, _keep_last]
    message_id: Annotated[str, _keep_last]
    user_input: Annotated[str, _keep_last]

    # ── 基础上下文 ────────────────────────────────────────────────────────────
    character_data: Annotated[dict, _keep_last] = field(default_factory=dict)
    world_plugin: Annotated[str, _keep_last] = "crossover"
    mode: Annotated[str, _keep_last] = "play"              # play | plan | review
    turn_index: Annotated[int, _keep_last] = 0             # 本会话第几轮（从 1 开始）

    # ── 设计文档补充字段（03-agent-system.md §4）─────────────────────────────
    novel_id: Annotated[str, _keep_last] = ""
    chapter_id: Annotated[str, _keep_last] = ""
    dice_results: Annotated[list, _keep_last] = field(default_factory=list)

    # ── DM 阶段产出 ───────────────────────────────────────────────────────────
    dm_verdict: Annotated[str, _keep_last] = "allow"
    dm_note: Annotated[str, _keep_last] = ""
    roll_request: Annotated[Optional[dict], _keep_last] = None
    roll_result: Annotated[Optional[dict], _keep_last] = None

    # ── Rules 阶段产出 ────────────────────────────────────────────────────────
    rules_verdict: Annotated[str, _keep_last] = "pass"
    rules_reason: Annotated[str, _keep_last] = ""
    rules_notes: Annotated[list, _keep_last] = field(default_factory=list)
    rules_roll: Annotated[Optional[dict], _keep_last] = None

    # ── 叙事阶段产出 ──────────────────────────────────────────────────────────
    narrative_plan: Annotated[str, _keep_last] = ""
    scene_goal: Annotated[str, _keep_last] = ""
    memory_context: Annotated[str, _keep_last] = ""
    narrative_text: Annotated[str, _keep_last] = ""
    state_patches: Annotated[list, _keep_last] = field(default_factory=list)
    narrative_part_id: Annotated[str, _keep_last] = ""

    # ── NPC/World 阶段产出 ────────────────────────────────────────────────────
    npc_reactions: Annotated[list, _keep_last] = field(default_factory=list)
    world_events: Annotated[list, _keep_last] = field(default_factory=list)

    # ── Style 阶段产出 ────────────────────────────────────────────────────────
    polished_narrative: Annotated[str, _keep_last] = ""
    purity_score: Annotated[float, _keep_last] = 1.0
    style_warnings: Annotated[list, _keep_last] = field(default_factory=list)

    # ── Var 阶段产出 ──────────────────────────────────────────────────────────
    var_updates: Annotated[list, _keep_last] = field(default_factory=list)
    var_errors: Annotated[list, _keep_last] = field(default_factory=list)
    vm_code: Annotated[str, _keep_last] = ""
    tavern_commands: Annotated[list, _keep_last] = field(default_factory=list)

    # ── Gacha 阶段产出（P1，无限武库抽卡发货）────────────────────────────────
    gacha_pending: Annotated[list, _keep_last] = field(default_factory=list)
    gacha_granted: Annotated[list, _keep_last] = field(default_factory=list)

    # ── DM modify 产出（P5）──────────────────────────────────────────────────
    modified_action: Annotated[str, _keep_last] = ""

    # ── 归档层产出 ────────────────────────────────────────────────────────────
    chapter_anchor_id: Annotated[str, _keep_last] = ""
    info_matrix_updates: Annotated[list, _keep_last] = field(default_factory=list)

    # ── 技能与警告 ────────────────────────────────────────────────────────────
    active_skills: Annotated[list, _keep_last] = field(default_factory=list)
    warnings: Annotated[list, _keep_last] = field(default_factory=list)

    # ── 杂项 ──────────────────────────────────────────────────────────────────
    dice_part_id: Annotated[str, _keep_last] = ""
    error: Annotated[str, _keep_last] = ""

    # ── 历史消息（LangGraph add_messages reducer）─────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages] = field(default_factory=list)

    # ── 设计文档字段名兼容属性 ────────────────────────────────────────────────
    @property
    def player_input(self) -> str:
        """设计文档字段名（§4: player_input）→ 实现字段 user_input 的别名。"""
        return self.user_input

    @property
    def dm_decision(self) -> DMDecision:
        """设计文档字段名（§4: dm_decision: DMDecision）→ 从拆分字段组装。"""
        verdict_map = {"allow": "pass", "block": "reject", "modify": "modify"}
        mapped = verdict_map.get(self.dm_verdict, "pass")
        return DMDecision(
            verdict=mapped,  # type: ignore[arg-type]
            reason=self.dm_note,
            modified_action=self.modified_action or None,
        )

    @property
    def npc_responses(self) -> list[NPCResponse]:
        """设计文档字段名（§4: npc_responses）→ npc_reactions 的类型化视图。"""
        result = []
        for r in self.npc_reactions:
            if isinstance(r, NPCResponse):
                result.append(r)
            elif isinstance(r, dict):
                result.append(NPCResponse(
                    npc_key=r.get("npc_key", ""),
                    dialogue=r.get("dialogue"),
                    action=r.get("action"),
                    emotion_delta=r.get("emotion_delta", {}),
                    knowledge_gained=r.get("knowledge_gained", []),
                ))
        return result

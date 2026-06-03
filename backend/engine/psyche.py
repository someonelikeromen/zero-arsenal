"""
OCEAN 心理模型（NPC 心理状态量化引擎）。
用途: python engine/psyche.py --profile '{"openness":0.7,...}' --event stress
MCP集成: 可包装为 MCP tool，函数签名见 compute_action_bias()
环境变量: 无

五维度（OCEAN）量化 NPC 心理状态，为 NPCAgent 的行为决策提供数值基础。
参考设计文档 03-agent-system.md §3.3 NPCAgent
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────────────────

_TRAIT_MIN = 0.0
_TRAIT_MAX = 1.0
_DRIFT_DECAY = 0.05   # 每次重大事件最大漂移幅度
_DRIFT_FLOOR = 0.1    # 漂移后不低于此值
_DRIFT_CEIL  = 0.9    # 漂移后不高于此值


# ── 数据类 ────────────────────────────────────────────────────────────────────

@dataclass
class PsycheProfile:
    """
    NPC 的 OCEAN 五维度心理档案。

    每个维度 0.0（极低）- 1.0（极高），0.5 为中性。

    O - Openness       : 开放性（好奇心、想象力、对新体验的接纳度）
    C - Conscientiousness : 责任感（自律、组织性、目标导向）
    E - Extraversion   : 外向性（社交驱动力、活跃度）
    A - Agreeableness  : 宜人性（合作意愿、信任他人）
    N - Neuroticism    : 神经质（情绪不稳定性、焦虑倾向）
    """
    openness:          float = 0.5   # O
    conscientiousness: float = 0.5   # C
    extraversion:      float = 0.5   # E
    agreeableness:     float = 0.5   # A
    neuroticism:       float = 0.5   # N

    # 扩展元数据（不参与数值计算，供叙事使用）
    dominant_trait:   str   = ""     # 最突出维度的英文名
    personality_label: str  = ""     # 人格标签（如"内省-严苛型"）
    history: list[dict] = field(default_factory=list)  # 漂移历史（最近 10 条）

    def __post_init__(self) -> None:
        self._clamp_all()
        if not self.dominant_trait:
            self.dominant_trait = self._compute_dominant()
        if not self.personality_label:
            self.personality_label = self._compute_label()

    def _clamp_all(self) -> None:
        for attr in ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"):
            val = getattr(self, attr)
            setattr(self, attr, max(_TRAIT_MIN, min(_TRAIT_MAX, float(val))))

    def _compute_dominant(self) -> str:
        traits = {
            "openness":          self.openness,
            "conscientiousness": self.conscientiousness,
            "extraversion":      self.extraversion,
            "agreeableness":     self.agreeableness,
            "neuroticism":       self.neuroticism,
        }
        return max(traits, key=traits.__getitem__)

    def _compute_label(self) -> str:
        """基于 OCEAN 分布生成简短人格描述标签。"""
        tags: list[str] = []
        if self.extraversion < 0.35:
            tags.append("内倾")
        elif self.extraversion > 0.65:
            tags.append("外向")

        if self.agreeableness > 0.65:
            tags.append("亲和")
        elif self.agreeableness < 0.35:
            tags.append("对立")

        if self.conscientiousness > 0.65:
            tags.append("自律")
        elif self.conscientiousness < 0.35:
            tags.append("散漫")

        if self.neuroticism > 0.65:
            tags.append("敏感")
        elif self.neuroticism < 0.35:
            tags.append("稳健")

        if self.openness > 0.65:
            tags.append("好奇")
        elif self.openness < 0.35:
            tags.append("保守")

        return "-".join(tags) if tags else "平衡型"

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("history", None)  # 不序列化漂移历史到 NPC profile（太长）
        return d


@dataclass
class ActionBias:
    """
    NPC 在当前情境下的行为倾向分数（0-1，越高越倾向该行为）。
    供 NPCAgent 在生成回应时参考。
    """
    cooperate:   float = 0.5   # 合作/帮助主角
    resist:      float = 0.5   # 抵制/拒绝
    deceive:     float = 0.2   # 欺骗/掩盖信息
    flee:        float = 0.3   # 回避/逃离冲突
    aggress:     float = 0.2   # 主动攻击/对抗
    disclose:    float = 0.4   # 主动透露信息
    neutral:     float = 0.4   # 中立观望
    dominant_action: str = "neutral"


# ── 核心函数 ─────────────────────────────────────────────────────────────────

def load_from_npc_data(profile_json: dict) -> PsycheProfile:
    """
    从 NPC 档案 JSON 解析 OCEAN 数据。

    支持两种格式：
      1. 直接有 "ocean" 子键：{"ocean": {"openness": 0.7, ...}}
      2. 顶层有 "psyche" 子键（与 05-character-consistency.mdc 格式一致）
      3. 顶层直接有 OCEAN 字段
      4. 无数据时返回中性值

    Parameters
    ----------
    profile_json : NPC profile dict（来自 DB npc_profiles.profile_json）

    Returns
    -------
    PsycheProfile 实例
    """
    src: dict = {}

    if "ocean" in profile_json:
        src = profile_json["ocean"]
    elif "psyche" in profile_json and isinstance(profile_json["psyche"], dict):
        psyche = profile_json["psyche"]
        src = psyche.get("ocean", psyche)
    else:
        # 尝试直接从顶层读取
        for key in ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"):
            if key in profile_json:
                src[key] = profile_json[key]

    try:
        return PsycheProfile(
            openness          = float(src.get("openness", src.get("O", 0.5))),
            conscientiousness = float(src.get("conscientiousness", src.get("C", 0.5))),
            extraversion      = float(src.get("extraversion", src.get("E", 0.5))),
            agreeableness     = float(src.get("agreeableness", src.get("A", 0.5))),
            neuroticism       = float(src.get("neuroticism", src.get("N", 0.5))),
            dominant_trait    = src.get("dominant_trait", ""),
            personality_label = src.get("personality_label", ""),
        )
    except Exception as e:
        logger.warning(f"[psyche] load_from_npc_data failed: {e}, using defaults")
        return PsycheProfile()


def compute_action_bias(
    psyche: PsycheProfile,
    context: dict[str, Any] | None = None,
) -> ActionBias:
    """
    基于 OCEAN 分布 + 情境信息计算 NPC 行为偏向。

    情境修正因子（来自 context dict）：
      threat_level   : 0-1  当前环境威胁程度（越高越倾向逃跑/抵抗）
      trust_level    : 0-1  NPC 对主角的信任度（越高越倾向合作/透露）
      goal_pressure  : 0-1  NPC 当前目标紧迫度（越高越倾向采取主动行动）

    Returns
    -------
    ActionBias 实例，dominant_action 为得分最高的行为键
    """
    ctx = context or {}
    threat   = float(ctx.get("threat_level",  0.3))
    trust    = float(ctx.get("trust_level",   0.5))
    pressure = float(ctx.get("goal_pressure", 0.4))

    O, C, E, A, N = (
        psyche.openness, psyche.conscientiousness,
        psyche.extraversion, psyche.agreeableness, psyche.neuroticism,
    )

    # 合作：高宜人性 + 高信任 → 更倾向合作
    cooperate = _sigmoid(A * 0.6 + trust * 0.4 - threat * 0.3)

    # 抵制：低宜人性 + 低信任 + 威胁高 → 倾向抵制
    resist = _sigmoid((1 - A) * 0.5 + (1 - trust) * 0.3 + threat * 0.2)

    # 欺骗：低宜人性 + 高责任感（目的性） + 低外向 → 冷静撒谎
    deceive = _sigmoid((1 - A) * 0.4 + C * 0.2 + (1 - E) * 0.1 + (1 - trust) * 0.3)

    # 逃跑：高神经质 + 高威胁 → 回避
    flee = _sigmoid(N * 0.5 + threat * 0.5 - C * 0.2)

    # 攻击：低宜人性 + 低神经质（冷静攻击） + 高威胁
    aggress = _sigmoid((1 - A) * 0.4 + (1 - N) * 0.2 + threat * 0.4 - trust * 0.2)

    # 透露信息：高开放性 + 高宜人性 + 高信任
    disclose = _sigmoid(O * 0.3 + A * 0.3 + trust * 0.4)

    # 中立：中等一切
    neutral = _sigmoid(0.5 - abs(O - 0.5) - abs(A - 0.5) - abs(N - 0.5))

    bias = ActionBias(
        cooperate=cooperate,
        resist=resist,
        deceive=deceive,
        flee=flee,
        aggress=aggress,
        disclose=disclose,
        neutral=neutral,
    )

    scores = {
        "cooperate": cooperate, "resist": resist, "deceive": deceive,
        "flee": flee, "aggress": aggress, "disclose": disclose, "neutral": neutral,
    }
    bias.dominant_action = max(scores, key=scores.__getitem__)
    return bias


def apply_drift(
    psyche: PsycheProfile,
    event_type: str,
    intensity: float = 0.5,
) -> PsycheProfile:
    """
    根据重大事件对 OCEAN 产生有限度的漂移。

    Parameters
    ----------
    psyche     : 当前 PsycheProfile
    event_type : 事件类型键（见 _EVENT_DRIFT_MAP）
    intensity  : 事件强度 0-1（影响漂移幅度）

    Returns
    -------
    新的 PsycheProfile（原对象不可变）
    """
    delta = _EVENT_DRIFT_MAP.get(event_type, {})
    if not delta:
        logger.debug(f"[psyche] unknown event_type: {event_type}, no drift applied")
        return psyche

    scale = max(0.0, min(1.0, float(intensity))) * _DRIFT_DECAY

    new_vals: dict[str, float] = {}
    for trait in ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"):
        current = getattr(psyche, trait)
        d = delta.get(trait, 0.0) * scale
        new_val = max(_DRIFT_FLOOR, min(_DRIFT_CEIL, current + d))
        new_vals[trait] = new_val

    new_history = (psyche.history + [{"event": event_type, "intensity": intensity}])[-10:]

    return PsycheProfile(
        openness          = new_vals["openness"],
        conscientiousness = new_vals["conscientiousness"],
        extraversion      = new_vals["extraversion"],
        agreeableness     = new_vals["agreeableness"],
        neuroticism       = new_vals["neuroticism"],
        history           = new_history,
    )


def describe(psyche: PsycheProfile, lang: str = "zh") -> str:
    """
    生成 NPC 心理状态的自然语言简述（供提示词注入使用）。

    Parameters
    ----------
    psyche : PsycheProfile
    lang   : "zh"（中文，默认）

    Returns
    -------
    str  单段描述文字，≤80 字
    """
    O, C, E, A, N = (
        psyche.openness, psyche.conscientiousness,
        psyche.extraversion, psyche.agreeableness, psyche.neuroticism,
    )

    parts: list[str] = []

    if E > 0.65:
        parts.append("外向主动")
    elif E < 0.35:
        parts.append("内敛寡言")

    if A > 0.65:
        parts.append("乐于合作")
    elif A < 0.35:
        parts.append("警惕多疑")

    if C > 0.65:
        parts.append("目标明确")
    elif C < 0.35:
        parts.append("随性而为")

    if N > 0.65:
        parts.append("情绪易波动")
    elif N < 0.35:
        parts.append("处事冷静")

    if O > 0.65:
        parts.append("对新信息开放")
    elif O < 0.35:
        parts.append("固守既有立场")

    label = psyche.personality_label or "平衡型"
    desc = "；".join(parts) if parts else "性格均衡"
    return f"[{label}] {desc}。"


# ── 内部工具 ─────────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    """将任意实数映射到 (0, 1)，中心 0.5 对应 0。"""
    return 1 / (1 + math.exp(-4 * x))


# 事件类型 → OCEAN 漂移方向（正=升高，负=降低）
# 仅描述方向，实际幅度由 intensity * _DRIFT_DECAY 控制
_EVENT_DRIFT_MAP: dict[str, dict[str, float]] = {
    "betrayal":        {"agreeableness": -1.0, "neuroticism":  0.5, "extraversion": -0.3},
    "rescue":          {"agreeableness":  0.5, "extraversion":  0.3, "neuroticism": -0.3},
    "success_major":   {"conscientiousness": 0.3, "neuroticism": -0.5, "extraversion": 0.2},
    "failure_major":   {"neuroticism":  0.7, "conscientiousness": -0.3},
    "stress":          {"neuroticism":  0.8, "agreeableness": -0.3, "openness": -0.2},
    "discovery":       {"openness":     0.8, "extraversion":  0.2},
    "loss":            {"neuroticism":  0.6, "agreeableness": -0.2, "extraversion": -0.4},
    "bond_formed":     {"agreeableness": 0.5, "extraversion":  0.3, "neuroticism": -0.2},
    "threat_faced":    {"neuroticism":  0.4, "conscientiousness":  0.3},
    "moral_conflict":  {"openness":     0.4, "neuroticism":  0.3, "conscientiousness": -0.2},
}


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def main(
    profile: dict | None = None,
    event: str | None = None,
    intensity: float = 0.5,
    context: dict | None = None,
) -> dict:
    """核心入口，供 import 或 MCP 包装调用。"""
    psyche = load_from_npc_data(profile or {})
    result: dict[str, Any] = {
        "ok": True,
        "profile": psyche.to_dict(),
        "description": describe(psyche),
    }

    if context is not None:
        bias = compute_action_bias(psyche, context)
        result["action_bias"] = {
            "cooperate": round(bias.cooperate, 3),
            "resist":    round(bias.resist, 3),
            "deceive":   round(bias.deceive, 3),
            "flee":      round(bias.flee, 3),
            "aggress":   round(bias.aggress, 3),
            "disclose":  round(bias.disclose, 3),
            "neutral":   round(bias.neutral, 3),
            "dominant":  bias.dominant_action,
        }

    if event:
        new_psyche = apply_drift(psyche, event, intensity)
        result["drifted_profile"] = new_psyche.to_dict()
        result["drift_description"] = describe(new_psyche)

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OCEAN Psyche Engine CLI")
    parser.add_argument("--profile", default="{}", help="NPC profile JSON 字符串")
    parser.add_argument("--event", default=None, help="重大事件类型（如 betrayal / stress）")
    parser.add_argument("--intensity", type=float, default=0.5, help="事件强度 0-1")
    parser.add_argument("--context", default=None, help="情境 JSON（threat_level/trust_level/goal_pressure）")
    args = parser.parse_args()

    try:
        profile_data = json.loads(args.profile)
    except Exception:
        profile_data = {}

    try:
        ctx_data = json.loads(args.context) if args.context else None
    except Exception:
        ctx_data = None

    result = main(profile=profile_data, event=args.event, intensity=args.intensity, context=ctx_data)
    print(json.dumps(result, ensure_ascii=False, indent=2))

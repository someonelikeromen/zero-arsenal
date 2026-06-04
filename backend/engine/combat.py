"""
engine/combat.py — 部位 HP 伤害计算引擎
用途: 处理战斗回合的伤害分配、状态效果、战斗结束判定。
参考设计文档 02-system-architecture.md §4（engine/combat.py）

用法:
    from backend.engine.combat import CombatEngine, DamageResult
    result = CombatEngine.apply_damage(char_data, damage=30, part="torso")

MCP集成: 可包装为 MCP tool，函数签名见 CombatEngine 各方法。
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── 部位配置 ─────────────────────────────────────────────────────────────────

# 部位 → (默认最大HP, 暴击乘数, 中文名)
_PART_CONFIG: dict[str, tuple[int, float, str]] = {
    "head":      (50,  2.0, "头部"),
    "torso":     (200, 1.0, "躯干"),
    "left_arm":  (80,  0.8, "左臂"),
    "right_arm": (80,  0.8, "右臂"),
    "left_leg":  (100, 0.9, "左腿"),
    "right_leg": (100, 0.9, "右腿"),
}

# 状态效果持续回合数（默认）
_STATUS_DURATION: dict[str, int] = {
    "bleeding":   3,
    "fractured":  5,
    "stunned":    1,
    "paralyzed":  2,
    "burned":     4,
    "poisoned":   6,
}

# 出血每轮额外伤害
_BLEEDING_DAMAGE_PER_TURN = 5


# ── 数据类 ────────────────────────────────────────────────────────────────────

@dataclass
class DamageResult:
    """单次伤害计算结果。"""
    target_part: str                       # 受击部位 key
    part_name: str                         # 部位中文名
    raw_damage: int                        # 原始伤害值
    absorbed_by_armor: int                 # 护甲吸收量
    actual_damage: int                     # 实际造成伤害
    hp_before: int
    hp_after: int
    new_status_effects: list[str] = field(default_factory=list)  # 新触发的状态效果
    is_critical: bool = False
    knocked_out: bool = False              # 该部位 HP <= 0（失能）
    is_fatal: bool = False                 # 躯干/头部 HP <= 0（死亡判定）
    narrative_hint: str = ""               # 供 DM 参考的叙事提示


@dataclass
class HealResult:
    """单次治疗计算结果。"""
    target_part: str
    part_name: str
    heal_amount: int
    hp_before: int
    hp_after: int
    removed_status_effects: list[str] = field(default_factory=list)


# R-M15：原 `CombatRoundResult`（整轮聚合结算）已移除 —— 全仓无任何生产者/消费者。
# 战斗实际按「单次施害」粒度结算：`apply_damage` 工具（builtin_tools.py）与
# /engine/combat 路由直接消费 `DamageResult` / `HealResult`，无回合聚合需求。
# 若未来引入回合制聚合，应在有明确消费方时再重新引入并接线，而非留死结构。


# ── 伤害计算引擎 ──────────────────────────────────────────────────────────────

class CombatEngine:
    """
    战斗伤害计算引擎。
    无状态，所有方法均为 classmethod / staticmethod。
    直接操作 character_data 字典（与数据库 character_cards 结构对齐）。
    """

    # ── 核心接口 ──────────────────────────────────────────────────────────────

    @classmethod
    def apply_damage(
        cls,
        char_data: dict,
        damage: int,
        *,
        part: str = "torso",
        damage_type: str = "physical",   # physical / qi / magic / tech
        is_critical: bool | None = None,  # None = 自动计算
        attacker_tier: int = 1,
        bypass_armor: bool = False,
    ) -> DamageResult:
        """
        对指定部位施加伤害，返回 DamageResult。
        char_data 会被原地修改（attributes.hp.parts[part]）。

        Args:
            char_data:    角色卡字典（来自 DB character_cards.attributes_json）
            damage:       原始伤害值
            part:         受击部位（head/torso/left_arm/right_arm/left_leg/right_leg）
            damage_type:  伤害类型（影响护甲减免公式）
            is_critical:  强制暴击；None = 按 5% 概率随机
            attacker_tier: 攻击方等级（影响穿甲系数）
            bypass_armor: 是否忽略护甲（真伤）
        """
        part = part if part in _PART_CONFIG else "torso"
        cfg_max, crit_mult, part_name = _PART_CONFIG[part]

        attrs = char_data.setdefault("attributes", {})
        hp_node = attrs.setdefault("hp", {})
        parts_node = hp_node.setdefault("parts", {})
        part_node = parts_node.setdefault(part, {
            "current": cfg_max,
            "max": cfg_max,
            "armor": 0,
            "status_effects": [],
        })

        hp_before = int(part_node.get("current", cfg_max))
        armor = int(part_node.get("armor", 0)) if not bypass_armor else 0

        # ── 暴击判定 ──────────────────────────────────────────────────────────
        if is_critical is None:
            is_critical = random.random() < 0.05
        if is_critical:
            damage = int(damage * crit_mult)

        # ── 护甲减免 ──────────────────────────────────────────────────────────
        # 穿甲系数 = attacker_tier / (attacker_tier + 5)，tier=1 约 16.7% 穿甲
        penetration = attacker_tier / (attacker_tier + 5) if not bypass_armor else 1.0
        effective_armor = max(0, int(armor * (1 - penetration)))
        # 魔法/气功伤害护甲减免效率降低 50%
        if damage_type in ("qi", "magic"):
            effective_armor = int(effective_armor * 0.5)
        absorbed = min(effective_armor, damage)
        actual = max(0, damage - absorbed)

        hp_after = max(0, hp_before - actual)
        part_node["current"] = hp_after

        # ── 状态效果触发 ──────────────────────────────────────────────────────
        new_effects: list[str] = []
        effects = list(part_node.get("status_effects", []))
        max_hp = int(part_node.get("max", cfg_max))
        ratio_after = hp_after / max_hp if max_hp > 0 else 0.0

        if actual > 0:
            # 骨折：部位 HP < 30% 且非骨折状态
            if ratio_after < 0.30 and "fractured" not in effects:
                effects.append("fractured")
                new_effects.append("fractured")
            # 出血：物理暴击 或 武器伤害 > 20
            if damage_type == "physical" and (is_critical or actual >= 20) and "bleeding" not in effects:
                effects.append("bleeding")
                new_effects.append("bleeding")
            # 头部击晕：头部实际伤害 > 15
            if part == "head" and actual >= 15 and "stunned" not in effects:
                effects.append("stunned")
                new_effects.append("stunned")

        part_node["status_effects"] = effects

        knocked_out = hp_after <= 0
        is_fatal = knocked_out and part in ("head", "torso")

        # ── 叙事提示 ──────────────────────────────────────────────────────────
        hints: list[str] = []
        if is_critical:
            hints.append("重击")
        if knocked_out:
            hints.append(f"{part_name}失能")
        if "fractured" in new_effects:
            hints.append("骨折")
        if "bleeding" in new_effects:
            hints.append("出血")
        if "stunned" in new_effects:
            hints.append("眩晕")
        narrative_hint = f"[{part_name}受创：{actual}点]" + (
            f"（{', '.join(hints)}）" if hints else ""
        )

        return DamageResult(
            target_part=part,
            part_name=part_name,
            raw_damage=damage,
            absorbed_by_armor=absorbed,
            actual_damage=actual,
            hp_before=hp_before,
            hp_after=hp_after,
            new_status_effects=new_effects,
            is_critical=is_critical,
            knocked_out=knocked_out,
            is_fatal=is_fatal,
            narrative_hint=narrative_hint,
        )

    @classmethod
    def apply_heal(
        cls,
        char_data: dict,
        heal_amount: int,
        *,
        part: str = "torso",
        remove_status: list[str] | None = None,
    ) -> HealResult:
        """
        对指定部位施加治疗效果，返回 HealResult。
        remove_status: 同时移除指定状态效果列表（如 ["bleeding", "fractured"]）。
        """
        part = part if part in _PART_CONFIG else "torso"
        cfg_max, _, part_name = _PART_CONFIG[part]

        attrs = char_data.setdefault("attributes", {})
        hp_node = attrs.setdefault("hp", {})
        parts_node = hp_node.setdefault("parts", {})
        part_node = parts_node.setdefault(part, {
            "current": cfg_max, "max": cfg_max,
            "armor": 0, "status_effects": [],
        })

        max_hp = int(part_node.get("max", cfg_max))
        hp_before = int(part_node.get("current", max_hp))
        hp_after = min(max_hp, hp_before + heal_amount)
        part_node["current"] = hp_after

        removed: list[str] = []
        if remove_status:
            effects = part_node.get("status_effects", [])
            for eff in remove_status:
                if eff in effects:
                    effects.remove(eff)
                    removed.append(eff)
            part_node["status_effects"] = effects

        return HealResult(
            target_part=part,
            part_name=part_name,
            heal_amount=hp_after - hp_before,
            hp_before=hp_before,
            hp_after=hp_after,
            removed_status_effects=removed,
        )

    @classmethod
    def apply_turn_effects(cls, char_data: dict) -> dict[str, int]:
        """
        处理回合开始的持续状态效果（出血伤害等）。
        返回 {部位key: 实际伤害} 的字典。
        """
        damage_dealt: dict[str, int] = {}
        attrs = char_data.get("attributes", {})
        parts_node = attrs.get("hp", {}).get("parts", {})

        for part_key, part_node in parts_node.items():
            if not isinstance(part_node, dict):
                continue
            effects = part_node.get("status_effects", [])
            if "bleeding" in effects:
                hp_before = int(part_node.get("current", 0))
                hp_after = max(0, hp_before - _BLEEDING_DAMAGE_PER_TURN)
                part_node["current"] = hp_after
                damage_dealt[part_key] = hp_before - hp_after

        return damage_dealt

    @classmethod
    def get_overall_hp_ratio(cls, char_data: dict) -> float:
        """返回全身综合 HP 比例（0.0 ~ 1.0）。"""
        attrs = char_data.get("attributes", {})
        parts_node = attrs.get("hp", {}).get("parts", {})
        if not parts_node:
            hp = attrs.get("hp", {})
            if isinstance(hp, dict):
                cur = int(hp.get("current", hp.get("base", 100)))
                mx  = int(hp.get("max", 100))
                return cur / mx if mx > 0 else 0.0
            return 1.0

        total_cur = total_max = 0
        for part_node in parts_node.values():
            if isinstance(part_node, dict):
                total_cur += int(part_node.get("current", 0))
                total_max += int(part_node.get("max", 100))
        return total_cur / total_max if total_max > 0 else 0.0

    @classmethod
    def is_incapacitated(cls, char_data: dict) -> bool:
        """判断角色是否因 HP 判定战斗失能（躯干或头部 HP = 0）。"""
        attrs = char_data.get("attributes", {})
        parts_node = attrs.get("hp", {}).get("parts", {})
        for key in ("head", "torso"):
            part = parts_node.get(key, {})
            if isinstance(part, dict) and int(part.get("current", 1)) <= 0:
                return True
        return False

    @classmethod
    def roll_hit_location(cls, bias: str = "none") -> str:
        """
        随机决定命中部位（可通过 bias 偏向某区域）。
        bias: "upper" / "lower" / "head" / "none"
        """
        weights = {
            "head":      5,
            "torso":     35,
            "left_arm":  15,
            "right_arm": 15,
            "left_leg":  15,
            "right_leg": 15,
        }
        if bias == "upper":
            weights["head"] += 10
            weights["torso"] += 10
        elif bias == "lower":
            weights["left_leg"] += 15
            weights["right_leg"] += 15
        elif bias == "head":
            weights["head"] += 30

        parts = list(weights.keys())
        wts   = list(weights.values())
        return random.choices(parts, weights=wts, k=1)[0]

    @classmethod
    def format_combat_summary(cls, char_data: dict) -> str:
        """返回单行战斗状态摘要，供 DM 提示词快速参考。"""
        ratio = cls.get_overall_hp_ratio(char_data)
        incap = cls.is_incapacitated(char_data)
        parts_node = char_data.get("attributes", {}).get("hp", {}).get("parts", {})
        all_effects: list[str] = []
        for p in parts_node.values():
            if isinstance(p, dict):
                all_effects.extend(p.get("status_effects", []))
        unique_effects = list(dict.fromkeys(all_effects))  # 去重保序

        status = "失能" if incap else (
            "危重" if ratio < 0.30 else
            "重伤" if ratio < 0.50 else
            "轻伤" if ratio < 0.80 else "健康"
        )
        effect_str = f"（{', '.join(unique_effects[:4])}）" if unique_effects else ""
        return f"HP {ratio:.0%} | {status}{effect_str}"

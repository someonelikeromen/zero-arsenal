"""
角色卡 v4 Schema — 完整 JSON Schema 定义和构造 helper。
设计文档 06-data-model.md §2 角色卡 v4 Schema

本模块在保持向后兼容（旧消费方读取扁平 attributes / max_hp / current_hp /
physical_state / mental_state / skills / inventory）的前提下，补齐设计 §2.1 要求的
完整 v4 结构：meta / identity / attributes(schema+values) / body_parts(六部位) /
energy_pools / loadout / psychology(OCEAN) / economy(badges/tier/tier_sub/cash) /
relationships / achievements。

校验（R-M14）：validate_character() 优先使用 jsonschema 库做完整 schema 校验，
缺失依赖时回落到内置手写规则校验，二者错误合并返回。
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "4.0.0"

# jsonschema 为可选依赖（R-M14）：存在时做完整 draft-07 校验，否则回落手写规则
try:  # pragma: no cover - import guard
    import jsonschema as _jsonschema
    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover
    _jsonschema = None  # type: ignore[assignment]
    _HAS_JSONSCHEMA = False


# ── JSON Schema（完整 v4，设计 06-data-model.md §2.1）────────────────────────────
#
# 设计原则：
#   - required 仅保留 ["name", "plugin_key"]，以兼容历史上已生成的简化卡（避免
#     旧卡加载即报必填缺失）。完整 v4 字段全部以 properties 声明，供校验/补全使用。
#   - attributes 同时容纳「扁平 5 维（strength..empathy）」与设计的「schema + values」
#     体系（additionalProperties: true）。
#   - 同时保留 body_parts（六部位 hp_max/hp_current，设计版）与 physical_state
#     （四部位 hp_ratio，历史简化版），消费方按需读取。

_BODY_PART = {
    "type": "object",
    "properties": {
        "hp_max":         {"type": "integer", "minimum": 0},
        "hp_current":     {"type": "integer", "minimum": 0},
        "armor":          {"type": "integer", "minimum": 0},
        "status_effects": {"type": "array", "items": {"type": "string"}},
    },
}

_ENERGY_POOL = {
    "type": "object",
    "required": ["name", "current", "max"],
    "properties": {
        "name":           {"type": "string"},
        "current":        {"type": "number", "minimum": 0},
        "max":            {"type": "number", "minimum": 0},
        "regen_per_turn": {"type": "number"},
        "type":           {"type": "string",
                           "enum": ["qi", "mana", "stamina", "tech_charge", "custom"]},
    },
}

_ABILITY = {
    "type": "object",
    "required": ["id", "name"],
    "properties": {
        "id":          {"type": "string"},
        "name":        {"type": "string"},
        "description": {"type": "string"},
        "tier":        {"type": "integer"},
        "tier_sub":    {"type": "string"},
        "source":      {"type": "string"},
        "proficiency": {"type": "integer", "minimum": 0, "maximum": 100},
    },
}

CHARACTER_V4_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "https://zero-arsenal.local/schemas/character-card-v4.json",
    "title": "CharacterCardV4",
    "version": SCHEMA_VERSION,
    "type": "object",
    "required": ["name", "plugin_key"],
    "properties": {
        "name": {"type": "string", "description": "角色名称"},
        "plugin_key": {
            "type": "string",
            "description": "所在世界插件标识，如 muv_luv / crossover",
        },

        # ── meta（设计 §2.1 meta）─────────────────────────────────────────────
        "meta": {
            "type": "object",
            "description": "卡片元数据",
            "properties": {
                "schema_version": {"type": "string"},
                "plugin_key":   {"type": "string"},
                "card_id":        {"type": "string"},
                "created_at":     {"type": ["number", "string"]},
                "updated_at":     {"type": ["number", "string"]},
                "session_id":     {"type": "string"},
                "writing_style":  {"type": "string"},
            },
        },

        # ── identity（设计 §2.1 identity）─────────────────────────────────────
        "identity": {
            "type": "object",
            "properties": {
                "name":          {"type": "string"},
                "aliases":       {"type": "array", "items": {"type": "string"}},
                "age":           {"type": ["number", "string"]},
                "gender":        {"type": "string",
                                  "enum": ["male", "female", "other", "unknown"]},
                "origin_world":  {"type": "string"},
                "current_world": {"type": "string"},
                "cycle_count":   {"type": "integer", "minimum": 0},
                "appearance": {
                    "type": "object",
                    "properties": {
                        "hair_color":  {"type": "string"},
                        "hair_style":  {"type": "string"},
                        "eye_color":   {"type": "string"},
                        "height_cm":   {"type": "number"},
                        "build":       {"type": "string",
                                        "enum": ["slim", "athletic", "muscular",
                                                 "heavy", "petite", "average"]},
                        "distinctive_features": {"type": "array",
                                                 "items": {"type": "string"}},
                        "typical_outfit": {"type": "string"},
                    },
                },
            },
        },

        # ── attributes（兼容扁平 5 维 + 设计 schema/values 体系）──────────────
        "attributes": {
            "type": "object",
            "description": "基础属性（兼容扁平 5 维与 schema/values 体系）",
            "properties": {
                "strength":     {"type": "integer", "minimum": 1, "maximum": 10},
                "dexterity":    {"type": "integer", "minimum": 1, "maximum": 10},
                "intelligence": {"type": "integer", "minimum": 1, "maximum": 10},
                "will":         {"type": "integer", "minimum": 1, "maximum": 10},
                "empathy":      {"type": "integer", "minimum": 1, "maximum": 10},
                "schema": {"type": "string",
                           "enum": ["standard_5d", "standard_10d",
                                    "cultivation_8d", "custom"]},
                "values": {"type": "object",
                           "additionalProperties": {"type": "number"}},
            },
            "additionalProperties": True,
        },

        # ── 历史简化字段（向后兼容，消费方仍在读取）──────────────────────────
        "max_hp":     {"type": "integer", "description": "最大生命值（兼容字段）"},
        "current_hp": {"type": "integer", "description": "当前生命值（兼容字段）"},
        "physical_state": {
            "type": "object",
            "description": "生理状态（四部位 hp_ratio，历史兼容字段）",
            "properties": {
                "body_parts": {
                    "type": "object",
                    "properties": {
                        "head":  {"type": "object"},
                        "chest": {"type": "object"},
                        "arms":  {"type": "object"},
                        "legs":  {"type": "object"},
                    },
                }
            },
        },
        "mental_state": {
            "type": "object",
            "description": "心理状态（历史兼容字段）",
            "properties": {
                "stress":       {"type": "integer", "minimum": 0, "maximum": 100},
                "morale":       {"type": "integer", "minimum": 0, "maximum": 100},
                "trauma_level": {"type": "integer", "minimum": 0, "maximum": 5},
            },
        },
        "skills": {
            "type": "object",
            "description": "技能组 {skill_name: level}",
            "additionalProperties": {"type": "integer", "minimum": 0},
        },
        "inventory": {
            "type": "array",
            "description": "物品栏（历史字段；v4 推荐使用 loadout.equipped）",
            "items": {
                "type": "object",
                "properties": {
                    "name":       {"type": "string"},
                    "type":       {"type": "string"},
                    "quantity":   {"type": "integer", "minimum": 0},
                    "properties": {"type": "object"},
                },
            },
        },

        # ── 六部位身体状态（设计 §2.1 body_parts）──────────────────────────────
        "body_parts": {
            "type": "object",
            "description": "六部位身体状态（hp_max/hp_current/armor/status_effects）",
            "properties": {
                "head":      _BODY_PART,
                "torso":     _BODY_PART,
                "left_arm":  _BODY_PART,
                "right_arm": _BODY_PART,
                "left_leg":  _BODY_PART,
                "right_leg": _BODY_PART,
            },
        },

        # ── 能量池（设计 §2.1 energy_pools）───────────────────────────────────
        "energy_pools": {
            "type": "array",
            "description": "能量池列表（内力/体力/特殊能量）",
            "items": _ENERGY_POOL,
        },

        # ── 技能与装备配置（设计 §2.1 loadout）────────────────────────────────
        "loadout": {
            "type": "object",
            "properties": {
                "passive_abilities":      {"type": "array", "items": _ABILITY},
                "power_sources":          {"type": "array", "items": {"type": "object"}},
                "application_techniques": {"type": "array", "items": {"type": "object"}},
                "equipped":               {"type": "array", "items": {"type": "object"}},
            },
        },

        # ── 心理模型（设计 §2.1 psychology，OCEAN）────────────────────────────
        "psychology": {
            "type": "object",
            "properties": {
                "ocean": {
                    "type": "object",
                    "properties": {
                        "openness":          {"type": "number", "minimum": 0, "maximum": 100},
                        "conscientiousness": {"type": "number", "minimum": 0, "maximum": 100},
                        "extraversion":      {"type": "number", "minimum": 0, "maximum": 100},
                        "agreeableness":     {"type": "number", "minimum": 0, "maximum": 100},
                        "neuroticism":       {"type": "number", "minimum": 0, "maximum": 100},
                    },
                },
                "stress":   {"type": "number", "minimum": 0, "maximum": 100},
                "morale":   {"type": "number", "minimum": 0, "maximum": 100},
                "clarity":  {"type": "number", "minimum": 0, "maximum": 100},
                "emotion_state": {"type": "string",
                                  "enum": ["calm", "anxious", "angry", "joyful",
                                           "fearful", "grieving", "determined",
                                           "numb", "elated", "despair"]},
                "traumas":  {"type": "array", "items": {"type": "object"}},
                "beliefs":  {"type": "array", "items": {"type": "object"}},
                "core_values": {"type": "array", "items": {"type": "string"},
                                "maxItems": 3},
                "behavior_patterns":  {"type": "string"},
                "emotional_triggers": {"type": "string"},
            },
        },

        # ── 关系网络（设计 §2.1 relationships 为数组；兼容历史 dict 形态）──────
        "relationships": {
            "description": "关系网络（v4 数组形态；兼容历史 {npc_name: {...}} dict 形态）",
            "oneOf": [
                {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["npc_id", "name"],
                        "properties": {
                            "npc_id":   {"type": "string"},
                            "name":     {"type": "string"},
                            "type":     {"type": "string",
                                         "enum": ["ally", "friend", "neutral", "rival",
                                                  "hostile", "mentor", "student",
                                                  "romantic", "family"]},
                            "affinity": {"type": "integer", "minimum": -100, "maximum": 100},
                            "trust":    {"type": "integer", "minimum": 0, "maximum": 100},
                            "tags":     {"type": "array", "items": {"type": "string"}},
                            "last_interaction_turn": {"type": "integer"},
                        },
                    },
                },
                {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "affinity":      {"type": "integer", "minimum": -100, "maximum": 100},
                            "known_secrets": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            ],
        },

        # ── 经济（设计 §2.1 economy：points/badges/tier/tier_sub/cash）─────────
        "economy": {
            "type": "object",
            "properties": {
                "points":   {"type": "integer", "minimum": 0},
                "badges":   {"type": "integer", "minimum": 0},
                "tier":     {"type": "integer", "minimum": 0, "maximum": 10},
                "tier_sub": {"type": "string", "enum": ["L", "M", "U", ""]},
                "cash":     {"type": "object", "additionalProperties": {"type": "number"}},
                # 历史兼容字段
                "currency":       {"type": "object"},
                "special_tokens": {"type": "object"},
            },
        },

        # ── 成就（设计 §2.1 achievements）─────────────────────────────────────
        "achievements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id":          {"type": "string"},
                    "name":        {"type": "string"},
                    "description": {"type": "string"},
                    "unlocked_at": {"type": "number"},
                },
            },
        },
    },
}


# ── Helper：构造默认 v4 卡（完整结构 + 历史兼容字段）──────────────────────────

def _default_body_parts() -> dict:
    """六部位满血默认值（设计 §8.4 _migrate_3_to_4 默认部位 HP）。"""
    base = {"armor": 0, "status_effects": []}
    return {
        "head":      {**base, "hp_max": 60,  "hp_current": 60},
        "torso":     {**base, "hp_max": 100, "hp_current": 100},
        "left_arm":  {**base, "hp_max": 70,  "hp_current": 70},
        "right_arm": {**base, "hp_max": 70,  "hp_current": 70},
        "left_leg":  {**base, "hp_max": 80,  "hp_current": 80},
        "right_leg": {**base, "hp_max": 80,  "hp_current": 80},
    }


def create_default_character(
    name: str,
    plugin_key: str = "crossover",
) -> dict:
    """创建具有默认值的 v4 角色卡（完整结构，含历史兼容字段）。"""
    strength = 5
    max_hp = strength * 10
    now_ts = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()

    attributes = {
        "strength":     strength,
        "dexterity":    5,
        "intelligence": 5,
        "will":         5,
        "empathy":      5,
    }

    return {
        "name": name,
        "plugin_key": plugin_key,
        # 完整 v4
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "plugin_key":   plugin_key,
            "card_id":        str(uuid.uuid4()),
            "created_at":     now_ts,
            "updated_at":     now_ts,
            "session_id":     "",
            "writing_style":  "网文",
        },
        "identity": {
            "name":          name,
            "aliases":       [],
            "gender":        "unknown",
            "current_world": plugin_key,
            "cycle_count":   0,
            "appearance":    {},
        },
        "attributes": {
            **attributes,
            "schema": "standard_5d",
            "values": dict(attributes),
        },
        # 历史兼容字段
        "max_hp":     max_hp,
        "current_hp": max_hp,
        "physical_state": {
            "body_parts": {
                "head":  {"hp_ratio": 1.0},
                "chest": {"hp_ratio": 1.0},
                "arms":  {"hp_ratio": 1.0},
                "legs":  {"hp_ratio": 1.0},
            }
        },
        "mental_state": {
            "stress":       0,
            "morale":       80,
            "trauma_level": 0,
        },
        "skills": {},
        "inventory": [],
        # 完整 v4 结构
        "body_parts": _default_body_parts(),
        "energy_pools": [
            {"name": "体力", "current": 100.0, "max": 100.0,
             "regen_per_turn": 5.0, "type": "stamina"},
        ],
        "loadout": {
            "passive_abilities": [],
            "power_sources": [],
            "application_techniques": [],
            "equipped": [],
        },
        "psychology": {
            "ocean": {
                "openness": 50, "conscientiousness": 50, "extraversion": 50,
                "agreeableness": 50, "neuroticism": 50,
            },
            "stress": 0,
            "morale": 80,
            "clarity": 100,
            "emotion_state": "calm",
            "traumas": [],
            "beliefs": [],
            "core_values": [],
            "behavior_patterns": "",
            "emotional_triggers": "",
        },
        "relationships": {},
        "economy": {
            "points":         0,
            "badges":         0,
            "tier":           0,
            "tier_sub":       "",
            "cash":           {},
            # 历史兼容字段
            "currency":       {},
            "special_tokens": {},
        },
        "achievements": [],
    }


# ── 校验（R-M14：jsonschema + 手写规则）──────────────────────────────────────

def _manual_validate(data: dict) -> list[str]:
    """内置手写规则校验（jsonschema 缺失时的回落，且永远执行作为补充）。"""
    errors: list[str] = []

    for required in ("name", "plugin_key"):
        if not data.get(required):
            errors.append(f"缺少必填字段: {required}")

    attrs = data.get("attributes", {}) or {}
    for attr in ("strength", "dexterity", "intelligence", "will", "empathy"):
        val = attrs.get(attr)
        if val is not None and not (1 <= val <= 10):
            errors.append(f"attributes.{attr} 必须在 1-10 范围内，当前值: {val}")

    strength = attrs.get("strength", 5)
    expected_max_hp = strength * 10
    max_hp = data.get("max_hp", expected_max_hp)
    current_hp = data.get("current_hp", max_hp)
    if current_hp is not None and max_hp is not None and current_hp > max_hp:
        errors.append(f"current_hp ({current_hp}) 不能超过 max_hp ({max_hp})")

    mental = data.get("mental_state", {}) or {}
    if mental:
        stress = mental.get("stress", 0)
        morale = mental.get("morale", 80)
        trauma = mental.get("trauma_level", 0)
        if not (0 <= stress <= 100):
            errors.append(f"mental_state.stress 必须在 0-100，当前值: {stress}")
        if not (0 <= morale <= 100):
            errors.append(f"mental_state.morale 必须在 0-100，当前值: {morale}")
        if not (0 <= trauma <= 5):
            errors.append(f"mental_state.trauma_level 必须在 0-5，当前值: {trauma}")

    # 关系网络亲密度范围（兼容 dict 与数组两种形态）
    rels = data.get("relationships", {})
    if isinstance(rels, dict):
        for npc, rel in rels.items():
            if isinstance(rel, dict):
                affinity = rel.get("affinity", 0)
                if not (-100 <= affinity <= 100):
                    errors.append(
                        f"relationships.{npc}.affinity 必须在 -100~100，当前值: {affinity}")
    elif isinstance(rels, list):
        for i, rel in enumerate(rels):
            if isinstance(rel, dict):
                affinity = rel.get("affinity", 0)
                if not (-100 <= affinity <= 100):
                    errors.append(
                        f"relationships[{i}].affinity 必须在 -100~100，当前值: {affinity}")

    # economy 范围
    econ = data.get("economy", {}) or {}
    if isinstance(econ, dict):
        pts = econ.get("points", 0)
        if isinstance(pts, (int, float)) and pts < 0:
            errors.append(f"economy.points 不能为负，当前值: {pts}")
        tier = econ.get("tier", 0)
        if isinstance(tier, (int, float)) and not (0 <= tier <= 10):
            errors.append(f"economy.tier 必须在 0-10，当前值: {tier}")

    return errors


def validate_character(data: dict) -> tuple[bool, list[str]]:
    """
    校验角色卡 v4 数据合法性（R-M14）。
    返回 (valid: bool, errors: list[str])

    策略：jsonschema 可用时执行完整 draft-07 校验，并叠加手写业务规则；
    jsonschema 不可用时仅执行手写规则（功能不缺失，但覆盖度降低）。
    """
    errors: list[str] = []

    if _HAS_JSONSCHEMA:
        validator_cls = _jsonschema.Draft7Validator  # type: ignore[attr-defined]
        try:
            validator = validator_cls(CHARACTER_V4_SCHEMA)
            for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
                loc = ".".join(str(p) for p in err.path) or "<root>"
                errors.append(f"[jsonschema] {loc}: {err.message}")
        except Exception as e:  # schema 自身异常不应吞掉业务校验
            errors.append(f"[jsonschema] 校验器异常: {e}")

    errors.extend(_manual_validate(data))
    # 去重保持顺序
    seen: set[str] = set()
    deduped = [e for e in errors if not (e in seen or seen.add(e))]
    return (len(deduped) == 0, deduped)


# ── 迁移：v3 → v4（设计 §8.4 _migrate_3_to_4）────────────────────────────────

def migrate_v3_to_v4(v3_data: dict) -> dict:
    """
    将 v3 格式的角色卡迁移到完整 v4 格式（设计 06-data-model.md §8.4）。

    主要变更：
      - inventory → loadout.equipped（同时保留 inventory 兼容字段）
      - 生成六部位 body_parts（hp_max/hp_current）
      - 补 energy_pools（默认体力池）
      - psychology 补 OCEAN 默认 + 迁移 stress/morale/trauma
      - economy 补 badges/tier/tier_sub/cash
      - 补 meta(schema_version/plugin_key/card_id) 与 identity
    """
    name = v3_data.get("name", "未知角色")
    plugin_key = v3_data.get("world", v3_data.get("plugin_key", "crossover"))

    attrs_raw = v3_data.get("attributes", v3_data.get("stats", {})) or {}
    attributes = {
        "strength":     int(attrs_raw.get("strength", attrs_raw.get("str", 5))),
        "dexterity":    int(attrs_raw.get("dexterity", attrs_raw.get("dex", 5))),
        "intelligence": int(attrs_raw.get("intelligence", attrs_raw.get("int", 5))),
        "will":         int(attrs_raw.get("will", attrs_raw.get("wil", 5))),
        "empathy":      int(attrs_raw.get("empathy", attrs_raw.get("emp", 5))),
    }

    strength = attributes["strength"]
    max_hp = int(v3_data.get("max_hp", strength * 10))
    current_hp = int(v3_data.get("hp", v3_data.get("current_hp", max_hp)))

    psych = v3_data.get("psychology", v3_data.get("mental_state", {})) or {}
    stress = int(psych.get("stress", 0))
    morale = int(psych.get("morale", 80))
    trauma = int(psych.get("trauma_level", psych.get("trauma", 0)))

    # 物品迁移：inventory → loadout.equipped + 保留 inventory
    v3_items: list[Any] = v3_data.get("items", v3_data.get("inventory", [])) or []
    inventory: list[dict] = []
    for item in v3_items:
        if isinstance(item, str):
            inventory.append({"name": item, "type": "misc", "quantity": 1, "properties": {}})
        elif isinstance(item, dict):
            inventory.append({
                "name":       item.get("name", "未知物品"),
                "type":       item.get("type", "misc"),
                "quantity":   int(item.get("quantity", item.get("count", 1))),
                "properties": item.get("properties", {}),
            })

    # 经济迁移
    points = int(v3_data.get("points", v3_data.get("score", 0)))
    currency = v3_data.get("currency", {})
    economy = {
        "points":         points,
        "badges":         int(v3_data.get("badges", 0)),
        "tier":           int(v3_data.get("tier", 0)),
        "tier_sub":       v3_data.get("tier_sub", ""),
        "cash":           currency if isinstance(currency, dict) else {},
        "currency":       currency if isinstance(currency, dict) else {},
        "special_tokens": v3_data.get("special_tokens", {}),
    }

    # 关系迁移（保留 dict 形态，兼容历史消费方）
    v3_rels = v3_data.get("relationships", v3_data.get("relations", {})) or {}
    relationships: dict[str, dict] = {}
    if isinstance(v3_rels, dict):
        for npc, rel in v3_rels.items():
            if isinstance(rel, (int, float)):
                relationships[npc] = {"affinity": int(rel), "known_secrets": []}
            elif isinstance(rel, dict):
                relationships[npc] = {
                    "affinity":      int(rel.get("affinity", rel.get("trust", 0))),
                    "known_secrets": rel.get("known_secrets", []),
                }

    now_ts = time.time()
    return {
        "name":           name,
        "plugin_key":   plugin_key,
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "plugin_key":   plugin_key,
            "card_id":        v3_data.get("card_id", str(uuid.uuid4())),
            "created_at":     v3_data.get("created_at", now_ts),
            "updated_at":     now_ts,
            "session_id":     v3_data.get("session_id", ""),
            "writing_style":  v3_data.get("writing_style", "网文"),
        },
        "identity": {
            "name":          name,
            "aliases":       v3_data.get("aliases", []),
            "gender":        v3_data.get("gender", "unknown"),
            "current_world": plugin_key,
            "cycle_count":   int(v3_data.get("cycle_count", 0)),
            "appearance":    v3_data.get("appearance", {}),
        },
        "attributes": {
            **attributes,
            "schema": "standard_5d",
            "values": dict(attributes),
        },
        # 历史兼容字段
        "max_hp":         max_hp,
        "current_hp":     current_hp,
        "physical_state": {
            "body_parts": {
                "head":  {"hp_ratio": 1.0},
                "chest": {"hp_ratio": 1.0},
                "arms":  {"hp_ratio": 1.0},
                "legs":  {"hp_ratio": 1.0},
            }
        },
        "mental_state": {
            "stress":       stress,
            "morale":       morale,
            "trauma_level": trauma,
        },
        "skills":         v3_data.get("skills", {}),
        "inventory":      inventory,
        # 完整 v4 结构
        "body_parts":     _default_body_parts(),
        "energy_pools": [
            {"name": "体力", "current": float(current_hp), "max": float(max_hp),
             "regen_per_turn": 5.0, "type": "stamina"},
        ],
        "loadout": {
            "passive_abilities": [],
            "power_sources": [],
            "application_techniques": [],
            "equipped": inventory,
        },
        "psychology": {
            "ocean": {
                "openness": 50, "conscientiousness": 50, "extraversion": 50,
                "agreeableness": 50, "neuroticism": 50,
            },
            "stress": stress,
            "morale": morale,
            "clarity": 100,
            "emotion_state": "calm",
            "traumas": [],
            "beliefs": [],
            "core_values": v3_data.get("core_values", []),
            "behavior_patterns": v3_data.get("behavior_patterns", ""),
            "emotional_triggers": v3_data.get("emotional_triggers", ""),
        },
        "relationships":  relationships,
        "economy":        economy,
        "achievements":   v3_data.get("achievements", []),
    }

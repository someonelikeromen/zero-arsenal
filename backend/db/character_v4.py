"""
角色卡 v4 Schema — 完整 JSON Schema 定义和构造 helper。
设计文档 06-data-model.md §2 角色卡 v4 Schema
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ── JSON Schema ───────────────────────────────────────────────────────────────

CHARACTER_V4_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "version": "4.0",
    "title": "CharacterCardV4",
    "type": "object",
    "required": ["name", "world_plugin"],
    "properties": {
        "name": {
            "type": "string",
            "description": "角色名称"
        },
        "world_plugin": {
            "type": "string",
            "description": "所在世界插件标识，如 muv_luv / crossover"
        },
        "attributes": {
            "type": "object",
            "description": "基础属性（各 1-10）",
            "properties": {
                "strength":     {"type": "integer", "minimum": 1, "maximum": 10},
                "dexterity":    {"type": "integer", "minimum": 1, "maximum": 10},
                "intelligence": {"type": "integer", "minimum": 1, "maximum": 10},
                "will":         {"type": "integer", "minimum": 1, "maximum": 10},
                "empathy":      {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "additionalProperties": False,
        },
        "max_hp": {
            "type": "integer",
            "description": "最大生命值（= strength × 10）",
        },
        "current_hp": {
            "type": "integer",
            "description": "当前生命值",
        },
        "physical_state": {
            "type": "object",
            "description": "生理状态",
            "properties": {
                "body_parts": {
                    "type": "object",
                    "description": "各部位 HP 比例（0.0-1.0）",
                    "properties": {
                        "head":  {"type": "object", "properties": {"hp_ratio": {"type": "number", "minimum": 0.0, "maximum": 1.0}}},
                        "chest": {"type": "object", "properties": {"hp_ratio": {"type": "number", "minimum": 0.0, "maximum": 1.0}}},
                        "arms":  {"type": "object", "properties": {"hp_ratio": {"type": "number", "minimum": 0.0, "maximum": 1.0}}},
                        "legs":  {"type": "object", "properties": {"hp_ratio": {"type": "number", "minimum": 0.0, "maximum": 1.0}}},
                    },
                }
            },
        },
        "mental_state": {
            "type": "object",
            "description": "心理状态",
            "properties": {
                "stress":       {"type": "integer", "minimum": 0, "maximum": 100},
                "morale":       {"type": "integer", "minimum": 0, "maximum": 100},
                "trauma_level": {"type": "integer", "minimum": 0, "maximum": 5},
            },
            "additionalProperties": False,
        },
        "skills": {
            "type": "object",
            "description": "技能组 {skill_name: level}",
            "additionalProperties": {"type": "integer", "minimum": 0},
        },
        "inventory": {
            "type": "array",
            "description": "物品栏",
            "items": {
                "type": "object",
                "required": ["name", "type", "quantity"],
                "properties": {
                    "name":       {"type": "string"},
                    "type":       {"type": "string"},
                    "quantity":   {"type": "integer", "minimum": 0},
                    "properties": {"type": "object"},
                },
            },
        },
        "relationships": {
            "type": "object",
            "description": "关系网络 {npc_name: {affinity, known_secrets}}",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "affinity":       {"type": "integer", "minimum": -100, "maximum": 100},
                    "known_secrets":  {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "economy": {
            "type": "object",
            "description": "积分与货币",
            "properties": {
                "points":         {"type": "integer", "minimum": 0},
                "currency":       {"type": "object", "additionalProperties": {"type": "number"}},
                "special_tokens": {"type": "object", "additionalProperties": {"type": "integer"}},
            },
            "additionalProperties": False,
        },
        "meta": {
            "type": "object",
            "description": "元数据",
            "properties": {
                "created_at":    {"type": "string", "format": "date-time"},
                "session_id":    {"type": "string"},
                "writing_style": {"type": "string"},
            },
        },
    },
}


# ── Helper 函数 ───────────────────────────────────────────────────────────────

def create_default_character(
    name: str,
    world_plugin: str = "crossover",
) -> dict:
    """创建具有默认值的 v4 角色卡。"""
    strength = 5
    max_hp = strength * 10

    return {
        "name": name,
        "world_plugin": world_plugin,
        "attributes": {
            "strength":     strength,
            "dexterity":    5,
            "intelligence": 5,
            "will":         5,
            "empathy":      5,
        },
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
        "relationships": {},
        "economy": {
            "points":         0,
            "currency":       {},
            "special_tokens": {},
        },
        "meta": {
            "created_at":    datetime.now(timezone.utc).isoformat(),
            "session_id":    "",
            "writing_style": "网文",
        },
    }


def validate_character(data: dict) -> tuple[bool, list[str]]:
    """
    简单验证角色卡 v4 数据合法性。
    返回 (valid: bool, errors: list[str])
    """
    errors: list[str] = []

    # 必填字段
    for required in ("name", "world_plugin"):
        if not data.get(required):
            errors.append(f"缺少必填字段: {required}")

    # 属性范围
    attrs = data.get("attributes", {})
    for attr in ("strength", "dexterity", "intelligence", "will", "empathy"):
        val = attrs.get(attr)
        if val is not None and not (1 <= val <= 10):
            errors.append(f"attributes.{attr} 必须在 1-10 范围内，当前值: {val}")

    # HP 一致性
    strength = attrs.get("strength", 5)
    expected_max_hp = strength * 10
    max_hp = data.get("max_hp", expected_max_hp)
    current_hp = data.get("current_hp", max_hp)
    if current_hp > max_hp:
        errors.append(f"current_hp ({current_hp}) 不能超过 max_hp ({max_hp})")

    # 心理状态范围
    mental = data.get("mental_state", {})
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

    # 关系网络亲密度范围
    relationships = data.get("relationships", {})
    for npc, rel in relationships.items():
        affinity = rel.get("affinity", 0)
        if not (-100 <= affinity <= 100):
            errors.append(f"relationships.{npc}.affinity 必须在 -100-100，当前值: {affinity}")

    return (len(errors) == 0, errors)


def migrate_v3_to_v4(v3_data: dict) -> dict:
    """
    将 v3.2 格式的角色卡迁移到 v4 格式。
    v3 → v4 主要变更：
    - attributes 扁平化 → 嵌套 object
    - hp 字段 → max_hp / current_hp
    - psychology → mental_state
    - items[] → inventory[]
    - points → economy.points
    """
    name = v3_data.get("name", "未知角色")
    world_plugin = v3_data.get("world", v3_data.get("world_plugin", "crossover"))

    # 属性迁移（兼容 v3 扁平属性名）
    attrs_raw = v3_data.get("attributes", v3_data.get("stats", {}))
    attributes = {
        "strength":     int(attrs_raw.get("strength", attrs_raw.get("str", 5))),
        "dexterity":    int(attrs_raw.get("dexterity", attrs_raw.get("dex", 5))),
        "intelligence": int(attrs_raw.get("intelligence", attrs_raw.get("int", 5))),
        "will":         int(attrs_raw.get("will", attrs_raw.get("wil", 5))),
        "empathy":      int(attrs_raw.get("empathy", attrs_raw.get("emp", 5))),
    }

    strength = attributes["strength"]
    max_hp = v3_data.get("max_hp", strength * 10)
    current_hp = v3_data.get("hp", v3_data.get("current_hp", max_hp))

    # 心理状态迁移
    psych = v3_data.get("psychology", v3_data.get("mental_state", {}))
    mental_state = {
        "stress":       int(psych.get("stress", 0)),
        "morale":       int(psych.get("morale", 80)),
        "trauma_level": int(psych.get("trauma_level", psych.get("trauma", 0))),
    }

    # 物品栏迁移
    v3_items: list[Any] = v3_data.get("items", v3_data.get("inventory", []))
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
    economy = {
        "points":         int(v3_data.get("points", v3_data.get("score", 0))),
        "currency":       v3_data.get("currency", {}),
        "special_tokens": v3_data.get("special_tokens", {}),
    }

    # 关系网络迁移
    v3_rels = v3_data.get("relationships", v3_data.get("relations", {}))
    relationships: dict[str, dict] = {}
    for npc, rel in v3_rels.items():
        if isinstance(rel, (int, float)):
            relationships[npc] = {"affinity": int(rel), "known_secrets": []}
        elif isinstance(rel, dict):
            relationships[npc] = {
                "affinity":      int(rel.get("affinity", rel.get("trust", 0))),
                "known_secrets": rel.get("known_secrets", []),
            }

    return {
        "name":           name,
        "world_plugin":   world_plugin,
        "attributes":     attributes,
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
        "mental_state":   mental_state,
        "skills":         v3_data.get("skills", {}),
        "inventory":      inventory,
        "relationships":  relationships,
        "economy":        economy,
        "meta": {
            "created_at":    datetime.now(timezone.utc).isoformat(),
            "session_id":    v3_data.get("session_id", ""),
            "writing_style": v3_data.get("writing_style", "网文"),
        },
    }

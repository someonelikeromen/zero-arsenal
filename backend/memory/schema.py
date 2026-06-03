"""
记忆节点 Schema 定义 — 精确对应 ST-BME schema.js
8类节点类型 + 8种关系边类型
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any


# ════════════════════════════════════════════════════════════════════════════
# 节点类型枚举
# ════════════════════════════════════════════════════════════════════════════

class NodeType(str, Enum):
    EVENT       = "event"       # 事件节点：已发生的情节
    RULE        = "rule"        # 规则节点：世界观/体系规则（Core 层常驻）
    THREAD      = "thread"      # 线索节点：正在推进的叙事线（Core 层常驻）
    SYNOPSIS    = "synopsis"    # 章节摘要（Core 层常驻）
    CHARACTER   = "character"   # 角色节点：NPC/主角特质档案
    LOCATION    = "location"    # 地点节点：场景/区域描述
    REFLECTION  = "reflection"  # 感悟节点：主角内心洞见/成长记录
    POV_MEMORY  = "pov_memory"  # 视角记忆：分角色的主观感知

    @classmethod
    def core_types(cls) -> list["NodeType"]:
        """Core 层：每次召回都强制包含"""
        return [cls.RULE, cls.THREAD, cls.SYNOPSIS]

    @classmethod
    def recalled_types(cls) -> list["NodeType"]:
        """动态层：按相关性召回"""
        return [cls.EVENT, cls.CHARACTER, cls.LOCATION, cls.REFLECTION, cls.POV_MEMORY]


# ════════════════════════════════════════════════════════════════════════════
# 关系边类型枚举
# ════════════════════════════════════════════════════════════════════════════

class RelationType(str, Enum):
    INVOLVED_IN  = "involved_in"   # 角色 → 事件（参与关系）
    OCCURRED_AT  = "occurred_at"   # 事件 → 地点（发生地关系）
    ADVANCES     = "advances"      # 事件 → 线索（推进关系）
    RELATED      = "related"       # 通用关联（同类节点间）
    CAUSED_BY    = "caused_by"     # 因果关系
    KNOWS        = "knows"         # 角色 → 角色（认知关系）
    LOCATED_IN   = "located_in"    # 地点 → 地点（包含/毗邻）
    REFERENCES   = "references"    # 节点 → 规则（引用关系）
    # ── 情感/社会关系（CHARACTER ↔ CHARACTER）────────────────────────────
    FAMILY       = "family"        # 亲情（血缘/义亲/兄弟姐妹）
    ROMANCE      = "romance"       # 爱情/暧昧/单恋
    FRIENDSHIP   = "friendship"    # 友情/战友/兄弟情
    HOSTILE      = "hostile"       # 敌对/仇恨
    AFFILIATED   = "affiliated"    # 从属/雇佣/组织关系
    MIXED        = "mixed"         # 多种感情混杂（如亦师亦友、爱恨交织）

    @classmethod
    def emotional_types(cls) -> set["RelationType"]:
        """情感型关系——自动建立双向边"""
        return {cls.FAMILY, cls.ROMANCE, cls.FRIENDSHIP, cls.MIXED}

    @classmethod
    def all_interpersonal(cls) -> set["RelationType"]:
        """所有人际关系类型（用于图过滤）"""
        return {cls.KNOWS, cls.FAMILY, cls.ROMANCE, cls.FRIENDSHIP,
                cls.HOSTILE, cls.AFFILIATED, cls.MIXED}


# ════════════════════════════════════════════════════════════════════════════
# 时序分桶
# ════════════════════════════════════════════════════════════════════════════

class TemporalBucket(str, Enum):
    CURRENT       = "current"        # 当前章节/场景
    ADJACENT_PAST = "adjacent_past"  # 近期（最近3章）
    UNDATED       = "undated"        # 无明确时间标记
    FLASHBACK     = "flashback"      # 闪回/回忆
    DISTANT_PAST  = "distant_past"   # 历史（更早）
    FUTURE        = "future"         # 预言/伏笔引用的未来


# ════════════════════════════════════════════════════════════════════════════
# 节点数据类
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class MemoryNode:
    """统一的记忆节点数据结构"""
    # 基础标识
    node_id:   str
    novel_id:  str
    node_type: NodeType
    world_key: str = ""

    # 核心内容
    title:   str = ""       # 节点标题（主字段，用于词法匹配）
    content: str = ""       # 节点正文（嵌入向量 + 展示用）
    summary: str = ""       # 简短摘要（节省 LLM Token）

    # 时序与结构
    temporal_bucket: TemporalBucket = TemporalBucket.UNDATED
    chapter_id:      str = ""
    created_at:      str = ""
    updated_at:      str = ""

    # POV 专属字段
    scope_owner: str = ""    # pov_memory 的视角所有者（角色名）

    # 置信度与重要性
    confidence:  float = 1.0    # 来源可信度 0~1
    importance:  float = 0.5    # 重要性权重 0~1（影响压缩优先级）

    # 通用扩展字段（各类型特有内容）
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "node_id":        self.node_id,
            "novel_id":       self.novel_id,
            "node_type":      self.node_type.value,
            "world_key":      self.world_key,
            "title":          self.title,
            "content":        self.content,
            "summary":        self.summary,
            "temporal_bucket":self.temporal_bucket.value,
            "chapter_id":     self.chapter_id,
            "created_at":     self.created_at,
            "updated_at":     self.updated_at,
            "scope_owner":    self.scope_owner,
            "confidence":     self.confidence,
            "importance":     self.importance,
            "extra":          self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryNode":
        return cls(
            node_id=d["node_id"],
            novel_id=d["novel_id"],
            node_type=NodeType(d["node_type"]),
            world_key=d.get("world_key", ""),
            title=d.get("title", ""),
            content=d.get("content", ""),
            summary=d.get("summary", ""),
            temporal_bucket=TemporalBucket(d.get("temporal_bucket", "undated")),
            chapter_id=d.get("chapter_id", ""),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            scope_owner=d.get("scope_owner", ""),
            confidence=d.get("confidence", 1.0),
            importance=d.get("importance", 0.5),
            extra=d.get("extra", {}),
        )

    def metadata_dict(self) -> dict:
        """返回用于 ChromaDB metadata 的扁平化字典（仅基础类型）"""
        return {
            "node_id":        self.node_id,
            "novel_id":       self.novel_id,
            "node_type":      self.node_type.value,
            "world_key":      self.world_key,
            "node_title":     self.title,
            "temporal_bucket":self.temporal_bucket.value,
            "chapter_id":     self.chapter_id,
            "scope_owner":    self.scope_owner,
            "confidence":     self.confidence,
            "importance":     self.importance,
        }


# ════════════════════════════════════════════════════════════════════════════
# 节点类型专属字段说明（供 LLM 提取 Prompt 使用）
# ════════════════════════════════════════════════════════════════════════════

NODE_TYPE_EXTRACTION_HINTS: dict[NodeType, dict] = {
    NodeType.EVENT: {
        "title_hint":   "事件简称（5字以内，如'吴森初遇混混'）",
        "content_hint": "事件经过（人物/地点/行为/结果/影响，200字以内）",
        "extra_fields": ["participants", "location", "outcome", "foreshadow_ids"],
    },
    NodeType.RULE: {
        "title_hint":   "规则名称（如'破碎虚空境界设定'）",
        "content_hint": "规则说明（世界观设定/体系规则，严格描述）",
        "extra_fields": ["source_world", "rule_category", "strictness"],
    },
    NodeType.THREAD: {
        "title_hint":   "线索名称（如'混混组织调查线'）",
        "content_hint": "线索当前状态（起始/进展/阻碍/预期走向）",
        "extra_fields": ["status", "urgency", "related_hook_ids"],
    },
    NodeType.SYNOPSIS: {
        "title_hint":   "章节/段落标题（如'第3章-对话'）",
        "content_hint": "段落精华摘要（情节推进/人物变化/伏笔植入，100字以内）",
        "extra_fields": ["chapter_id", "arc_progress_pct"],
    },
    NodeType.CHARACTER: {
        "title_hint":   "角色名称",
        "content_hint": "角色最新状态（外貌/立场/情绪/已知信息/当前位置）",
        "extra_fields": ["trait_lock", "knowledge_scope", "capability_cap",
                         "relationship_map", "is_protagonist"],
    },
    NodeType.LOCATION: {
        "title_hint":   "地点名称（如'东城区废弃仓库'）",
        "content_hint": "地点描述（环境/氛围/重要细节/控制方）",
        "extra_fields": ["region", "is_current_scene", "connected_locations"],
    },
    NodeType.REFLECTION: {
        "title_hint":   "感悟标题（如'对战斗本质的新理解'）",
        "content_hint": "主角内心洞见（第一人称，具体化，有叙事影响力）",
        "extra_fields": ["trigger_event_id", "growth_domain", "insight"],
    },
    NodeType.POV_MEMORY: {
        "title_hint":   "视角记忆标题（如'吴森对李四的第一印象'）",
        "content_hint": "该角色对某事/某人的主观认知（包含偏见/盲区）",
        "extra_fields": ["scope_owner", "target", "is_accurate", "known_at_chapter"],
    },
}


# ── 层级压缩阈值配置 ─────────────────────────────────────────────────────────
CONSOLIDATION_CONFIG = {
    "event_to_synopsis": {
        "threshold": 10,    # 同章节event节点超过10条时触发压缩
        "keep_top_n": 3,    # 保留最重要的3条
        "output_type": NodeType.SYNOPSIS,
    },
    "synopsis_to_arc": {
        "threshold": 5,     # 连续5个chapter synopsis触发弧线摘要
        "output_type": NodeType.SYNOPSIS,
    },
}

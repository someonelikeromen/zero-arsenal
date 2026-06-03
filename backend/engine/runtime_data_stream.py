"""
RuntimeDataStreamBuilder — 18 轴 DM 参考层数据流。
用途: 每回合将 TurnContext 转换为 Markdown 注入 DM/Narrator Agent 的 user 前缀（Layer 4）。
参考设计文档 05-prompt-architecture.md §6

18 轴分组：
  轴 1-3   : 生命与能量（HP、能量池、被动技能）
  轴 4-6   : 装备与技能（已装备物品、主动技能、能量来源）
  轴 7-9   : 心理状态（情绪、压力、士气、神志）
  轴 10-11 : 关系网络（NPC 快照、信任度矩阵）
  轴 12-13 : 世界状态（世界时间、当前地点）
  轴 14-15 : 任务进度（进行中任务、悬挂叙事钩）
  轴 16    : 经济状态（积分/徽章/tier）
  轴 17    : 战斗状态（战斗详情，非战斗时为 None）
  轴 18    : 记忆召回结果（RAG 相关片段）

入口函数：
  RuntimeDataStreamBuilder.build(ctx: TurnContext) -> str
  RuntimeDataStreamBuilder.build_from_dict(char_data, ...) -> str
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..agents.state import TurnContext

logger = logging.getLogger(__name__)


# ── 支撑数据类 ────────────────────────────────────────────────────────────────

@dataclass
class BodyPartHP:
    current: int = 100
    max: int = 100
    armor: int = 0
    status_effects: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return self.current / self.max if self.max > 0 else 0.0


@dataclass
class HPStatus:
    head:      BodyPartHP = field(default_factory=BodyPartHP)
    torso:     BodyPartHP = field(default_factory=BodyPartHP)
    left_arm:  BodyPartHP = field(default_factory=BodyPartHP)
    right_arm: BodyPartHP = field(default_factory=BodyPartHP)
    left_leg:  BodyPartHP = field(default_factory=BodyPartHP)
    right_leg: BodyPartHP = field(default_factory=BodyPartHP)

    @property
    def overall_ratio(self) -> float:
        parts = [self.head, self.torso, self.left_arm, self.right_arm, self.left_leg, self.right_leg]
        total_cur = sum(p.current for p in parts)
        total_max = sum(p.max for p in parts)
        return total_cur / total_max if total_max > 0 else 0.0

    @property
    def critical_parts(self) -> list[str]:
        mapping = {
            "头部": self.head,
            "躯干": self.torso,
            "左臂": self.left_arm,
            "右臂": self.right_arm,
            "左腿": self.left_leg,
            "右腿": self.right_leg,
        }
        return [name for name, p in mapping.items() if p.ratio < 0.20]


@dataclass
class EnergyPool:
    name: str = "体力"
    current: int = 100
    max: int = 100
    regen_per_turn: int = 5
    type: str = "stamina"  # qi / mana / stamina / tech_charge


@dataclass
class RelationshipSnapshot:
    npc_id: str = ""
    name: str = ""
    affinity: int = 0          # -100 到 +100
    relationship_type: str = "neutral"  # ally / neutral / hostile
    is_present: bool = False


@dataclass
class EnemySnapshot:
    id: str = ""
    name: str = ""
    tier: int = 1
    tier_sub: str = "M"
    hp_ratio: float = 1.0
    known_abilities: list[str] = field(default_factory=list)
    status_effects: list[str] = field(default_factory=list)
    intent: str = "未知"


@dataclass
class CombatSnapshot:
    active: bool = False
    round: int = 0
    initiative_order: list[str] = field(default_factory=list)
    enemies: list[EnemySnapshot] = field(default_factory=list)
    environment_effects: list[str] = field(default_factory=list)


@dataclass
class MemorySnippet:
    content: str = ""
    relevance_score: float = 0.0
    tier: str = "episodic"   # episodic / semantic / core
    created_at: str = ""


@dataclass
class QuestSnapshot:
    id: str = ""
    title: str = ""
    status: str = "active"
    progress: str = ""


@dataclass
class HookSnapshot:
    id: str = ""
    description: str = ""
    trigger_condition: str = ""


@dataclass
class EconomySnapshot:
    points: int = 0
    badges: int = 0
    tier: str = "0★"
    currency: dict[str, int] = field(default_factory=dict)  # 自定义货币


# ── 主数据结构 ────────────────────────────────────────────────────────────────

@dataclass
class BackendDataStream:
    """
    18 轴 DM 参考层数据结构。
    设计文档 05-prompt-architecture.md §6.2
    """
    # 轴 1-3：生命与能量
    hp_status: HPStatus = field(default_factory=HPStatus)
    energy_pools: list[EnergyPool] = field(default_factory=list)
    passive_abilities: list[str] = field(default_factory=list)

    # 轴 4-6：装备与技能
    equipped_items: list[dict] = field(default_factory=list)
    application_techniques: list[dict] = field(default_factory=list)
    power_sources: list[dict] = field(default_factory=list)

    # 轴 7-9：心理状态
    emotion_state: str = "平静"
    stress_level: int = 0    # 0-100
    morale: int = 80         # 0-100
    clarity: int = 100       # 0-100

    # 轴 10-11：关系网络
    active_relationships: list[RelationshipSnapshot] = field(default_factory=list)
    trust_matrix: dict[str, int] = field(default_factory=dict)

    # 轴 12-13：世界状态
    world_time: str = ""
    current_location: str = ""

    # 轴 14-15：任务进度
    active_quests: list[QuestSnapshot] = field(default_factory=list)
    active_hooks: list[HookSnapshot] = field(default_factory=list)

    # 轴 16：经济状态
    economy: EconomySnapshot = field(default_factory=EconomySnapshot)

    # 轴 17：战斗状态
    combat: Optional[CombatSnapshot] = None

    # 轴 18：记忆召回
    recalled_memories: list[MemorySnippet] = field(default_factory=list)


# ── 构建器 ────────────────────────────────────────────────────────────────────

class RuntimeDataStreamBuilder:
    """
    将 TurnContext / 字典数据组装为 BackendDataStream，
    并序列化为 Markdown 格式供 Agent 提示词注入（Layer 4）。

    设计文档 05-prompt-architecture.md §6.3
    """

    # ── 公共入口 ──────────────────────────────────────────────────────────────

    @classmethod
    def build(cls, ctx: "TurnContext") -> str:
        """
        从 TurnContext 提取 18 轴数据并序列化为 Markdown。
        返回空字符串时表示数据不足，调用方可选择跳过注入。
        注：同步版本无法在已运行的事件循环中从 DB 补全 quests/hooks，
        建议 async 上下文使用 build_async。
        """
        try:
            stream = cls._extract_stream(ctx)
            return cls._render(stream)
        except Exception as e:
            logger.warning(f"[DataStream] build failed: {e}")
            return ""

    @classmethod
    async def build_async(cls, ctx: "TurnContext") -> str:
        """
        异步版本：从 TurnContext + DB 提取 18 轴数据并序列化为 Markdown。
        在 async 上下文中使用此方法以确保 active_quests/active_hooks 能从 DB 读取。
        """
        try:
            stream = await cls._extract_stream_async(ctx)
            return cls._render(stream)
        except Exception as e:
            logger.warning(f"[DataStream] build_async failed: {e}")
            return ""

    @classmethod
    def build_from_dict(
        cls,
        char_data: dict,
        *,
        npc_reactions: list[dict] | None = None,
        world_events: list[dict] | None = None,
        memory_context: str = "",
        active_quests: list[dict] | None = None,
        active_hooks: list[dict] | None = None,
    ) -> str:
        """
        从字典数据（已解包的 TurnContext 字段）构建数据流。
        适用于测试和工具调用场景。
        """
        try:
            stream = cls._extract_from_dict(
                char_data,
                npc_reactions=npc_reactions or [],
                world_events=world_events or [],
                memory_context=memory_context,
                active_quests=active_quests or [],
                active_hooks=active_hooks or [],
            )
            return cls._render(stream)
        except Exception as e:
            logger.warning(f"[DataStream] build_from_dict failed: {e}")
            return ""

    # ── 提取逻辑 ──────────────────────────────────────────────────────────────

    @classmethod
    def _extract_stream(cls, ctx: "TurnContext") -> BackendDataStream:
        char = ctx.character_data or {}

        # 从 character_data 读取 active_quests / active_hooks
        char_quests: list[dict] = char.get("quests", char.get("active_quests", []))
        char_hooks: list[dict] = char.get("narrative_hooks", char.get("active_hooks", []))

        # ctx 若携带专属字段，覆盖 char 中的静态快照
        ctx_quests: list = getattr(ctx, "active_quests", []) or []
        ctx_hooks: list = getattr(ctx, "active_hooks", []) or []

        active_quests = ctx_quests if ctx_quests else char_quests
        active_hooks  = ctx_hooks  if ctx_hooks  else char_hooks

        # 若两个来源均为空，尝试从 DB 补全（character_data 未包含 quests/hooks 时兜底）
        if not active_quests and not active_hooks and ctx.session_id:
            try:
                import asyncio, json as _json
                from ..db import get_db

                async def _db_fetch() -> tuple[list, list]:
                    async with get_db() as db:
                        row = await (await db.execute(
                            "SELECT data_json FROM character_cards "
                            "WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
                            (ctx.session_id,)
                        )).fetchone()
                    if not row:
                        return [], []
                    data = _json.loads(row["data_json"]) if isinstance(row["data_json"], str) else row["data_json"]
                    q = data.get("quests", data.get("active_quests", []))
                    h = data.get("narrative_hooks", data.get("active_hooks", []))
                    return q, h

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 已在 async 上下文中：创建 Task 等待（使用 asyncio.ensure_future）
                    import concurrent.futures
                    future = asyncio.ensure_future(_db_fetch())
                    # 非阻塞：如果 char 已有数据则下次会命中，此次返回 char 已有的（可能为空）
                    # 为了不阻塞 sync 方法，跳过等待；async 调用方应直接使用 _extract_stream_async
                else:
                    db_quests, db_hooks = loop.run_until_complete(_db_fetch())
                    active_quests = db_quests
                    active_hooks = db_hooks
            except Exception as e:
                logger.debug("[DataStream] DB fallback for quests/hooks failed: %s", e)

        return cls._extract_from_dict(
            char,
            npc_reactions=ctx.npc_reactions,
            world_events=ctx.world_events,
            memory_context=ctx.memory_context,
            active_quests=active_quests,
            active_hooks=active_hooks,
        )

    @classmethod
    async def _extract_stream_async(cls, ctx: "TurnContext") -> BackendDataStream:
        """
        异步版本的 _extract_stream，直接从 DB 查询 active_quests/active_hooks。
        在 async 上下文中优先使用此方法以获得完整的任务/钩子数据。
        """
        char = ctx.character_data or {}
        char_quests: list[dict] = char.get("quests", char.get("active_quests", []))
        char_hooks: list[dict] = char.get("narrative_hooks", char.get("active_hooks", []))
        ctx_quests: list = getattr(ctx, "active_quests", []) or []
        ctx_hooks: list = getattr(ctx, "active_hooks", []) or []
        active_quests = ctx_quests if ctx_quests else char_quests
        active_hooks  = ctx_hooks  if ctx_hooks  else char_hooks

        if not active_quests and not active_hooks and ctx.session_id:
            try:
                import json as _json
                from ..db import get_db
                async with get_db() as db:
                    row = await (await db.execute(
                        "SELECT data_json FROM character_cards "
                        "WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
                        (ctx.session_id,)
                    )).fetchone()
                if row:
                    data = _json.loads(row["data_json"]) if isinstance(row["data_json"], str) else row["data_json"]
                    active_quests = data.get("quests", data.get("active_quests", []))
                    active_hooks  = data.get("narrative_hooks", data.get("active_hooks", []))
            except Exception as e:
                logger.debug("[DataStream] async DB fallback for quests/hooks failed: %s", e)

        return cls._extract_from_dict(
            char,
            npc_reactions=ctx.npc_reactions,
            world_events=ctx.world_events,
            memory_context=ctx.memory_context,
            active_quests=active_quests,
            active_hooks=active_hooks,
        )

    @classmethod
    def _extract_from_dict(
        cls,
        char: dict,
        *,
        npc_reactions: list[dict],
        world_events: list[dict],
        memory_context: str,
        active_quests: list[dict],
        active_hooks: list[dict],
    ) -> BackendDataStream:
        attrs: dict = char.get("attributes", {})
        meta: dict = char.get("meta", {})
        psyche: dict = char.get("psyche", {})
        inventory: list = char.get("inventory", [])
        skills: list = char.get("skills", [])

        stream = BackendDataStream()

        # ── 轴 1：HP 状态 ────────────────────────────────────────────────────
        stream.hp_status = cls._extract_hp(attrs)

        # ── 轴 2：能量池 ─────────────────────────────────────────────────────
        stream.energy_pools = cls._extract_energy(attrs)

        # ── 轴 3：被动技能 ───────────────────────────────────────────────────
        stream.passive_abilities = [
            s.get("name", s) if isinstance(s, dict) else str(s)
            for s in skills
            if (isinstance(s, dict) and s.get("type") == "passive") or
               (isinstance(s, str) and "passive" in s.lower())
        ]

        # ── 轴 4：已装备物品 ─────────────────────────────────────────────────
        stream.equipped_items = [
            item for item in inventory
            if isinstance(item, dict) and item.get("equipped", False)
        ]

        # ── 轴 5：主动技能 ───────────────────────────────────────────────────
        stream.application_techniques = [
            {"name": s.get("name", "?"), "cost": s.get("cost", 0), "desc": s.get("description", "")}
            for s in skills
            if isinstance(s, dict) and s.get("type") in ("active", "technique", "application")
        ]

        # ── 轴 6：能量来源 ───────────────────────────────────────────────────
        stream.power_sources = [
            pool for pool in attrs.values()
            if isinstance(pool, dict) and pool.get("pool_type") in ("qi", "mana", "tech_charge")
        ]

        # ── 轴 7-9：心理状态 ─────────────────────────────────────────────────
        stream.emotion_state = psyche.get("emotion", meta.get("emotion", "平静"))
        stream.stress_level  = int(psyche.get("stress", attrs.get("stress", {}).get("base", 0)) or 0)
        stream.morale        = int(psyche.get("morale", attrs.get("morale", {}).get("base", 80)) or 80)
        stream.clarity       = int(psyche.get("clarity", attrs.get("clarity", {}).get("base", 100)) or 100)

        # ── 轴 10-11：关系网络 ───────────────────────────────────────────────
        stream.active_relationships = cls._extract_relationships(npc_reactions)
        stream.trust_matrix = {
            r.name: r.affinity for r in stream.active_relationships
        }

        # ── 轴 12-13：世界状态 ───────────────────────────────────────────────
        for ev in world_events:
            if isinstance(ev, dict):
                if "world_time" in ev:
                    stream.world_time = str(ev["world_time"])
                if "location" in ev:
                    stream.current_location = str(ev["location"])
        if not stream.world_time:
            stream.world_time = meta.get("world_time", "未知时间")
        if not stream.current_location:
            stream.current_location = meta.get("location", "未知地点")

        # ── 轴 14-15：任务进度 ───────────────────────────────────────────────
        stream.active_quests = [
            QuestSnapshot(
                id=q.get("id", ""),
                title=q.get("title", q.get("name", "未命名任务")),
                status=q.get("status", "active"),
                progress=q.get("progress", ""),
            )
            for q in active_quests
            if isinstance(q, dict)
        ]
        stream.active_hooks = [
            HookSnapshot(
                id=h.get("id", ""),
                description=h.get("description", h.get("title", "")),
                trigger_condition=h.get("trigger_condition", ""),
            )
            for h in active_hooks
            if isinstance(h, dict)
        ]

        # ── 轴 16：经济状态 ──────────────────────────────────────────────────
        econ_attr = attrs.get("points", {})
        stream.economy = EconomySnapshot(
            points=int(econ_attr.get("base", 0) if isinstance(econ_attr, dict) else econ_attr or 0),
            badges=int(attrs.get("badges", {}).get("base", 0) if isinstance(attrs.get("badges"), dict) else 0),
            tier=str(meta.get("anti_feat_tier", attrs.get("tier", "0★"))),
            currency={
                k: int(v.get("base", 0) if isinstance(v, dict) else v or 0)
                for k, v in attrs.items()
                if k not in ("points", "badges", "hp", "stress", "morale", "clarity")
                   and isinstance(v, (dict, int, float))
                   and k.endswith("_coin")
            },
        )

        # ── 轴 17：战斗状态 ──────────────────────────────────────────────────
        combat_data = char.get("combat", None) or meta.get("combat", None)
        if isinstance(combat_data, dict) and combat_data.get("active"):
            stream.combat = CombatSnapshot(
                active=True,
                round=int(combat_data.get("round", 1)),
                initiative_order=combat_data.get("initiative_order", []),
                enemies=[
                    EnemySnapshot(
                        id=e.get("id", ""),
                        name=e.get("name", "未知敌人"),
                        tier=int(e.get("tier", 1)),
                        tier_sub=e.get("tier_sub", "M"),
                        hp_ratio=float(e.get("hp_ratio", 1.0)),
                        known_abilities=e.get("known_abilities", []),
                        status_effects=e.get("status_effects", []),
                        intent=e.get("intent", "未知"),
                    )
                    for e in combat_data.get("enemies", [])
                ],
                environment_effects=combat_data.get("environment_effects", []),
            )

        # ── 轴 18：记忆召回 ──────────────────────────────────────────────────
        if memory_context:
            stream.recalled_memories = cls._parse_memory_context(memory_context)

        return stream

    # ── 辅助提取方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_hp(attrs: dict) -> HPStatus:
        """从 character_data.attributes 提取部位 HP（兼容简单 hp 字段和部位 HP 结构）。"""
        status = HPStatus()
        hp_attr = attrs.get("hp", attrs.get("health", None))

        if isinstance(hp_attr, dict):
            parts_map = hp_attr.get("parts", {})
            if parts_map:
                def _part(key: str, default_max: int = 100) -> BodyPartHP:
                    p = parts_map.get(key, {})
                    return BodyPartHP(
                        current=int(p.get("current", p.get("base", default_max))),
                        max=int(p.get("max", default_max)),
                        armor=int(p.get("armor", 0)),
                        status_effects=p.get("status_effects", []),
                    )
                status.head      = _part("head",      50)
                status.torso     = _part("torso",     200)
                status.left_arm  = _part("left_arm",  80)
                status.right_arm = _part("right_arm", 80)
                status.left_leg  = _part("left_leg",  100)
                status.right_leg = _part("right_leg", 100)
            else:
                # 简单 {base, max} 结构 → 全部映射到躯干
                cur = int(hp_attr.get("current", hp_attr.get("base", 100)))
                mx  = int(hp_attr.get("max", 100))
                part = BodyPartHP(current=cur, max=mx)
                status.head = status.left_arm = status.right_arm = BodyPartHP(
                    current=cur, max=mx)
                status.torso = status.left_leg = status.right_leg = part
        return status

    @staticmethod
    def _extract_energy(attrs: dict) -> list[EnergyPool]:
        """从 attributes 提取能量池（qi / mana / stamina 等）。"""
        pools: list[EnergyPool] = []
        energy_keys = {
            "qi": ("内力", "qi"),
            "mana": ("魔力", "mana"),
            "stamina": ("体力", "stamina"),
            "tech_charge": ("科技充能", "tech_charge"),
            "ki": ("气", "qi"),
        }
        for key, (display, pool_type) in energy_keys.items():
            v = attrs.get(key)
            if isinstance(v, dict):
                cur = int(v.get("current", v.get("base", 0)))
                mx  = int(v.get("max", 100))
                if mx > 0:
                    pools.append(EnergyPool(
                        name=v.get("name", display),
                        current=cur,
                        max=mx,
                        regen_per_turn=int(v.get("regen", v.get("regen_per_turn", 5))),
                        type=pool_type,
                    ))
        return pools

    @staticmethod
    def _extract_relationships(npc_reactions: list[dict]) -> list[RelationshipSnapshot]:
        """从 npc_reactions 生成关系快照（all_present=True 因为都在当前场景）。"""
        snapshots: list[RelationshipSnapshot] = []
        for r in npc_reactions:
            if not isinstance(r, dict):
                continue
            affinity = r.get("affinity", r.get("trust", 0))
            try:
                affinity = int(affinity)
            except (TypeError, ValueError):
                affinity = 0
            rt = "neutral"
            if affinity >= 30:
                rt = "ally"
            elif affinity <= -30:
                rt = "hostile"
            snapshots.append(RelationshipSnapshot(
                npc_id=r.get("npc_id", r.get("id", "")),
                name=r.get("name", r.get("npc_name", "未知NPC")),
                affinity=affinity,
                relationship_type=rt,
                is_present=True,
            ))
        return snapshots

    @staticmethod
    def _parse_memory_context(memory_context: str) -> list[MemorySnippet]:
        """
        将字符串格式的记忆上下文解析为 MemorySnippet 列表。
        支持以 '---' 或换行分隔的记忆片段。
        """
        snippets: list[MemorySnippet] = []
        if not memory_context.strip():
            return snippets
        # 按分隔符切分
        chunks = [c.strip() for c in memory_context.split("---") if c.strip()]
        for chunk in chunks[:5]:  # 最多 5 条
            lines = chunk.splitlines()
            tier = "episodic"
            score = 0.7
            # 尝试解析标记行（如 [semantic|0.92]）
            first = lines[0] if lines else ""
            if first.startswith("[") and "|" in first:
                try:
                    meta = first[1:first.index("]")]
                    parts = meta.split("|")
                    tier = parts[0].strip()
                    score = float(parts[1].strip())
                    lines = lines[1:]
                except Exception:
                    pass
            content = "\n".join(lines).strip()
            if content:
                snippets.append(MemorySnippet(
                    content=content,
                    relevance_score=score,
                    tier=tier,
                ))
        return snippets

    # ── 序列化为 Markdown ─────────────────────────────────────────────────────

    @staticmethod
    def _render(s: BackendDataStream) -> str:
        """将 BackendDataStream 序列化为 Markdown 格式（设计文档 §6.3）。"""
        lines: list[str] = [
            "<backend_data_stream>",
            "<!-- 以下内容仅 Agent 可见，不展示给玩家 -->",
            "",
        ]

        # === 轴 1-3：生命与能量 ===
        lines.append("## 生命状态")
        lines.append(f"- 综合HP：{s.hp_status.overall_ratio:.0%}")
        if s.hp_status.critical_parts:
            lines.append(f"- ⚠️ 危急部位：{', '.join(s.hp_status.critical_parts)}")
        for pool in s.energy_pools:
            pct = pool.current / pool.max if pool.max > 0 else 0
            lines.append(
                f"- {pool.name}：{pool.current}/{pool.max}（{pct:.0%}），"
                f"回复 {pool.regen_per_turn}/轮"
            )
        if s.passive_abilities:
            lines.append(f"- 被动技能：{' | '.join(s.passive_abilities[:5])}")

        # === 轴 4-6：装备与技能 ===
        if s.equipped_items:
            lines.append("")
            lines.append("## 已装备")
            for item in s.equipped_items[:6]:
                name = item.get("name", item.get("item_name", "?"))
                tier = item.get("tier", item.get("final_tier", ""))
                lines.append(f"- {name}" + (f"（{tier}★）" if tier else ""))

        if s.application_techniques:
            lines.append("")
            lines.append("## 可用技能")
            for tech in s.application_techniques[:8]:
                cost = f"消耗{tech['cost']}" if tech.get("cost") else ""
                lines.append(f"- {tech['name']}" + (f"（{cost}）" if cost else ""))

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
        if s.world_time or s.current_location:
            lines.append("")
            lines.append("## 世界状态")
            if s.world_time:
                lines.append(f"- 时间：{s.world_time}")
            if s.current_location:
                lines.append(f"- 位置：{s.current_location}")

        # === 轴 14-15：任务进度 ===
        if s.active_quests:
            lines.append("")
            lines.append("## 进行中任务")
            for q in s.active_quests[:5]:
                progress = f" — {q.progress}" if q.progress else ""
                lines.append(f"- {q.title}{progress}")

        if s.active_hooks:
            lines.append("")
            lines.append("## 悬挂叙事钩")
            for h in s.active_hooks[:3]:
                lines.append(f"- {h.description}")

        # === 轴 16：经济状态 ===
        lines.append("")
        lines.append("## 经济状态")
        lines.append(f"- 积分：{s.economy.points} | 徽章：{s.economy.badges} | 等级：{s.economy.tier}")
        if s.economy.currency:
            currency_str = " | ".join(f"{k}: {v}" for k, v in s.economy.currency.items())
            lines.append(f"- 货币：{currency_str}")

        # === 轴 17：战斗状态 ===
        if s.combat and s.combat.active:
            lines.append("")
            lines.append("## 战斗状态 ⚔️")
            lines.append(f"- 当前轮：第 {s.combat.round} 轮")
            if s.combat.initiative_order:
                lines.append(f"- 行动顺序：{' → '.join(s.combat.initiative_order)}")
            for enemy in s.combat.enemies:
                lines.append(
                    f"- 敌方 {enemy.name}（{enemy.tier}★{enemy.tier_sub}）"
                    f" HP {enemy.hp_ratio:.0%}，意图：{enemy.intent}"
                )
            if s.combat.environment_effects:
                lines.append(f"- 环境效果：{', '.join(s.combat.environment_effects)}")

        # === 轴 18：记忆召回 ===
        if s.recalled_memories:
            lines.append("")
            lines.append("## 相关记忆")
            for mem in s.recalled_memories[:3]:
                snippet = mem.content[:120].replace("\n", " ")
                lines.append(f"- [{mem.tier}|{mem.relevance_score:.2f}] {snippet}")

        lines.append("")
        lines.append("</backend_data_stream>")
        return "\n".join(lines)

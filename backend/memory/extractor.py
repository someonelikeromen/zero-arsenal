"""
记忆节点提取管线 — LLM 驱动的对话→8类节点自动提取器
在每个写作回合结束后，作为后台任务异步执行，不阻塞 SSE 流。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from memory.schema import (
    MemoryNode,
    NodeType,
    RelationType,
    TemporalBucket,
    NODE_TYPE_EXTRACTION_HINTS,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


# ════════════════════════════════════════════════════════════════════════════
# 提取 Prompt 模板
# ════════════════════════════════════════════════════════════════════════════

EXTRACTION_SYSTEM_PROMPT = """
你是一个专业的叙事记忆提取器。从对话片段中提取结构化的记忆节点，用于构建小说的知识图谱。

提取规则：
1. 优先提取新信息（对已知节点的修正/补充也要提取）
2. 每条信息只提取一次，避免重复
3. 严格按照指定的 node_type 分类
4. title 必须简洁准确（5~15字）
5. content 包含具体信息（50~200字）
6. temporal_bucket 选择：current（本章）/adjacent_past（近期）/undated（无时间标记）

输出格式（JSON 数组）：
[
  {
    "node_type": "event|rule|thread|character|location|reflection|pov_memory",
    "title": "节点标题",
    "content": "节点内容（具体化，可直接作为后续写作参考）",
    "temporal_bucket": "current",
    "scope_owner": "",  // 仅 pov_memory 需要填写角色名
    "confidence": 0.9,
    "importance": 0.7,
    "extra": {},        // 类型专属字段（见下方说明）
    "relations": [      // 与其他已知节点的关系（可选）
      {
        "target_title": "目标节点标题",
        "relation": "involved_in|occurred_at|advances|caused_by|related|knows|family|romance|friendship|hostile|affiliated|mixed",
        "affinity": 75,               // 仅情感关系填写，0-100
        "emotion_tags": ["亲情"],      // 情感标签，可多个
        "relation_label": "一句话描述关系"  // 如"义妹，过度依赖浩一"
      }
    ]
  }
]

人际情感关系类型说明：
- family:     亲情（血缘/义亲/兄弟姐妹/义父母）
- romance:    爱情/暧昧/单恋/初恋
- friendship: 友情/战友/知己
- hostile:    敌对/仇恨/竞争
- affiliated: 从属/雇佣/组织（上下级关系）
- mixed:      混合感情（亦师亦友/爱恨交织/复杂关系）
家庭、爱情、友情、混合类关系会自动建立双向边。

注意：
- 若无需提取任何节点，输出空数组 []
- 不要编造信息，只提取文本中明确提到的内容
- pov_memory 节点必须指定 scope_owner（角色名）
"""


def _build_extraction_user_prompt(
    dialog_text: str,
    novel_config: dict,
    recent_nodes_summary: str = "",
) -> str:
    """构建提取用 User Prompt"""
    world_name = novel_config.get("world_name", "未知世界")
    protagonist_name = novel_config.get("protagonist_name", "主角")

    hints_section = ""
    for node_type, hints in NODE_TYPE_EXTRACTION_HINTS.items():
        hints_section += f"  {node_type.value}:\n"
        hints_section += f"    title: {hints['title_hint']}\n"
        hints_section += f"    content: {hints['content_hint']}\n"
        if hints.get("extra_fields"):
            hints_section += f"    extra字段: {', '.join(hints['extra_fields'])}\n"
        hints_section += "\n"

    recent_section = (
        f"\n已有记忆节点摘要（避免重复提取）：\n{recent_nodes_summary}\n"
        if recent_nodes_summary
        else ""
    )

    return f"""
世界观：{world_name}
主角名：{protagonist_name}
{recent_section}
各节点类型字段说明：
{hints_section}

请从以下对话片段中提取记忆节点：

---
{dialog_text}
---

输出 JSON 数组（仅 JSON，不要任何解释）：
"""


# ════════════════════════════════════════════════════════════════════════════
# MemoryExtractor — 主提取器
# ════════════════════════════════════════════════════════════════════════════

class MemoryExtractor:
    """
    LLM 驱动的记忆节点提取器。
    对每次写作回合结束后的对话进行分析，提取 8 类节点写入三套存储。
    """

    async def extract_and_persist(
        self,
        novel_id: str,
        world_key: str,
        chapter_id: str,
        new_messages: list[dict],
        novel_config: dict = None,
    ) -> list[str]:
        """
        主入口：从 new_messages 提取节点并写入三套存储。
        Returns: 新创建的 node_id 列表
        """
        if not new_messages:
            return []

        # 1. 拼接对话文本
        dialog_text = self._format_messages(new_messages)
        if not dialog_text.strip():
            return []

        # 2. 获取近期节点摘要（减少重复提取）
        recent_summary = await self._get_recent_nodes_summary(novel_id, world_key)

        # 3. LLM 提取
        raw_nodes = await self._llm_extract(
            dialog_text=dialog_text,
            novel_config=novel_config or {},
            recent_nodes_summary=recent_summary,
        )
        if not raw_nodes:
            return []

        logger.info(f"[Extractor:{novel_id}] 提取到 {len(raw_nodes)} 个节点")

        # 4. 构建 MemoryNode 对象
        nodes = self._build_nodes(raw_nodes, novel_id, world_key, chapter_id)

        # 5. 三套存储原子写入
        created_ids = await self._persist_nodes(novel_id, nodes, raw_nodes)

        return created_ids

    def _format_messages(self, messages: list[dict]) -> str:
        """将消息列表格式化为提取 Prompt 的输入文本"""
        lines = []
        for msg in messages:
            role = "玩家" if msg.get("role") == "user" else "AI"
            content = msg.get("display_content") or msg.get("raw_content", "")
            # 截断过长的正文（避免 Token 超限）
            if len(content) > 2000:
                content = content[:2000] + "...[截断]"
            lines.append(f"【{role}】{content}")
        return "\n\n".join(lines)

    async def _get_recent_nodes_summary(
        self, novel_id: str, world_key: str, max_nodes: int = 20
    ) -> str:
        """获取最近节点的简要摘要（抑制重复提取）"""
        try:
            from memory.graph import graph_manager
            # 取最近的 event/character 节点
            nodes = await graph_manager.get_nodes_by_type(
                novel_id,
                [NodeType.EVENT, NodeType.CHARACTER, NodeType.LOCATION],
                world_key=world_key,
            )
            # 按创建时间降序
            nodes.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            nodes = nodes[:max_nodes]

            if not nodes:
                return ""

            lines = []
            for n in nodes:
                lines.append(f"- [{n.get('node_type')}] {n.get('title', '(无标题)')}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"[Extractor] 获取近期节点失败: {e}")
            return ""

    async def _llm_extract(
        self,
        dialog_text: str,
        novel_config: dict,
        recent_nodes_summary: str,
    ) -> list[dict]:
        """调用 LLM 执行提取，返回原始 JSON 列表"""
        from utils.llm_client import get_llm_client
        llm = get_llm_client()

        user_prompt = _build_extraction_user_prompt(
            dialog_text, novel_config, recent_nodes_summary
        )

        try:
            result = await llm.chat_json(
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                role="dm",           # 使用逻辑推理模型
                temperature=0.3,
                max_tokens=4096,
            )
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and "nodes" in result:
                return result["nodes"]
            return []
        except Exception as e:
            logger.error(f"[Extractor] LLM 提取失败: {e}")
            return []

    def _build_nodes(
        self,
        raw_nodes: list[dict],
        novel_id: str,
        world_key: str,
        chapter_id: str,
    ) -> list[MemoryNode]:
        """将 LLM 输出的原始 JSON 转换为 MemoryNode 对象"""
        nodes = []
        for raw in raw_nodes:
            try:
                node_type_str = raw.get("node_type", "event")
                try:
                    node_type = NodeType(node_type_str)
                except ValueError:
                    node_type = NodeType.EVENT

                bucket_str = raw.get("temporal_bucket", "undated")
                try:
                    temporal_bucket = TemporalBucket(bucket_str)
                except ValueError:
                    temporal_bucket = TemporalBucket.UNDATED

                node = MemoryNode(
                    node_id=_uid(),
                    novel_id=novel_id,
                    node_type=node_type,
                    world_key=world_key,
                    title=raw.get("title", "")[:100],
                    content=raw.get("content", ""),
                    summary=raw.get("summary", raw.get("content", ""))[:200],
                    temporal_bucket=temporal_bucket,
                    chapter_id=chapter_id,
                    created_at=_now(),
                    updated_at=_now(),
                    scope_owner=raw.get("scope_owner", ""),
                    confidence=float(raw.get("confidence", 1.0)),
                    importance=float(raw.get("importance", 0.5)),
                    extra=raw.get("extra", {}),
                )
                nodes.append(node)
            except Exception as e:
                logger.warning(f"[Extractor] 节点构建失败: {e}, raw={raw}")

        return nodes

    async def _persist_nodes(
        self,
        novel_id: str,
        nodes: list[MemoryNode],
        raw_nodes: list[dict],
    ) -> list[str]:
        """
        三套存储原子写入：
        1. NetworkX 图（本地 JSON）
        2. ChromaDB 向量（批量嵌入）
        3. SQLite node_sync_status 记录同步状态
        """
        from memory.graph import graph_manager
        from memory.vector import vector_manager
        from utils.llm_client import get_embedding_client
        from db.queries import get_db

        db = get_db()
        created_ids: list[str] = []

        # Step A: 写入图（NetworkX）
        for node in nodes:
            try:
                await graph_manager.add_node(node.novel_id, node)
                await db.upsert_node_sync(novel_id, node.node_id, sqlite_written=1, graph_written=1)
                created_ids.append(node.node_id)
            except Exception as e:
                logger.error(f"[Extractor] 图写入失败 {node.node_id[:8]}: {e}")

        # Step B: 批量向量嵌入写入（ChromaDB）
        if nodes:
            try:
                emb_client = get_embedding_client()
                texts = [n.content or n.summary or n.title for n in nodes]
                embeddings = await emb_client.embed_batch(texts)
                await vector_manager.upsert_batch(novel_id, nodes, embeddings)
                for node in nodes:
                    await db.upsert_node_sync(novel_id, node.node_id, vector_written=1)
                    await db.mark_node_synced(novel_id, node.node_id)
                logger.info(f"[Extractor] 向量写入: {len(nodes)} 个节点")
            except Exception as e:
                logger.error(f"[Extractor] 向量写入失败: {e}")
                # 标记 retry（后台补偿任务会重试）
                for node in nodes:
                    await db._exec(
                        "UPDATE node_sync_status SET retry_count=retry_count+1 WHERE novel_id=? AND node_id=?",
                        (novel_id, node.node_id),
                    )

        # Step C: 处理关系边
        await self._persist_edges(novel_id, nodes, raw_nodes)

        return created_ids

    async def _persist_edges(
        self,
        novel_id: str,
        nodes: list[MemoryNode],
        raw_nodes: list[dict],
    ) -> None:
        """根据 LLM 提取的 relations 字段建立图谱关系边（情感类型自动建双向边）"""
        from memory.graph import graph_manager
        from memory.schema import RelationType

        title_to_id = {n.title: n.node_id for n in nodes}

        # 情感类型自动双向
        bidirectional = RelationType.emotional_types()

        for node, raw in zip(nodes, raw_nodes):
            relations = raw.get("relations", [])
            for rel in relations:
                target_title  = rel.get("target_title", "")
                rel_type_str  = rel.get("relation", "related")
                affinity      = rel.get("affinity", None)
                emotion_tags  = rel.get("emotion_tags", [])
                relation_label = rel.get("relation_label", "")

                # 在新节点中查找目标
                target_id = title_to_id.get(target_title)

                # 若未找到，尝试在图中精确匹配
                if not target_id:
                    graph = graph_manager.get(novel_id)
                    for nid, data in graph._G.nodes(data=True):
                        if data.get("title") == target_title:
                            target_id = nid
                            break

                if target_id and target_id != node.node_id:
                    try:
                        relation = RelationType(rel_type_str)
                    except ValueError:
                        relation = RelationType.RELATED

                    # 构建边属性
                    edge_attrs = {}
                    if affinity is not None:
                        edge_attrs["affinity"] = int(affinity)
                    if emotion_tags:
                        edge_attrs["emotion_tags"] = json.dumps(emotion_tags, ensure_ascii=False)
                    if relation_label:
                        edge_attrs["relation_label"] = relation_label

                    # 正向边
                    await graph_manager.add_edge(
                        novel_id, node.node_id, target_id, relation, **edge_attrs
                    )

                    # 情感类型：自动建反向边
                    if relation in bidirectional:
                        await graph_manager.add_edge(
                            novel_id, target_id, node.node_id, relation, **edge_attrs
                        )

        # 同步更新 NPC affinity
        await self._sync_npc_affinity_from_edges(novel_id, nodes, raw_nodes)

    async def _sync_npc_affinity_from_edges(
        self,
        novel_id: str,
        nodes: list[MemoryNode],
        raw_nodes: list[dict],
    ) -> None:
        """
        对本轮提取的情感关系边，同步更新 npc_profiles.initial_affinity
        （仅当 affinity 字段明确存在时才更新，避免覆盖无关 NPC）
        """
        from db.queries import get_db
        db = get_db()

        for raw in raw_nodes:
            for rel in raw.get("relations", []):
                if rel.get("affinity") is None:
                    continue
                target_name = rel.get("target_title", "")
                affinity    = int(rel["affinity"])
                if not target_name:
                    continue
                try:
                    # 查找是否有对应的 NPC 档案
                    npc = await db._fetchone(
                        "SELECT name FROM npc_profiles WHERE novel_id=? AND name=?",
                        (novel_id, target_name),
                    )
                    if npc:
                        await db._exec(
                            "UPDATE npc_profiles SET initial_affinity=? WHERE novel_id=? AND name=?",
                            (affinity, novel_id, target_name),
                        )
                except Exception as e:
                    logger.warning(f"[Extractor] NPC affinity 更新失败 {target_name}: {e}")


# ── 全局单例 ──────────────────────────────────────────────────────────────
memory_extractor = MemoryExtractor()

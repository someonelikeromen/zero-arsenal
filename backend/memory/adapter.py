"""
记忆子系统适配器 — 将 ai-vn-system-backend memory/ 接入零度武库 session 体系。
- novel_id = session_id
- world_key = plugin_key
- DB 路径由 set_memory_db_path() 配置
"""
from __future__ import annotations
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 认知分区权重（fallback 模式下用于重排序，与 retriever.SCOPE_WEIGHTS 保持一致）
_SCOPE_WEIGHTS_FALLBACK: dict[str, float] = {
    "character_pov":    1.25,
    "world_state":      1.10,
    "relationship":     1.00,
    "objective_local":  0.90,
    "objective_global": 0.75,
}

# 确保 backend/ 在 sys.path，让 from memory.xxx 能找到
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# 尝试加载完整引擎（防错加固：逐步导入，各阶段独立捕获异常）
_engine = None
_engine_available = False
_engine_unavailable_reason: str = ""

def _try_load_full_engine() -> tuple[object | None, bool, str]:
    """
    分三阶段加载全量引擎，逐步隔离失败点（08-memory-system.md §MemoryEngine full_mode）：
    1. 依赖库检查（sentence-transformers / chromadb）
    2. 子模块导入（graph / vector）
    3. MemoryEngine 实例化（可能触发 model 下载）
    返回 (engine, available, reason)
    """
    # Phase 1: 检查关键依赖库是否可用
    try:
        import importlib
        for lib in ("sentence_transformers", "chromadb"):
            spec = importlib.util.find_spec(lib)
            if spec is None:
                return None, False, f"依赖库缺失: {lib}"
    except Exception as e:
        return None, False, f"依赖检查异常: {e}"

    # Phase 2: 导入子模块（graph / vector）
    try:
        from memory.graph import graph_manager  # type: ignore  # noqa: F401
        from memory.vector import vector_manager  # type: ignore  # noqa: F401
    except Exception as e:
        return None, False, f"子模块导入失败: {e}"

    # Phase 3: 实例化 MemoryEngine（可能触发 embedding model 下载）
    try:
        from memory.engine import MemoryEngine  # type: ignore
        engine = MemoryEngine()
        return engine, True, ""
    except MemoryError as e:
        return None, False, f"内存不足（CUDA OOM/RAM OOM）: {e}"
    except Exception as e:
        return None, False, f"MemoryEngine 实例化失败: {e}"

_engine, _engine_available, _engine_unavailable_reason = _try_load_full_engine()

if _engine_available:
    logger.info("Memory engine loaded (full mode: vector + graph + bigram)")
else:
    logger.warning(
        f"Memory engine unavailable, using SQLite fallback. "
        f"Reason: {_engine_unavailable_reason}"
    )


def get_engine_status() -> dict:
    """返回记忆引擎状态（可挂载到 /health 端点）。"""
    return {
        "mode": "full" if _engine_available else "fallback",
        "available": _engine_available,
        "reason": _engine_unavailable_reason if not _engine_available else "",
    }


def set_memory_db_path(db_path: str) -> None:
    """配置 memory 子系统使用的 SQLite 路径。"""
    if not _engine_available:
        return
    try:
        from memory.graph import graph_manager as gm  # type: ignore
        from memory.vector import vector_manager as vm  # type: ignore
        gm.db_path = db_path
        vm.db_path = db_path
    except Exception as e:
        logger.warning(f"set_memory_db_path failed: {e}")


class MemoryAdapter:
    """
    记忆系统统一接口。
    完整模式：向量（65%）+ Bigram词法（35%）+ 图扩散 + 认知分区权重
    降级模式：SQLite 最近 narrative Parts
    """

    # ── 召回 ─────────────────────────────────────────────────────────────────

    async def recall(
        self,
        session_id: str,
        plugin_key: str,
        query_text: str,
        viewer_agent: str = "narrator",
        top_k: int = 10,
    ) -> str:
        """混合召回，返回拼接后的上下文字符串。"""
        if _engine_available and _engine and query_text.strip():
            try:
                result = await _engine.recall(
                    novel_id=session_id,
                    world_key=plugin_key,
                    query_text=query_text,
                    viewer_agent=viewer_agent,
                    top_k=top_k,
                )
                core = result.get("core", [])
                recalled = result.get("recalled", [])
                parts: list[str] = []
                for node in core[:3]:
                    content = node.get("content", "")
                    ntype = node.get("type", "")
                    if content:
                        parts.append(f"[{ntype}] {content}")
                for node in recalled[:top_k]:
                    content = node.get("content", "")
                    if content:
                        parts.append(content)
                if parts:
                    return "\n---\n".join(parts)
            except Exception as e:
                logger.debug(f"Full recall failed, fallback: {e}")

        return await self._fallback_recall(
            session_id, top_k, query_text=query_text, viewer_agent=viewer_agent
        )

    async def _fallback_recall(
        self, session_id: str, top_k: int = 8,
        query_text: str = "", viewer_agent: str = "narrator",
    ) -> str:
        """
        4 层混合 SQLite fallback（无 ChromaDB 时降级）：
        - Layer 0 core   — 核心记忆（世界规则/关键身份）
        - Layer 1 semantic — 语义记忆（NPC/设定/关键词匹配）
        - Layer 2 episodic — 情节记忆（关键词匹配 + 最近事件）
        - Layer 3 working — 工作记忆（最近 N 条 narrative Parts）
        + 章节摘要作为长程记忆锚点

        viewer_agent POV 过滤：
        - world/rules：仅 objective_global + objective_local 分区（不看主角内心）
        - npc：仅 objective_global + objective_local（不看玩家隐私）
        - narrator/default：无额外限制
        """
        # D6 认知分区白名单（按 viewer_agent 的 5 分区可见集合限制可见范围）
        # 全分区视角（chronicler/narrator）不过滤；受限视角按 allowed 集合构造 IN 白名单。
        partition_cond = ""
        try:
            from memory.retriever import viewer_allowed_partitions, ALL_PARTITIONS
            _allowed = viewer_allowed_partitions(viewer_agent)
            if _allowed and _allowed < ALL_PARTITIONS:
                _inlist = ",".join(f"'{p}'" for p in sorted(_allowed))
                partition_cond = f" AND cognitive_partition IN ({_inlist})"
        except Exception as _vf_err:
            logger.debug(f"[_fallback_recall] viewer filter unavailable: {_vf_err}")
        try:
            from ..db import get_db
            import re as _re

            # 分词（取前 3 个有效词元做 LIKE 匹配）
            tokens: list[str] = []
            if query_text and len(query_text.strip()) >= 2:
                tokens = [t for t in _re.split(r"[\s，。！？、,.\!\?]+", query_text)
                          if len(t) >= 2][:3]

            async with get_db() as db:

                # ── Layer 0: core tier ──────────────────────────────────────
                core_rows = await db.execute(
                    "SELECT content FROM memory_entries "
                    "WHERE session_id=? AND tier='core' "
                    "ORDER BY created_at DESC LIMIT 3",
                    (session_id,),
                )
                core_items = [
                    f"[核心] {r['content']}"
                    for r in await core_rows.fetchall()
                    if r["content"]
                ]

                # ── POV 分区约束已在上方按 viewer_agent 计算为 partition_cond ──

                # ── Layer 1: semantic tier（NPC/设定/lore）+ 关键词过滤 ──
                semantic_like = ""
                semantic_params: list = [session_id]
                if tokens:
                    like_conds = " OR ".join(["content LIKE ?"] * len(tokens))
                    semantic_like = f" AND ({like_conds})"
                    semantic_params += [f"%{t}%" for t in tokens]
                semantic_rows = await db.execute(
                    f"SELECT id, content, cognitive_partition, importance FROM memory_entries "
                    f"WHERE session_id=? AND tier='semantic'{partition_cond}{semantic_like} "
                    f"ORDER BY importance DESC, created_at DESC LIMIT 6",
                    semantic_params,
                )
                _semantic_fetched = await semantic_rows.fetchall()
                # 按 cognitive_partition 权重重排序，取前 4 条
                _scope_w = _SCOPE_WEIGHTS_FALLBACK
                _semantic_scored = sorted(
                    _semantic_fetched,
                    key=lambda r: float(r["importance"] or 0.5) * _scope_w.get(r["cognitive_partition"] or "", 1.0),
                    reverse=True,
                )[:4]
                semantic_items = [
                    f"[设定] {r['content']}"
                    for r in _semantic_scored
                    if r["content"]
                ]
                await self._update_access(db, [r["id"] for r in _semantic_fetched])

                # ── Layer 2: episodic tier（情节事件）+ 关键词过滤 ─────────
                episodic_like = ""
                episodic_params: list = [session_id]
                if tokens:
                    like_conds = " OR ".join(["content LIKE ?"] * len(tokens))
                    episodic_like = f" AND ({like_conds})"
                    episodic_params += [f"%{t}%" for t in tokens]
                episodic_rows = await db.execute(
                    f"SELECT id, content, cognitive_partition, importance FROM memory_entries "
                    f"WHERE session_id=? AND tier='episodic'{partition_cond}{episodic_like} "
                    f"ORDER BY importance DESC, created_at DESC LIMIT 6",
                    episodic_params,
                )
                _episodic_fetched = await episodic_rows.fetchall()
                # 按 cognitive_partition 权重重排序，取前 4 条
                _episodic_scored = sorted(
                    _episodic_fetched,
                    key=lambda r: float(r["importance"] or 0.5) * _scope_w.get(r["cognitive_partition"] or "", 1.0),
                    reverse=True,
                )[:4]
                await self._update_access(db, [r["id"] for r in _episodic_fetched])
                episodic_items = [
                    r["content"]
                    for r in _episodic_scored
                    if r["content"]
                ]

                # ── Layer 3: working memory（最近叙事 Parts）──────────────
                working_limit = max(2, top_k - len(core_items) - len(semantic_items)
                                    - len(episodic_items) // 2)
                narrative_rows = await db.execute(
                    "SELECT content FROM message_parts "
                    "WHERE session_id=? AND type='narrative' AND status='done' "
                    "ORDER BY created_at DESC LIMIT ?",
                    (session_id, working_limit),
                )
                working_items = []
                for r in await narrative_rows.fetchall():
                    try:
                        working_items.append(json.loads(r["content"]).get("text", ""))
                    except Exception:
                        pass

                # ── 世界档案关键词匹配 ─────────────────────────────────────
                world_items: list[str] = []
                for token in tokens[:2]:
                    arch_rows = await db.execute(
                        "SELECT content FROM world_archives "
                        "WHERE session_id=? AND content LIKE ? "
                        "ORDER BY created_at DESC LIMIT 2",
                        (session_id, f"%{token}%"),
                    )
                    for r in await arch_rows.fetchall():
                        try:
                            c = json.loads(r["content"])
                            text = c.get("description") or c.get("content") or ""
                            if text and text not in world_items:
                                world_items.append(f"[世界] {text}")
                        except Exception:
                            pass

                # ── 章节摘要（长程锚点）──────────────────────────────────
                ch_rows = await db.execute(
                    "SELECT summary FROM chapters "
                    "WHERE session_id=? AND is_consolidated=1 AND summary!='' "
                    "ORDER BY created_at DESC LIMIT 3",
                    (session_id,),
                )
                summaries = [f"[章节摘要] {r['summary']}" for r in await ch_rows.fetchall()]

            # 合并（按优先级：摘要 > core > semantic > 世界 > episodic > working）
            combined = (
                summaries
                + core_items
                + semantic_items[:3]
                + world_items[:2]
                + episodic_items[:3]
                + list(reversed(working_items))
            )
            return "\n---\n".join(filter(None, combined)) if combined else ""
        except Exception as e:
            logger.debug(f"[_fallback_recall] failed: {e}")
            return ""

    # ── 写入（提取） ─────────────────────────────────────────────────────────

    async def add_memory(
        self,
        session_id: str,
        plugin_key: str,
        content: str,
        node_type: str = "event",
        chapter_id: str = "",
        metadata: Optional[dict] = None,
    ) -> bool:
        """写入一条记忆，同时写 SQLite 和向量引擎（如可用）。"""
        import uuid
        from datetime import datetime
        from ..db import get_db

        try:
            # 写 SQLite memory_entries
            async with get_db() as db:
                entry_id = str(uuid.uuid4())
                now = datetime.now().timestamp()
                # 将 node_type（event/npc/setting/scene）映射到 tier（episodic/semantic/core）
                _tier_map = {
                    "event":   "episodic",
                    "scene":   "episodic",
                    "npc":     "semantic",
                    "setting": "semantic",
                    "lore":    "semantic",
                    "core":    "core",
                    "rule":    "core",
                }
                tier = _tier_map.get(node_type, "episodic")
                await db.execute(
                    "INSERT INTO memory_entries (id, session_id, chapter_id, content, tier, "
                    "cognitive_partition, source_agent, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (entry_id, session_id, chapter_id or "",
                     content, tier, "objective_global", "system", now)
                )
                await db.commit()

            # 写图谱 + 向量（C5-05：使用模块级单例 + 正确字段名 + 端到端 embedding）
            # 图写入仅依赖 networkx，无 chromadb 也可工作；向量写入在依赖缺失时优雅降级。
            await self._write_node_to_engine(
                entry_id, session_id, plugin_key, content, node_type,
                chapter_id or "", metadata or {},
            )

            return True
        except Exception as e:
            logger.warning(f"add_memory failed: {e}")
            return False

    @staticmethod
    async def _write_node_to_engine(
        entry_id: str,
        session_id: str,
        plugin_key: str,
        content: str,
        node_type: str,
        chapter_id: str,
        metadata: dict,
    ) -> None:
        """
        将一条记忆写入图谱（NetworkX）与向量库（ChromaDB/FAISS，可用时）。
        C5-05：对齐向量写入全链路——
          - 使用模块级 graph_manager / vector_manager 单例（MemoryEngine 无这两属性）
          - MemoryNode 使用正确字段名 node_id / node_type / extra
          - embedding 经 get_embedding_client().embed() 生成（缺失时返回 []，跳过向量写）
        任何一步失败都不影响 SQLite 主写入。
        """
        try:
            from memory.schema import MemoryNode, NodeType
            from memory.graph import graph_manager
            from memory.vector import vector_manager
            from utils.llm_client import get_embedding_client
            from datetime import datetime, timezone

            valid_types = {n.value for n in NodeType}
            nt = NodeType(node_type) if node_type in valid_types else NodeType.EVENT
            now_iso = datetime.now(timezone.utc).isoformat()
            node = MemoryNode(
                node_id=entry_id,
                novel_id=session_id,
                node_type=nt,
                world_key=plugin_key,
                title=(metadata.get("title", "") if isinstance(metadata, dict) else "") or content[:30],
                content=content,
                summary=content[:200],
                chapter_id=chapter_id,
                created_at=now_iso,
                updated_at=now_iso,
                extra=metadata if isinstance(metadata, dict) else {},
            )

            # 图写入（无 chromadb 也可工作）
            await graph_manager.add_node(session_id, node)

            # 向量写入（embedding 缺失则跳过，不报错）
            emb_client = get_embedding_client()
            embedding = await emb_client.embed(content or node.summary or node.title)
            if embedding:
                await vector_manager.upsert_node(session_id, node, embedding)
        except Exception as ve:
            logger.debug(f"Engine node write failed (non-critical): {ve}")

    def enqueue_extraction(
        self,
        session_id: str,
        plugin_key: str,
        chapter_id: str,
        messages: list[dict],
        narrative_text: str = "",
        novel_config: Optional[dict] = None,
    ) -> bool:
        """
        将后台记忆提取任务加入队列（生产主路径，C5-03/D5）。

        无论 full engine 是否可用，入队的任务都携带完整 payload
        （messages / novel_id / world_key / novel_config），使队列消费者
        extract_queue._process_task 能够运行 LLM 图谱提取（轨道 A，写 NetworkX 图，
        图写入不依赖 chromadb），同时保留启发式 SQLite 兜底（轨道 B）。
        """
        # 拼接 narrative 文本（轨道 B 兜底用）
        text = narrative_text
        if not text:
            text = "\n".join(
                m.get("content", "")
                for m in messages
                if m.get("role") in ("assistant", "narrator")
            )
        # 提取 user_input（第一条 user 消息）
        user_input = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"), ""
        )
        task = {
            "session_id":     session_id,
            "novel_id":       session_id,   # session 体系中 novel_id == session_id
            "world_key":      plugin_key,
            "chapter_id":     chapter_id,
            "narrative_text": text,
            "user_input":     user_input,
            "messages":       messages,
            "novel_config":   novel_config or {},
            "source_agent":   "auto_extraction",
        }

        # 优先 full engine（其 enqueue 也会带上 messages）
        if _engine_available and _engine:
            try:
                return _engine.enqueue_extraction(
                    novel_id=session_id,
                    world_key=plugin_key,
                    chapter_id=chapter_id,
                    messages=messages,
                    novel_config=novel_config or {},
                )
            except Exception as e:
                logger.warning(f"enqueue_extraction (engine) failed: {e}")

        # 降级/默认：内置 ExtractQueue（双轨：LLM 图谱 + SQLite 兜底）
        try:
            from .extract_queue import extract_queue
            return extract_queue.enqueue(task)
        except Exception as e:
            logger.warning(f"enqueue_extraction (fallback) failed: {e}")
            return False

    async def get_chapter_summaries(self, session_id: str, limit: int = 3) -> str:
        """获取最近 N 章摘要。"""
        try:
            from ..db import get_db
            async with get_db() as db:
                rows = await db.execute(
                    "SELECT summary, branch_label FROM chapters "
                    "WHERE session_id=? AND is_consolidated=1 AND summary!='' "
                    "ORDER BY created_at DESC LIMIT ?",
                    (session_id, limit)
                )
                parts = []
                for r in await rows.fetchall():
                    label = f"[{r['branch_label']}] " if r["branch_label"] else ""
                    parts.append(f"{label}{r['summary']}")
            return "\n\n".join(reversed(parts)) if parts else ""
        except Exception:
            return ""

    @staticmethod
    async def _update_access(db, ids: list[str]) -> None:
        """被召回时更新 access_count 和 last_accessed_at（遗忘曲线支撑）。"""
        if not ids:
            return
        from datetime import datetime as _dt
        _now = _dt.now().timestamp()
        try:
            placeholders = ",".join("?" * len(ids))
            await db.execute(
                f"UPDATE memory_entries SET "
                f"access_count = access_count + 1, "
                f"last_accessed_at = ? "
                f"WHERE id IN ({placeholders})",
                [_now] + ids,
            )
            await db.commit()
        except Exception as _e:
            logger.debug(f"_update_access failed (non-critical): {_e}")

    async def consolidate_session(self, session_id: str) -> dict:
        """
        固化会话记忆：将 100 条以上的 episodic 记忆（按 importance 排序）
        中最低 importance 的一批合并为一条 semantic 摘要，然后删除原条目。
        SQLite fallback 模式下可用；full engine 模式下委托 MemoryEngine。
        返回 {"compressed": int, "kept": int, "summary_created": bool}
        """
        if _engine_available and _engine:
            try:
                from ..db import get_db as _get_db
                async with _get_db() as db:
                    ch_row = await (await db.execute(
                        "SELECT plugin_key FROM sessions WHERE id=?", (session_id,)
                    )).fetchone()
                world_key = ch_row["plugin_key"] if ch_row else "crossover"
                ch_row2 = None
                async with _get_db() as db:
                    ch_row2 = await (await db.execute(
                        "SELECT id FROM chapters WHERE session_id=? AND is_consolidated=0 "
                        "ORDER BY created_at DESC LIMIT 1", (session_id,)
                    )).fetchone()
                chapter_id = ch_row2["id"] if ch_row2 else session_id
                removed = await _engine.consolidate(
                    novel_id=session_id, world_key=world_key, chapter_id=chapter_id
                )
                return {"compressed": removed, "kept": -1, "summary_created": removed > 0}
            except Exception as e:
                logger.warning(f"consolidate_session (engine) failed: {e}")

        # ── SQLite fallback: episodic 压缩 ────────────────────────────────────
        _THRESHOLD = 100
        _COMPRESS_RATIO = 0.3  # 压缩最旧的 30%
        try:
            from ..db import get_db as _get_db
            import uuid as _uuid
            from datetime import datetime as _dt

            async with _get_db() as db:
                rows = await (await db.execute(
                    "SELECT id, content, importance FROM memory_entries "
                    "WHERE session_id=? AND cognitive_partition='episodic' "
                    "ORDER BY importance ASC, created_at ASC",
                    (session_id,)
                )).fetchall()

            total = len(rows)
            if total < _THRESHOLD:
                return {"compressed": 0, "kept": total, "summary_created": False}

            n_compress = max(1, int(total * _COMPRESS_RATIO))
            to_compress = rows[:n_compress]
            ids_to_del = [r["id"] for r in to_compress]
            combined = "；".join(r["content"][:80] for r in to_compress)
            summary_content = f"[历史摘要×{n_compress}] {combined}"

            async with _get_db() as db:
                await db.execute(
                    "INSERT OR IGNORE INTO memory_entries "
                    "(id, session_id, content, tier, cognitive_partition, "
                    " source_agent, importance, created_at) "
                    "VALUES (?, ?, ?, 'semantic', 'semantic_world', 'consolidator', 0.6, ?)",
                    (_uuid.uuid4().hex, session_id, summary_content, _dt.now().timestamp())
                )
                ph = ",".join("?" * len(ids_to_del))
                await db.execute(
                    f"DELETE FROM memory_entries WHERE id IN ({ph})", ids_to_del
                )
                await db.commit()

            return {"compressed": n_compress, "kept": total - n_compress, "summary_created": True}
        except Exception as e:
            logger.warning(f"consolidate_session (fallback) failed: {e}")
            return {"compressed": 0, "kept": -1, "summary_created": False, "error": str(e)}

    @property
    def is_full_mode(self) -> bool:
        return _engine_available


# 全局单例
memory_adapter = MemoryAdapter()

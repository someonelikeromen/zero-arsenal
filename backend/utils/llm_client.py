"""
用途: utils 层 LLM 客户端封装，供 memory/ 子系统使用。
      提供 get_llm_client() 和 get_embedding_client() 两个工厂函数。
用法: from utils.llm_client import get_llm_client, get_embedding_client
环境变量:
  DEEPSEEK_API_KEY — DeepSeek API Key
  OPENAI_API_KEY   — OpenAI API Key
MCP集成: 可直接包装为 MCP tool
Skill集成: memory/ 子系统自动导入
"""
from __future__ import annotations
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class _LLMClient:
    """
    简单的 LLM 客户端包装，统一 memory/ 调用接口。
    底层复用 agents.llm.llm_complete。
    """

    def __init__(self, provider: str = "deepseek", model: str = "deepseek-chat") -> None:
        self.provider = provider
        self.model = model

    async def chat(
        self,
        messages: list[dict],
        role: str = "narrator",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        """非流式聊天，返回完整字符串。"""
        try:
            from agents.llm import llm_complete, load_agent_config
            cfg = load_agent_config(role)
            return await llm_complete(
                messages=messages,
                provider=cfg.get("provider", self.provider),
                model=cfg.get("model", self.model),
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except ImportError:
            from backend.agents.llm import llm_complete  # type: ignore[no-redef]
            return await llm_complete(
                messages=messages,
                provider=self.provider,
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    async def chat_json(
        self,
        messages: list[dict],
        role: str = "narrator",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> Any:
        """调用 LLM 并解析 JSON 响应，失败时返回空列表。"""
        raw = await self.chat(messages=messages, role=role,
                              temperature=temperature, max_tokens=max_tokens)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"[LLMClient] chat_json parse error: {e}, raw={raw[:200]}")
            return []


class _EmbeddingClient:
    """
    Embedding 客户端包装。
    优先使用 sentence-transformers；不可用时退化为零向量并记录警告。
    """

    def __init__(self) -> None:
        self._model = None
        self._unavailable = False

    def _load(self) -> None:
        if self._unavailable or self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        except Exception as e:
            logger.warning(f"[EmbeddingClient] sentence-transformers 不可用: {e}，向量召回降级为空")
            self._unavailable = True

    async def embed(self, text: str) -> list[float]:
        """将文本转换为 embedding 向量。不可用时返回空列表。"""
        self._load()
        if self._unavailable or self._model is None:
            return []
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(None, self._model.encode, text)
            return embedding.tolist()
        except Exception as e:
            logger.warning(f"[EmbeddingClient] embed 失败: {e}")
            return []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量将文本转换为 embedding 向量。不可用时返回等长空向量列表。"""
        self._load()
        if self._unavailable or self._model is None or not texts:
            return [[] for _ in texts]
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            # SentenceTransformer.encode 接受 list[str] 返回 ndarray[N, D]
            embeddings = await loop.run_in_executor(None, self._model.encode, texts)
            return [e.tolist() for e in embeddings]
        except Exception as e:
            logger.warning(f"[EmbeddingClient] embed_batch 失败: {e}")
            return [[] for _ in texts]


_llm_client_instance: _LLMClient | None = None
_emb_client_instance: _EmbeddingClient | None = None


def get_llm_client() -> _LLMClient:
    """返回全局 LLM 客户端单例。"""
    global _llm_client_instance
    if _llm_client_instance is None:
        _llm_client_instance = _LLMClient()
    return _llm_client_instance


def get_embedding_client() -> _EmbeddingClient:
    """返回全局 Embedding 客户端单例。"""
    global _emb_client_instance
    if _emb_client_instance is None:
        _emb_client_instance = _EmbeddingClient()
    return _emb_client_instance

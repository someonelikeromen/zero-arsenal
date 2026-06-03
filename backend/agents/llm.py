"""
LiteLLM 封装层 — 统一 LLM 调用接口。
支持非流式调用和流式 delta 回调。
"""
from __future__ import annotations
import os
import json
import logging
from typing import AsyncIterator, Callable, Awaitable, Optional
import litellm

logger = logging.getLogger(__name__)

# 自动从 .env 加载（若 python-dotenv 可用）
def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        # 向上查找 .env 文件
        p = Path(__file__).resolve()
        for _ in range(6):
            env_file = p / ".env"
            if env_file.exists():
                load_dotenv(env_file, override=False)
                break
            p = p.parent
    except ImportError:
        pass

_load_env()

# litellm 全局 key 配置
_deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
_openai_key = os.environ.get("OPENAI_API_KEY", "")
if _deepseek_key:
    os.environ["DEEPSEEK_API_KEY"] = _deepseek_key
if _openai_key:
    os.environ["OPENAI_API_KEY"] = _openai_key


def _build_model_str(provider: str, model: str) -> str:
    """构建 litellm 模型字符串。"""
    if provider == "deepseek":
        return f"deepseek/{model}"
    if provider == "openai":
        return f"openai/{model}"
    return model


async def llm_complete(
    messages: list[dict],
    provider: str = "deepseek",
    model: str = "deepseek-chat",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    response_format: Optional[dict] = None,
    timeout: float = 60.0,
) -> str:
    """非流式 LLM 调用，返回完整字符串。超时抛出 asyncio.TimeoutError。"""
    import asyncio
    model_str = _build_model_str(provider, model)
    kwargs: dict = dict(
        model=model_str,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if response_format:
        kwargs["response_format"] = response_format

    try:
        resp = await asyncio.wait_for(
            litellm.acompletion(**kwargs),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError(f"llm_complete timeout after {timeout}s ({model_str})")
    return resp.choices[0].message.content or ""


async def llm_stream(
    messages: list[dict],
    on_delta: Callable[[str], Awaitable[None]],
    provider: str = "deepseek",
    model: str = "deepseek-chat",
    temperature: float = 0.85,
    max_tokens: int = 2048,
    timeout: float = 120.0,
) -> str:
    """
    流式 LLM 调用。
    每次收到 delta 调用 on_delta(delta_text)，最终返回完整文本。
    总超时 120 秒（叙事较长，预留足够时间）。
    """
    import asyncio
    model_str = _build_model_str(provider, model)

    async def _stream_inner() -> str:
        full_text = ""
        async for chunk in await litellm.acompletion(
            model=model_str,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        ):
            delta = chunk.choices[0].delta.content or ""
            if delta:
                full_text += delta
                await on_delta(delta)
        return full_text

    try:
        return await asyncio.wait_for(_stream_inner(), timeout=timeout)
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError(f"llm_stream timeout after {timeout}s ({model_str})")


_AGENT_CONFIG_WARNED: set[str] = set()


def load_agent_config(agent_name: str) -> dict:
    """从 data/sys_config/agents.json 读取 Agent LLM 配置。"""
    _default = {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.7, "max_tokens": 1024}
    config_path = _find_config()
    if config_path is None:
        if "agents.json" not in _AGENT_CONFIG_WARNED:
            _AGENT_CONFIG_WARNED.add("agents.json")
            logger.warning(
                "[LLM] agents.json 未找到，所有 Agent 使用硬编码默认配置（deepseek-chat）。"
                "请在 data/sys_config/agents.json 中配置各 Agent 的模型参数。"
            )
        return _default
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    agents = data.get("agents", {})
    cfg = agents.get(agent_name)
    if cfg is None:
        warn_key = f"agent:{agent_name}"
        if warn_key not in _AGENT_CONFIG_WARNED:
            _AGENT_CONFIG_WARNED.add(warn_key)
            logger.warning(
                "[LLM] agents.json 中未找到 Agent '%s' 的配置，使用硬编码默认值。"
                "请在 agents.json 的 'agents' 字段中添加 '%s' 配置项。",
                agent_name, agent_name,
            )
        return _default
    return cfg


def _find_config() -> Optional[str]:
    """向上查找 data/sys_config/agents.json。"""
    from pathlib import Path
    p = Path(__file__).resolve()
    for _ in range(5):
        candidate = p.parent / "data" / "sys_config" / "agents.json"
        if candidate.exists():
            return str(candidate)
        p = p.parent
    return None

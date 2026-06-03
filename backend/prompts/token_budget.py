"""
TokenBudget — 管理 Agent 管线的 Token 使用，防止 context 超限。
设计文档 05-prompt-architecture.md §7 Token 预算管理
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

DEFAULT_BUDGETS: dict[str, int] = {
    "rules":          512,
    "dm":             768,
    "npc":            512,
    "world":          512,
    "narrator_plan":  512,
    "narrator_write": 2048,
    "narrator_var":   1024,
    "style":          256,
    "var":            512,
    "chronicler":     1024,
}

_PROFILE_MULTIPLIERS: dict[str, float] = {
    "play":   1.0,
    "plan":   1.5,
    "review": 0.8,
}

# 中文字符正则
_ZH_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


class TokenBudget:
    """
    Token 预算控制器。
    提供估算、预算查询、上下文裁剪三个核心功能。
    """

    def estimate_tokens(self, text: str) -> int:
        """
        简单估算文本 token 数量。
        - 中文字符：每个字约 1.5 token（CJK 通常被分为 1-2 个 token）
        - 英文：每个单词约 0.75 token（平均约 1.3 个单词/token）
        - 其余字符参与英文估算
        """
        if not text:
            return 0

        zh_chars = len(_ZH_PATTERN.findall(text))
        remaining = text
        # 去除中文字符后估算英文部分
        non_zh = _ZH_PATTERN.sub("", remaining)
        en_words = len(non_zh.split())

        tokens = int(zh_chars * 1.5 + en_words * 0.75)
        return max(tokens, 1) if text.strip() else 0

    def check_budget(
        self,
        agent_name: str,
        input_tokens: int,
        profile: str = "play",
    ) -> int:
        """
        返回该 agent 在当前 profile 下可用的 output token 数。

        profile:
          - play:   满额（×1.0）
          - plan:   允许更多分析（×1.5）
          - review: 限制输出（×0.8）
        """
        base = DEFAULT_BUDGETS.get(agent_name, 512)
        multiplier = _PROFILE_MULTIPLIERS.get(profile, 1.0)
        budget = int(base * multiplier)

        logger.debug(
            f"TokenBudget: {agent_name} | profile={profile} | "
            f"base={base} | multiplier={multiplier} | budget={budget} | input={input_tokens}"
        )
        return budget

    def compress_context(
        self,
        messages: list[dict],
        max_tokens: int,
    ) -> list[dict]:
        """
        裁剪消息列表，使估算 token 总量不超过 max_tokens。
        策略：
        1. 始终保留 system message（role=="system"）
        2. 从最老的中间消息开始移除，直到符合预算
        3. 至少保留最新一条消息
        """
        if not messages:
            return messages

        # 分离 system 消息
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system  = [m for m in messages if m.get("role") != "system"]

        def _total_tokens(msgs: list[dict]) -> int:
            return sum(
                self.estimate_tokens(m.get("content", "") if isinstance(m.get("content"), str) else "")
                for m in msgs
            )

        system_tokens = _total_tokens(system_msgs)
        remaining_budget = max_tokens - system_tokens

        if remaining_budget <= 0:
            # system 消息本身已超预算，只返回 system 消息
            logger.warning("TokenBudget: system 消息已超出预算，截断为仅 system 消息")
            return system_msgs

        # 从最老的中间消息开始裁剪（保留最后一条）
        working = list(non_system)
        while len(working) > 1 and _total_tokens(working) > remaining_budget:
            removed = working.pop(0)
            logger.debug(
                f"TokenBudget: 移除最老消息 role={removed.get('role')} "
                f"(剩余 {len(working)} 条)"
            )

        return system_msgs + working


# 全局单例
token_budget = TokenBudget()

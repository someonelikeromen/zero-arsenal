"""
PromptFragment Registry — 5层提示词架构管理器。
参考设计文档 05-prompt-architecture.md。

层级（priority 决定拼接顺序）：
  core(0-99) → agent(100-199) → world(200-299) → skill(300-399) → runtime(400+)

Trigger 类型：
  always    — 每次都注入（默认）
  auto      — 满足 condition 时自动注入
  on_demand — 只在显式调用 load_skill / PUSH 时注入
"""
from __future__ import annotations
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# 设置 ZERO_ARSENAL_PROMPT_AUDIT=1 启用 prompt audit log（P1 修复）
_AUDIT_ENABLED: bool = os.getenv("ZERO_ARSENAL_PROMPT_AUDIT", "0") == "1"

logger = logging.getLogger(__name__)


@dataclass
class PromptFragment:
    id: str
    layer: str                              # core | agent | world | skill | runtime
    phase: list[str]                        # ["all"] | ["p1","p3"] 等
    content: str
    priority: int = 100
    inject_as: str = "system"              # system | user
    condition: Optional[str] = None        # 条件表达式（auto trigger 时求值）
    trigger: str = "always"               # always | auto | on_demand
    agent_filter: list[str] = field(default_factory=list)  # 空=全 agent，非空=限定 agent
    depth: int = 0                         # 嵌套深度（用于 PUSH/POP）
    enabled: bool = True                   # False=跳过（热开关）

    def matches_phase(self, phase: str) -> bool:
        return "all" in self.phase or phase in self.phase

    def matches_agent(self, agent_name: str) -> bool:
        """若 agent_filter 为空则全部匹配，否则仅允许列表中的 agent。"""
        return not self.agent_filter or agent_name in self.agent_filter


class PromptRegistry:
    """
    提示词片段注册表（5层架构）。
    设计文档 05-prompt-architecture.md

    层级：
      core(0-99) → agent(100-199) → world(200-299) → skill(300-399) → runtime(400+)

    runtime 层是会话级/回合级动态片段：
    - register_runtime(): 注入当前回合的动态上下文（如骰子结果、世界事件）
    - clear_runtime(): 回合结束后清理（可选，TTL 自动过期）
    - 支持 condition 表达式求值（Python eval，安全沙箱）
    """

    def __init__(self) -> None:
        self._fragments: dict[str, PromptFragment] = {}
        # runtime 层：session_id → {frag_id: PromptFragment}
        self._runtime: dict[str, dict[str, PromptFragment]] = {}

    def register(self, frag: PromptFragment) -> None:
        self._fragments[frag.id] = frag

    def register_from_dict(self, data: dict) -> None:
        self.register(PromptFragment(
            id=data["id"],
            layer=data.get("layer", "runtime"),
            phase=data.get("phase", ["all"]) if isinstance(data.get("phase"), list) else [data.get("phase", "all")],
            content=data["content"],
            priority=data.get("priority", 100),
            inject_as=data.get("inject_as", "system"),
            condition=data.get("condition"),
            trigger=data.get("trigger", "always"),
            agent_filter=data.get("agent_filter", []),
            depth=data.get("depth", 0),
            enabled=data.get("enabled", True),
        ))

    def register_runtime(
        self,
        session_id: str,
        frag_id: str,
        content: str,
        phase: list[str] | None = None,
        priority: int = 450,
        inject_as: str = "system",
    ) -> None:
        """
        注册一个 runtime 层动态片段（当前会话/回合专用）。
        设计文档 05 §4.5 — Layer 5 runtime 动态注入。
        """
        frag = PromptFragment(
            id=frag_id,
            layer="runtime",
            phase=phase or ["all"],
            content=content,
            priority=priority,
            inject_as=inject_as,
        )
        if session_id not in self._runtime:
            self._runtime[session_id] = {}
        self._runtime[session_id][frag_id] = frag

    def clear_runtime(self, session_id: str) -> None:
        """清理指定会话的所有 runtime 片段（回合结束时调用）。"""
        self._runtime.pop(session_id, None)

    def get_runtime_frags(self, session_id: str) -> list[PromptFragment]:
        """获取指定会话的 runtime 层片段列表。"""
        return list(self._runtime.get(session_id, {}).values())

    def _evaluate_condition(self, condition: str, state: dict) -> bool:
        """
        安全评估 condition 字段（表达式）。

        D18：此前用裸 `eval()`（即便清空 __builtins__，属性访问 / dunder 仍可能
        被滥用）。改用 simpleeval 沙箱；simpleeval 不可用时降级为受限 eval
        （清空 builtins）并记录一次告警，绝不静默放行任意代码。
        """
        try:
            from simpleeval import simple_eval
            return bool(simple_eval(condition, names={"state": state}))
        except ImportError:
            logger.warning(
                "[PromptRegistry] simpleeval 未安装，condition 降级为受限 eval（建议安装 simpleeval）"
            )
            try:
                return bool(eval(condition, {"__builtins__": {}}, {"state": state}))  # noqa: S307
            except Exception:
                logger.warning("[PromptRegistry] condition eval failed: %s — skipping fragment", condition)
                return False
        except Exception:
            logger.warning("[PromptRegistry] condition eval failed: %s — skipping fragment", condition)
            return False  # 条件求值失败时跳过，不注入

    def get_for_phase(
        self,
        phase: str,
        layers: Optional[list[str]] = None,
        inject_as: Optional[str] = None,
        session_id: Optional[str] = None,
        state: Optional[dict] = None,
        agent_name: Optional[str] = None,
        exclude_on_demand: bool = True,
        token_budget: Optional[int] = None,
    ) -> list[PromptFragment]:
        """
        返回匹配 phase 的片段，按 priority 升序。

        新增过滤条件（对齐 05-prompt-architecture.md）：
        - enabled=False 的片段跳过
        - trigger=on_demand 的片段默认跳过（显式调用时传 exclude_on_demand=False）
        - agent_filter 非空时，只返回包含 agent_name 的片段
        - trigger=auto 时，evaluation condition 决定是否注入
        """
        def _passes(f: PromptFragment) -> bool:
            if not f.enabled:
                return False
            if exclude_on_demand and f.trigger == "on_demand":
                return False
            if not f.matches_phase(phase):
                return False
            if layers is not None and f.layer not in layers:
                return False
            if inject_as is not None and f.inject_as != inject_as:
                return False
            if agent_name and not f.matches_agent(agent_name):
                return False
            # auto trigger: condition 决定
            if f.trigger == "auto" and f.condition:
                return self._evaluate_condition(f.condition, state or {})
            # always/on_demand trigger: condition 是额外过滤器
            if f.condition and f.trigger != "auto":
                return self._evaluate_condition(f.condition, state or {})
            return True

        result = [f for f in self._fragments.values() if _passes(f)]

        # runtime 层片段
        if session_id and (layers is None or "runtime" in layers):
            for f in self.get_runtime_frags(session_id):
                if (f.enabled
                        and f.matches_phase(phase)
                        and (inject_as is None or f.inject_as == inject_as)
                        and (not agent_name or f.matches_agent(agent_name))):
                    result.append(f)

        result = sorted(result, key=lambda x: x.priority)

        # TokenBudget 裁剪（P2 / NEW-C12-02）：按 priority 升序保留，
        # 累计 token_estimate 不超过 budget。NEW-C12-06：先判断是否放得下再纳入，
        # 避免「先 append 后减」造成的 off-by-one 过量包含。
        if token_budget is not None and token_budget > 0:
            try:
                from .token_budget import TokenBudget as _TB
                _tb = _TB()
                kept: list[PromptFragment] = []
                remaining = token_budget
                for frag in result:
                    est = _tb.estimate_tokens(frag.content)
                    if est > remaining:
                        # 高优先级（已排序靠前）片段优先；放不下则停止纳入后续低优先级片段
                        break
                    kept.append(frag)
                    remaining -= est
                if len(kept) < len(result):
                    logger.debug(
                        "[PromptRegistry] token_budget=%d 裁剪片段 %d → %d",
                        token_budget, len(result), len(kept),
                    )
                result = kept
            except Exception as e:
                logger.warning(
                    "[PromptRegistry] TokenBudget 裁剪异常，退化为无裁剪: %s", e
                )

        return result

    def build_system_prompt(
        self,
        phase: str,
        extra_vars: dict | None = None,
        session_id: Optional[str] = None,
        state: Optional[dict] = None,
        agent_name: Optional[str] = None,
        audit_log: bool | None = None,
        token_budget: Optional[int] = None,
    ) -> str:
        """
        拼接所有 inject_as=system 的片段为完整 system prompt。
        session_id: 若提供，同时包含 runtime 层动态片段。
        agent_name: 若提供，过滤 agent_filter。
        audit_log: True 时将使用的 fragment ID 列表写入 prompt_log.jsonl。
        token_budget: 非 None 时按 TokenBudget 裁剪 fragment 总量（P2）。
        """
        # NEW-C12-04：统一经规范入口 build()（设计 §5.3）构建 messages，
        # 再抽取 system 角色内容，使 build() 不再是死代码而成为主路径核心。
        _do_audit = _AUDIT_ENABLED if audit_log is None else audit_log
        messages = self.build(
            phase=phase,
            agent_id=agent_name or "",
            state=state,
            extra_vars=extra_vars,
            session_id=session_id,
            audit_log=_do_audit,
            token_budget=token_budget,
        )
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        return "\n\n".join(p for p in system_parts if p.strip())

    def build_user_prefix(
        self,
        phase: str,
        extra_vars: dict | None = None,
        session_id: Optional[str] = None,
        state: Optional[dict] = None,
        agent_name: Optional[str] = None,
    ) -> str:
        """拼接所有 inject_as=user 的片段（SKILL.md 注入）。"""
        frags = self.get_for_phase(phase, inject_as="user",
                                   session_id=session_id, state=state,
                                   agent_name=agent_name)
        parts = [self._interpolate(f.content, extra_vars or {}) for f in frags]
        return "\n\n".join(p for p in parts if p.strip())

    def build(
        self,
        phase: str,
        agent_id: str,
        state: Optional[dict] = None,
        extra_vars: dict | None = None,
        session_id: Optional[str] = None,
        audit_log: bool = False,
        token_budget: Optional[int] = None,
    ) -> list[dict[str, str]]:
        """
        设计文档 05-prompt-architecture.md §5.3 PromptRegistry.build()

        返回 OpenAI messages 格式：[{"role": "system"|"user", "content": "..."}]

        构建规则：
          1. 收集当前 phase + agent_id 匹配的所有片段，按 priority 升序排序
          2. 按 inject_as 分组为 "system" 和 "user" 两种 role
          3. 同 role 连续片段合并为一条消息（减少 token 计数 overhead）
          4. 若有 user 片段，最终结构为 [system_msg, user_msg]；否则仅 [system_msg]
          5. 空内容消息（strip 后为空）不输出

        Args:
            phase:      当前阶段，如 "p1" / "p2" / "dm" / "all"
            agent_id:   Agent 名称，用于 agent_filter 过滤
            state:      回合状态字典，用于 condition 求值
            extra_vars: 额外模板变量（{key} 插值）
            session_id: 提供时包含 runtime 层动态片段
            audit_log:  True 时将 fragment 使用记录写入 prompt_log.jsonl
        """
        frags = self.get_for_phase(
            phase,
            session_id=session_id,
            state=state,
            agent_name=agent_id,
            token_budget=token_budget,
        )
        vars_ = extra_vars or {}

        # 按 inject_as 收集内容
        system_parts: list[str] = []
        user_parts: list[str] = []
        used_ids: list[str] = []

        for f in frags:
            text = self._interpolate(f.content, vars_).strip()
            if not text:
                continue
            used_ids.append(f.id)
            if f.inject_as == "user":
                user_parts.append(text)
            else:
                system_parts.append(text)

        messages: list[dict[str, str]] = []
        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})
        if user_parts:
            messages.append({"role": "user", "content": "\n\n".join(user_parts)})

        if audit_log and used_ids:
            combined_content = "".join(m["content"] for m in messages)
            self._write_prompt_log(
                phase=phase,
                agent_name=agent_id,
                session_id=session_id or "",
                frag_ids=used_ids,
                char_count=len(combined_content),
            )

        return messages

    def _write_prompt_log(
        self,
        phase: str,
        agent_name: str,
        session_id: str,
        frag_ids: list[str],
        char_count: int,
    ) -> None:
        """将每次 build 使用的 fragment 列表追加写入 prompt_log.jsonl（审计落盘）。"""
        try:
            log_dir = Path("data/logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "prompt_log.jsonl"
            entry = {
                "ts": datetime.utcnow().isoformat(),
                "phase": phase,
                "agent": agent_name,
                "session": session_id,
                "frags": frag_ids,
                "chars": char_count,
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug(f"[prompt_log] write failed: {e}")

    def _interpolate(self, template: str, vars_: dict) -> str:
        """简单 {key} 模板替换。"""
        def replacer(m: re.Match) -> str:
            key = m.group(1)
            return str(vars_.get(key, m.group(0)))
        return re.sub(r"\{(\w+)\}", replacer, template)

    def list_fragments(self) -> list[dict]:
        return [
            {"id": f.id, "layer": f.layer, "phase": f.phase,
             "priority": f.priority, "inject_as": f.inject_as}
            for f in sorted(self._fragments.values(), key=lambda x: x.priority)
        ]


# 全局单例
registry = PromptRegistry()

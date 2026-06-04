"""
RulesLoader — 扫描 extensions/*/rules/*.md 并解析规则扩展。
规则文件 frontmatter 格式（yaml）：
    trigger: always | on_demand
    applicable_agents: [rules, dm, narrator]  # 空=全部
    priority: 0-100（数字越大越优先注入）
    enabled: true
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RuleEntry:
    rule_id: str          # 唯一 ID，格式：{extension_key}/{filename_without_ext}
    extension_key: str
    title: str
    content: str          # 规则正文（frontmatter 之后的部分）
    trigger: str = "always"       # always | on_demand
    applicable_agents: list = field(default_factory=list)  # 空=全部
    priority: int = 50
    enabled: bool = True

    def matches_agent(self, agent_name: str) -> bool:
        return not self.applicable_agents or agent_name in self.applicable_agents


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, RuleEntry] = {}

    def register(self, rule: RuleEntry) -> None:
        self._rules[rule.rule_id] = rule

    def get(self, rule_id: str) -> Optional[RuleEntry]:
        return self._rules.get(rule_id)

    def list_rules(self) -> list[dict]:
        return [
            {
                "rule_id": r.rule_id,
                "title": r.title,
                "trigger": r.trigger,
                "applicable_agents": r.applicable_agents,
                "priority": r.priority,
                "enabled": r.enabled,
            }
            for r in self._rules.values()
        ]

    def get_for_agent(self, agent_name: str, trigger: str = "always") -> list[RuleEntry]:
        """获取适用于指定 agent 的规则，按 priority 降序。"""
        rules = [
            r for r in self._rules.values()
            if r.enabled and r.matches_agent(agent_name)
            and (trigger == "all" or r.trigger == trigger or r.trigger == "always")
        ]
        return sorted(rules, key=lambda r: r.priority, reverse=True)

    def build_injection_block(
        self,
        agent_name: str,
        on_demand_ids: list[str] | None = None,
    ) -> str:
        """
        构建注入到系统提示的规则文本块。

        总是包含 trigger=always 的规则。
        若提供 on_demand_ids，额外包含 trigger=on_demand 且 rule_id 在列表中的规则。
        """
        rules = self.get_for_agent(agent_name, trigger="always")
        if on_demand_ids:
            od_rules = [
                r for r in self._rules.values()
                if r.enabled
                and r.trigger == "on_demand"
                and r.rule_id in on_demand_ids
                and r.matches_agent(agent_name)
            ]
            rules = sorted(rules + od_rules, key=lambda r: r.priority, reverse=True)
        if not rules:
            return ""
        parts = ["[扩展规则]"]
        for r in rules:
            parts.append(f"### {r.title}\n{r.content}")
        return "\n\n".join(parts)

    def activate(self, rule_id: str, enabled: bool = True) -> bool:
        """按需激活/停用规则（运行时，不写文件）。"""
        rule = self._rules.get(rule_id)
        if rule:
            rule.enabled = enabled
            return True
        return False

    def reload(self) -> int:
        """重新扫描并加载所有规则（热加载用）。"""
        self._rules.clear()
        return _scan_and_load(self)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (meta_dict, body)。"""
    meta: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                import yaml
                meta = yaml.safe_load(parts[1]) or {}
            except Exception:
                # yaml 不可用时用简单 key: value 解析
                for line in parts[1].strip().splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        v = v.strip()
                        # NEW-C8-07：回退解析下显式转 bool，否则 "false" 非空字符串
                        # 恒真 → enabled:false 失效（被停用的规则仍被注入）。
                        if v.lower() in ("true", "false"):
                            meta[k.strip()] = (v.lower() == "true")
                        else:
                            meta[k.strip()] = v
            body = parts[2].strip()
    return meta, body


def _iter_rules_dirs() -> list[tuple[str, Path]]:
    """
    NEW-C8-04：返回三级目录（内置/用户/项目）下所有 (extension_key, rules_dir)。
    复用 extension_loader.discover_extensions() 的 bundle 路径，使 user/project 级
    扩展的 rules/*.md 也能被加载（此前硬编码仅扫 backend/extensions/）。
    """
    try:
        from .extension_loader import discover_extensions
        bundles = discover_extensions().values()
        dirs = [(b.ext_id, b.path / "rules") for b in bundles]
        if dirs:
            return [(k, d) for k, d in dirs if d.is_dir()]
    except Exception as e:
        logger.warning(f"[RuleRegistry] discover_extensions 失败，回退仅扫描内置目录: {e}")
    # 回退：仅内置目录（跳过 `_` 前缀目录）
    ext_root = Path(__file__).parent
    return [
        (rd.parent.name, rd) for rd in ext_root.glob("*/rules")
        if rd.is_dir() and not rd.parent.name.startswith("_")
    ]


def _scan_and_load(registry: RuleRegistry) -> int:
    """扫描三级目录的 */rules/*.md，注册到 registry，返回数量。"""
    count = 0
    for extension_key, rules_dir in _iter_rules_dirs():
        for md_file in sorted(rules_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                meta, body = _parse_frontmatter(text)
                if not body.strip():
                    continue

                applicable = meta.get("applicable_agents", [])
                if isinstance(applicable, str):
                    applicable = [a.strip() for a in applicable.split(",") if a.strip()]

                rule = RuleEntry(
                    rule_id=f"{extension_key}/{md_file.stem}",
                    extension_key=extension_key,
                    title=meta.get("title", md_file.stem),
                    content=body,
                    trigger=meta.get("trigger", "always"),
                    applicable_agents=applicable,
                    priority=int(meta.get("priority", 50)),
                    enabled=meta.get("enabled", True),
                )
                registry.register(rule)
                count += 1
                logger.debug(f"[RuleRegistry] loaded rule: {rule.rule_id}")
            except Exception as e:
                logger.warning(f"[RuleRegistry] failed to load {md_file}: {e}")
    return count


# 全局单例
rule_registry = RuleRegistry()
_scan_and_load(rule_registry)

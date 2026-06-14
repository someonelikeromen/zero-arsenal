"""
SKILL.md 技能按需加载系统
参考 pi agent/harness/skills.ts + opencode skill/ 的设计
"""
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger(__name__)


@dataclass
class SkillMeta:
    name: str
    description: str
    trigger: str = "on_demand"          # always | on_demand | auto
    phases: list = field(default_factory=lambda: ["p3"])
    priority: int = 100
    condition: Optional[str] = None
    inject_as: str = "user"             # system | user
    path: Path = field(default_factory=Path)
    content: str = ""                   # 完整 markdown 内容（lazy load）
    applicable_worlds: list = field(default_factory=list)  # [] = 全局；非空 = 指定 plugin_key


class SkillRegistry:
    """扫描 skills/ 目录并注册所有 SKILL.md 文件。"""

    def __init__(self) -> None:
        self._skills: dict[str, SkillMeta] = {}
        self._skill_dirs: list[Path] = []

    def add_skill_dir(self, path: Path) -> None:
        if path.exists():
            self._skill_dirs.append(path)

    def discover(self) -> None:
        """扫描所有注册目录，发现并注册 SKILL.md 文件。"""
        for skill_dir in self._skill_dirs:
            for md_file in skill_dir.rglob("*.md"):
                self._register_file(md_file)

    def _register_file(self, path: Path) -> None:
        try:
            raw = path.read_text(encoding="utf-8")
            meta = self._parse_frontmatter(raw, path)
            if meta:
                self._skills[meta.name] = meta
        except Exception:
            pass

    def _parse_frontmatter(self, raw: str, path: Path) -> Optional[SkillMeta]:
        """解析 YAML frontmatter（--- ... ---）。"""
        match = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.DOTALL)
        if not match:
            # 无 frontmatter，用文件名作为 name
            name = path.stem
            return SkillMeta(name=name, description="", path=path)

        fm_str, body = match.group(1), match.group(2)
        if yaml:
            try:
                fm = yaml.safe_load(fm_str) or {}
            except Exception:
                fm = {}
        else:
            fm = self._simple_parse(fm_str)

        name = fm.get("name", path.stem)
        phases_raw = fm.get("phases", ["p3"])
        if isinstance(phases_raw, str):
            phases_raw = [phases_raw]

        worlds_raw = fm.get("applicable_worlds", [])
        if isinstance(worlds_raw, str):
            worlds_raw = [w.strip() for w in worlds_raw.split(",") if w.strip()]

        return SkillMeta(
            name=name,
            description=fm.get("description", ""),
            trigger=fm.get("trigger", "on_demand"),
            phases=phases_raw,
            priority=int(fm.get("priority", 100)),
            condition=fm.get("condition"),
            inject_as=fm.get("inject_as", "user"),
            path=path,
            applicable_worlds=worlds_raw,
        )

    def _simple_parse(self, fm_str: str) -> dict:
        """无 PyYAML 时的简单 key: value 解析。"""
        result = {}
        for line in fm_str.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                result[k.strip()] = v.strip().strip("\"'")
        return result

    def get_skill(self, name: str) -> Optional[SkillMeta]:
        """按名称获取技能元数据（不加载内容），不存在返回 None。"""
        return self._skills.get(name)

    def load_skill(self, name: str) -> Optional[SkillMeta]:
        """按需加载技能内容。"""
        skill = self._skills.get(name)
        if skill and not skill.content:
            try:
                raw = skill.path.read_text(encoding="utf-8")
                # 去掉 frontmatter 只保留正文
                match = re.match(r"^---\n.*?\n---\n(.*)$", raw, re.DOTALL)
                skill.content = match.group(1).strip() if match else raw.strip()
            except Exception:
                skill.content = ""
        return skill

    def format_for_injection(self, name: str) -> Optional[str]:
        """
        格式化为注入字符串（参考 pi 的 XML 包装 + superpowers 注入方式）。
        inject_as=user 时返回 XML 格式，inject_as=system 时返回原始内容。
        """
        skill = self.load_skill(name)
        if not skill or not skill.content:
            return None
        return f'<skill name="{skill.name}">\n{skill.content}\n</skill>'

    def list_skills(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "trigger": s.trigger,
                "phases": s.phases,
                "priority": s.priority,
                "file_path": str(s.path),
            }
            for s in sorted(self._skills.values(), key=lambda x: x.priority)
        ]

    def load_skill_content(self, name: str) -> str:
        """读取技能文件全文（去除 frontmatter），失败返回空字符串。"""
        skill = self.load_skill(name)
        if skill is None:
            return ""
        return skill.content or ""

    def get_always_skills(self, phase: str) -> list[SkillMeta]:
        """返回所有 trigger=always 且包含指定 phase 的技能。"""
        return [
            s for s in self._skills.values()
            if s.trigger == "always" and (phase in s.phases or "all" in s.phases)
        ]

    def evaluate_condition(self, skill: SkillMeta, state: dict) -> bool:
        """
        安全地评估 Skill frontmatter condition 字段（Python 表达式）。
        state: AgentState / TurnContext 的 dict 快照。
        
        示例 condition（来自 04-extension-system.md §2.3）：
            'state["mode"] == "combat" and "crossover" in state["plugin_key"]'
        """
        if skill.trigger != "auto" or not skill.condition:
            return False
        try:
            from ..utils.safe_condition import evaluate_condition_expr
            return evaluate_condition_expr(skill.condition, state)
        except Exception as e:
            logger.warning("[SkillRegistry] condition eval failed: %s — skipping skill %s", e, skill.name)
            return False

    def get_active_skills(self, phase: str, state: dict | None = None,
                          plugin_key: str = "") -> list[SkillMeta]:
        """
        返回当前相位激活的所有技能，按 priority 降序排列。

        激活规则：
        - trigger=always：直接激活（只要 phase 匹配）
        - trigger=auto：evaluate_condition(state) 为 True 时激活
        - trigger=on_demand：不自动激活（由玩家/DM 手动触发）

        applicable_worlds 过滤：若 skill 设定了适用世界且 plugin_key 不在其中，跳过。
        """
        result: list[SkillMeta] = []
        for s in self._skills.values():
            # Phase 过滤
            if s.phases and phase not in s.phases and "all" not in s.phases:
                continue
            # applicable_worlds 过滤（E8）：非空则必须包含当前 plugin_key
            if s.applicable_worlds and plugin_key not in s.applicable_worlds:
                continue
            # trigger 过滤
            if s.trigger == "always":
                result.append(s)
            elif s.trigger == "auto" and state is not None:
                if self.evaluate_condition(s, state):
                    result.append(s)
            # on_demand 跳过

        # 按 priority 降序（数字大的先注入）
        result.sort(key=lambda x: x.priority, reverse=True)
        return result

    def build_injection_block(self, phase: str, state: dict | None = None,
                              plugin_key: str = "") -> str:
        """
        构建当前相位所有激活技能的注入文本块（按 priority 顺序）。
        返回空字符串表示无激活技能。
        """
        active = self.get_active_skills(phase, state, plugin_key)
        if not active:
            return ""
        parts = []
        for skill in active:
            formatted = self.format_for_injection(skill.name)
            if formatted:
                parts.append(formatted)
        return "\n\n".join(parts)


# 全局注册表
skill_registry = SkillRegistry()

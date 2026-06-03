"""
用途: 扫描 backend/data/writing-styles/ 目录，将所有 .md 文件注册为写作风格技能。
用法: python writing_styles.py（或在 main.py lifespan 中调用 init_writing_style_skills()）
环境变量: 无
MCP集成: 不直接暴露为 MCP tool；通过 skill_registry 向 Narrator 注入风格内容。
Skill集成: 在 main.py lifespan 中调用 init_writing_style_skills()
"""
from __future__ import annotations
from pathlib import Path
from ..tools.skill_loader import SkillMeta, skill_registry

# writing-styles 目录相对于本文件的路径
_WRITING_STYLES_DIR = Path(__file__).resolve().parent.parent / "data" / "writing-styles"


def _get_first_line(md_path: Path) -> str:
    """读取 .md 文件的第一行作为 description。"""
    try:
        with md_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip().lstrip("#").strip()
                if line:
                    return line[:120]
    except Exception:
        pass
    return ""


def init_writing_style_skills(styles_dir: Path = _WRITING_STYLES_DIR) -> int:
    """
    扫描 writing-styles 目录，将每个 .md 文件注册为 SkillMeta。
    返回注册数量。
    """
    if not styles_dir.exists():
        return 0

    count = 0
    for md_file in sorted(styles_dir.glob("*.md")):
        # README.md 跳过
        if md_file.stem.lower() == "readme":
            continue

        name = md_file.stem
        description = _get_first_line(md_file)

        skill = SkillMeta(
            name=name,
            description=description,
            trigger="on_demand",
            phases=["p3"],          # 写作阶段可用
            priority=200,
            inject_as="user",
            path=md_file,
        )

        # 直接注入 _skills 字典（SkillRegistry 公开接口）
        skill_registry._skills[name] = skill
        count += 1

    return count

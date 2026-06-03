"""
扩展骨架模板 — 复制本目录为 backend/extensions/<your_plugin>/ 后按需修改。

5 个文件：
  __init__.py  导出插件实例
  plugin.py    WorldPlugin 子类（世界设定 / 生命周期钩子 / 权限覆盖）
  tools.py     扩展工具集（TOOLS 列表自动注册到 ToolRegistry）
  hooks.py     生命周期钩子（on_turn_end / on_chapter_end 等）
  manifest.json 元数据（id / display_name / entry_points）

去掉前缀下划线后，扩展加载器会自动发现本目录。
"""
from .plugin import template_plugin

__all__ = ["template_plugin"]

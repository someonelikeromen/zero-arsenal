"""
web_scraper 扩展包级导出
提供 TOOLS 列表供 extension_loader 自动注册。
"""
from .tools import TOOLS

__all__ = ["TOOLS"]

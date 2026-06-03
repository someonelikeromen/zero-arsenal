# memory package — 适配层
# 原始模块使用绝对导入 from memory.xxx，
# 通过适配器暴露简化接口给 agents 使用
from .adapter import MemoryAdapter, memory_adapter

__all__ = ["MemoryAdapter", "memory_adapter"]

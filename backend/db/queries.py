"""
用途: db 层查询入口，供 memory/ 等跨模块代码以 from db.queries import get_db 方式导入。
      本文件是 db/__init__.py 中 get_db 的别名模块，解决 memory/ 子系统对 db.queries 的依赖。
用法: from db.queries import get_db
"""
from .connection import get_db  # noqa: F401  re-export

__all__ = ["get_db"]

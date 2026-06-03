"""
数据库连接管理 — aiosqlite WAL 模式
"""
import hashlib
import time
import aiosqlite
from pathlib import Path
from contextlib import asynccontextmanager
from .schema import CREATE_TABLES_SQL, MIGRATION_PATCHES_SQL

_DB_PATH: Path = Path("data/zero_arsenal.db")


def set_db_path(path: Path) -> None:
    global _DB_PATH
    _DB_PATH = path
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def get_db():
    """获取数据库连接（异步上下文管理器）。"""
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA busy_timeout=5000")
        yield db


async def init_db() -> None:
    """初始化数据库，执行建表 SQL + 在线列迁移。

    使用逐语句执行（而非 executescript 原子脚本），允许 CREATE INDEX 等依赖迁移列的
    语句在旧数据库上静默失败，待 _migrate_columns 补齐列后再重试。
    """
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(_DB_PATH) as db:
        # Phase 1: 逐语句执行建表+索引（旧DB上缺列的索引允许失败）
        deferred_indices: list[str] = []
        for stmt in _split_sql(CREATE_TABLES_SQL):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                await db.execute(stmt)
            except Exception as e:
                err = str(e).lower()
                if "no such column" in err and stmt.upper().startswith("CREATE INDEX"):
                    deferred_indices.append(stmt)  # 延后到列迁移后重试
                elif "already exists" in err or "duplicate" in err:
                    pass  # 索引/表已存在，忽略
                else:
                    pass  # 其他非致命错误静默忽略（PRAGMA 语句等）
        await db.commit()

        # Phase 2: 列迁移（补齐旧数据库中缺失的列）
        await _migrate_columns(db)
        await db.commit()

        # Phase 3: 重试之前因缺列失败的索引
        for stmt in deferred_indices:
            try:
                await db.execute(stmt)
            except Exception:
                pass  # 如果仍失败则静默忽略
        await db.commit()


def _split_sql(script: str) -> list[str]:
    """将 SQL 脚本按分号切分为独立语句（跳过注释行）。"""
    stmts = []
    buf = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmts.append("\n".join(buf))
            buf = []
    if buf:
        stmts.append("\n".join(buf))
    return stmts


async def _migrate_columns(db: aiosqlite.Connection) -> None:
    """
    在线列迁移：对旧数据库安全追加缺失列。
    SQLite 不支持 ALTER TABLE ADD COLUMN IF NOT EXISTS，用 try/except 处理。
    """
    migrations = [
        ("sessions",  "status",   "TEXT NOT NULL DEFAULT 'active'"),
        ("messages",  "status",   "TEXT NOT NULL DEFAULT 'active'"),
        ("messages",  "updated_at", "REAL"),
        ("chapters",  "status",   "TEXT NOT NULL DEFAULT 'active'"),
        ("world_archives", "title",        "TEXT NOT NULL DEFAULT ''"),
        ("world_archives", "content",      "TEXT NOT NULL DEFAULT '{}'"),
        ("world_archives", "archive_type", "TEXT NOT NULL DEFAULT 'lore'"),
        ("world_archives", "world_key",    "TEXT NOT NULL DEFAULT ''"),
        ("world_archives", "created_at",   "REAL"),
        # Lorebook 触发关键词（逗号分隔），命中后在叙事侧标注 🔑
        ("world_archives", "trigger_keywords", "TEXT NOT NULL DEFAULT ''"),
        ("world_archive_entries", "trigger_keywords", "TEXT NOT NULL DEFAULT ''"),
        # 新增表的保险列迁移（若旧 DB 已建表但缺列）
        ("memory_entries", "consolidated_at", "REAL"),
        ("character_cards", "schema_version", "TEXT NOT NULL DEFAULT '4.0'"),
    ]
    for table, col, col_def in migrations:
        try:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
        except Exception:
            pass  # 列已存在，忽略

    # schema.py 中定义的批量迁移补丁（带版本记录）
    # 读取已执行的版本号
    try:
        rows = await db.execute("SELECT version FROM schema_version")
        applied_versions = {r[0] for r in await rows.fetchall()}
    except Exception:
        applied_versions = set()

    for idx, patch_sql in enumerate(MIGRATION_PATCHES_SQL, start=1):
        if idx in applied_versions:
            continue  # 已执行，跳过
        try:
            await db.execute(patch_sql)
            checksum = hashlib.md5(patch_sql.encode()).hexdigest()
            # 取补丁的简短描述（SQL 前50字符）
            desc = patch_sql.strip()[:50].replace("\n", " ")
            await db.execute(
                "INSERT OR REPLACE INTO schema_version (version, description, applied_at, checksum) "
                "VALUES (?, ?, ?, ?)",
                (idx, desc, time.time(), checksum),
            )
        except Exception:
            pass  # 列已存在或其他可忽略错误

"""
数据库连接管理 — aiosqlite WAL 模式
"""
import hashlib
import logging
import time
import aiosqlite
from pathlib import Path
from contextlib import asynccontextmanager
from .schema import CREATE_TABLES_SQL, MIGRATION_PATCHES_SQL

logger = logging.getLogger(__name__)

# 可安全忽略的“非致命”错误关键词（幂等建表/重复列/PRAGMA 等）
_BENIGN_ERR_KEYWORDS = ("already exists", "duplicate column", "duplicate")

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
        # NEW-C7-08：对真正的致命错误（建表语法错误/约束冲突等）fail-loud（记录并抛出），
        # 仅容忍 ① "no such column" 的 CREATE INDEX（延后重试）② "already exists"/"duplicate"（幂等）。
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
                elif any(k in err for k in _BENIGN_ERR_KEYWORDS):
                    pass  # 索引/表/列已存在，幂等忽略
                elif stmt.upper().startswith("PRAGMA"):
                    logger.debug("init_db: PRAGMA 语句忽略错误: %s", e)
                else:
                    # 致命错误：建表/索引语法错误、约束冲突等 → fail-loud
                    logger.error(
                        "init_db: 建表语句执行失败（致命）: %s\nSQL: %s",
                        e, stmt[:200],
                    )
                    raise
        await db.commit()

        # Phase 2: 列迁移（补齐旧数据库中缺失的列）
        await _migrate_columns(db)
        await db.commit()

        # Phase 3: 重试之前因缺列失败的索引
        for stmt in deferred_indices:
            try:
                await db.execute(stmt)
            except Exception as e:
                err = str(e).lower()
                if any(k in err for k in _BENIGN_ERR_KEYWORDS) or "no such column" in err:
                    logger.warning("init_db: 延后索引仍失败（已忽略）: %s | SQL=%s", e, stmt[:120])
                else:
                    logger.error("init_db: 延后索引执行失败（致命）: %s | SQL=%s", e, stmt[:120])
                    raise
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
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in _BENIGN_ERR_KEYWORDS):
                pass  # 列已存在，幂等忽略
            else:
                # 非预期错误（如表不存在）记录，但不中止启动（迁移尽力而为）
                logger.warning("init_db: 列迁移失败 %s.%s: %s", table, col, e)

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
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in _BENIGN_ERR_KEYWORDS):
                pass  # 列/表/索引已存在，幂等忽略
            else:
                logger.warning("init_db: 迁移补丁 #%d 失败（已忽略）: %s | SQL=%s",
                               idx, e, patch_sql[:80])

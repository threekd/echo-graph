"""统一的 SQLite 连接层与 schema 迁移(策展 + 贡献 + 审计共用)。"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

# 统一在此加载 .env:所有数据层/管理/公开接口都经由本模块导入,
# 保证本地 `uvicorn` 运行时 ADMIN_BOOTSTRAP_EMAIL、PUBLIC_REVIEWED_ONLY 等配置生效
load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "echo-graph.db"

# 进程内写互斥:admin 写事务与快照恢复互斥(恢复期间禁止写入,避免覆盖竞态)
_write_lock = threading.Lock()


def normalize_ts(value) -> str | None:
    """时间戳归一:无时区按 UTC 处理,统一输出秒级 ISO-8601 +00:00;无法解析则原样保留。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        parsed = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    else:
        parsed = parsed.astimezone(dt.UTC)
    return parsed.isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    """事务上下文:迁移 schema,正常退出提交,异常/结束关闭连接。"""
    conn = _connect()
    try:
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def audit(
    conn: sqlite3.Connection,
    action: str,
    kind: str,
    row_id: str | None,
    detail: str = "",
    before: dict | None = None,
    after: dict | None = None,
    actor: str = "admin",
) -> None:
    """写一条审计记录(与业务写入同一事务)。

    detail 为人读摘要(含对象名称与变更字段);before/after 为改动前后的行 JSON,
    供管理端审计页展开对比定位。
    """
    conn.execute(
        "INSERT INTO audit_log (ts, actor, action, kind, row_id, detail, before, after)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            actor,
            action,
            kind,
            row_id,
            detail,
            json.dumps(before, ensure_ascii=False) if before is not None else None,
            json.dumps(after, ensure_ascii=False) if after is not None else None,
        ),
    )


# ---- schema 迁移 ----

# v1:与迁移前一致的建表(旧库 CREATE IF NOT EXISTS 幂等;新库照此创建)
MIGRATION_V1 = [
    """
    CREATE TABLE IF NOT EXISTS authors (
        id TEXT PRIMARY KEY,
        originalName TEXT NOT NULL,
        Name_CN TEXT NOT NULL,
        Name_EN TEXT,
        nationality TEXT,
        birthYear INTEGER,
        deathYear INTEGER,
        reviewStatus TEXT NOT NULL DEFAULT 'draft' CHECK (reviewStatus IN ('draft','reviewed','rejected')),
        createdAt TEXT,
        updatedAt TEXT,
        deletedAt TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS works (
        id TEXT PRIMARY KEY,
        language TEXT NOT NULL,
        originalTitle TEXT NOT NULL,
        Title_CN TEXT NOT NULL,
        Title_EN TEXT,
        Title_Other TEXT,
        publicationYear INTEGER,
        creationYear INTEGER,
        genre TEXT CHECK (genre IN ('Fiction','Non-fiction','Poetry','Drama') OR genre IS NULL),
        reviewStatus TEXT NOT NULL DEFAULT 'draft' CHECK (reviewStatus IN ('draft','reviewed','rejected')),
        createdAt TEXT,
        updatedAt TEXT,
        deletedAt TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS work_authors (
        work_id TEXT NOT NULL REFERENCES works(id),
        author_id TEXT NOT NULL REFERENCES authors(id),
        PRIMARY KEY (work_id, author_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS edges (
        id TEXT PRIMARY KEY,
        source_work_id TEXT NOT NULL REFERENCES works(id),
        target_work_id TEXT NOT NULL REFERENCES works(id),
        evidence TEXT NOT NULL,
        evidenceSource TEXT,
        note TEXT,
        reviewStatus TEXT NOT NULL DEFAULT 'draft' CHECK (reviewStatus IN ('draft','reviewed','rejected')),
        createdAt TEXT,
        updatedAt TEXT,
        deletedAt TEXT,
        UNIQUE (source_work_id, target_work_id),
        CHECK (source_work_id <> target_work_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contributions (
        id TEXT PRIMARY KEY,
        source_work TEXT NOT NULL,
        target_work TEXT NOT NULL,
        source_author TEXT NOT NULL,
        target_author TEXT NOT NULL,
        evidence TEXT NOT NULL,
        evidence_source TEXT NOT NULL,
        note TEXT,
        contact TEXT,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
        created_at TEXT NOT NULL,
        reviewed_at TEXT
    )
    """,
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
]


def _migration_v2(conn: sqlite3.Connection) -> None:
    """索引 + 审计表 + 时间戳归一。"""
    conn.execute("CREATE TABLE IF NOT EXISTS audit_log ("
                 " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                 " ts TEXT NOT NULL, actor TEXT NOT NULL DEFAULT 'admin',"
                 " action TEXT NOT NULL, kind TEXT NOT NULL, row_id TEXT, detail TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_work_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_work_authors_author ON work_authors(author_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contributions_status_created ON contributions(status, created_at)")

    # 兼容旧库:contributions 若缺作者列则 ALTER 补齐
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(contributions)")}
    if "source_author" not in cols:
        conn.execute("ALTER TABLE contributions ADD COLUMN source_author TEXT NOT NULL DEFAULT ''")
    if "target_author" not in cols:
        conn.execute("ALTER TABLE contributions ADD COLUMN target_author TEXT NOT NULL DEFAULT ''")

    # 时间戳归一(无时区按 UTC)
    for table, cols in (
        ("authors", ("createdAt", "updatedAt", "deletedAt")),
        ("works", ("createdAt", "updatedAt", "deletedAt")),
        ("edges", ("createdAt", "updatedAt", "deletedAt")),
        ("contributions", ("created_at", "reviewed_at")),
    ):
        col_sql = ", ".join(f'"{c}"' for c in cols)
        rows = conn.execute(f"SELECT id, {col_sql} FROM {table}").fetchall()
        for r in rows:
            updates = {c: normalize_ts(r[c]) for c in cols}
            if all(updates[c] == r[c] for c in cols):
                continue
            conn.execute(
                f"UPDATE {table} SET " + ", ".join(f'"{c}" = ?' for c in cols) + " WHERE id = ?",
                [updates[c] for c in cols] + [r["id"]],
            )


def _migration_v3(conn: sqlite3.Connection) -> None:
    """重建 works/edges 补 DB 级 CHECK(语言长度、证据长度),并校验外键。"""
    conn.execute("""
        CREATE TABLE works_v3 (
            id TEXT PRIMARY KEY,
            language TEXT NOT NULL CHECK (length(language) BETWEEN 2 AND 3),
            originalTitle TEXT NOT NULL,
            Title_CN TEXT NOT NULL,
            Title_EN TEXT,
            Title_Other TEXT,
            publicationYear INTEGER,
            creationYear INTEGER,
            genre TEXT CHECK (genre IN ('Fiction','Non-fiction','Poetry','Drama') OR genre IS NULL),
            reviewStatus TEXT NOT NULL DEFAULT 'draft' CHECK (reviewStatus IN ('draft','reviewed','rejected')),
            createdAt TEXT,
            updatedAt TEXT,
            deletedAt TEXT
        )
    """)
    conn.execute(
        "INSERT INTO works_v3 (id, language, originalTitle, Title_CN, Title_EN, Title_Other,"
        " publicationYear, creationYear, genre, reviewStatus, createdAt, updatedAt, deletedAt)"
        " SELECT id, language, originalTitle, Title_CN, Title_EN, Title_Other,"
        " publicationYear, creationYear, genre, reviewStatus, createdAt, updatedAt, deletedAt FROM works"
    )
    conn.execute("DROP TABLE works")
    conn.execute("ALTER TABLE works_v3 RENAME TO works")
    conn.execute("""
        CREATE TABLE edges_v3 (
            id TEXT PRIMARY KEY,
            source_work_id TEXT NOT NULL REFERENCES works(id),
            target_work_id TEXT NOT NULL REFERENCES works(id),
            evidence TEXT NOT NULL CHECK (length(evidence) <= 2000),
            evidenceSource TEXT,
            note TEXT,
            reviewStatus TEXT NOT NULL DEFAULT 'draft' CHECK (reviewStatus IN ('draft','reviewed','rejected')),
            createdAt TEXT,
            updatedAt TEXT,
            deletedAt TEXT,
            UNIQUE (source_work_id, target_work_id),
            CHECK (source_work_id <> target_work_id)
        )
    """)
    conn.execute(
        "INSERT INTO edges_v3 (id, source_work_id, target_work_id, evidence, evidenceSource, note,"
        " reviewStatus, createdAt, updatedAt, deletedAt)"
        " SELECT id, source_work_id, target_work_id, evidence, evidenceSource, note,"
        " reviewStatus, createdAt, updatedAt, deletedAt FROM edges"
    )
    conn.execute("DROP TABLE edges")
    conn.execute("ALTER TABLE edges_v3 RENAME TO edges")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_work_id)")


def _migration_v4(conn: sqlite3.Connection) -> None:
    """审计表补充 before/after JSON 列(改动前后行,供审计页对比)。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(audit_log)")}
    if "before" not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN before TEXT")
    if "after" not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN after TEXT")


def _migration_v5(conn: sqlite3.Connection) -> None:
    """补充 edges(source_work_id) 索引(路径/扩散按源查询)。"""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_work_id)")


def _migration_v6(conn: sqlite3.Connection) -> None:
    """审计表按时间查询/裁剪加索引(配合 scripts/prune_audit.py)。"""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts)")


def _migration_v7(conn: sqlite3.Connection) -> None:
    """authors / works 增加可选备注列 note。"""
    for table in ("authors", "works"):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "note" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN note TEXT")


def _migration_v8(conn: sqlite3.Connection) -> None:
    """多用户账号体系:users(邮箱+Argon2 密码哈希)+ sessions(httpOnly Cookie 会话)。

    sessions 只存 token 的 SHA-256 哈希,泄露数据库也无法伪造会话;
    users.status 为 active / disabled(禁用即不可登录)。
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
            createdAt TEXT,
            updatedAt TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_seen_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)")


def _migration_v9(conn: sqlite3.Connection) -> None:
    """用户空间数据隔离:业务表增加 owner_id,贡献表增加归属 user_id。

    - owner_id 为空 = 历史/未认领数据(认领到引导管理员后不再有空值)。
    - 公共星云 = 引导管理员(ADMIN_BOOTSTRAP_EMAIL)认领的空间;普通用户空间私有。
    - 数据隔离在查询层强制:所有行级读写按 owner 上下文过滤。
    """
    for table in ("authors", "works", "edges"):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "owner_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN owner_id TEXT REFERENCES users(id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_owner ON {table}(owner_id)")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(contributions)")}
    if "user_id" not in cols:
        conn.execute("ALTER TABLE contributions ADD COLUMN user_id TEXT REFERENCES users(id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contributions_user ON contributions(user_id)")


def _migration_v10(conn: sqlite3.Connection) -> None:
    """星云可见性:users.space_visibility(默认 public,星际跃迁可访问)。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "space_visibility" not in cols:
        conn.execute(
            "ALTER TABLE users ADD COLUMN space_visibility TEXT NOT NULL DEFAULT 'public'"
            " CHECK (space_visibility IN ('private','public'))"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_space_visibility ON users(space_visibility)"
    )


def _migration_v11(conn: sqlite3.Connection) -> None:
    """用户空间的作者/作品可见性 + 审核语义调整。

    - authors / works 增加 visibility(public/private,默认 public):
      决定该节点是否显示在他人的视图(星际跃迁)中。
    - 普通用户空间的数据视为「用户输入即确认」:作者/作品/涟漪 reviewStatus
      统一为 reviewed(管理端不再展示该字段);公共星云(admin)保持策展语义不变。
    """
    for table in ("authors", "works"):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "visibility" not in cols:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public'"
                " CHECK (visibility IN ('public','private'))"
            )
    # 既有用户空间数据按新语义置为已审核(公共星云/管理员行不动)
    for table in ("authors", "works", "edges"):
        conn.execute(
            f"UPDATE {table} SET reviewStatus = 'reviewed'"
            " WHERE owner_id IS NOT NULL"
            " AND owner_id NOT IN (SELECT id FROM users WHERE role = 'admin')"
        )


def _migration_v12(conn: sqlite3.Connection) -> None:
    """作品增加个人评价字段:recommendation(推荐/不推荐)+ review(长文本)。

    属于用户空间的个人语义字段,不进 CSV(与 visibility 同策略);
    admin 公共星云行保持 NULL(策展视图不展示)。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(works)")}
    if "recommendation" not in cols:
        conn.execute(
            "ALTER TABLE works ADD COLUMN recommendation TEXT"
            " CHECK (recommendation IN ('recommend','not_recommend'))"
        )
    if "review" not in cols:
        conn.execute("ALTER TABLE works ADD COLUMN review TEXT")


MIGRATIONS: list[tuple[int, list[str] | Callable[[sqlite3.Connection], None]]] = [
    (1, MIGRATION_V1),
    (2, _migration_v2),
    (3, _migration_v3),
    (4, _migration_v4),
    (5, _migration_v5),
    (6, _migration_v6),
    (7, _migration_v7),
    (8, _migration_v8),
    (9, _migration_v9),
    (10, _migration_v10),
    (11, _migration_v11),
    (12, _migration_v12),
]


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    try:
        return int(row["value"]) if row else 0
    except (TypeError, ValueError):
        return 0


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    current = _current_version(conn)
    if current >= max(v for v, _ in MIGRATIONS):
        return
    # 迁移使用显式事务;完成后恢复默认隔离级别供业务使用
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        for version, payload in MIGRATIONS:
            if version <= current:
                continue
            conn.execute("BEGIN")
            try:
                if isinstance(payload, list):
                    for stmt in payload:
                        conn.execute(stmt)
                else:
                    payload(conn)
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(version),),
            )
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.isolation_level = ""
    bad = conn.execute("PRAGMA foreign_key_check").fetchall()
    if bad:
        raise RuntimeError(f"迁移后外键校验失败:{bad}")

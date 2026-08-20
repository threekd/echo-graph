"""策展数据的 SQLite 存储层(SQLite 为唯一权威,CSV 为确定性导出产物)。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "echo-graph.db"

SCHEMA = """
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
);
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
);
CREATE TABLE IF NOT EXISTS work_authors (
    work_id TEXT NOT NULL REFERENCES works(id),
    author_id TEXT NOT NULL REFERENCES authors(id),
    PRIMARY KEY (work_id, author_id)
);
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
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

AUTHOR_COLS = [
    "id", "originalName", "Name_CN", "Name_EN", "nationality",
    "birthYear", "deathYear", "reviewStatus", "createdAt", "updatedAt", "deletedAt",
]
WORK_COLS = [
    "id", "language", "originalTitle", "Title_CN", "Title_EN",
    "Title_Other", "publicationYear", "creationYear", "genre", "reviewStatus",
    "createdAt", "updatedAt", "deletedAt",
]
EDGE_COLS = [
    "id", "source_work_id", "target_work_id", "evidence", "evidenceSource",
    "note", "reviewStatus", "createdAt", "updatedAt", "deletedAt",
]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    """事务上下文:确保建表,正常退出提交,异常/结束关闭连接。"""
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _db():
        pass


def replace_all(author_models, work_models, echo_models, work_authors: dict[str, list[str]]) -> None:
    """单事务整库重建(迁移用)。入参为 parse_rows 产出的模型与作者关联。"""
    def insert(table: str, cols: list[str], models: list[Any]) -> None:
        placeholders = ",".join("?" for _ in cols)
        rows = [{k: m.model_dump().get(k) for k in cols} for m in models]
        conn.executemany(
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
            [tuple(r[c] for c in cols) for r in rows],
        )

    with _db() as conn:
        conn.execute("DELETE FROM work_authors")
        conn.execute("DELETE FROM edges")
        conn.execute("DELETE FROM works")
        conn.execute("DELETE FROM authors")
        insert("authors", AUTHOR_COLS, author_models)
        insert("works", WORK_COLS, work_models)
        insert("edges", EDGE_COLS, echo_models)
        conn.executemany(
            "INSERT INTO work_authors (work_id, author_id) VALUES (?, ?)",
            [(wid, aid) for wid, aids in work_authors.items() for aid in aids],
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '1')"
        )


def rewrite_all(author_rows, work_rows, edge_rows) -> None:
    """单事务整库重写(admin 保存路径):入参为与 load_rows 同形状的行 dict。"""
    def normalized(rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            row = dict(r)
            row["reviewStatus"] = row.get("reviewStatus") or "draft"
            out.append(row)
        return out

    author_rows = normalized(author_rows)
    work_rows = normalized(work_rows)
    edge_rows = normalized(edge_rows)

    with _db() as conn:
        conn.execute("DELETE FROM work_authors")
        conn.execute("DELETE FROM edges")
        conn.execute("DELETE FROM works")
        conn.execute("DELETE FROM authors")

        placeholders = ",".join("?" for _ in AUTHOR_COLS)
        conn.executemany(
            f"INSERT INTO authors ({','.join(AUTHOR_COLS)}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in AUTHOR_COLS) for r in author_rows],
        )
        placeholders = ",".join("?" for _ in WORK_COLS)
        conn.executemany(
            f"INSERT INTO works ({','.join(WORK_COLS)}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in WORK_COLS) for r in work_rows],
        )
        placeholders = ",".join("?" for _ in EDGE_COLS)
        conn.executemany(
            f"INSERT INTO edges ({','.join(EDGE_COLS)}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in EDGE_COLS) for r in edge_rows],
        )
        work_authors = [
            (r["id"], aid)
            for r in work_rows
            for aid in (str(r.get("author_id") or "").split(","))
            if aid.strip()
        ]
        conn.executemany(
            "INSERT INTO work_authors (work_id, author_id) VALUES (?, ?)",
            [(wid, aid.strip()) for wid, aid in work_authors],
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '1')"
        )


def list_all() -> dict:
    """返回与 CSV load_rows 同形状的行(works 行重组 author_id 逗号串)。"""
    with _db() as conn:
        authors = [dict(r) for r in conn.execute("SELECT * FROM authors ORDER BY id")]
        works = [dict(r) for r in conn.execute("SELECT * FROM works ORDER BY id")]
        edges = [dict(r) for r in conn.execute("SELECT * FROM edges ORDER BY id")]
        wa_rows = conn.execute(
            "SELECT work_id, author_id FROM work_authors ORDER BY work_id, author_id"
        ).fetchall()
    work_authors: dict[str, list[str]] = {}
    for r in wa_rows:
        work_authors.setdefault(r["work_id"], []).append(r["author_id"])
    for w in works:
        w["author_id"] = ",".join(work_authors.get(w["id"], []))
    return {"authors": authors, "works": works, "edges": edges, "work_authors": work_authors}


# ---- 同步比对规范化(与 admin 的 CSV 侧共用,Phase 2 后 CSV 侧移除) ----


def sync_norm(value):
    """同步比对用的字段归一化:去空白、数值字符串转 int、空串统一为 None。"""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return s
    return value


def canonical_payload(author_rows, work_rows, edge_rows) -> dict:
    """规范化活跃数据载荷(忽略时间戳),用于 SQLite/CSV 与 Neo4j 比对。"""
    active_a = [r for r in author_rows if not r.get("deletedAt")]
    active_w = [r for r in work_rows if not r.get("deletedAt")]
    active_e = [r for r in edge_rows if not r.get("deletedAt")]

    authors = []
    for r in active_a:
        authors.append({
            "id": sync_norm(r.get("id")),
            "originalName": sync_norm(r.get("originalName")),
            "Name_CN": sync_norm(r.get("Name_CN")),
            "Name_EN": sync_norm(r.get("Name_EN")),
            "nationality": sync_norm((r.get("nationality") or "").upper()),
            "birthYear": sync_norm(r.get("birthYear")),
            "deathYear": sync_norm(r.get("deathYear")),
            "reviewStatus": sync_norm(r.get("reviewStatus") or "draft"),
        })
    works = []
    for r in active_w:
        works.append({
            "id": sync_norm(r.get("id")),
            "language": sync_norm((r.get("language") or "").lower()),
            "originalTitle": sync_norm(r.get("originalTitle")),
            "Title_CN": sync_norm(r.get("Title_CN")),
            "Title_EN": sync_norm(r.get("Title_EN")),
            "Title_Other": sync_norm(r.get("Title_Other")),
            "publicationYear": sync_norm(r.get("publicationYear")),
            "creationYear": sync_norm(r.get("creationYear")),
            "genre": sync_norm(r.get("genre")),
            "reviewStatus": sync_norm(r.get("reviewStatus") or "draft"),
            "author_ids": sorted(
                sync_norm(x) for x in (r.get("author_id") or "").split(",") if x.strip()
            ),
        })
    echoes = []
    for r in active_e:
        echoes.append({
            "id": sync_norm(r.get("id")),
            "source": sync_norm(r.get("source_work_id")),
            "target": sync_norm(r.get("target_work_id")),
            "evidence": sync_norm(r.get("evidence")),
            "evidenceSource": sync_norm(r.get("evidenceSource")),
            "note": sync_norm(r.get("note")),
            "reviewStatus": sync_norm(r.get("reviewStatus") or "draft"),
        })
    return {
        "authors": sorted(authors, key=lambda x: x["id"]),
        "works": sorted(works, key=lambda x: x["id"]),
        "echoes": sorted(echoes, key=lambda x: x["id"]),
    }


def sync_payload() -> dict:
    """SQLite 侧的规范化载荷(供与 Neo4j 比对)。"""
    data = list_all()
    return canonical_payload(data["authors"], data["works"], data["edges"])


def migrate_from_csv(db_path: Path | str, check: bool = True) -> dict:
    """校验 data/real/*.csv 并整库重建 SQLite;校验失败抛 ValueError。"""
    from app.data_models import parse_rows
    from app.data_store import load_csv_rows

    global DB_PATH
    DB_PATH = Path(db_path)
    authors, works, edges = load_csv_rows()
    author_models, work_models, echo_models, work_authors = parse_rows(authors, works, edges)
    replace_all(author_models, work_models, echo_models, work_authors)
    if check:
        db_payload = sync_payload()
        csv_payload = canonical_payload(authors, works, edges)
        if db_payload != csv_payload:
            raise RuntimeError("迁移后一致性校验失败:SQLite 与 CSV 规范化载荷不一致")
    return {
        "authors": len(author_models),
        "works": len(work_models),
        "echoes": len(echo_models),
        "authored_links": sum(len(v) for v in work_authors.values()),
    }

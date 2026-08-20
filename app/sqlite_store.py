"""策展数据的 SQLite 存储层(SQLite 为唯一权威,CSV 为确定性导出产物)。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app import db_sqlite

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
KIND_COLS = {"authors": AUTHOR_COLS, "works": WORK_COLS, "edges": EDGE_COLS}
KIND_TABLE = {"authors": "authors", "works": "works", "edges": "edges"}


def init_db() -> None:
    with db_sqlite._db():
        pass


def _norm_row(row: dict) -> dict:
    """reviewStatus 空值归一为 draft(NOT NULL 约束)。"""
    out = dict(row)
    out["reviewStatus"] = out.get("reviewStatus") or "draft"
    return out


# ---- 行级 CRUD(admin 写路径;由调用方在 db_sqlite._db 事务内使用) ----


def get_row(conn, kind: str, row_id: str) -> dict | None:
    row = conn.execute(f"SELECT * FROM {KIND_TABLE[kind]} WHERE id = ?", (row_id,)).fetchone()
    return dict(row) if row else None


def row_exists(conn, kind: str, row_id: str) -> bool:
    return conn.execute(
        f"SELECT 1 FROM {KIND_TABLE[kind]} WHERE id = ?", (row_id,)
    ).fetchone() is not None


def insert_row(conn, kind: str, row: dict) -> None:
    row = _norm_row(row)
    cols = KIND_COLS[kind]
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO {KIND_TABLE[kind]} ({','.join(cols)}) VALUES ({placeholders})",
        [row.get(c) for c in cols],
    )


def update_row(conn, kind: str, row_id: str, row: dict, expected_updated_at: str | None = None) -> int:
    """更新一行。返回 1=成功, 0=行不存在, -1=乐观锁冲突(updatedAt 已变化)。"""
    row = _norm_row(row)
    cols = [c for c in KIND_COLS[kind] if c != "id"]
    if expected_updated_at is not None:
        cur = conn.execute(
            f"UPDATE {KIND_TABLE[kind]} SET " + ", ".join(f"{c} = ?" for c in cols)
            + " WHERE id = ? AND updatedAt = ?",
            [row.get(c) for c in cols] + [row_id, expected_updated_at],
        )
        if cur.rowcount == 0:
            return -1 if row_exists(conn, kind, row_id) else 0
        return 1
    cur = conn.execute(
        f"UPDATE {KIND_TABLE[kind]} SET " + ", ".join(f"{c} = ?" for c in cols) + " WHERE id = ?",
        [row.get(c) for c in cols] + [row_id],
    )
    return 1 if cur.rowcount > 0 else 0


def set_work_authors(conn, work_id: str, author_ids: list[str]) -> None:
    conn.execute("DELETE FROM work_authors WHERE work_id = ?", (work_id,))
    conn.executemany(
        "INSERT INTO work_authors (work_id, author_id) VALUES (?, ?)",
        [(work_id, aid) for aid in author_ids],
    )


def mark_deleted(conn, kind: str, ids: list[str], deleted_at: str) -> int:
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(
        f"UPDATE {KIND_TABLE[kind]} SET deletedAt = ?, updatedAt = ? WHERE id IN ({placeholders})",
        [deleted_at, deleted_at] + list(ids),
    )
    return cur.rowcount


def restore_by_ts(conn, kind: str, ids: list[str], ts: str, updated_at: str) -> int:
    """按相同 deletedAt 时间戳恢复一批行(级联恢复)。"""
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(
        f"UPDATE {KIND_TABLE[kind]} SET deletedAt = NULL, updatedAt = ?"
        f" WHERE deletedAt = ? AND id IN ({placeholders})",
        [updated_at, ts] + list(ids),
    )
    return cur.rowcount


# ---- 级联删除/恢复(纯 SQL,不读取全量数据) ----


def cascade_work_edge_ids(conn, work_id: str) -> list[str]:
    """作品相关的活跃涟漪边 id(删除/恢复时用)。"""
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM edges WHERE deletedAt IS NULL"
            " AND (source_work_id = ? OR target_work_id = ?)",
            (work_id, work_id),
        )
    ]


def cascade_author_work_ids(conn, author_id: str) -> list[str]:
    """作者名下活跃作品 id。"""
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM works WHERE deletedAt IS NULL"
            " AND id IN (SELECT work_id FROM work_authors WHERE author_id = ?)",
            (author_id,),
        )
    ]


def cascade_author_edge_ids(conn, author_id: str) -> list[str]:
    """作者名下作品相关的活跃涟漪边 id。"""
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM edges WHERE deletedAt IS NULL AND ("
            " source_work_id IN (SELECT work_id FROM work_authors WHERE author_id = ?)"
            " OR target_work_id IN (SELECT work_id FROM work_authors WHERE author_id = ?))",
            (author_id, author_id),
        )
    ]


def restore_work_edge_ids(conn, work_id: str, ts: str) -> list[str]:
    """同批删除(相同 deletedAt)且涉及该作品的涟漪边 id。"""
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM edges WHERE deletedAt = ?"
            " AND (source_work_id = ? OR target_work_id = ?)",
            (ts, work_id, work_id),
        )
    ]


def restore_author_work_ids(conn, author_id: str, ts: str) -> list[str]:
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM works WHERE deletedAt = ?"
            " AND id IN (SELECT work_id FROM work_authors WHERE author_id = ?)",
            (ts, author_id),
        )
    ]


def restore_author_edge_ids(conn, author_id: str, ts: str) -> list[str]:
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM edges WHERE deletedAt = ? AND ("
            " source_work_id IN (SELECT work_id FROM work_authors WHERE author_id = ?)"
            " OR target_work_id IN (SELECT work_id FROM work_authors WHERE author_id = ?))",
            (ts, author_id, author_id),
        )
    ]


def restore_edge_work_ids(conn, source_id: str, target_id: str, ts: str) -> list[str]:
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM works WHERE deletedAt = ? AND id IN (?, ?)",
            (ts, source_id, target_id),
        )
    ]


def active_counts() -> dict:
    """活跃行数(供同步状态快速预检)。"""
    with db_sqlite._db() as conn:
        return {
            "authors": conn.execute(
                "SELECT count(*) AS c FROM authors WHERE deletedAt IS NULL"
            ).fetchone()["c"],
            "works": conn.execute(
                "SELECT count(*) AS c FROM works WHERE deletedAt IS NULL"
            ).fetchone()["c"],
            "echoes": conn.execute(
                "SELECT count(*) AS c FROM edges WHERE deletedAt IS NULL"
            ).fetchone()["c"],
        }


# ---- 整库重写(迁移 / 恢复工具;普通写入请用行级 CRUD) ----


def replace_all(author_models, work_models, echo_models, work_authors: dict[str, list[str]]) -> None:
    """单事务整库重建(迁移用)。入参为 parse_rows 产出的模型与作者关联。"""
    def insert(table: str, cols: list[str], models: list[Any]) -> None:
        placeholders = ",".join("?" for _ in cols)
        rows = [{k: m.model_dump().get(k) for k in cols} for m in models]
        conn.executemany(
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
            [tuple(r[c] for c in cols) for r in rows],
        )

    with db_sqlite._db() as conn:
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


def rewrite_all(author_rows, work_rows, edge_rows) -> None:
    """单事务整库重写(恢复工具;admin 已改行级写入)。入参为与 load_rows 同形状的行 dict。"""
    def normalized(rows: list[dict]) -> list[dict]:
        return [_norm_row(r) for r in rows]

    author_rows = normalized(author_rows)
    work_rows = normalized(work_rows)
    edge_rows = normalized(edge_rows)

    with db_sqlite._db() as conn:
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


def list_all() -> dict:
    """返回与 CSV load_rows 同形状的行(works 行重组 author_id 逗号串)。"""
    with db_sqlite._db() as conn:
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
        ids = work_authors.get(w["id"], [])
        w["author_id"] = ",".join(ids)
        w["author_ids"] = ids
    return {"authors": authors, "works": works, "edges": edges, "work_authors": work_authors}


def load_rows() -> tuple[list[dict], list[dict], list[dict]]:
    """读取策展数据(权威来源:SQLite),与 CSV load_rows 同形状。"""
    data = list_all()
    return data["authors"], data["works"], data["edges"]


def list_audit(limit: int = 100, offset: int = 0, action: str | None = None, kind: str | None = None) -> dict:
    """审计记录查询(管理端)。"""
    where: list[str] = []
    params: list = []
    if action:
        where.append("action = ?")
        params.append(action)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with db_sqlite._db() as conn:
        rows = conn.execute(
            f"SELECT * FROM audit_log{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        total = conn.execute(
            f"SELECT count(*) AS c FROM audit_log{clause}", params
        ).fetchone()["c"]
    return {"items": [dict(r) for r in rows], "total": total}


# ---- 同步比对规范化(与 Neo4j 比对共用) ----


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

    db_sqlite.DB_PATH = Path(db_path)
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

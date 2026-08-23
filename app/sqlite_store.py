"""策展数据的 SQLite 存储层(SQLite 为唯一权威,CSV 为确定性导出产物)。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from app import db_sqlite
from app.db import invalidate_cache

AUTHOR_COLS = [
    "id", "originalName", "Name_CN", "Name_EN", "nationality",
    "birthYear", "deathYear", "note", "reviewStatus", "createdAt", "updatedAt", "deletedAt",
]
WORK_COLS = [
    "id", "language", "originalTitle", "Title_CN", "Title_EN",
    "Title_Other", "publicationYear", "genre", "note", "reviewStatus",
    "createdAt", "updatedAt", "deletedAt",
]
EDGE_COLS = [
    "id", "source_work_id", "target_work_id", "evidence", "evidenceSource",
    "note", "reviewStatus", "createdAt", "updatedAt", "deletedAt",
]
KIND_COLS = {"authors": AUTHOR_COLS, "works": WORK_COLS, "edges": EDGE_COLS}
KIND_TABLE = {"authors": "authors", "works": "works", "edges": "edges"}


def _norm_row(row: dict) -> dict:
    """reviewStatus 空值归一为 draft(NOT NULL 约束)。"""
    out = dict(row)
    out["reviewStatus"] = out.get("reviewStatus") or "draft"
    return out


# ---- 行级 CRUD(admin 写路径;由调用方在 db_sqlite._db 事务内使用) ----


def get_row(conn, kind: str, row_id: str, owner_id: str | None = None) -> dict | None:
    if owner_id is None:
        row = conn.execute(f"SELECT * FROM {KIND_TABLE[kind]} WHERE id = ?", (row_id,)).fetchone()
    else:
        row = conn.execute(
            f"SELECT * FROM {KIND_TABLE[kind]} WHERE id = ? AND owner_id = ?",
            (row_id, owner_id),
        ).fetchone()
    return dict(row) if row else None


def row_exists(conn, kind: str, row_id: str, owner_id: str | None = None) -> bool:
    if owner_id is None:
        return conn.execute(
            f"SELECT 1 FROM {KIND_TABLE[kind]} WHERE id = ?", (row_id,)
        ).fetchone() is not None
    return conn.execute(
        f"SELECT 1 FROM {KIND_TABLE[kind]} WHERE id = ? AND owner_id = ?",
        (row_id, owner_id),
    ).fetchone() is not None


def active_row_exists(conn, kind: str, row_id: str, owner_id: str | None = None) -> bool:
    """同空间内存在且未软删除的行(交叉引用校验用,软删除行不可作为引用目标)。"""
    if owner_id is None:
        return conn.execute(
            f"SELECT 1 FROM {KIND_TABLE[kind]} WHERE id = ? AND deletedAt IS NULL",
            (row_id,),
        ).fetchone() is not None
    return conn.execute(
        f"SELECT 1 FROM {KIND_TABLE[kind]} WHERE id = ? AND owner_id = ? AND deletedAt IS NULL",
        (row_id, owner_id),
    ).fetchone() is not None


def insert_row(
    conn,
    kind: str,
    row: dict,
    owner_id: str | None = None,
    extra: dict | None = None,
) -> None:
    row = _norm_row(row)
    cols = KIND_COLS[kind]
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO {KIND_TABLE[kind]} ({','.join(cols)}) VALUES ({placeholders})",
        [row.get(c) for c in cols],
    )
    sets, params = [], []
    if owner_id:
        sets.append("owner_id = ?")
        params.append(owner_id)
    for key, value in (extra or {}).items():
        if value is not None:
            sets.append(f"{key} = ?")
            params.append(value)
    if sets:
        conn.execute(
            f"UPDATE {KIND_TABLE[kind]} SET {', '.join(sets)} WHERE id = ?",
            params + [row["id"]],
        )


def update_row(
    conn,
    kind: str,
    row_id: str,
    row: dict,
    expected_updated_at: str | None = None,
    owner_id: str | None = None,
    extra: dict | None = None,
) -> int:
    """更新一行。返回 1=成功, 0=行不存在, -1=乐观锁冲突(updatedAt 已变化)。"""
    row = _norm_row(row)
    cols = [c for c in KIND_COLS[kind] if c not in ("id", "owner_id")]
    scope = " AND owner_id = ?" if owner_id else ""
    scope_params = [owner_id] if owner_id else []
    extra_parts: list[str] = []
    extra_params: list = []
    for key, value in (extra or {}).items():
        extra_parts.append(f"{key} = ?")
        extra_params.append(value)
    extra_sql = (", " + ", ".join(extra_parts)) if extra_parts else ""
    if expected_updated_at is not None:
        cur = conn.execute(
            f"UPDATE {KIND_TABLE[kind]} SET " + ", ".join(f"{c} = ?" for c in cols)
            + extra_sql
            + f" WHERE id = ? AND updatedAt = ?{scope}",
            [row.get(c) for c in cols] + extra_params
            + [row_id, expected_updated_at] + scope_params,
        )
        if cur.rowcount == 0:
            return -1 if row_exists(conn, kind, row_id, owner_id) else 0
        return 1
    cur = conn.execute(
        f"UPDATE {KIND_TABLE[kind]} SET " + ", ".join(f"{c} = ?" for c in cols)
        + extra_sql
        + f" WHERE id = ?{scope}",
        [row.get(c) for c in cols] + extra_params + [row_id] + scope_params,
    )
    return 1 if cur.rowcount > 0 else 0


def set_work_authors(conn, work_id: str, author_ids: list[str]) -> None:
    conn.execute("DELETE FROM work_authors WHERE work_id = ?", (work_id,))
    conn.executemany(
        "INSERT INTO work_authors (work_id, author_id) VALUES (?, ?)",
        [(work_id, aid) for aid in author_ids],
    )


def mark_deleted(conn, kind: str, ids: list[str], deleted_at: str, owner_id: str | None = None) -> int:
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    scope = " AND owner_id = ?" if owner_id else ""
    extra = [owner_id] if owner_id else []
    cur = conn.execute(
        f"UPDATE {KIND_TABLE[kind]} SET deletedAt = ?, updatedAt = ?"
        f" WHERE id IN ({placeholders}){scope}",
        [deleted_at, deleted_at] + list(ids) + extra,
    )
    return cur.rowcount


def restore_by_ts(
    conn, kind: str, ids: list[str], ts: str, updated_at: str, owner_id: str | None = None
) -> int:
    """按相同 deletedAt 时间戳恢复一批行(级联恢复)。"""
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    scope = " AND owner_id = ?" if owner_id else ""
    extra = [owner_id] if owner_id else []
    cur = conn.execute(
        f"UPDATE {KIND_TABLE[kind]} SET deletedAt = NULL, updatedAt = ?"
        f" WHERE deletedAt = ? AND id IN ({placeholders}){scope}",
        [updated_at, ts] + list(ids) + extra,
    )
    return cur.rowcount


# ---- 级联删除/恢复(纯 SQL,不读取全量数据) ----


def cascade_work_edge_ids(conn, work_id: str, owner_id: str | None = None) -> list[str]:
    """作品相关的活跃涟漪边 id(删除/恢复时用)。"""
    scope = " AND owner_id = ?" if owner_id else ""
    params = (work_id, work_id) + ((owner_id,) if owner_id else ())
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM edges WHERE deletedAt IS NULL"
            f" AND (source_work_id = ? OR target_work_id = ?){scope}",
            params,
        )
    ]


def cascade_author_work_ids(conn, author_id: str, owner_id: str | None = None) -> list[str]:
    """作者名下活跃作品 id。"""
    scope = " AND owner_id = ?" if owner_id else ""
    params = (author_id,) + ((owner_id,) if owner_id else ())
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM works WHERE deletedAt IS NULL"
            f" AND id IN (SELECT work_id FROM work_authors WHERE author_id = ?){scope}",
            params,
        )
    ]


def cascade_author_edge_ids(conn, author_id: str, owner_id: str | None = None) -> list[str]:
    """作者名下作品相关的活跃涟漪边 id。"""
    scope = " AND owner_id = ?" if owner_id else ""
    params = (author_id, author_id) + ((owner_id,) if owner_id else ())
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM edges WHERE deletedAt IS NULL AND ("
            " source_work_id IN (SELECT work_id FROM work_authors WHERE author_id = ?)"
            " OR target_work_id IN (SELECT work_id FROM work_authors WHERE author_id = ?))"
            + scope,
            params,
        )
    ]


def restore_work_edge_ids(conn, work_id: str, ts: str, owner_id: str | None = None) -> list[str]:
    """同批删除(相同 deletedAt)且涉及该作品的涟漪边 id。"""
    scope = " AND owner_id = ?" if owner_id else ""
    params = (ts, work_id, work_id) + ((owner_id,) if owner_id else ())
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM edges WHERE deletedAt = ?"
            f" AND (source_work_id = ? OR target_work_id = ?){scope}",
            params,
        )
    ]


def restore_author_work_ids(conn, author_id: str, ts: str, owner_id: str | None = None) -> list[str]:
    scope = " AND owner_id = ?" if owner_id else ""
    params = (ts, author_id) + ((owner_id,) if owner_id else ())
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM works WHERE deletedAt = ?"
            f" AND id IN (SELECT work_id FROM work_authors WHERE author_id = ?){scope}",
            params,
        )
    ]


def restore_author_edge_ids(conn, author_id: str, ts: str, owner_id: str | None = None) -> list[str]:
    scope = " AND owner_id = ?" if owner_id else ""
    params = (ts, author_id, author_id) + ((owner_id,) if owner_id else ())
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM edges WHERE deletedAt = ? AND ("
            " source_work_id IN (SELECT work_id FROM work_authors WHERE author_id = ?)"
            " OR target_work_id IN (SELECT work_id FROM work_authors WHERE author_id = ?))"
            + scope,
            params,
        )
    ]


def restore_edge_work_ids(
    conn, source_id: str, target_id: str, ts: str, owner_id: str | None = None
) -> list[str]:
    scope = " AND owner_id = ?" if owner_id else ""
    params = (ts, source_id, target_id) + ((owner_id,) if owner_id else ())
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM works WHERE deletedAt = ?"
            f" AND id IN (?, ?){scope}",
            params,
        )
    ]


# ---- 整库重写(迁移 / 恢复工具;普通写入请用行级 CRUD) ----


def replace_all(author_models, work_models, echo_models, work_authors: dict[str, list[str]]) -> None:
    """单事务整库重建(迁移用)。入参为 parse_rows 产出的模型与作者关联。"""
    def insert(table: str, cols: list[str], models: list[Any]) -> None:
        placeholders = ",".join("?" for _ in cols)
        rows = [{**m.model_dump(), "owner_id": None} for m in models]
        conn.executemany(
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
            [tuple(r[c] for c in cols) for r in rows],
        )

    with db_sqlite._db() as conn:
        conn.execute("DELETE FROM work_authors")
        conn.execute("DELETE FROM edges")
        conn.execute("DELETE FROM works")
        conn.execute("DELETE FROM authors")
        insert("authors", AUTHOR_COLS + ["owner_id"], author_models)
        insert("works", WORK_COLS + ["owner_id"], work_models)
        insert("edges", EDGE_COLS + ["owner_id"], echo_models)
        conn.executemany(
            "INSERT INTO work_authors (work_id, author_id) VALUES (?, ?)",
            [(wid, aid) for wid, aids in work_authors.items() for aid in aids],
        )
    invalidate_cache()


def replace_public_rows(
    author_models,
    work_models,
    echo_models,
    work_authors: dict[str, list[str]],
    owner_id: str | None,
) -> None:
    """单事务重建公共星云(admin 空间 + 未认领行),用户私有空间原样保留。

    快照 CSV 恢复用:CSV 只含公共数据,恢复时不得清空用户星云。
    """
    def insert(table: str, cols: list[str], models: list[Any]) -> None:
        placeholders = ",".join("?" for _ in cols)
        rows = [{**m.model_dump(), "owner_id": owner_id} for m in models]
        conn.executemany(
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
            [tuple(r[c] for c in cols) for r in rows],
        )

    with db_sqlite._db() as conn:
        if owner_id is None:
            scope = "owner_id IS NULL"
            params: tuple = ()
        else:
            scope = "(owner_id IS NULL OR owner_id = ?)"
            params = (owner_id,)
        conn.execute(
            f"DELETE FROM work_authors WHERE work_id IN (SELECT id FROM works WHERE {scope})",
            params,
        )
        conn.execute(f"DELETE FROM edges WHERE {scope}", params)
        conn.execute(f"DELETE FROM works WHERE {scope}", params)
        conn.execute(f"DELETE FROM authors WHERE {scope}", params)
        insert("authors", AUTHOR_COLS + ["owner_id"], author_models)
        insert("works", WORK_COLS + ["owner_id"], work_models)
        insert("edges", EDGE_COLS + ["owner_id"], echo_models)
        conn.executemany(
            "INSERT INTO work_authors (work_id, author_id) VALUES (?, ?)",
            [(wid, aid) for wid, aids in work_authors.items() for aid in aids],
        )
    invalidate_cache()


def rewrite_all(author_rows, work_rows, edge_rows) -> None:
    """单事务整库重写(测试 / 恢复工具;admin 已改行级写入)。入参为与 load_rows 同形状的行 dict。

    与 replace_all 的分工:replace_all 接收 parse_rows 模型(迁移/导入用);
    rewrite_all 接收行 dict(测试造数 / 恢复用),内部自行拆分 author_id。
    """
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

        placeholders = ",".join("?" for _ in AUTHOR_COLS + ["owner_id"])
        conn.executemany(
            f"INSERT INTO authors ({','.join(AUTHOR_COLS + ['owner_id'])}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in AUTHOR_COLS + ["owner_id"]) for r in author_rows],
        )
        placeholders = ",".join("?" for _ in WORK_COLS + ["owner_id"])
        conn.executemany(
            f"INSERT INTO works ({','.join(WORK_COLS + ['owner_id'])}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in WORK_COLS + ["owner_id"]) for r in work_rows],
        )
        placeholders = ",".join("?" for _ in EDGE_COLS + ["owner_id"])
        conn.executemany(
            f"INSERT INTO edges ({','.join(EDGE_COLS + ['owner_id'])}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in EDGE_COLS + ["owner_id"]) for r in edge_rows],
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
    invalidate_cache()


def list_all(owner_id: str | None = None) -> dict:
    """返回与 CSV load_rows 同形状的行(works 行重组 author_id 逗号串)。"""
    with db_sqlite._db() as conn:
        if owner_id is None:
            authors = [dict(r) for r in conn.execute("SELECT * FROM authors ORDER BY id")]
            works = [dict(r) for r in conn.execute("SELECT * FROM works ORDER BY id")]
            edges = [dict(r) for r in conn.execute("SELECT * FROM edges ORDER BY id")]
            wa_rows = conn.execute(
                "SELECT work_id, author_id FROM work_authors ORDER BY work_id, author_id"
            ).fetchall()
        else:
            authors = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM authors WHERE owner_id = ? ORDER BY id", (owner_id,)
                )
            ]
            works = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM works WHERE owner_id = ? ORDER BY id", (owner_id,)
                )
            ]
            edges = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM edges WHERE owner_id = ? ORDER BY id", (owner_id,)
                )
            ]
            wa_rows = conn.execute(
                "SELECT wa.work_id, wa.author_id FROM work_authors wa"
                " JOIN works w ON w.id = wa.work_id WHERE w.owner_id = ?"
                " ORDER BY wa.work_id, wa.author_id",
                (owner_id,),
            ).fetchall()
    work_authors: dict[str, list[str]] = {}
    for r in wa_rows:
        work_authors.setdefault(r["work_id"], []).append(r["author_id"])
    for w in works:
        ids = work_authors.get(w["id"], [])
        w["author_id"] = ",".join(ids)
        w["author_ids"] = ids
    return {"authors": authors, "works": works, "edges": edges, "work_authors": work_authors}


def load_rows(owner_id: str | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """读取策展数据(权威来源:SQLite),与 CSV load_rows 同形状。"""
    data = list_all(owner_id)
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


def prune_audit(days: int = 90, dry_run: bool = False) -> int:
    """删除早于 N 天的审计记录(默认 90 天);dry_run 只统计不删除。

    返回受影响行数(dry_run 时返回将删除的行数)。配合 scripts/prune_audit.py。
    """
    cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).isoformat(timespec="seconds")
    with db_sqlite._db() as conn:
        if dry_run:
            return conn.execute(
                "SELECT count(*) AS c FROM audit_log WHERE ts < ?", (cutoff,)
            ).fetchone()["c"]
        cur = conn.execute("DELETE FROM audit_log WHERE ts < ?", (cutoff,))
        return cur.rowcount


# ---- 往返一致性校验规范化(SQLite <-> CSV 共用) ----


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
    """规范化活跃数据载荷(忽略时间戳),用于 SQLite <-> CSV 往返一致性校验。"""
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
            "note": sync_norm(r.get("note")),
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
            "genre": sync_norm(r.get("genre")),
            "note": sync_norm(r.get("note")),
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
    """SQLite 侧的规范化载荷(供迁移/恢复后的往返校验)。"""
    data = list_all()
    return canonical_payload(data["authors"], data["works"], data["edges"])


def migrate_from_csv(db_path: Path | str, check: bool = True) -> dict:
    """校验 data/export/*.csv 并整库重建 SQLite;校验失败抛 ValueError。"""
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

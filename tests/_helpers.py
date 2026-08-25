"""测试公共辅助(不入生产包):仅供测试使用的工具。

rewrite_all 原位于 app/sqlite_store.py(生产模块),仅被测试调用,
迁出到本模块避免「生产代码里躺着一个只被测试用的整库重写路径」。
"""

from __future__ import annotations

from app import db_sqlite
from app.db import invalidate_cache
from app.sqlite_store import AUTHOR_COLS, EDGE_COLS, WORK_COLS, _norm_row


def rewrite_all(author_rows, work_rows, edge_rows) -> None:
    """单事务整库重写(测试造数 / 恢复用)。入参为与 load_rows 同形状的行 dict。

    与 app.sqlite_store.replace_all 的分工:replace_all 接收 parse_rows 模型
    (迁移/导入用);rewrite_all 接收行 dict(测试造数),内部自行拆分 author_id。
    """
    author_rows = [_norm_row(r) for r in author_rows]
    work_rows = [_norm_row(r) for r in work_rows]
    edge_rows = [_norm_row(r) for r in edge_rows]

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

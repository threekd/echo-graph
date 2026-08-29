"""测试公共辅助(不入生产包):仅供测试使用的工具。

rewrite_all 原位于 app/sqlite_store.py(生产模块),仅被测试调用,
迁出到本模块避免「生产代码里躺着一个只被测试用的整库重写路径」。
"""

from __future__ import annotations

from app import auth, db_sqlite, space_crud
from app.db import invalidate_cache
from app.sqlite_store import AUTHOR_COLS, EDGE_COLS, WORK_COLS, _norm_row


class AdminCrudProxy:
    """已移除的 app.admin 星云 CRUD 端点的测试替身。

    旧端点只是把「当前 admin 用户」透传给 space_crud(见 app/me.py 同一套
    实现);这里每次调用实时解析引导管理员,与旧 `_admin_context` 的回退
    语义一致(测试 setUp 已注册 ADMIN_BOOTSTRAP_EMAIL)。
    """

    def _ctx(self) -> tuple[str, str]:
        admin_id = auth.admin_user_id()
        if admin_id is None:
            raise AssertionError("测试需要先注册引导管理员(ADMIN_BOOTSTRAP_EMAIL)")
        return admin_id, auth.bootstrap_email()

    def create(self, kind: str, row: dict) -> dict:
        owner, actor = self._ctx()
        return space_crud.create_row(kind, row, owner, actor)

    def update(self, kind: str, item_id: str, row: dict) -> dict:
        owner, actor = self._ctx()
        return space_crud.update_row(kind, item_id, row, owner, actor)

    def delete(self, kind: str, item_id: str) -> dict:
        owner, actor = self._ctx()
        return space_crud.delete_row(kind, item_id, owner, actor)

    def restore(self, kind: str, item_id: str) -> dict:
        owner, actor = self._ctx()
        return space_crud.restore_row(kind, item_id, owner, actor)

    def permanent_delete(self, kind: str, item_id: str) -> dict:
        owner, actor = self._ctx()
        return space_crud.permanent_delete_row(kind, item_id, owner, actor)

    def get_data(self, include_deleted: bool = True) -> dict:
        owner, _ = self._ctx()
        return space_crud.space_data(owner, include_deleted)


def admin_crud() -> AdminCrudProxy:
    """返回绑定引导管理员的 space_crud 代理(替代已移除的 app.admin CRUD 端点)。"""
    return AdminCrudProxy()


def rewrite_all(author_rows, work_rows, edge_rows) -> None:
    """单事务整库重写(测试造数 / 恢复用)。入参为与 load_rows 同形状的行 dict。

    app.sqlite_store 已不再提供整库重写(CSV 迁移层随备份层移除);
    本函数接收行 dict(测试造数),内部自行拆分 author_id。
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

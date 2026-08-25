"""AI 草稿归属工具。

AI 草稿不再使用共享 system_llm 账号:草稿行直接以 owner_id=上传者、
created_by='llm' 落库,「admin 只能看到自己上传的草稿」按这两列筛选即可
(见 app/llm_review.py)。CLI 管线没有登录用户,草稿归属引导管理员。

本模块还提供旧数据迁移:2026-08 之前草稿落在共享 system_llm 账号空间,
migrate_legacy_llm_drafts() 把它们改挂到引导管理员并删除空账号。
"""

from __future__ import annotations

from app import db_sqlite
from app.auth import admin_user_id

# 旧共享账号标识(仅迁移/兼容查询用,新写入不再创建)
SYSTEM_LLM_EMAIL = "system_llm@echo.local"
SYSTEM_LLM_USERNAME = "system_llm"


def draft_owner_id(user_id: str | None = None) -> str:
    """AI 草稿归属者:有上传者用上传者,否则回退引导管理员(CLI 管线)。"""
    if user_id:
        return user_id
    admin = admin_user_id()
    if not admin:
        raise RuntimeError("引导管理员不存在,无法归属 AI 草稿(请先注册 ADMIN_BOOTSTRAP_EMAIL 账号)")
    return admin


def migrate_legacy_llm_drafts() -> int:
    """把旧 system_llm 共享账号下的 llm 草稿改挂到引导管理员(owner_id=admin)。

    幂等:共享账号或草稿不存在时返回 0。迁移后删除已清空的 system_llm 账号。
    """
    admin = admin_user_id()
    if not admin:
        return 0
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", (SYSTEM_LLM_EMAIL,)
        ).fetchone()
        if row is None:
            return 0
        legacy_owner = row["id"]
        moved = 0
        for table in ("authors", "works", "edges"):
            cur = conn.execute(
                f"UPDATE {table} SET owner_id = ?"
                " WHERE owner_id = ? AND created_by = 'llm'",
                (admin, legacy_owner),
            )
            moved += cur.rowcount
        # 账号下仍有其他行(非 llm 数据)时保留账号,否则删除
        remaining = conn.execute(
            "SELECT count(*) c FROM users u"
            " LEFT JOIN authors a ON a.owner_id = u.id"
            " LEFT JOIN works w ON w.owner_id = u.id"
            " LEFT JOIN edges e ON e.owner_id = u.id"
            " WHERE u.id = ? AND (a.id IS NOT NULL OR w.id IS NOT NULL OR e.id IS NOT NULL)",
            (legacy_owner,),
        ).fetchone()["c"]
        if not remaining:
            conn.execute("DELETE FROM users WHERE id = ?", (legacy_owner,))
    return moved

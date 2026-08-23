"""用户资料公共辅助(展示名 / 行查询),space 与 follows 共用。

此前 `_display_name` / `_user_row` 在 app/space.py 与 app/follows.py 各实现一份,
语义相同(昵称 > 用户名 > 兜底),统一收敛到这里避免漂移。
"""

from __future__ import annotations

from app import db_sqlite


def display_name(row: dict) -> str:
    """星云显示名:昵称 > 用户名 > 兜底(不暴露邮箱)。"""
    return (
        (row.get("nickname") or "").strip()
        or (row.get("username") or "").strip()
        or "匿名星云"
    )


def user_row(user_id: str, active_only: bool = False) -> dict | None:
    """按 id 取用户行;active_only=True 时仅返回 status='active' 的用户。"""
    sql = "SELECT * FROM users WHERE id = ?"
    params: tuple = (user_id,)
    if active_only:
        sql += " AND status = 'active'"
    with db_sqlite._db() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None

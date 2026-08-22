"""星际跃迁基础:只读访问其他用户的星云。

可见性:users.space_visibility(默认 public)。private 空间对访客不可见(404);
本人通过 /api/me/* 访问;admin 可访问任意空间(审核/运营)。
读取返回与 /api/graph 同形状的图谱数据,附 spaceId / displayName(星云账号,
当前用邮箱;正式公网部署前建议改为显示名或脱敏,避免暴露邮箱)。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import db_sqlite
from app.auth import SESSION_COOKIE, current_user
from app.db import SqliteStore

router = APIRouter(prefix="/api/space", tags=["space"])


def _viewer(request: Request) -> dict | None:
    return current_user(request.cookies.get(SESSION_COOKIE))


def _user_row(user_id: str) -> dict | None:
    with db_sqlite._db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def _require_visible(user_id: str, viewer: dict | None) -> dict:
    """返回可见用户行;不存在/未公开一律 404,不暴露存在性。"""
    row = _user_row(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="星云不存在或未公开")
    if row["space_visibility"] == "public":
        return row
    if viewer and viewer["id"] == row["id"]:
        return row
    if viewer and viewer["role"] == "admin":
        return row
    raise HTTPException(status_code=404, detail="星云不存在或未公开")


@router.get("/random/graph")
def random_space_graph(request: Request) -> dict:
    """随机跃迁:返回一个公开星云的图谱(含 spaceId)。"""
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT id, email FROM users WHERE space_visibility = 'public'"
            " ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="暂无可公开访问的星云")
    return {
        "spaceId": row["id"],
        "displayName": row["email"],
        **SqliteStore(owner_id=row["id"], include_private=False).graph(),
    }


@router.get("/{user_id}/graph")
def space_graph(user_id: str, request: Request) -> dict:
    """定向访问:读取某用户公开的星云。"""
    row = _require_visible(user_id, _viewer(request))
    return {
        "spaceId": row["id"],
        "displayName": row["email"],
        **SqliteStore(owner_id=row["id"], include_private=False).graph(),
    }

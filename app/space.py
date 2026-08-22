"""星际跃迁基础:只读访问其他用户的星云。

可见性:users.space_visibility(默认 public)。private 空间对访客不可见(404);
本人通过 /api/me/* 访问;admin 可访问任意空间(审核/运营)。
读取返回与 /api/graph 同形状的数据,附 spaceId / displayName(星云账号,
displayName 优先昵称,其次用户名,不再暴露邮箱)。

跃迁后的完整交互(搜索/详情/扩散/路径)由 /api/space/{user_id}/search、
/api/space/{user_id}/work/{id}、/api/space/{user_id}/expansion/{id}、
/api/space/{user_id}/path 提供,前端按 space 上下文路由(见 api.ts 的 apiRoot)。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

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


def _space_store(row: dict) -> SqliteStore:
    """他人星云只读视图:与 /api/space/{user_id}/graph 一致的可见性规则(仅 public 节点)。"""
    return SqliteStore(owner_id=row["id"], include_private=False)


def _display_name(row: dict) -> str:
    """星云显示名:昵称 > 用户名 > 兜底(不暴露邮箱)。"""
    return (
        (row.get("nickname") or "").strip()
        or (row.get("username") or "").strip()
        or "匿名星云"
    )


@router.get("/random/graph")
def random_space_graph(request: Request) -> dict:
    """随机跃迁:返回一个公开星云的图谱(含 spaceId)。"""
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT id, username, nickname, bio FROM users WHERE space_visibility = 'public'"
            " ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="暂无可公开访问的星云")
    return {
        "spaceId": row["id"],
        "displayName": _display_name(dict(row)),
        "owner": {
            "username": row["username"],
            "nickname": row["nickname"],
            "bio": row["bio"],
        },
        **_space_store(row).graph(),
    }


@router.get("/{user_id}/graph")
def space_graph(user_id: str, request: Request) -> dict:
    """定向访问:读取某用户公开的星云。"""
    row = _require_visible(user_id, _viewer(request))
    return {
        "spaceId": row["id"],
        "displayName": _display_name(row),
        "owner": {
            "username": row["username"],
            "nickname": row["nickname"],
            "bio": row["bio"],
        },
        **_space_store(row).graph(),
    }


@router.get("/{user_id}/search")
def space_search(
    user_id: str,
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    request: Request = None,  # noqa: B008 - FastAPI 注入
) -> dict:
    """在目标星云内搜索作家 / 作品。"""
    row = _require_visible(user_id, _viewer(request))
    return {"hits": _space_store(row).search(q.strip(), limit)}


@router.get("/{user_id}/work/{work_id}")
def space_work_detail(user_id: str, work_id: str, request: Request = None) -> dict:  # noqa: B008
    """目标星云内作品详情(涟漪数据)。"""
    row = _require_visible(user_id, _viewer(request))
    detail = _space_store(row).work_detail(work_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"work not found: {work_id}")
    return detail


@router.get("/{user_id}/expansion/{work_id}")
def space_expansion(
    user_id: str,
    work_id: str,
    hops: int = Query(1, ge=1, description="向外扩散的级数(无上限,BFS 无更多节点时自动终止)"),
    request: Request = None,  # noqa: B008 - FastAPI 注入
) -> dict:
    """目标星云内以某作品为中心的 N 级扩散子图。"""
    row = _require_visible(user_id, _viewer(request))
    data = _space_store(row).expansion(work_id, hops)
    if data is None:
        raise HTTPException(status_code=404, detail=f"work not found: {work_id}")
    return data


@router.get("/{user_id}/path")
def space_path(
    user_id: str,
    frm: str = Query(..., alias="from", description="起点作品 id"),
    to: str = Query(..., description="终点作品 id"),
    max_hops: int = Query(15, ge=1, le=30),
    request: Request = None,  # noqa: B008 - FastAPI 注入
) -> dict:
    """目标星云内两作品间的有向最短提及链。"""
    row = _require_visible(user_id, _viewer(request))
    result = _space_store(row).path(frm.strip(), to.strip(), max_hops)
    if result is None:
        raise HTTPException(status_code=404, detail="no mention path found")
    return result

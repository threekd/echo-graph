"""星际跃迁基础:只读访问其他用户的星云。

星云可见性:users.space_visibility(默认 public)。private 空间对访客不可见(404);
本人通过 /api/me/* 访问;admin 可访问任意空间(审核/运营)。
公开星云内的作者/作品不再有节点级可见性(schema v21 移除),访客与 owner 看到一致数据。
读取返回与 /api/me 同形状的数据,附 spaceId / displayName(星云账号,
displayName 优先昵称,其次用户名,不再暴露邮箱)。

跃迁后的完整交互(搜索/详情/扩散/路径)由 /api/space/{user_id}/search、
/api/space/{user_id}/work/{id}、/api/space/{user_id}/expansion/{id}、
/api/space/{user_id}/path 提供,前端按 space 上下文路由(见 api.ts 的 apiRoot)。
公共星云/官方图谱概念已移除(2026-08-28):不存在默认视图,登录用户首页即自己的星云。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import db_sqlite
from app.auth import SESSION_COOKIE, current_user
from app.db import SqliteStore
from app.read_routes import register_read_routes
from app.users import display_name, user_row

router = APIRouter(prefix="/api/space", tags=["space"])


def _viewer(request: Request) -> dict | None:
    return current_user(request.cookies.get(SESSION_COOKIE))


def _require_visible(user_id: str, viewer: dict | None) -> dict:
    """返回可见用户行;不存在/已禁用/未公开一律 404,不暴露存在性。"""
    row = user_row(user_id, active_only=True)
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
    """目标星云只读视图:公开星云内所有数据对访客一致可见(节点级可见性已移除)。"""
    return SqliteStore(owner_id=row["id"])


def _space_context(request: Request, user_id: str) -> tuple[dict, dict | None]:
    """同一请求内只解析一次目标用户行(store 与 owner 资料共用,避免重复查库)。"""
    cached = getattr(request.state, "space_ctx", None)
    if cached and cached[0] == user_id:
        return cached[1], cached[2]
    viewer = _viewer(request)
    row = _require_visible(user_id, viewer)
    request.state.space_ctx = (user_id, row, viewer)
    return row, viewer


def _space_store_factory(request: Request, user_id: str | None = None) -> SqliteStore:
    row, _ = _space_context(request, user_id or "")
    return _space_store(row)


def _space_owner_provider(request: Request, user_id: str | None = None) -> dict:
    row, _ = _space_context(request, user_id or "")
    return {
        "username": row.get("username"),
        "nickname": row.get("nickname"),
        "bio": row.get("bio"),
    }


def _space_graph_extra(request: Request, user_id: str | None = None) -> dict:
    """图谱响应附加的顶层字段(前端跃迁需要 spaceId / displayName)。"""
    row, _ = _space_context(request, user_id or "")
    return {"spaceId": row["id"], "displayName": display_name(row)}


@router.get("/random/graph")
def random_space_graph(request: Request) -> dict:
    """随机跃迁:返回一个公开星云的图谱(含 spaceId)。"""
    viewer = _viewer(request)
    where = "space_visibility = 'public' AND status = 'active'"
    params: tuple = ()
    # 排除浏览者本人(避免跃迁到自己的星云);官方图谱概念已移除,不再排除 admin
    excludes = [x for x in (viewer["id"] if viewer else None,) if x]
    if excludes:
        placeholders = ",".join("?" for _ in excludes)
        where += f" AND id NOT IN ({placeholders})"
        params = tuple(excludes)
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT id, username, nickname, bio FROM users"
            f" WHERE {where} ORDER BY RANDOM() LIMIT 1",
            params,
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="暂无可公开访问的星云")
    return {
        "spaceId": row["id"],
        "displayName": display_name(dict(row)),
        "owner": {
            "username": row["username"],
            "nickname": row["nickname"],
            "bio": row["bio"],
        },
        **_space_store(row).graph(),
    }


@router.get("/by-username/{username}/graph")
def space_graph_by_username(username: str, request: Request) -> dict:
    """按用户名取公开星云图谱(游客落地星云用,见 .env 的 LANDING_SPACE)。

    用户名大小写不敏感;不存在 / 已禁用 / 未公开一律 404(与按 id 访问同口径,
    不暴露存在性)。用户名只作为服务端配置,不会写入前端 URL 或界面。
    """
    viewer = _viewer(request)
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND status = 'active'",
            (username.strip(),),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="星云不存在或未公开")
    visible = _require_visible(row["id"], viewer)
    data = _space_store(visible).graph()
    data.update(_space_graph_extra(request, visible["id"]))
    data["owner"] = _space_owner_provider(request, visible["id"])
    return data


# 只读六件套(与 /api、/api/me 共用同一套实现,见 app/read_routes.py)
# 注意:random / by-username 路由必须注册在 {user_id} 路由之前,避免被当作用户 id 匹配
register_read_routes(
    router,
    _space_store_factory,
    _space_owner_provider,
    graph_extra=_space_graph_extra,
    user_id_path=True,
    name_prefix="space_",
)

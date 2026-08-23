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

from fastapi import APIRouter, HTTPException, Request

from app import db_sqlite
from app.auth import SESSION_COOKIE, admin_user_id, current_user
from app.db import SqliteStore
from app.read_routes import register_read_routes
from app.users import display_name, user_row

router = APIRouter(prefix="/api/space", tags=["space"])


def _viewer(request: Request) -> dict | None:
    return current_user(request.cookies.get(SESSION_COOKIE))


def _require_visible(user_id: str, viewer: dict | None) -> dict:
    """返回可见用户行;不存在/未公开一律 404,不暴露存在性。"""
    row = user_row(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="星云不存在或未公开")
    if row["space_visibility"] == "public":
        return row
    if viewer and viewer["id"] == row["id"]:
        return row
    if viewer and viewer["role"] == "admin":
        return row
    raise HTTPException(status_code=404, detail="星云不存在或未公开")


def _space_store(row: dict, viewer: dict | None = None) -> SqliteStore:
    """目标星云只读视图:访客仅看 public 节点;owner 本人与 admin 看全部节点。

    admin 需要能审核/运营隐藏数据(与模块 docstring「admin 可访问任意空间」一致);
    owner 通过空间深链访问自己时也应看到 visibility=private 的节点。
    """
    if viewer and (viewer["id"] == row["id"] or viewer["role"] == "admin"):
        return SqliteStore(owner_id=row["id"], include_private=True)
    return SqliteStore(owner_id=row["id"], include_private=False)


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
    row, viewer = _space_context(request, user_id or "")
    return _space_store(row, viewer)


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
    admin = admin_user_id()
    where = "space_visibility = 'public'"
    params: tuple = ()
    # 排除公共星云所有者(与「公共星云」重复)与浏览者本人(避免跃迁到自己的星云)
    excludes = [x for x in (admin, viewer["id"] if viewer else None) if x]
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
        **_space_store(row, viewer).graph(),
    }


# 只读五件套(与 /api、/api/me 共用同一套实现,见 app/read_routes.py)
# 注意:random 路由必须注册在 {user_id} 路由之前,避免被当作用户 id 匹配
register_read_routes(
    router,
    _space_store_factory,
    _space_owner_provider,
    graph_extra=_space_graph_extra,
    user_id_path=True,
    name_prefix="space_",
)

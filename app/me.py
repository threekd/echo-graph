"""个人空间 API:登录用户自己的星云(私有,仅本人可见)。

与公共星云共用同一套读取/写路径,只是 owner 上下文不同:
- 读取:SqliteStore(owner_id=当前用户),严格过滤本人数据;
- 写入:app.space_crud(owner_id=当前用户),不接纳未认领行,行不属于本人一律 404。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_user
from app.db import SqliteStore
from app.read_routes import register_read_routes
from app.space_crud import (
    Kind,
    create_row,
    delete_row,
    restore_row,
    space_data,
    update_row,
)

router = APIRouter(prefix="/api/me", tags=["me"], dependencies=[Depends(require_user)])


def _me_user(request: Request) -> dict:
    """当前登录用户(同一请求内只解析一次,store 与 owner 资料共用)。"""
    user = getattr(request.state, "me_user", None)
    if user is None:
        user = require_user(request)
        request.state.me_user = user
    return user


def _me_store(request: Request, user_id: str | None = None) -> SqliteStore:
    return SqliteStore(owner_id=_me_user(request)["id"])


def _me_owner(request: Request, user_id: str | None = None) -> dict:
    user = _me_user(request)
    return {
        "username": user.get("username"),
        "nickname": user.get("nickname"),
        "bio": user.get("bio"),
    }


@router.get("/data")
def my_data(
    include_deleted: bool = Query(True, description="是否包含软删除行(前端按需拉取)"),
    user: dict = Depends(require_user),  # noqa: B008
) -> dict:
    """个人空间管理表格数据(仅本人数据 + 重复提醒)。"""
    return space_data(user["id"], include_deleted)


@router.post("/{kind}")
def my_create(kind: Kind, row: dict, user: dict = Depends(require_user)) -> dict:  # noqa: B008
    return create_row(kind, row, user["id"], user["email"])


@router.put("/{kind}/{item_id}")
def my_update(
    kind: Kind, item_id: str, row: dict, user: dict = Depends(require_user)  # noqa: B008
) -> dict:
    return update_row(kind, item_id, row, user["id"], user["email"])


@router.delete("/{kind}/{item_id}")
def my_delete(kind: Kind, item_id: str, user: dict = Depends(require_user)) -> dict:  # noqa: B008
    return delete_row(kind, item_id, user["id"], user["email"])


@router.post("/{kind}/{item_id}/restore")
def my_restore(kind: Kind, item_id: str, user: dict = Depends(require_user)) -> dict:  # noqa: B008
    return restore_row(kind, item_id, user["id"], user["email"])


# 只读六件套(与 /api、/api/space 共用同一套实现,见 app/read_routes.py)
register_read_routes(
    router,
    _me_store,
    _me_owner,
    name_prefix="my_",
)

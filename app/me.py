"""个人空间 API:登录用户自己的星云(私有,仅本人可见)。

与公共星云共用同一套读取/写路径,只是 owner 上下文不同:
- 读取:SqliteStore(owner_id=当前用户),严格过滤本人数据;
- 写入:app.space_crud(owner_id=当前用户),不接纳未认领行,行不属于本人一律 404。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_user
from app.db import SqliteStore
from app.space_crud import (
    Kind,
    create_row,
    delete_row,
    restore_row,
    space_data,
    update_row,
)

router = APIRouter(prefix="/api/me", tags=["me"])


def _store(user: dict) -> SqliteStore:
    return SqliteStore(owner_id=user["id"])


@router.get("/data")
def my_data(
    include_deleted: bool = Query(True, description="是否包含软删除行(前端按需拉取)"),
    user: dict = Depends(require_user),  # noqa: B008
) -> dict:
    """个人空间管理表格数据(仅本人数据 + 重复提醒)。"""
    return space_data(user["id"], include_deleted)


@router.get("/graph")
def my_graph(user: dict = Depends(require_user)) -> dict:  # noqa: B008
    data = _store(user).graph()
    data["owner"] = {
        "username": user.get("username"),
        "nickname": user.get("nickname"),
        "bio": user.get("bio"),
    }
    return data


@router.get("/stats")
def my_stats(user: dict = Depends(require_user)) -> dict:  # noqa: B008
    return _store(user).stats()


@router.get("/search")
def my_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    user: dict = Depends(require_user),  # noqa: B008
) -> dict:
    return {"hits": _store(user).search(q.strip(), limit)}


@router.get("/work/{work_id}")
def my_work_detail(work_id: str, user: dict = Depends(require_user)) -> dict:  # noqa: B008
    detail = _store(user).work_detail(work_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"work not found: {work_id}")
    return detail


@router.get("/expansion/{work_id}")
def my_expansion(
    work_id: str,
    hops: int = Query(1, ge=1, description="向外扩散的级数(无上限,BFS 无更多节点时自动终止)"),
    user: dict = Depends(require_user),  # noqa: B008
) -> dict:
    data = _store(user).expansion(work_id, hops)
    if data is None:
        raise HTTPException(status_code=404, detail=f"work not found: {work_id}")
    return data


@router.get("/path")
def my_path(
    frm: str = Query(..., alias="from", description="起点作品 id"),
    to: str = Query(..., description="终点作品 id"),
    max_hops: int = Query(15, ge=1, le=30),
    user: dict = Depends(require_user),  # noqa: B008
) -> dict:
    result = _store(user).path(frm.strip(), to.strip(), max_hops)
    if result is None:
        raise HTTPException(status_code=404, detail="no mention path found")
    return result


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

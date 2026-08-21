"""数据管理 API(admin 角色):公共星云三张表的增删改查、软删除、审计、贡献审核、快照。

鉴权:admin 角色登录态(httpOnly Cookie),不再使用 ADMIN_TOKEN。
写路径复用 app/space_crud(owner=引导管理员);每次公共星云写入自动导出 CSV(git 审计)。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app import db_sqlite, sqlite_store
from app.auth import admin_user_id, bootstrap_admin, bootstrap_email, require_admin
from app.backups import create_snapshot, list_snapshots, restore_snapshot
from app.contributions import get_contribution, list_contributions, set_status
from app.data_store import export_csv_files
from app.db import invalidate_cache
from app.space_crud import (
    Kind,
    create_row,
    delete_row,
    restore_row,
    space_data,
    update_row,
)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _admin_context(user) -> dict:
    """HTTP 请求由 Depends(require_admin) 提供用户;直连调用(测试)回退到引导管理员。"""
    if isinstance(user, dict) and user.get("id"):
        return user
    admin = admin_user_id()
    if admin is None:
        raise HTTPException(status_code=401, detail="未登录")
    return {"id": admin, "email": bootstrap_email(), "role": "admin"}


def _review_contribution(item_id: str, status: str, actor: str) -> bool:
    """审核贡献并写审计(通过/驳回)。"""
    contrib = get_contribution(item_id)
    if contrib is None or not set_status(item_id, status):
        return False
    action = "approve" if status == "approved" else "reject"
    label = f"{contrib.get('source_work')} → {contrib.get('target_work')}"
    detail = f"审核「{label}」: {contrib.get('status')} → {status}"
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        db_sqlite.audit(
            conn, action, "contributions", item_id, detail,
            before={"status": contrib.get("status")},
            after={"status": status},
            actor=actor,
        )
    return True


@router.get("/data")
def get_data(
    include_deleted: bool = Query(True, description="是否包含软删除行(前端按需拉取)"),
    user: dict | None = Depends(require_admin),  # noqa: B008
) -> dict:
    admin = _admin_context(user)
    return space_data(admin["id"], include_deleted)


@router.get("/backups")
def admin_backups() -> dict:
    """可恢复的快照/备份列表(backups/ 与 data/versions/)。"""
    return {"items": list_snapshots()}


@router.post("/backups/create")
def admin_create_backup() -> dict:
    """为当前权威库创建一份快照(backups/echo-graph-<ts>.db)。"""
    try:
        return create_snapshot()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 文件/数据库错误转 500
        raise HTTPException(status_code=500, detail=f"创建快照失败:{exc}") from exc


@router.post("/backups/restore")
def admin_restore(body: dict) -> dict:
    """把指定快照恢复到权威库;恢复前自动安全备份当前库,成功后重新导出 CSV。"""
    name = str((body or {}).get("file") or "").strip()
    try:
        result = restore_snapshot(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"恢复失败:\n{exc}") from exc
    except Exception as exc:  # noqa: BLE001 - 文件/数据库错误转 500
        raise HTTPException(status_code=500, detail=f"恢复失败:{exc}") from exc
    bootstrap_admin()  # CSV 恢复后重新认领未归属数据到引导管理员
    export_csv_files()
    invalidate_cache()
    return result


@router.post("/{kind}")
def create(kind: Kind, row: dict, user: dict | None = Depends(require_admin)) -> dict:  # noqa: B008
    admin = _admin_context(user)
    return create_row(kind, row, admin["id"], admin["email"])


@router.put("/{kind}/{item_id}")
def update(
    kind: Kind, item_id: str, row: dict, user: dict | None = Depends(require_admin)  # noqa: B008
) -> dict:
    admin = _admin_context(user)
    return update_row(kind, item_id, row, admin["id"], admin["email"], adopt_unowned=True)


@router.delete("/{kind}/{item_id}")
def delete(kind: Kind, item_id: str, user: dict | None = Depends(require_admin)) -> dict:  # noqa: B008
    admin = _admin_context(user)
    return delete_row(kind, item_id, admin["id"], admin["email"], adopt_unowned=True)


@router.post("/{kind}/{item_id}/restore")
def restore(kind: Kind, item_id: str, user: dict | None = Depends(require_admin)) -> dict:  # noqa: B008
    admin = _admin_context(user)
    return restore_row(kind, item_id, admin["id"], admin["email"], adopt_unowned=True)


@router.get("/contributions")
def admin_contributions(
    status: str | None = Query(None, pattern="^(pending|approved|rejected)$"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """贡献收件箱列表(按审核状态过滤)。"""
    return list_contributions(status, limit, offset)


@router.post("/contributions/{item_id}/approve")
def approve_contribution(item_id: str, user: dict | None = Depends(require_admin)) -> dict:  # noqa: B008
    admin = _admin_context(user)
    if not _review_contribution(item_id, "approved", admin["email"]):
        raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
    return {"ok": True}


@router.post("/contributions/{item_id}/reject")
def reject_contribution(item_id: str, user: dict | None = Depends(require_admin)) -> dict:  # noqa: B008
    admin = _admin_context(user)
    if not _review_contribution(item_id, "rejected", admin["email"]):
        raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
    return {"ok": True}


@router.get("/audit")
def admin_audit(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, pattern="^(create|update|delete|restore|approve|reject)$"),
    kind: str | None = Query(None, pattern="^(authors|works|edges|contributions)$"),
) -> dict:
    """管理写操作审计记录。"""
    return sqlite_store.list_audit(limit, offset, action, kind)

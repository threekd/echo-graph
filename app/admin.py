"""数据管理 API(admin 角色):admin 自己星云三张表的增删改查、软删除、审计、快照。

鉴权:admin 角色登录态(httpOnly Cookie),不再使用 ADMIN_TOKEN。
写路径复用 app/space_crud(owner=当前 admin);公共星云/官方图谱概念已于
2026-08-28 移除,admin 星云与其他用户星云在数据语义上完全一致。
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app import data_store, db_sqlite, sqlite_store
from app.auth import (
    admin_user_id,
    bootstrap_admin,
    bootstrap_email,
    is_bootstrap_email,
    require_admin,
)
from app.backups import create_snapshot, list_snapshots, restore_snapshot
from app.db import invalidate_cache
from app.space_crud import (
    Kind,
    create_row,
    delete_row,
    permanent_delete_row,
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
    """把指定快照恢复到权威库;恢复前自动安全备份当前库,成功后清空读缓存。"""
    name = str((body or {}).get("file") or "").strip()
    try:
        result = restore_snapshot(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"恢复失败:\n{exc}") from exc
    except Exception as exc:  # noqa: BLE001 - 文件/数据库错误转 500
        raise HTTPException(status_code=500, detail=f"恢复失败:{exc}") from exc
    bootstrap_admin()  # 快照恢复后兜底为引导管理员补 admin 角色
    invalidate_cache()
    return result


@router.get("/export")
def admin_export(user: dict | None = Depends(require_admin)) -> Response:  # noqa: B008
    """导出 admin 自己星云三张表为 CSV zip(数据管理页「导出 CSV」按钮)。"""
    admin = _admin_context(user)
    buf = data_store.space_csv_zip(admin["id"])
    filename = f"echo-graph-export-{dt.datetime.now(dt.UTC).strftime('%Y%m%d-%H%M%S')}.zip"
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{kind}")
def create(kind: Kind, row: dict, user: dict | None = Depends(require_admin)) -> dict:  # noqa: B008
    admin = _admin_context(user)
    return create_row(kind, row, admin["id"], admin["email"])


@router.put("/{kind}/{item_id}")
def update(
    kind: Kind, item_id: str, row: dict, user: dict | None = Depends(require_admin)  # noqa: B008
) -> dict:
    admin = _admin_context(user)
    return update_row(kind, item_id, row, admin["id"], admin["email"])


@router.delete("/{kind}/{item_id}")
def delete(kind: Kind, item_id: str, user: dict | None = Depends(require_admin)) -> dict:  # noqa: B008
    admin = _admin_context(user)
    return delete_row(kind, item_id, admin["id"], admin["email"])


@router.post("/{kind}/{item_id}/restore")
def restore(kind: Kind, item_id: str, user: dict | None = Depends(require_admin)) -> dict:  # noqa: B008
    admin = _admin_context(user)
    return restore_row(kind, item_id, admin["id"], admin["email"])


@router.delete("/{kind}/{item_id}/permanent")
def permanent_delete(kind: Kind, item_id: str, user: dict | None = Depends(require_admin)) -> dict:  # noqa: B008
    """永久删除一条已软删除的行(物理删除,不可恢复),级联清理引用。"""
    admin = _admin_context(user)
    return permanent_delete_row(kind, item_id, admin["id"], admin["email"])


@router.post("/users/{user_id}/vip")
def admin_set_vip(
    user_id: str,
    body: dict,
    user: dict | None = Depends(require_admin),  # noqa: B008
) -> dict:
    """标记/取消用户 VIP(admin)。VIP 用户拥有 AI 书籍导入与本人 AI 草稿审核权限。"""
    vip = bool((body or {}).get("vip"))
    return admin_update_user(user_id, UserPatchBody(vip=vip), user)


class UserPatchBody(BaseModel):
    """用户管理可修改字段(至少一项;取值由 Literal 校验)。"""

    status: Literal["active", "disabled"] | None = None
    role: Literal["user", "admin"] | None = None
    space_visibility: Literal["public", "private"] | None = None
    vip: bool | None = None


def _safe_user_row(row: dict) -> dict:
    """审计记录排除密码哈希等敏感字段。"""
    return {k: v for k, v in row.items() if k != "password_hash"}


def _space_counts(conn) -> dict[str, dict[str, int]]:
    """每个 owner 的活跃星云数据量(作者/作品/涟漪)。"""
    counts: dict[str, dict[str, int]] = {}
    for table in ("authors", "works", "edges"):
        for r in conn.execute(
            f"SELECT owner_id AS uid, count(*) AS c FROM {table}"
            " WHERE deletedAt IS NULL GROUP BY owner_id"
        ):
            counts.setdefault(r["uid"], {})[table] = r["c"]
    return counts


@router.get("/users")
def admin_users(user: dict | None = Depends(require_admin)) -> dict:  # noqa: B008
    """用户列表(含角色/状态/星云可见性/VIP 与星云数据量,仅 admin)。"""
    _admin_context(user)
    with db_sqlite._db() as conn:
        rows = conn.execute(
            "SELECT id, email, username, nickname, bio, role, status,"
            " space_visibility, vip, createdAt, updatedAt"
            " FROM users ORDER BY createdAt DESC, id DESC"
        ).fetchall()
        counts = _space_counts(conn)
    return {
        "items": [
            {
                "id": r["id"],
                "email": r["email"],
                "username": r["username"],
                "nickname": r["nickname"],
                "bio": r["bio"],
                "role": r["role"],
                "status": r["status"],
                "space_visibility": r["space_visibility"],
                "vip": bool(r["vip"]),
                "createdAt": r["createdAt"],
                "updatedAt": r["updatedAt"],
                "counts": {
                    "authors": counts.get(r["id"], {}).get("authors", 0),
                    "works": counts.get(r["id"], {}).get("works", 0),
                    "edges": counts.get(r["id"], {}).get("edges", 0),
                },
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.patch("/users/{user_id}")
def admin_update_user(
    user_id: str,
    body: UserPatchBody,
    user: dict | None = Depends(require_admin),  # noqa: B008
) -> dict:
    """修改用户状态/角色/星云可见性/VIP(至少一项)。

    保护规则:
    - 不能修改自己的 role/status(防止最后一个管理员把自己锁出系统);
    - 引导管理员不能被禁用或降级;
    - 系统至少保留一名可用管理员(防御性兜底)。
    """
    admin = _admin_context(user)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return {"ok": True, "user_id": user_id, "changed": []}
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        row = dict(row)
        if user_id == admin["id"] and (updates.get("status") or updates.get("role")):
            raise HTTPException(status_code=400, detail="不能修改自己的角色或状态")
        if is_bootstrap_email(row["email"]) and (
            updates.get("status") == "disabled" or updates.get("role") == "user"
        ):
            raise HTTPException(status_code=400, detail="不能禁用或降级引导管理员")
        if row["role"] == "admin" and (
            updates.get("role") == "user" or updates.get("status") == "disabled"
        ):
            active_admins = conn.execute(
                "SELECT count(*) AS c FROM users"
                " WHERE role = 'admin' AND status = 'active'"
            ).fetchone()["c"]
            if active_admins <= 1:
                raise HTTPException(status_code=400, detail="系统至少需要保留一名可用管理员")
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE users SET {sets}, updatedAt = ? WHERE id = ?",
            [*updates.values(), db_sqlite.now_iso(), user_id],
        )
        label = row.get("username") or row.get("email") or user_id
        detail = (
            f"用户管理「{label}」:"
            + "；".join(f"{k}: {row.get(k)} → {v}" for k, v in updates.items())
        )
        db_sqlite.audit(
            conn, "update", "users", user_id, detail,
            before=_safe_user_row(row),
            after=_safe_user_row({**row, **updates}),
            actor=admin["email"],
        )
    return {"ok": True, "user_id": user_id, "changed": list(updates)}


@router.get("/audit")
def admin_audit(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = Query(
        None,
        pattern="^(create|update|delete|restore|approve|reject|"
        "llm_ingest|llm_publish|llm_reuse|llm_reject|llm_reopen)$",
    ),
    kind: str | None = Query(None, pattern="^(authors|works|edges|users)$"),
) -> dict:
    """管理写操作审计记录。"""
    return sqlite_store.list_audit(limit, offset, action, kind)

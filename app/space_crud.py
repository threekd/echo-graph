"""空间数据 CRUD:公共星云(admin)与个人空间(me)共用的行级写路径。

隔离规则:所有写操作必须带 owner_id。admin 空间 = admin 认领的数据
(owner_id 为空的历史行在 admin 写入时自动认领);个人空间 = 精确匹配 owner_id。
行不属于该空间一律视为不存在(404),不暴露存在性,防越权探测。

CSV 导出只针对公共星云(admin 空间),用户私有数据不进 git 审计产物。
"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException

from app import db_sqlite, sqlite_store
from app.auth import admin_user_id
from app.data_models import AuthorRow, EchoRow, WorkRow, find_duplicates
from app.data_store import clean_row, export_csv_files
from app.db import invalidate_cache

Kind = Literal["authors", "works", "edges"]
KIND_TABLE = sqlite_store.KIND_TABLE  # 表名映射单一来源:sqlite_store

AUDIT_FIELDS: dict[Kind, list[str]] = {
    "authors": [
        "originalName", "Name_CN", "Name_EN", "nationality",
        "birthYear", "deathYear", "note", "reviewStatus", "visibility",
    ],
    "works": [
        "language", "originalTitle", "Title_CN", "Title_EN", "Title_Other",
        "publicationYear", "genre", "note", "reviewStatus", "visibility",
        "recommendation", "review",
    ],
    "edges": [
        "source_work_id", "target_work_id", "evidence",
        "evidenceSource", "note", "reviewStatus",
    ],
}


_now = db_sqlite.now_iso
_new_uuid = db_sqlite.new_uuid


def _author_id_list(value) -> list[str]:
    """把 works.author_id(逗号分隔,可能带空格)拆成去空后的 id 列表。"""
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def _work_title(conn, work_id: str | None, owner_id: str) -> str:
    row = conn.execute(
        "SELECT Title_CN FROM works WHERE id = ? AND owner_id = ?",
        (work_id, owner_id),
    ).fetchone()
    return row["Title_CN"] if row else str(work_id or "")


def _audit_label(conn, kind: Kind, row: dict, owner_id: str) -> str:
    """审计里的对象名称:作者中文名 / 作品中文名 / 涟漪 A → B。"""
    if kind == "authors":
        return str(row.get("Name_CN") or row.get("originalName") or row.get("id") or "")
    if kind == "works":
        return str(row.get("Title_CN") or row.get("originalTitle") or row.get("id") or "")
    return (
        f"{_work_title(conn, row.get('source_work_id'), owner_id)} → "
        f"{_work_title(conn, row.get('target_work_id'), owner_id)}"
    )


def _fmt_audit(value) -> str:
    return "(空)" if value is None or value == "" else str(value)


def _audit_changes(kind: Kind, before: dict, after: dict) -> str:
    """变更字段摘要:字段: 旧值 → 新值(忽略 id/时间戳/软删除/作者关联)。"""
    parts = []
    for field in AUDIT_FIELDS[kind]:
        b, a = before.get(field), after.get(field)
        if b != a:
            parts.append(f"{field}: {_fmt_audit(b)} → {_fmt_audit(a)}")
    return "；".join(parts)


def _resolve_row(
    conn, kind: Kind, row_id: str, owner_id: str, adopt_unowned: bool = False
) -> dict | None:
    """按空间取行:精确 owner 匹配;admin 空间额外接纳未认领历史行(认领后归 admin)。"""
    row = sqlite_store.get_row(conn, kind, row_id)
    if row is None:
        return None
    if row.get("owner_id") == owner_id:
        return row
    if adopt_unowned and owner_id is not None and row.get("owner_id") is None:
        conn.execute(
            f"UPDATE {KIND_TABLE[kind]} SET owner_id = ? WHERE id = ?",
            (owner_id, row_id),
        )
        row["owner_id"] = owner_id
        return row
    return None


def validate_row(conn, kind: str, row: dict, exclude_id: str | None = None, owner_id: str | None = None) -> list[str]:
    """行级校验(Pydantic)+ SQL 交叉引用(全部限定在同一空间内)。返回错误列表。"""
    errors: list[str] = []
    row_id = row.get("id")
    if row_id and sqlite_store.row_exists(conn, kind, row_id, owner_id) and row_id != exclude_id:
        errors.append(f"id 已存在:{row_id}")
    try:
        if kind == "authors":
            AuthorRow.model_validate(row)
        elif kind == "works":
            WorkRow.model_validate(row)
            for aid in _author_id_list(row.get("author_id")):
                if not sqlite_store.row_exists(conn, "authors", aid, owner_id):
                    errors.append(f"作者 id {aid} 未在作者表中找到")
        else:
            EchoRow.model_validate(row)
            if not (row.get("evidenceSource") or "").strip():
                errors.append("出处不能为空")
            for wid in (row.get("source_work_id"), row.get("target_work_id")):
                if not sqlite_store.row_exists(conn, "works", wid, owner_id):
                    errors.append(f"作品 {wid} 未找到")
            pair = (row.get("source_work_id"), row.get("target_work_id"))
            if all(pair) and pair[0] != pair[1]:
                dup = conn.execute(
                    "SELECT 1 FROM edges WHERE source_work_id = ? AND target_work_id = ?"
                    " AND id != ? AND owner_id = ?",
                    (pair[0], pair[1], exclude_id or "", owner_id),
                ).fetchone()
                if dup:
                    titles = {
                        r["id"]: r["Title_CN"]
                        for r in conn.execute(
                            "SELECT id, Title_CN FROM works WHERE id IN (?, ?) AND owner_id = ?",
                            (pair[0], pair[1], owner_id),
                        )
                    }
                    errors.append(
                        f"涟漪关系已存在:{titles.get(pair[0], pair[0])} -> {titles.get(pair[1], pair[1])}"
                    )
    except Exception as exc:  # noqa: BLE001 - Pydantic 校验错误转文案
        errors.append(str(exc))
    return errors


def _after_write(owner_id: str) -> None:
    """写入后的收尾:任何空间都失效读缓存;只有公共星云(admin 空间)刷新 CSV 导出。"""
    invalidate_cache()
    if owner_id == admin_user_id():
        export_csv_files()


def space_data(owner_id: str, include_deleted: bool = True) -> dict:
    """管理表格数据:某空间的行级数据 + 重复提醒 + 计数(与 CSV 同形状)。"""
    a, w, e = sqlite_store.load_rows(owner_id=owner_id)
    if not include_deleted:
        a = [r for r in a if not r.get("deletedAt")]
        w = [r for r in w if not r.get("deletedAt")]
        e = [r for r in e if not r.get("deletedAt")]
    return {
        "authors": a,
        "works": w,
        "edges": e,
        "warnings": find_duplicates(a, w, e),
        "counts": {
            "authors": len(a),
            "works": len(w),
            "edges": len(e),
            "deleted": {
                "authors": sum(1 for r in a if r.get("deletedAt")),
                "works": sum(1 for r in w if r.get("deletedAt")),
                "edges": sum(1 for r in e if r.get("deletedAt")),
            },
        },
    }


def create_row(kind: Kind, row: dict, owner_id: str, actor: str, adopt_unowned: bool = False) -> dict:
    row = clean_row(row)  # 落盘前基础清洗:去首尾空白、空串归一 None
    if not row.get("id"):
        row["id"] = _new_uuid()
    is_admin_space = owner_id == admin_user_id()
    # 用户输入即确认:普通用户空间默认 reviewed;公共星云(admin)保持策展 draft
    if not row.get("reviewStatus"):
        row["reviewStatus"] = "draft" if is_admin_space else "reviewed"
    visibility: str | None = None
    if kind in ("authors", "works"):
        visibility = "public" if is_admin_space else (row.get("visibility") or "public")
        if visibility not in ("public", "private"):
            raise HTTPException(status_code=400, detail="可见性取值仅支持 public / private")
        row["visibility"] = visibility
    extra: dict | None = None
    if kind == "works":
        recommendation = row.get("recommendation")
        if recommendation is not None and recommendation not in ("recommend", "not_recommend"):
            raise HTTPException(status_code=400, detail="评分取值仅支持 recommend / not_recommend")
        review = row.get("review")
        if review is not None and len(str(review)) > 2000:
            raise HTTPException(status_code=400, detail="评价过长(最多 2000 字)")
        row["recommendation"] = recommendation
        row["review"] = review
        extra = {"recommendation": recommendation, "review": review}
    now = _now()
    row.setdefault("createdAt", now)
    row["updatedAt"] = now
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        errors = validate_row(conn, kind, row, owner_id=owner_id)
        if errors:
            raise HTTPException(status_code=400, detail="校验失败:\n- " + "\n".join(errors))
        sqlite_store.insert_row(
            conn, kind, row, owner_id=owner_id, visibility=visibility, extra=extra,
        )
        if kind == "works":
            sqlite_store.set_work_authors(conn, row["id"], _author_id_list(row.get("author_id")))
        label = _audit_label(conn, kind, row, owner_id)
        db_sqlite.audit(
            conn, "create", kind, row.get("id"), f"新增「{label}」", after=row, actor=actor,
        )
    _after_write(owner_id)
    return {"ok": True, "row": row}


def update_row(
    kind: Kind, item_id: str, row: dict, owner_id: str, actor: str, adopt_unowned: bool = False
) -> dict:
    row = clean_row(row)
    now = _now()
    is_admin_space = owner_id == admin_user_id()
    extra: dict | None = None
    if kind == "works":
        recommendation = row.get("recommendation")
        if recommendation is not None and recommendation not in ("recommend", "not_recommend"):
            raise HTTPException(status_code=400, detail="评分取值仅支持 recommend / not_recommend")
        review = row.get("review")
        if review is not None and len(str(review)) > 2000:
            raise HTTPException(status_code=400, detail="评价过长(最多 2000 字)")
        row["recommendation"] = recommendation
        row["review"] = review
        # 用户表单总会携带这两个字段:空值代表清除(显式写 NULL)
        extra = {"recommendation": recommendation, "review": review}
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        existing = _resolve_row(conn, kind, item_id, owner_id, adopt_unowned)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
        if not is_admin_space:
            row["reviewStatus"] = "reviewed"  # 用户输入即确认,不允许改回草稿
        visibility: str | None = None
        if kind in ("authors", "works"):
            if is_admin_space:
                visibility = "public"  # 公共星云恒为公开
            else:
                visibility = row.get("visibility") or existing.get("visibility") or "public"
                if visibility not in ("public", "private"):
                    raise HTTPException(status_code=400, detail="可见性取值仅支持 public / private")
            row["visibility"] = visibility
        expected_ts = row.get("updatedAt") or existing.get("updatedAt")
        row["id"] = item_id
        row["createdAt"] = row.get("createdAt") or existing.get("createdAt") or now
        row["updatedAt"] = now
        errors = validate_row(conn, kind, row, exclude_id=item_id, owner_id=owner_id)
        if errors:
            raise HTTPException(status_code=400, detail="校验失败:\n- " + "\n".join(errors))
        status = sqlite_store.update_row(
            conn, kind, item_id, row, expected_updated_at=expected_ts,
            owner_id=owner_id, visibility=visibility, extra=extra,
        )
        if status == -1:
            raise HTTPException(status_code=409, detail="数据已被其他人修改,请刷新后重试")
        if status == 0:
            raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
        if kind == "works":
            sqlite_store.set_work_authors(conn, item_id, _author_id_list(row.get("author_id")))
        label = _audit_label(conn, kind, row, owner_id)
        changes = _audit_changes(kind, existing, row)
        detail = f"修改「{label}」" + (f": {changes}" if changes else "")
        db_sqlite.audit(
            conn, "update", kind, item_id, detail, before=existing, after=row, actor=actor,
        )
    _after_write(owner_id)
    return {"ok": True, "row": row}


def delete_row(kind: Kind, item_id: str, owner_id: str, actor: str, adopt_unowned: bool = False) -> dict:
    """软删除。作品连带其涟漪边;作者连带其名下作品与这些作品的涟漪边。"""
    now = _now()
    cascade: dict[str, list[str]] = {"works": [], "edges": []}
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        row = _resolve_row(conn, kind, item_id, owner_id, adopt_unowned)
        if row is None:
            raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
        if kind == "works":
            edge_ids = sqlite_store.cascade_work_edge_ids(conn, item_id, owner_id)
            sqlite_store.mark_deleted(conn, kind, [item_id], now, owner_id)
            sqlite_store.mark_deleted(conn, "edges", edge_ids, now, owner_id)
            cascade["edges"] = edge_ids
        elif kind == "authors":
            work_ids = sqlite_store.cascade_author_work_ids(conn, item_id, owner_id)
            edge_ids = sqlite_store.cascade_author_edge_ids(conn, item_id, owner_id)
            sqlite_store.mark_deleted(conn, kind, [item_id], now, owner_id)
            sqlite_store.mark_deleted(conn, "works", work_ids, now, owner_id)
            sqlite_store.mark_deleted(conn, "edges", edge_ids, now, owner_id)
            cascade = {"works": work_ids, "edges": edge_ids}
        else:
            sqlite_store.mark_deleted(conn, kind, [item_id], now, owner_id)
        label = _audit_label(conn, kind, row, owner_id)
        db_sqlite.audit(
            conn, "delete", kind, item_id,
            f"删除「{label}」"
            + (
                f"(连带 works={len(cascade['works'])} edges={len(cascade['edges'])})"
                if any(cascade.values()) else ""
            ),
            before=row,
            after={**row, "deletedAt": now},
            actor=actor,
        )
    _after_write(owner_id)
    return {"ok": True, "deletedAt": now, "cascade": cascade}


def restore_row(
    kind: Kind, item_id: str, owner_id: str, actor: str, adopt_unowned: bool = False
) -> dict:
    """恢复软删除。同一删除动作级联删除的作品/涟漪(相同 deletedAt)一并恢复。"""
    cascade: dict[str, list[str]] = {"works": [], "edges": []}
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        row = _resolve_row(conn, kind, item_id, owner_id, adopt_unowned)
        if row is None:
            raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
        ts = row.get("deletedAt")
        if not ts:
            return {"ok": True, "cascade": cascade}
        now = _now()
        if kind == "works":
            edge_ids = sqlite_store.restore_work_edge_ids(conn, item_id, ts, owner_id)
            sqlite_store.restore_by_ts(conn, kind, [item_id], ts, now, owner_id)
            sqlite_store.restore_by_ts(conn, "edges", edge_ids, ts, now, owner_id)
            cascade["edges"] = edge_ids
        elif kind == "authors":
            work_ids = sqlite_store.restore_author_work_ids(conn, item_id, ts, owner_id)
            edge_ids = sqlite_store.restore_author_edge_ids(conn, item_id, ts, owner_id)
            sqlite_store.restore_by_ts(conn, kind, [item_id], ts, now, owner_id)
            sqlite_store.restore_by_ts(conn, "works", work_ids, ts, now, owner_id)
            sqlite_store.restore_by_ts(conn, "edges", edge_ids, ts, now, owner_id)
            cascade = {"works": work_ids, "edges": edge_ids}
        else:
            work_ids = sqlite_store.restore_edge_work_ids(
                conn, row.get("source_work_id"), row.get("target_work_id"), ts, owner_id
            )
            sqlite_store.restore_by_ts(conn, kind, [item_id], ts, now, owner_id)
            sqlite_store.restore_by_ts(conn, "works", work_ids, ts, now, owner_id)
            cascade["works"] = work_ids
        db_sqlite.audit(
            conn, "restore", kind, item_id,
            f"恢复「{_audit_label(conn, kind, row, owner_id)}」"
            + (
                f"(连带 works={len(cascade['works'])} edges={len(cascade['edges'])})"
                if any(cascade.values()) else ""
            ),
            before=row,
            after={**row, "deletedAt": None},
            actor=actor,
        )
    _after_write(owner_id)
    return {"ok": True, "cascade": cascade}

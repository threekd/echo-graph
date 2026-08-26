"""空间数据 CRUD:admin 星云(官方图谱)与个人空间(me)共用的行级写路径。

隔离规则:所有写操作必须带 owner_id,精确匹配 owner_id;行不属于该空间一律
视为不存在(404),不暴露存在性,防越权探测。公共星云/未认领行概念已于
2026-08-27 移除,不再有 adopt_unowned 逻辑。
"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException

from app import db_sqlite, sqlite_store
from app.auth import admin_user_id
from app.data_models import AuthorRow, EchoRow, WorkRow, find_duplicates
from app.data_store import clean_row
from app.db import invalidate_cache

Kind = Literal["authors", "works", "edges"]
KIND_TABLE = sqlite_store.KIND_TABLE  # 表名映射单一来源:sqlite_store

AUDIT_FIELDS: dict[Kind, list[str]] = {
    "authors": [
        "originalName", "Name_CN", "Name_EN", "nationality",
        "birthYear", "deathYear", "note", "reviewStatus",
    ],
    "works": [
        "language", "originalTitle", "Title_CN", "Title_EN", "Title_Other",
        "publicationYear", "genre", "note", "reviewStatus",
        "recommendation", "review",
    ],
    "edges": [
        "source_work_id", "target_work_id", "evidence",
        "evidenceSource", "note", "reviewStatus",
    ],
}


_now = db_sqlite.now_iso
_new_uuid = db_sqlite.new_uuid


CREATED_BY_VALUES = ("curated", "user", "llm")


def _created_by_for(row: dict, owner_id: str) -> str:
    """溯源值:显式传 created_by 则校验后采用;缺省按 owner 推导(admin=策展,其他=用户)。"""
    value = str(row.get("created_by") or "").strip()
    if value:
        if value not in CREATED_BY_VALUES:
            raise HTTPException(status_code=400, detail="created_by 取值仅支持 curated / user / llm")
        return value
    return "curated" if owner_id == admin_user_id() else "user"


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


def _resolve_row(conn, kind: Kind, row_id: str, owner_id: str) -> dict | None:
    """按空间取行:精确 owner 匹配,不属于该空间视为不存在。"""
    row = sqlite_store.get_row(conn, kind, row_id)
    if row is None:
        return None
    if row.get("owner_id") == owner_id:
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
                if not sqlite_store.active_row_exists(conn, "authors", aid, owner_id):
                    errors.append(f"作者 id {aid} 未在作者表中找到")
        else:
            EchoRow.model_validate(row)
            if not (row.get("evidenceSource") or "").strip():
                errors.append("出处不能为空")
            for wid in (row.get("source_work_id"), row.get("target_work_id")):
                if not sqlite_store.active_row_exists(conn, "works", wid, owner_id):
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


def after_write(owner_id: str) -> None:
    """写入后的收尾:失效读缓存,保证编辑保存后即时可读。

    CSV 自动导出层已于 2026-08-27 移除(改为整库备份 + 用户手动导出,见 docs/to-do.md)。
    """
    invalidate_cache()


def space_data(owner_id: str, include_deleted: bool = True) -> dict:
    """管理表格数据:某空间的行级数据 + 重复提醒 + 计数(与 CSV 同形状)。

    计数(含 deleted)基于全量行统计,不随 include_deleted 过滤变化:
    include_deleted=False 时只裁剪返回列表,deleted 计数仍反映真实软删除行数。
    AI 草稿(created_by='llm' 未发布/保留映射)不属于策展/个人空间视图,一律剔除
    (草稿在「AI 草稿」页按 owner_id=上传者 单独展示)。
    """
    all_a, all_w, all_e = sqlite_store.load_rows(owner_id=owner_id)

    def _not_ai_draft(r: dict) -> bool:
        return not (
            r.get("created_by") == "llm"
            and (r.get("reviewStatus") != "reviewed" or r.get("published_to_id"))
        )

    all_a = [r for r in all_a if _not_ai_draft(r)]
    all_w = [r for r in all_w if _not_ai_draft(r)]
    all_e = [r for r in all_e if _not_ai_draft(r)]
    deleted = {
        "authors": sum(1 for r in all_a if r.get("deletedAt")),
        "works": sum(1 for r in all_w if r.get("deletedAt")),
        "edges": sum(1 for r in all_e if r.get("deletedAt")),
    }
    a, w, e = all_a, all_w, all_e
    if not include_deleted:
        a = [r for r in all_a if not r.get("deletedAt")]
        w = [r for r in all_w if not r.get("deletedAt")]
        e = [r for r in all_e if not r.get("deletedAt")]
    return {
        "authors": a,
        "works": w,
        "edges": e,
        "warnings": find_duplicates(a, w, e),
        "counts": {
            "authors": len(a),
            "works": len(w),
            "edges": len(e),
            "deleted": deleted,
        },
    }


def create_row(kind: Kind, row: dict, owner_id: str, actor: str) -> dict:
    row = clean_row(row)  # 落盘前基础清洗:去首尾空白、空串归一 None
    if not row.get("id"):
        row["id"] = _new_uuid()
    # 溯源列:显式传 created_by 则校验后采用;缺省按 owner 推导(admin=策展,其他=用户)
    row["created_by"] = _created_by_for(row, owner_id)
    # 输入即确认:created_by=user/curated 默认 reviewed(用户手动新增即确认);
    # created_by=llm 默认 draft(AI 提取进入草稿态);显式传 reviewStatus 仍可覆盖
    if not row.get("reviewStatus"):
        row["reviewStatus"] = "draft" if row["created_by"] == "llm" else "reviewed"
    extra: dict = {"created_by": row["created_by"]}
    if kind == "works":
        reading_status = row.get("readingStatus")
        if reading_status is not None and reading_status not in ("read", "reading", "unread"):
            raise HTTPException(status_code=400, detail="阅读状态取值仅支持 read / reading / unread")
        recommendation = row.get("recommendation")
        if recommendation is not None and recommendation not in ("recommend", "not_recommend"):
            raise HTTPException(status_code=400, detail="评分取值仅支持 recommend / not_recommend")
        review = row.get("review")
        if review is not None and len(str(review)) > 2000:
            raise HTTPException(status_code=400, detail="评价过长(最多 2000 字)")
        row["readingStatus"] = reading_status
        row["recommendation"] = recommendation
        row["review"] = review
        extra.update({
            "readingStatus": reading_status,
            "recommendation": recommendation,
            "review": review,
        })
    now = _now()
    row.setdefault("createdAt", now)
    row["updatedAt"] = now
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        errors = validate_row(conn, kind, row, owner_id=owner_id)
        if errors:
            raise HTTPException(status_code=400, detail="校验失败:\n- " + "\n".join(errors))
        # 行级校验只按 owner 判定 id 冲突;跨空间/未认领历史行需在此兜底,
        # 避免 INSERT 撞主键抛 IntegrityError 变成 500
        if sqlite_store.row_exists(conn, kind, row["id"]) \
                and not sqlite_store.row_exists(conn, kind, row["id"], owner_id):
            raise HTTPException(status_code=400, detail=f"校验失败:\n- id 已被占用:{row['id']}")
        sqlite_store.insert_row(
            conn, kind, row, owner_id=owner_id, extra=extra,
        )
        if kind == "works":
            sqlite_store.set_work_authors(conn, row["id"], _author_id_list(row.get("author_id")))
        label = _audit_label(conn, kind, row, owner_id)
        db_sqlite.audit(
            conn, "create", kind, row.get("id"), f"新增「{label}」", after=row, actor=actor,
        )
    after_write(owner_id)
    return {"ok": True, "row": row}


def update_row(
    kind: Kind, item_id: str, row: dict, owner_id: str, actor: str
) -> dict:
    row = clean_row(row)
    row.pop("created_by", None)  # 溯源列创建后不可修改(与 createdAt 同策略)
    now = _now()
    is_admin_space = owner_id == admin_user_id()
    extra: dict | None = None
    if kind == "works":
        reading_status = row.get("readingStatus")
        if reading_status is not None and reading_status not in ("read", "reading", "unread"):
            raise HTTPException(status_code=400, detail="阅读状态取值仅支持 read / reading / unread")
        recommendation = row.get("recommendation")
        if recommendation is not None and recommendation not in ("recommend", "not_recommend"):
            raise HTTPException(status_code=400, detail="评分取值仅支持 recommend / not_recommend")
        review = row.get("review")
        if review is not None and len(str(review)) > 2000:
            raise HTTPException(status_code=400, detail="评价过长(最多 2000 字)")
        row["readingStatus"] = reading_status
        row["recommendation"] = recommendation
        row["review"] = review
        # 用户表单总会携带这两个字段:空值代表清除(显式写 NULL)
        extra = {"readingStatus": reading_status, "recommendation": recommendation, "review": review}
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        existing = _resolve_row(conn, kind, item_id, owner_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
        row["created_by"] = existing.get("created_by")  # 返回行携带库内真实溯源值
        if not is_admin_space:
            row["reviewStatus"] = "reviewed"  # 用户输入即确认,不允许改回草稿
        expected_ts = row.get("updatedAt") or existing.get("updatedAt")
        row["id"] = item_id
        row["createdAt"] = row.get("createdAt") or existing.get("createdAt") or now
        row["updatedAt"] = now
        errors = validate_row(conn, kind, row, exclude_id=item_id, owner_id=owner_id)
        if errors:
            raise HTTPException(status_code=400, detail="校验失败:\n- " + "\n".join(errors))
        status = sqlite_store.update_row(
            conn, kind, item_id, row, expected_updated_at=expected_ts,
            owner_id=owner_id, extra=extra,
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
    after_write(owner_id)
    return {"ok": True, "row": row}


def delete_row(kind: Kind, item_id: str, owner_id: str, actor: str) -> dict:
    """软删除。作品连带其涟漪边;作者连带其名下作品与这些作品的涟漪边。"""
    now = _now()
    cascade: dict[str, list[str]] = {"works": [], "edges": []}
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        row = _resolve_row(conn, kind, item_id, owner_id)
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
    after_write(owner_id)
    return {"ok": True, "deletedAt": now, "cascade": cascade}


def restore_row(
    kind: Kind, item_id: str, owner_id: str, actor: str
) -> dict:
    """恢复软删除。同一删除动作级联删除的作品/涟漪(相同 deletedAt)一并恢复。"""
    cascade: dict[str, list[str]] = {"works": [], "edges": []}
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        row = _resolve_row(conn, kind, item_id, owner_id)
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
    after_write(owner_id)
    return {"ok": True, "cascade": cascade}

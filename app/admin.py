"""数据管理 API:三张表的增删改查、软删除、一键导入 Neo4j、导出。

存储层:data/real/*.csv(UTF-8 BOM),保存前自动版本快照。
"""

from __future__ import annotations

import datetime as dt
import hmac
import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import db_sqlite, sqlite_store
from app.contributions import list_contributions, set_status
from app.data_models import AuthorRow, EchoRow, WorkRow, find_duplicates
from app.data_store import (
    clean_row,
    export_csv_files,
)
from app.db import get_store
from app.importer import run_import

_admin_bearer = HTTPBearer(auto_error=False)


def require_admin_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_admin_bearer),  # noqa: B008
) -> None:
    """管理接口鉴权:需在 .env 配置 ADMIN_TOKEN,请求头带 Authorization: Bearer <token>。"""
    token = os.getenv("ADMIN_TOKEN", "")
    if not token or token.strip() == "change-me-to-a-long-random-token" or len(token) < 16:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_TOKEN 未配置或仍为示例值,管理接口已禁用",
        )
    if credentials is None or not hmac.compare_digest(
        credentials.credentials.encode("utf-8"), token.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401,
            detail="无效的管理令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )


router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)

Kind = Literal["authors", "works", "edges"]


def _warnings(a: list[dict], w: list[dict], e: list[dict]) -> dict[str, list[str]]:
    return find_duplicates(a, w, e)


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _new_uuid() -> str:
    try:
        return str(uuid.uuid7())  # Python 3.14: 时间有序 UUID v7
    except AttributeError:
        return str(uuid.uuid4())


def _author_id_list(value) -> list[str]:
    """把 works.author_id(逗号分隔,可能带空格)拆成去空后的 id 列表。"""
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def validate_row(conn, kind: str, row: dict, exclude_id: str | None = None) -> list[str]:
    """行级校验(P3b):目标行字段(Pydantic)+ SQL 交叉引用/唯一性。返回错误列表。"""
    errors: list[str] = []
    row_id = row.get("id")
    if row_id and sqlite_store.row_exists(conn, kind, row_id) and row_id != exclude_id:
        errors.append(f"id 已存在:{row_id}")
    try:
        if kind == "authors":
            AuthorRow.model_validate(row)
        elif kind == "works":
            WorkRow.model_validate(row)
            for aid in _author_id_list(row.get("author_id")):
                if not sqlite_store.row_exists(conn, "authors", aid):
                    errors.append(f"作者 id {aid} 未在作者表中找到")
        else:
            EchoRow.model_validate(row)
            if not (row.get("evidenceSource") or "").strip():
                errors.append("出处不能为空")
            for wid in (row.get("source_work_id"), row.get("target_work_id")):
                if not sqlite_store.row_exists(conn, "works", wid):
                    errors.append(f"作品 {wid} 未找到")
            pair = (row.get("source_work_id"), row.get("target_work_id"))
            if all(pair) and pair[0] != pair[1]:
                dup = conn.execute(
                    "SELECT 1 FROM edges WHERE source_work_id = ? AND target_work_id = ? AND id != ?",
                    (pair[0], pair[1], exclude_id or ""),
                ).fetchone()
                if dup:
                    titles = {
                        r["id"]: r["Title_CN"]
                        for r in conn.execute(
                            "SELECT id, Title_CN FROM works WHERE id IN (?, ?)", pair
                        )
                    }
                    errors.append(
                        f"涟漪关系已存在:{titles.get(pair[0], pair[0])} -> {titles.get(pair[1], pair[1])}"
                    )
    except Exception as exc:  # noqa: BLE001 - Pydantic 校验错误转文案
        errors.append(str(exc))
    return errors


def _source_sync_payload() -> dict:
    """当前权威来源(SQLite)活跃数据的规范化载荷,用于与 Neo4j 比对。"""
    a, w, e = sqlite_store.load_rows()
    return sqlite_store.canonical_payload(a, w, e)


def _neo4j_counts() -> dict | None:
    """Neo4j 活跃计数(单次查询);不可用时返回 None。"""
    store = get_store()
    primary = getattr(store, "primary", None)
    if primary is None or getattr(primary, "name", None) != "neo4j":
        return None
    try:
        row = primary._query(
            "MATCH (a:Author) WITH count(a) AS author_count "
            "MATCH (w:Work) WITH author_count, count(w) AS work_count "
            "MATCH ()-[r:ECHO]->() RETURN author_count, work_count, count(r) AS echo_count"
        )[0]
    except Exception:  # noqa: BLE001 - Neo4j 不可用时视为无法比对
        return None
    return {"authors": row["author_count"], "works": row["work_count"], "echoes": row["echo_count"]}


def _neo4j_sync_payload() -> dict | None:
    """Neo4j 主存储的规范化载荷;不可用(JSON 兜底/连接失败)时返回 None。

    合并查询:作者/作品与归属关系用一次查询取回(labels 区分类型),
    ECHO 关系一次取回,共 2 次网络往返。
    """
    store = get_store()
    primary = getattr(store, "primary", None)
    if primary is None or getattr(primary, "name", None) != "neo4j":
        return None
    try:
        q = primary._query
        node_rows = q(
            "MATCH (n) WHERE n:Author OR n:Work "
            "OPTIONAL MATCH (n)-[:AUTHORED_BY]->(a:Author) "
            "RETURN labels(n) AS ls, properties(n) AS p, collect(DISTINCT a.id) AS author_ids"
        )
        echo_rows = q("MATCH (s:Work)-[r:ECHO]->(t:Work) RETURN s.id AS s, t.id AS t, properties(r) AS p")
    except Exception:  # noqa: BLE001 - Neo4j 不可用时视为无法比对
        return None

    authors = []
    works = []
    for r in node_rows:
        p = r["p"]
        ls = r.get("ls") or []
        if "Author" in ls:
            authors.append({
                "id": sqlite_store.sync_norm(p.get("id")),
                "originalName": sqlite_store.sync_norm(p.get("originalName")),
                "Name_CN": sqlite_store.sync_norm(p.get("Name_CN")),
                "Name_EN": sqlite_store.sync_norm(p.get("Name_EN")),
                "nationality": sqlite_store.sync_norm((p.get("nationality") or "").upper()),
                "birthYear": sqlite_store.sync_norm(p.get("birthYear")),
                "deathYear": sqlite_store.sync_norm(p.get("deathYear")),
                "reviewStatus": sqlite_store.sync_norm(p.get("reviewStatus") or "draft"),
            })
        elif "Work" in ls:
            aids = [x for x in (r.get("author_ids") or []) if x]
            works.append({
                "id": sqlite_store.sync_norm(p.get("id")),
                "language": sqlite_store.sync_norm((p.get("language") or "").lower()),
                "originalTitle": sqlite_store.sync_norm(p.get("originalTitle")),
                "Title_CN": sqlite_store.sync_norm(p.get("Title_CN")),
                "Title_EN": sqlite_store.sync_norm(p.get("Title_EN")),
                "Title_Other": sqlite_store.sync_norm(p.get("Title_Other")),
                "publicationYear": sqlite_store.sync_norm(p.get("publicationYear")),
                "creationYear": sqlite_store.sync_norm(p.get("creationYear")),
                "genre": sqlite_store.sync_norm(p.get("genre")),
                "reviewStatus": sqlite_store.sync_norm(p.get("reviewStatus") or "draft"),
                "author_ids": sorted(sqlite_store.sync_norm(x) for x in aids),
            })
    echoes = []
    for r in echo_rows:
        p = r["p"]
        echoes.append({
            "id": sqlite_store.sync_norm(p.get("id")),
            "source": sqlite_store.sync_norm(r["s"]),
            "target": sqlite_store.sync_norm(r["t"]),
            "evidence": sqlite_store.sync_norm(p.get("evidence")),
            "evidenceSource": sqlite_store.sync_norm(p.get("evidenceSource")),
            "note": sqlite_store.sync_norm(p.get("note")),
            "reviewStatus": sqlite_store.sync_norm(p.get("reviewStatus") or "draft"),
        })
    return {
        "authors": sorted(authors, key=lambda x: x["id"]),
        "works": sorted(works, key=lambda x: x["id"]),
        "echoes": sorted(echoes, key=lambda x: x["id"]),
    }


@router.get("/data")
def get_data(
    include_deleted: bool = Query(True, description="是否包含软删除行(前端按需拉取)"),
) -> dict:
    a, w, e = sqlite_store.load_rows()
    if not include_deleted:
        a = [r for r in a if not r.get("deletedAt")]
        w = [r for r in w if not r.get("deletedAt")]
        e = [r for r in e if not r.get("deletedAt")]
    return {
        "authors": a,
        "works": w,
        "edges": e,
        "warnings": _warnings(a, w, e),
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


@router.get("/sync")
def admin_sync() -> dict:
    """SQLite 与 Neo4j 的同步状态(独立接口;计数不一致快速判定,一致才做全量比对)。"""
    neo_counts = _neo4j_counts()
    if neo_counts is None:
        return {"synced": None}
    if sqlite_store.active_counts() != neo_counts:
        return {"synced": False}
    source_payload = _source_sync_payload()
    neo_payload = _neo4j_sync_payload()
    return {
        "synced": (source_payload == neo_payload) if neo_payload is not None else None,
    }


@router.post("/import")
def do_import(body: dict) -> dict:
    wipe = bool(body.get("wipe", False))
    version = str(body.get("version", "1.1"))
    try:
        return {"ok": True, **run_import(wipe=wipe, version=version)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"校验失败:\n{exc}") from exc
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{kind}")
def create(kind: Kind, row: dict) -> dict:
    row = clean_row(row)  # 落盘前基础清洗:去首尾空白、空串归一 None
    if not row.get("id"):
        row["id"] = _new_uuid()  # 新增作者/作品/涟漪自动生成 UUID v7
    if not row.get("reviewStatus"):
        row["reviewStatus"] = "draft"  # 新增默认草稿(前端新增表单不展示该字段)
    now = _now()
    row.setdefault("createdAt", now)
    row["updatedAt"] = now
    with db_sqlite._db() as conn:
        errors = validate_row(conn, kind, row)
        if errors:
            raise HTTPException(status_code=400, detail="校验失败:\n- " + "\n".join(errors))
        sqlite_store.insert_row(conn, kind, row)
        if kind == "works":
            sqlite_store.set_work_authors(conn, row["id"], _author_id_list(row.get("author_id")))
        db_sqlite.audit(conn, "create", kind, row.get("id"))
    export_csv_files()
    return {"ok": True, "row": row}


@router.put("/{kind}/{item_id}")
def update(kind: Kind, item_id: str, row: dict) -> dict:
    row = clean_row(row)  # 落盘前基础清洗:去首尾空白、空串归一 None
    now = _now()
    with db_sqlite._db() as conn:
        existing = sqlite_store.get_row(conn, kind, item_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
        expected_ts = row.get("updatedAt") or existing.get("updatedAt")
        row["id"] = item_id
        row["createdAt"] = row.get("createdAt") or existing.get("createdAt") or now
        row["updatedAt"] = now
        errors = validate_row(conn, kind, row, exclude_id=item_id)
        if errors:
            raise HTTPException(status_code=400, detail="校验失败:\n- " + "\n".join(errors))
        status = sqlite_store.update_row(conn, kind, item_id, row, expected_updated_at=expected_ts)
        if status == -1:
            raise HTTPException(status_code=409, detail="数据已被其他人修改,请刷新后重试")
        if status == 0:
            raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
        if kind == "works":
            sqlite_store.set_work_authors(conn, item_id, _author_id_list(row.get("author_id")))
        db_sqlite.audit(conn, "update", kind, item_id)
    export_csv_files()
    return {"ok": True, "row": row}


@router.delete("/{kind}/{item_id}")
def delete(kind: Kind, item_id: str) -> dict:
    """软删除。作品连带其涟漪边;作者连带其名下作品与这些作品的涟漪边。"""
    now = _now()
    cascade: dict[str, list[str]] = {"works": [], "edges": []}
    with db_sqlite._db() as conn:
        if not sqlite_store.row_exists(conn, kind, item_id):
            raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
        if kind == "works":
            edge_ids = sqlite_store.cascade_work_edge_ids(conn, item_id)
            sqlite_store.mark_deleted(conn, kind, [item_id], now)
            sqlite_store.mark_deleted(conn, "edges", edge_ids, now)
            cascade["edges"] = edge_ids
        elif kind == "authors":
            work_ids = sqlite_store.cascade_author_work_ids(conn, item_id)
            edge_ids = sqlite_store.cascade_author_edge_ids(conn, item_id)
            sqlite_store.mark_deleted(conn, kind, [item_id], now)
            sqlite_store.mark_deleted(conn, "works", work_ids, now)
            sqlite_store.mark_deleted(conn, "edges", edge_ids, now)
            cascade = {"works": work_ids, "edges": edge_ids}
        else:
            sqlite_store.mark_deleted(conn, kind, [item_id], now)
        db_sqlite.audit(
            conn, "delete", kind, item_id,
            f"cascade works={len(cascade['works'])} edges={len(cascade['edges'])}",
        )
    export_csv_files()
    return {"ok": True, "deletedAt": now, "cascade": cascade}


@router.post("/{kind}/{item_id}/restore")
def restore(kind: Kind, item_id: str) -> dict:
    """恢复软删除。同一删除动作级联删除的作品/涟漪(相同 deletedAt)一并恢复。

    删除时用同一个时间戳标记父行与级联行,恢复时按该时间戳找回整组;
    单独删除的行(不同 deletedAt)不受影响。
    """
    cascade: dict[str, list[str]] = {"works": [], "edges": []}
    with db_sqlite._db() as conn:
        row = sqlite_store.get_row(conn, kind, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
        ts = row.get("deletedAt")
        if not ts:
            return {"ok": True, "cascade": cascade}
        now = _now()
        if kind == "works":
            edge_ids = sqlite_store.restore_work_edge_ids(conn, item_id, ts)
            sqlite_store.restore_by_ts(conn, kind, [item_id], ts, now)
            sqlite_store.restore_by_ts(conn, "edges", edge_ids, ts, now)
            cascade["edges"] = edge_ids
        elif kind == "authors":
            work_ids = sqlite_store.restore_author_work_ids(conn, item_id, ts)
            edge_ids = sqlite_store.restore_author_edge_ids(conn, item_id, ts)
            sqlite_store.restore_by_ts(conn, kind, [item_id], ts, now)
            sqlite_store.restore_by_ts(conn, "works", work_ids, ts, now)
            sqlite_store.restore_by_ts(conn, "edges", edge_ids, ts, now)
            cascade = {"works": work_ids, "edges": edge_ids}
        else:
            work_ids = sqlite_store.restore_edge_work_ids(
                conn, row.get("source_work_id"), row.get("target_work_id"), ts
            )
            sqlite_store.restore_by_ts(conn, kind, [item_id], ts, now)
            sqlite_store.restore_by_ts(conn, "works", work_ids, ts, now)
            cascade["works"] = work_ids
        db_sqlite.audit(
            conn, "restore", kind, item_id,
            f"cascade works={len(cascade['works'])} edges={len(cascade['edges'])}",
        )
    export_csv_files()
    return {"ok": True, "cascade": cascade}


@router.get("/contributions")
def admin_contributions(
    status: str | None = Query(None, pattern="^(pending|approved|rejected)$"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """贡献收件箱列表(按审核状态过滤)。"""
    return list_contributions(status, limit, offset)


@router.post("/contributions/{item_id}/approve")
def approve_contribution(item_id: str) -> dict:
    if not set_status(item_id, "approved"):
        raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
    return {"ok": True}


@router.post("/contributions/{item_id}/reject")
def reject_contribution(item_id: str) -> dict:
    if not set_status(item_id, "rejected"):
        raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
    return {"ok": True}


@router.get("/audit")
def admin_audit(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, pattern="^(create|update|delete|restore)$"),
    kind: str | None = Query(None, pattern="^(authors|works|edges)$"),
) -> dict:
    """管理写操作审计记录。"""
    return sqlite_store.list_audit(limit, offset, action, kind)

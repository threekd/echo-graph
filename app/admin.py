"""数据管理 API:三张表的增删改查、软删除、一键导入 Neo4j、导出。

存储层:data/real/*.csv(UTF-8 BOM),保存前自动版本快照。
"""

from __future__ import annotations

import csv
import datetime as dt
import hmac
import io
import json
import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.contributions import list_contributions, set_status
from app.data_models import find_duplicates, parse_rows
from app.data_store import AUTHOR_HEADER, EDGE_HEADER, WORK_HEADER, clean_row, load_rows, save_rows, snapshot
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
HEADERS = {"authors": AUTHOR_HEADER, "works": WORK_HEADER, "edges": EDGE_HEADER}


def _rows(kind: Kind) -> list[dict]:
    a, w, e = load_rows()
    return {"authors": a, "works": w, "edges": e}[kind]


def _validate(a: list[dict], w: list[dict], e: list[dict]) -> None:
    try:
        parse_rows(a, w, e)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"校验失败:\n{exc}") from exc


def _warnings(a: list[dict], w: list[dict], e: list[dict]) -> dict[str, list[str]]:
    return find_duplicates(a, w, e)


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _new_uuid() -> str:
    try:
        return str(uuid.uuid7())  # Python 3.14: 时间有序 UUID v7
    except AttributeError:
        return str(uuid.uuid4())


def _edge_pair(row: dict) -> tuple[str, str] | None:
    """边的配对标识:source_work_id + target_work_id,用于查重(同一对作品只允许一条涟漪)。"""
    s = row.get("source_work_id")
    t = row.get("target_work_id")
    if s and t:
        return (str(s), str(t))
    return None


def _work_title_map(works: list[dict]) -> dict[str, str]:
    """作品 id -> Title_CN,用于把报错里的 UUID 换成可读标题。"""
    return {str(x.get("id")): x.get("Title_CN") for x in works if x.get("id")}


def _author_ids_contain(value, author_id: str) -> bool:
    """works.author_id(逗号分隔,可能带空格)是否包含指定作者 id。"""
    return any(v.strip() == author_id for v in str(value or "").split(",") if v.strip())


@router.get("/data")
def get_data() -> dict:
    a, w, e = load_rows()
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


@router.post("/import")
def do_import(body: dict) -> dict:
    wipe = bool(body.get("wipe", False))
    version = str(body.get("version", "1.1"))
    try:
        return {"ok": True, **run_import("csv", wipe=wipe, version=version)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"校验失败:\n{exc}") from exc
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{kind}")
def create(kind: Kind, row: dict) -> dict:
    row = clean_row(row)  # 落盘前基础清洗:去首尾空白、空串归一 None
    a, w, e = load_rows()
    work_title = _work_title_map(w)
    cand = {"authors": a, "works": w, "edges": e}
    rows = cand[kind]
    if kind in ("authors", "works", "edges") and not row.get("id"):
        row["id"] = _new_uuid()  # 新增作者/作品/涟漪自动生成 UUID v7
    if not row.get("reviewStatus"):
        row["reviewStatus"] = "draft"  # 新增默认草稿(前端新增表单不展示该字段)
    now = _now()
    row.setdefault("createdAt", now)
    row["updatedAt"] = now
    if any(r.get("id") == row.get("id") for r in rows):
        raise HTTPException(status_code=400, detail=f"id 已存在:{row.get('id')}")
    if kind == "edges":
        pair = _edge_pair(row)
        if pair and any(_edge_pair(r) == pair for r in rows):
            raise HTTPException(
                status_code=400,
                detail=f"涟漪关系已存在:{work_title.get(pair[0], pair[0])} -> {work_title.get(pair[1], pair[1])}",
            )
    rows.append(row)
    _validate(cand["authors"], cand["works"], cand["edges"])
    snapshot("admin")
    save_rows(cand["authors"], cand["works"], cand["edges"])
    return {
        "ok": True,
        "row": row,
        "warnings": _warnings(cand["authors"], cand["works"], cand["edges"]),
    }


@router.put("/{kind}/{item_id}")
def update(kind: Kind, item_id: str, row: dict) -> dict:
    row = clean_row(row)  # 落盘前基础清洗:去首尾空白、空串归一 None
    a, w, e = load_rows()
    work_title = _work_title_map(w)
    cand = {"authors": a, "works": w, "edges": e}
    rows = cand[kind]
    if not any(r.get("id") == item_id for r in rows):
        raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
    row["id"] = item_id
    existing = next(r for r in rows if r.get("id") == item_id)
    now = _now()
    row["createdAt"] = row.get("createdAt") or existing.get("createdAt") or now
    row["updatedAt"] = now
    if kind == "edges":
        pair = _edge_pair(row)
        if pair and any(
            r.get("id") != item_id and _edge_pair(r) == pair for r in rows
        ):
            raise HTTPException(
                status_code=400,
                detail=f"涟漪关系已存在:{work_title.get(pair[0], pair[0])} -> {work_title.get(pair[1], pair[1])}",
            )
    cand[kind] = [row if r.get("id") == item_id else r for r in rows]
    _validate(cand["authors"], cand["works"], cand["edges"])
    snapshot("admin")
    save_rows(cand["authors"], cand["works"], cand["edges"])
    return {
        "ok": True,
        "row": row,
        "warnings": _warnings(cand["authors"], cand["works"], cand["edges"]),
    }


@router.delete("/{kind}/{item_id}")
def delete(kind: Kind, item_id: str) -> dict:
    """软删除。作品连带其涟漪边;作者连带其名下作品与这些作品的涟漪边。"""
    a, w, e = load_rows()
    cand = {"authors": a, "works": w, "edges": e}
    rows = cand[kind]
    found = False
    now = _now()
    for r in rows:
        if r.get("id") == item_id:
            r["deletedAt"] = now
            found = True
    if not found:
        raise HTTPException(status_code=404, detail=f"未找到 {item_id}")

    cascade: dict[str, list[str]] = {"works": [], "edges": []}
    if kind == "works":
        # 删除作品:把它作为源或目标的涟漪边一并软删除
        for r in e:
            if not r.get("deletedAt") and (
                r.get("source_work_id") == item_id or r.get("target_work_id") == item_id
            ):
                r["deletedAt"] = now
                cascade["edges"].append(r.get("id") or f"{r.get('source_work_id')}:{r.get('target_work_id')}")
    elif kind == "authors":
        # 删除作者:连带其名下作品,以及这些作品相关的涟漪边
        work_ids = {
            r.get("id")
            for r in w
            if not r.get("deletedAt") and _author_ids_contain(r.get("author_id"), item_id)
        }
        for r in w:
            if r.get("id") in work_ids:
                r["deletedAt"] = now
                cascade["works"].append(r.get("id"))
        for r in e:
            if not r.get("deletedAt") and (
                r.get("source_work_id") in work_ids or r.get("target_work_id") in work_ids
            ):
                r["deletedAt"] = now
                cascade["edges"].append(r.get("id") or f"{r.get('source_work_id')}:{r.get('target_work_id')}")

    _validate(cand["authors"], cand["works"], cand["edges"])
    snapshot("admin")
    save_rows(cand["authors"], cand["works"], cand["edges"])
    return {
        "ok": True,
        "deletedAt": now,
        "warnings": _warnings(cand["authors"], cand["works"], cand["edges"]),
        "cascade": cascade,
    }


@router.post("/{kind}/{item_id}/restore")
def restore(kind: Kind, item_id: str) -> dict:
    """恢复软删除。同一删除动作级联删除的作品/涟漪(相同 deletedAt)一并恢复。

    删除时用同一个时间戳标记父行与级联行,恢复时按该时间戳找回整组;
    单独删除的行(不同 deletedAt)不受影响。
    """
    a, w, e = load_rows()
    cand = {"authors": a, "works": w, "edges": e}
    rows = cand[kind]
    row = next((r for r in rows if r.get("id") == item_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
    ts = row.get("deletedAt")
    if not ts:
        return {"ok": True, "warnings": _warnings(cand["authors"], cand["works"], cand["edges"]), "cascade": {"works": [], "edges": []}}

    now = _now()
    cascade: dict[str, list[str]] = {"works": [], "edges": []}

    def restore_row(r: dict, bucket: list[str]) -> None:
        if r.get("deletedAt") == ts:
            r["deletedAt"] = None
            r["updatedAt"] = now
            bucket.append(r.get("id") or f"{r.get('source_work_id')}:{r.get('target_work_id')}")

    if kind == "works":
        # 恢复作品:同批删除的涟漪边一并恢复
        for r in e:
            if r.get("source_work_id") == item_id or r.get("target_work_id") == item_id:
                restore_row(r, cascade["edges"])
    elif kind == "authors":
        # 恢复作者:同批删除的作品与涟漪边一并恢复
        work_ids = {r.get("id") for r in w if _author_ids_contain(r.get("author_id"), item_id)}
        for r in w:
            if r.get("id") in work_ids:
                restore_row(r, cascade["works"])
        for r in e:
            if r.get("source_work_id") in work_ids or r.get("target_work_id") in work_ids:
                restore_row(r, cascade["edges"])
    else:
        # 恢复涟漪边:同批删除的源/目标作品一并恢复,避免活跃边引用已删作品
        for r in w:
            if r.get("id") in (row.get("source_work_id"), row.get("target_work_id")):
                restore_row(r, cascade["works"])

    row["deletedAt"] = None
    row["updatedAt"] = now
    _validate(cand["authors"], cand["works"], cand["edges"])
    snapshot("admin")
    save_rows(cand["authors"], cand["works"], cand["edges"])
    return {
        "ok": True,
        "warnings": _warnings(cand["authors"], cand["works"], cand["edges"]),
        "cascade": cascade,
    }


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


@router.get("/export/json")
def export_json() -> Response:
    a, w, e = load_rows()
    payload = {"authors": a, "works": w, "edges": e, "exportedAt": _now()}
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="echo-graph-data.json"'},
    )


@router.get("/export/csv/{kind}")
def export_csv(kind: Kind) -> Response:
    rows = _rows(kind)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=HEADERS[kind], extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({h: (r.get(h) if r.get(h) is not None else "") for h in HEADERS[kind]})
    return Response(
        "\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'},
    )

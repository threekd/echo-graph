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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.data_models import parse_rows
from app.data_store import AUTHOR_HEADER, EDGE_HEADER, WORK_HEADER, load_rows, save_rows, snapshot
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


@router.get("/data")
def get_data() -> dict:
    a, w, e = load_rows()
    return {
        "authors": a,
        "works": w,
        "edges": e,
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
    a, w, e = load_rows()
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
            raise HTTPException(status_code=400, detail=f"涟漪关系已存在:{pair[0]} -> {pair[1]}")
    rows.append(row)
    _validate(cand["authors"], cand["works"], cand["edges"])
    snapshot("admin")
    save_rows(cand["authors"], cand["works"], cand["edges"])
    return {"ok": True, "row": row}


@router.put("/{kind}/{item_id}")
def update(kind: Kind, item_id: str, row: dict) -> dict:
    a, w, e = load_rows()
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
            raise HTTPException(status_code=400, detail=f"涟漪关系已存在:{pair[0]} -> {pair[1]}")
    cand[kind] = [row if r.get("id") == item_id else r for r in rows]
    _validate(cand["authors"], cand["works"], cand["edges"])
    snapshot("admin")
    save_rows(cand["authors"], cand["works"], cand["edges"])
    return {"ok": True, "row": row}


@router.delete("/{kind}/{item_id}")
def delete(kind: Kind, item_id: str) -> dict:
    a, w, e = load_rows()
    cand = {"authors": a, "works": w, "edges": e}
    rows = cand[kind]
    found = False
    for r in rows:
        if r.get("id") == item_id:
            r["deletedAt"] = _now()
            found = True
    if not found:
        raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
    _validate(cand["authors"], cand["works"], cand["edges"])
    snapshot("admin")
    save_rows(cand["authors"], cand["works"], cand["edges"])
    return {"ok": True, "deletedAt": _now()}


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

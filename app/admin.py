"""数据管理 API:三张表的增删改查、软删除、一键导入 Neo4j、导出。

存储层:data/real/*.csv(UTF-8 BOM),保存前自动版本快照。
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.data_models import parse_rows
from app.data_store import EDGE_HEADER, AUTHOR_HEADER, WORK_HEADER, load_rows, save_rows, snapshot
from app.importer import run_import

_admin_bearer = HTTPBearer(auto_error=False)


def require_admin_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_admin_bearer),
) -> None:
    """管理接口鉴权:需在 .env 配置 ADMIN_TOKEN,请求头带 Authorization: Bearer <token>。"""
    token = os.getenv("ADMIN_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN 未配置,管理接口已禁用")
    if credentials is None or credentials.credentials != token:
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
        raise HTTPException(status_code=400, detail=f"校验失败:\n{exc}")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _new_uuid() -> str:
    try:
        return str(uuid.uuid7())  # Python 3.14: 时间有序 UUID v7
    except AttributeError:
        return str(uuid.uuid4())


def _edge_pair(row: dict) -> Optional[tuple[str, str]]:
    """边的复合标识:source_work_id + ':' + target_work_id(边没有独立 id 字段)。"""
    s = row.get("source_work_id")
    t = row.get("target_work_id")
    if s and t:
        return (str(s), str(t))
    return None


def _split_edge_id(item_id: str) -> tuple[str, str]:
    parts = item_id.split(":", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail=f"无效的提及标识:{item_id}")
    return parts[0], parts[1]


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
        raise HTTPException(status_code=400, detail=f"校验失败:\n{exc}")
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{kind}")
def create(kind: Kind, row: dict) -> dict:
    a, w, e = load_rows()
    cand = {"authors": a, "works": w, "edges": e}
    rows = cand[kind]
    if kind in ("authors", "works") and not row.get("id"):
        row["id"] = _new_uuid()  # 新增作者/作品自动生成 UUID v7
    if kind == "edges":
        pair = _edge_pair(row)
        if pair and any(_edge_pair(r) == pair for r in rows):
            raise HTTPException(status_code=400, detail=f"提及关系已存在:{pair[0]} -> {pair[1]}")
    elif any(r.get("id") == row.get("id") for r in rows):
        raise HTTPException(status_code=400, detail=f"id 已存在:{row.get('id')}")
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
    if kind == "edges":
        s0, t0 = _split_edge_id(item_id)
        idx = next(
            (i for i, r in enumerate(rows) if r.get("source_work_id") == s0 and r.get("target_work_id") == t0),
            None,
        )
        if idx is None:
            raise HTTPException(status_code=404, detail=f"未找到提及 {item_id}")
        if not row.get("source_work_id") or not row.get("target_work_id"):
            raise HTTPException(status_code=400, detail="source_work_id / target_work_id 不能为空")
        pair = (str(row["source_work_id"]), str(row["target_work_id"]))
        if any(i != idx and _edge_pair(r) == pair for i, r in enumerate(rows)):
            raise HTTPException(status_code=400, detail=f"提及关系已存在:{pair[0]} -> {pair[1]}")
        rows[idx] = row
    else:
        if not any(r.get("id") == item_id for r in rows):
            raise HTTPException(status_code=404, detail=f"未找到 {item_id}")
        row["id"] = item_id
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
    if kind == "edges":
        s0, t0 = _split_edge_id(item_id)
        for r in rows:
            if r.get("source_work_id") == s0 and r.get("target_work_id") == t0:
                r["deletedAt"] = _now()
                found = True
    else:
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

"""用户贡献收件箱:SQLite 存储,公开提交无需令牌,审核走管理接口。

用户提交只进入收件箱,不会直接写入策展数据;
审核通过后由后续流程(如人工录入 / AI 校正)再并入正式数据。
"""

from __future__ import annotations

import datetime as dt
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from app import db_sqlite
from app.data_store import remove_invisible_chars

# 极简进程内限流:同一 IP 每小时最多 SUBMIT_LIMIT 条(多 worker 下按进程独立计数,后续可换持久化)
SUBMIT_LIMIT = 10
_rate: dict[str, list[float]] = {}

MAX_LEN = {
    "source_work": 200,
    "target_work": 200,
    "source_author": 200,
    "target_author": 200,
    "evidence": 2000,
    "evidence_source": 300,
    "note": 1000,
    "contact": 200,
}


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _clean(value) -> str:
    if value is None:
        return ""
    return remove_invisible_chars(str(value)).strip()


def _validate(payload: dict) -> dict:
    """清洗 + 校验提交内容,失败抛 ValueError。"""
    data = {k: _clean(payload.get(k)) for k in MAX_LEN}
    errors = []
    for key, label in (
        ("source_work", "源作品"),
        ("target_work", "目标作品"),
        ("source_author", "源作品作者"),
        ("target_author", "目标作品作者"),
        ("evidence", "原文片段"),
        ("evidence_source", "出处"),
    ):
        if not data[key]:
            errors.append(f"{label}不能为空")
    for key, label in (
        ("source_work", "源作品"),
        ("target_work", "目标作品"),
        ("source_author", "源作品作者"),
        ("target_author", "目标作品作者"),
        ("evidence", "原文片段"),
        ("evidence_source", "出处"),
        ("note", "备注"),
        ("contact", "联系方式"),
    ):
        if len(data[key]) > MAX_LEN[key]:
            errors.append(f"{label}过长(最多 {MAX_LEN[key]} 字)")
    if errors:
        raise ValueError("\n- ".join(errors))
    return data


def submit_contribution(payload: dict) -> dict:
    """写入一条 pending 贡献,返回落库后的行。"""
    data = _validate(payload)
    row = {
        "id": str(uuid.uuid7()) if hasattr(uuid, "uuid7") else str(uuid.uuid4()),
        **data,
        "status": "pending",
        "created_at": _now(),
        "reviewed_at": None,
    }
    with db_sqlite._db() as conn:
        conn.execute(
            "INSERT INTO contributions (id, source_work, target_work, source_author,"
            " target_author, evidence, evidence_source, note, contact, status, created_at, reviewed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"], row["source_work"], row["target_work"],
                row["source_author"], row["target_author"],
                row["evidence"], row["evidence_source"], row["note"], row["contact"],
                row["status"], row["created_at"], row["reviewed_at"],
            ),
        )
    return row


def list_contributions(
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    with db_sqlite._db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM contributions WHERE status = ?"
                " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT count(*) AS c FROM contributions WHERE status = ?",
                (status,),
            ).fetchone()["c"]
        else:
            rows = conn.execute(
                "SELECT * FROM contributions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = conn.execute("SELECT count(*) AS c FROM contributions").fetchone()["c"]
    return {"items": [dict(r) for r in rows], "total": total}


def set_status(contribution_id: str, status: str) -> bool:
    """pending -> approved / rejected;返回是否命中。"""
    with db_sqlite._db() as conn:
        cur = conn.execute(
            "UPDATE contributions SET status = ?, reviewed_at = ? WHERE id = ?",
            (status, _now(), contribution_id),
        )
        return cur.rowcount > 0


def _rate_limited(client_ip: str) -> bool:
    now = time.monotonic()
    window = 3600.0
    ts = [t for t in _rate.get(client_ip, []) if now - t < window]
    if len(ts) >= SUBMIT_LIMIT:
        _rate[client_ip] = ts
        return True
    ts.append(now)
    _rate[client_ip] = ts
    return False


router = APIRouter(prefix="/api/contribute", tags=["contribute"])


@router.post("/echo")
def submit_echo(payload: dict, request: Request) -> dict:
    """公开提交:涟漪建议(源/目标作品自由填写,不需要是已收录作品)。"""
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="提交过于频繁,请稍后再试")
    try:
        row = submit_contribution(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"校验失败:\n{exc}") from exc
    return {"ok": True, "id": row["id"], "msg": "提交成功,审核通过后展示"}

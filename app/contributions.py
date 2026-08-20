"""用户贡献收件箱:SQLite 存储,公开提交无需令牌,审核走管理接口。

用户提交只进入收件箱,不会直接写入策展数据;
审核通过后由后续流程(如人工录入 / AI 校正)再并入正式数据。

限流策略(三层):
1. 应用层:进程内滑动窗口,默认每 IP 每小时最多 SUBMIT_LIMIT(20) 条;
   单 worker 部署下计数精确,多 worker 需依赖 nginx 层或换共享存储。
2. 信任边界:仅当连接来源属于 TRUSTED_PROXIES(默认 127.0.0.1,::1)时,
   才解析 X-Forwarded-For 取最左客户端 IP;直连 uvicorn 时伪造头无效。
3. nginx 层:deploy 模板提供 limit_req 防洪(粗粒度,不替代应用策略)。
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import logging
import os
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from app import db_sqlite
from app.data_store import remove_invisible_chars

logger = logging.getLogger("echo_graph")

# 应用层限流:同一 IP 每小时最多 SUBMIT_LIMIT 条
SUBMIT_LIMIT = 20
WINDOW_SECONDS = 3600.0
# 进程内计数键数上限:超过后整体重置(防内存无限增长,限流短暂放开)
_MAX_RATE_KEYS = 10_000
# 可信代理列表(逗号分隔的 IP / CIDR):只有来自这些来源的连接才解析 X-Forwarded-For
TRUSTED_PROXIES = os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1")
_rate: dict[str, list[float]] = {}
_trusted_networks: list[ipaddress.ip_network] | None = None

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
    with db_sqlite._write_lock, db_sqlite._db() as conn:
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


def get_contribution(contribution_id: str) -> dict | None:
    """按 id 取单条贡献(审核审计用)。"""
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT * FROM contributions WHERE id = ?", (contribution_id,)
        ).fetchone()
    return dict(row) if row else None


def set_status(contribution_id: str, status: str) -> bool:
    """pending -> approved / rejected;返回是否命中。"""
    with db_sqlite._db() as conn:
        cur = conn.execute(
            "UPDATE contributions SET status = ?, reviewed_at = ? WHERE id = ?",
            (status, _now(), contribution_id),
        )
        return cur.rowcount > 0


def _trusted_networks_list() -> list[ipaddress.ip_network]:
    """解析 TRUSTED_PROXIES 为网络对象列表(进程内缓存一次)。"""
    global _trusted_networks
    if _trusted_networks is None:
        nets: list[ipaddress.ip_network] = []
        for item in TRUSTED_PROXIES.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                nets.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                logger.warning("忽略无效的 TRUSTED_PROXIES 项:%r", item)
        _trusted_networks = nets
    return _trusted_networks


def _client_ip(request: Request) -> str:
    """解析限流用客户端 IP。

    仅当对端地址属于可信代理列表时才取 X-Forwarded-For 的最左有效 IP;
    否则(直连 uvicorn / 伪造头)一律使用对端地址,防伪造绕过。
    """
    peer = request.client.host if request.client else ""
    if not peer:
        return "unknown"
    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not any(peer_addr in net for net in _trusted_networks_list()):
        return peer
    xff = request.headers.get("x-forwarded-for", "")
    for hop in xff.split(","):
        hop = hop.strip()
        if not hop:
            continue
        try:
            ipaddress.ip_address(hop)
            return hop
        except ValueError:
            continue
    return peer


def _prune_rate_map() -> None:
    """防内存无限增长:键数超限时整体重置(限流短暂放开)。"""
    if len(_rate) > _MAX_RATE_KEYS:
        _rate.clear()


def _rate_limited(client_ip: str) -> bool:
    now = time.monotonic()
    _prune_rate_map()
    ts = [t for t in _rate.get(client_ip, []) if now - t < WINDOW_SECONDS]
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
    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="提交过于频繁,请稍后再试")
    try:
        row = submit_contribution(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"校验失败:\n{exc}") from exc
    return {"ok": True, "id": row["id"], "msg": "提交成功,审核通过后展示"}

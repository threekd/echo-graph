"""进程内滑动窗口限流(单 worker 部署下精确;多 worker 需换共享存储如 Redis)。

通用实现:客户端 IP 解析 + 滑动窗口计数(供关注等写接口限流)。
键数超限时整体重置,防止内存无限增长(限流短暂放开)。
"""

from __future__ import annotations

import ipaddress
import logging
import os
import time

from fastapi import Request

logger = logging.getLogger("echo_graph")

# 可信代理列表(逗号分隔的 IP / CIDR):只有来自这些来源的连接才解析 X-Forwarded-For
TRUSTED_PROXIES = os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1")
# 进程内计数键数上限:超过后整体重置(防内存无限增长,限流短暂放开)
_MAX_RATE_KEYS = 10_000
_rate: dict[str, list[float]] = {}
_trusted_networks: list[ipaddress.ip_network] | None = None


def clear_rate_limits() -> None:
    """清空进程内限流计数(测试用)。"""
    _rate.clear()


def _trusted_networks_list() -> list[ipaddress.ip_network]:
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


def client_ip(request: Request) -> str:
    """解析限流用客户端 IP。

    仅当对端地址属于可信代理列表时才解析 X-Forwarded-For;解析从右向左
    跳过可信代理段,取第一个不可信的客户端 IP(与 uvicorn 的
    ProxyHeadersMiddleware 语义一致,客户端无法通过在左侧预置伪造值绕过
    限流);全部为可信代理时回退最左值。直连 uvicorn(非可信对端)或伪造
    请求头时一律使用对端地址。
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
    hops = [h.strip() for h in xff.split(",") if h.strip()]
    valid: list[str] = []
    for hop in hops:
        try:
            ipaddress.ip_address(hop)
            valid.append(hop)
        except ValueError:
            continue
    if not valid:
        return peer
    # 每一跳由上游代理追加到末尾,从右向左取第一个非可信 IP
    for hop in reversed(valid):
        hop_addr = ipaddress.ip_address(hop)
        if not any(hop_addr in net for net in _trusted_networks_list()):
            return hop
    return valid[0]


def sliding_limited(key: str, limit: int, window_seconds: float) -> bool:
    """同键在窗口内已满 limit 次则返回 True(应拒绝);否则计数并返回 False。"""
    if len(_rate) > _MAX_RATE_KEYS:
        _rate.clear()
    now = time.monotonic()
    ts = [t for t in _rate.get(key, []) if now - t < window_seconds]
    if len(ts) >= limit:
        _rate[key] = ts
        return True
    ts.append(now)
    _rate[key] = ts
    return False

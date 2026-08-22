"""CSRF 同源校验(全局中间件,防御纵深)。

会话 Cookie 为 httpOnly + SameSite=Lax,主流浏览器已挡掉跨站 POST 携带 Cookie;
本中间件是第二道防线:所有状态变更请求(POST/PUT/PATCH/DELETE)若带 Origin 头,
必须与本站同源,否则 403。无 Origin 头放行(同源 fetch 之外的 CLI/服务端调用)。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_state_changing(method: str) -> bool:
    return method in STATE_CHANGING_METHODS


def same_origin_allowed(request: Request) -> bool:
    """带 Origin 头的请求必须与本站同源;无 Origin 头视为非浏览器调用,放行。"""
    origin = request.headers.get("origin")
    if not origin:
        return True
    expected = str(request.base_url).rstrip("/")
    return origin.rstrip("/") == expected


async def same_origin_middleware(request: Request, call_next):
    """FastAPI http 中间件:状态变更请求先做同源校验。"""
    if is_state_changing(request.method) and not same_origin_allowed(request):
        return JSONResponse(status_code=403, content={"detail": "跨站请求被拒绝"})
    return await call_next(request)

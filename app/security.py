"""CSRF 同源校验(判定函数,防御纵深)。

会话 Cookie 为 httpOnly + SameSite=Lax,主流浏览器已挡掉跨站 POST 携带 Cookie;
这里提供同源判定,真正的全局中间件注册在 app/main.py(csrf_same_origin_guard):
所有状态变更请求(POST/PUT/PATCH/DELETE)若带 Origin 头,必须与本站同源,否则 403。
无 Origin 头放行(同源 fetch 之外的 CLI/服务端调用)。
"""

from __future__ import annotations

from fastapi import Request

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

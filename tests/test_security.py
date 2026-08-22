"""全局 CSRF 同源校验测试(中间件 + 纯函数)。"""

from __future__ import annotations

import asyncio
import unittest

import app.main as main
from app.security import is_state_changing, same_origin_allowed


class _FakeRequest:
    def __init__(self, method: str, headers: dict | None = None, base_url: str = "http://testserver") -> None:
        self.method = method
        self.headers = headers or {}
        self._base = base_url

    @property
    def base_url(self) -> str:
        return self._base


class SameOriginUnitTest(unittest.TestCase):
    def test_state_changing_methods(self) -> None:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertTrue(is_state_changing(method))
        for method in ("GET", "HEAD", "OPTIONS"):
            self.assertFalse(is_state_changing(method))

    def test_same_origin_allowed(self) -> None:
        base = "http://testserver/"
        self.assertTrue(same_origin_allowed(_FakeRequest("POST", base_url=base)))
        self.assertTrue(
            same_origin_allowed(
                _FakeRequest("POST", {"origin": "http://testserver"}, base_url=base)
            )
        )
        # 带尾斜杠也视为同源
        self.assertTrue(
            same_origin_allowed(
                _FakeRequest("POST", {"origin": "http://testserver/"}, base_url=base)
            )
        )
        self.assertFalse(
            same_origin_allowed(
                _FakeRequest("POST", {"origin": "https://evil.example"}, base_url=base)
            )
        )
        # Origin: null(沙箱 iframe 等)不视为同源
        self.assertFalse(
            same_origin_allowed(_FakeRequest("POST", {"origin": "null"}, base_url=base))
        )


class SameOriginMiddlewareTest(unittest.TestCase):
    def _run(self, request) -> tuple:
        called: list = []

        async def call_next(req):
            called.append(req)
            return "passed"

        return asyncio.run(main.csrf_same_origin_guard(request, call_next)), called

    def test_cross_origin_state_change_rejected(self) -> None:
        resp, called = self._run(
            _FakeRequest("POST", {"origin": "https://evil.example"}, base_url="http://testserver")
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(called, [])  # 未进入业务处理

    def test_same_origin_state_change_passes(self) -> None:
        req = _FakeRequest("POST", {"origin": "http://testserver"}, base_url="http://testserver")
        resp, called = self._run(req)
        self.assertEqual(resp, "passed")
        self.assertEqual(called, [req])

    def test_no_origin_state_change_passes(self) -> None:
        req = _FakeRequest("POST", base_url="http://testserver")
        resp, called = self._run(req)
        self.assertEqual(resp, "passed")
        self.assertEqual(called, [req])

    def test_safe_methods_not_guarded(self) -> None:
        req = _FakeRequest("GET", {"origin": "https://evil.example"}, base_url="http://testserver")
        resp, called = self._run(req)
        self.assertEqual(resp, "passed")
        self.assertEqual(called, [req])


if __name__ == "__main__":
    unittest.main()

"""账号体系测试:注册/登录/会话/Cookie/Turnstile/限流(SQLite 临时库)。"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, Response

from app import auth, db_sqlite, ratelimit


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    def __init__(self, host: str | None = None, headers: dict | None = None, cookies: dict | None = None) -> None:
        self.client = _FakeClient(host) if host is not None else None
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.base_url = "http://testserver"


class AuthStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "auth.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        ratelimit.clear_rate_limits()

    def test_register_normalizes_email_and_hashes_password(self) -> None:
        user = auth.register("  Test@Example.com ", "password123")
        self.assertEqual(user["email"], "test@example.com")
        self.assertEqual(user["role"], "user")
        with db_sqlite._db() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (user["email"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["password_hash"], "password123")
        self.assertTrue(auth.verify_password("password123", row["password_hash"]))
        self.assertFalse(auth.verify_password("wrong-password", row["password_hash"]))

    def test_register_validation_errors(self) -> None:
        with self.assertRaises(ValueError):
            auth.register("not-an-email", "password123")
        with self.assertRaises(ValueError):
            auth.register("a@b.com", "short")
        auth.register("dup@example.com", "password123")
        with self.assertRaises(ValueError):
            auth.register("DUP@example.com", "password123")  # 邮箱大小写归一后判重

    def test_login(self) -> None:
        auth.register("user@example.com", "password123")
        user = auth.login("USER@example.com", "password123")
        self.assertEqual(user["email"], "user@example.com")
        self.assertIsNone(auth.login("user@example.com", "wrong"))
        self.assertIsNone(auth.login("nobody@example.com", "password123"))
        self.assertIsNone(auth.login("", ""))

    def test_session_flow_and_token_hashed(self) -> None:
        user = auth.register("session@example.com", "password123")
        token = auth.create_session(user["id"])
        with db_sqlite._db() as conn:
            row = conn.execute("SELECT * FROM sessions").fetchone()
        self.assertEqual(row["token_hash"], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotEqual(row["token_hash"], token)
        self.assertEqual(auth.current_user(token), {
            "id": user["id"], "email": "session@example.com", "role": "user",
        })
        auth.delete_session(token)
        self.assertIsNone(auth.current_user(token))
        self.assertIsNone(auth.current_user(None))

    def test_expired_session_rejected_and_cleaned(self) -> None:
        user = auth.register("expire@example.com", "password123")
        token = auth.create_session(user["id"])
        past = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).isoformat(timespec="seconds")
        with db_sqlite._db() as conn:
            conn.execute("UPDATE sessions SET expires_at = ?", (past,))
        self.assertIsNone(auth.current_user(token))
        with db_sqlite._db() as conn:
            count = conn.execute("SELECT count(*) AS c FROM sessions").fetchone()["c"]
        self.assertEqual(count, 0)

    def test_register_endpoint_sets_http_only_cookie(self) -> None:
        with patch.object(auth, "verify_turnstile", return_value=True):
            resp = Response()
            result = auth.register_endpoint(
                {"email": "a@b.com", "password": "password123"},
                _FakeRequest(host="127.0.0.1"),
                resp,
            )
        self.assertTrue(result["ok"])
        cookie = resp.headers["set-cookie"]
        self.assertIn("echo_graph_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("samesite=lax", cookie.lower())
        self.assertNotIn("Secure", cookie)  # 本地默认非 HTTPS

    def test_login_endpoint_wrong_password_401(self) -> None:
        auth.register("x@example.com", "password123")
        with self.assertRaises(HTTPException) as ctx:
            auth.login_endpoint(
                {"email": "x@example.com", "password": "bad-password"},
                _FakeRequest(host="127.0.0.1"),
                Response(),
            )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_login_rate_limited(self) -> None:
        with patch.object(auth, "LOGIN_LIMIT", 3):
            for _ in range(3):
                with self.assertRaises(HTTPException) as ctx:
                    auth.login_endpoint(
                        {"email": "nobody@example.com", "password": "password123"},
                        _FakeRequest(host="127.0.0.1"),
                        Response(),
                    )
                self.assertEqual(ctx.exception.status_code, 401)
            with self.assertRaises(HTTPException) as ctx:
                auth.login_endpoint(
                    {"email": "nobody@example.com", "password": "password123"},
                    _FakeRequest(host="127.0.0.1"),
                    Response(),
                )
            self.assertEqual(ctx.exception.status_code, 429)

    def test_turnstile_skip_without_secret(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(auth.verify_turnstile(None, "127.0.0.1"))

    def test_turnstile_requires_token_when_configured(self) -> None:
        with patch.dict(os.environ, {"TURNSTILE_SECRET_KEY": "secret"}):
            self.assertFalse(auth.verify_turnstile(None, "127.0.0.1"))
            with patch.object(auth, "_turnstile_siteverify", return_value=True):
                self.assertTrue(auth.verify_turnstile("token", "127.0.0.1"))
            with patch.object(auth, "_turnstile_siteverify", return_value=False):
                self.assertFalse(auth.verify_turnstile("token", "127.0.0.1"))

    def test_me_endpoint(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            auth.me(_FakeRequest(headers={}, cookies={}))
        self.assertEqual(ctx.exception.status_code, 401)
        user = auth.register("me@example.com", "password123")
        token = auth.create_session(user["id"])
        result = auth.me(_FakeRequest(headers={}, cookies={auth.SESSION_COOKIE: token}))
        self.assertEqual(result["user"]["email"], "me@example.com")


class RateLimitTest(unittest.TestCase):
    def setUp(self) -> None:
        ratelimit.clear_rate_limits()

    def test_sliding_window(self) -> None:
        self.assertFalse(ratelimit.sliding_limited("k", 3, 60.0))
        self.assertFalse(ratelimit.sliding_limited("k", 3, 60.0))
        self.assertFalse(ratelimit.sliding_limited("k", 3, 60.0))
        self.assertTrue(ratelimit.sliding_limited("k", 3, 60.0))
        # 不同键互不影响
        self.assertFalse(ratelimit.sliding_limited("other", 3, 60.0))

    def test_client_ip_ignores_untrusted_xff(self) -> None:
        req = _FakeRequest(
            host="203.0.113.9",
            headers={"x-forwarded-for": "6.6.6.6"},
        )
        self.assertEqual(ratelimit.client_ip(req), "203.0.113.9")

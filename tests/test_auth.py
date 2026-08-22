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

from app import auth, db_sqlite, ratelimit, sqlite_store


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
            "id": user["id"], "email": "session@example.com",
            "username": "session", "nickname": None, "bio": None,
            "role": "user", "space_visibility": "public",
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

    def test_turnstile_remoteip_only_for_public_ip(self) -> None:
        """本地回环/私有地址不传 remoteip,公网 IP 才传(避免与 Cloudflare 侧 IP 不一致)。"""
        captured: dict[str, bytes] = {}

        def fake_urlopen(url, data=None, timeout=None):
            captured["data"] = data

            class FakeResp:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return b'{"success": true}'

            return FakeResp()

        with patch.object(auth.urllib.request, "urlopen", fake_urlopen):
            self.assertTrue(auth._turnstile_siteverify("secret", "token", "127.0.0.1"))
        self.assertNotIn(b"remoteip", captured["data"])
        with patch.object(auth.urllib.request, "urlopen", fake_urlopen):
            self.assertTrue(auth._turnstile_siteverify("secret", "token", "8.8.8.8"))
        self.assertIn(b"remoteip=8.8.8.8", captured["data"])

    def test_me_endpoint(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            auth.me(_FakeRequest(headers={}, cookies={}))
        self.assertEqual(ctx.exception.status_code, 401)
        user = auth.register("me@example.com", "password123")
        token = auth.create_session(user["id"])
        result = auth.me(_FakeRequest(headers={}, cookies={auth.SESSION_COOKIE: token}))
        self.assertEqual(result["user"]["email"], "me@example.com")

    def test_update_me_space_visibility(self) -> None:
        """PATCH /api/auth/me:星云可见性自服务切换。"""
        user = auth.register("vis@test.local", "password123")
        token = auth.create_session(user["id"])
        req = _FakeRequest(headers={}, cookies={auth.SESSION_COOKIE: token})
        result = auth.update_me({"space_visibility": "private"}, req)
        self.assertEqual(result["user"]["space_visibility"], "private")
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT space_visibility FROM users WHERE id = ?", (user["id"],)
            ).fetchone()
        self.assertEqual(row["space_visibility"], "private")
        # 非法取值 400
        with self.assertRaises(HTTPException) as ctx:
            auth.update_me({"space_visibility": "secret"}, req)
        self.assertEqual(ctx.exception.status_code, 400)
        # 未登录 401
        with self.assertRaises(HTTPException) as ctx:
            auth.update_me(
                {"space_visibility": "private"}, _FakeRequest(headers={}, cookies={})
            )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_register_username_and_nickname(self) -> None:
        user = auth.register(
            "handle@example.com", "password123", username="starlit",
            nickname="小星星", bio="热爱文学,专注跨语言影响研究。",
        )
        self.assertEqual(user["username"], "starlit")
        self.assertEqual(user["nickname"], "小星星")
        self.assertEqual(user["bio"], "热爱文学,专注跨语言影响研究。")
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT username, nickname, bio FROM users WHERE id = ?", (user["id"],)
            ).fetchone()
        self.assertEqual(row["username"], "starlit")
        self.assertEqual(row["nickname"], "小星星")
        self.assertEqual(row["bio"], "热爱文学,专注跨语言影响研究。")

    def test_register_username_defaults_from_email(self) -> None:
        user = auth.register("John.Doe+tag@example.com", "password123")
        # 邮箱已归一为小写;本地部分截断 +tag,仅保留字母/数字/下划线(点被移除)
        self.assertEqual(user["username"], "johndoe")
        self.assertIsNone(user["nickname"])

    def test_register_username_validation(self) -> None:
        with self.assertRaises(ValueError):
            auth.register("a@b.com", "password123", username="abcd")  # 不足 5 位
        with self.assertRaises(ValueError):
            auth.register("a@b.com", "password123", username="has space")
        with self.assertRaises(ValueError):
            auth.register("a@b.com", "password123", username="文学星人")  # 不支持中文
        with self.assertRaises(ValueError):
            auth.register("a@b.com", "password123", username="user.name")  # 不支持点/中划线
        with self.assertRaises(ValueError):
            auth.register("a@b.com", "password123", nickname="长" * 33)  # 昵称过长
        with self.assertRaises(ValueError):
            auth.register("a@b.com", "password123", bio="长" * 501)  # 简介过长
        # 5-32 位合法
        user = auth.register("ok@example.com", "password123", username="abcde")
        self.assertEqual(user["username"], "abcde")

    def test_register_username_unique_case_insensitive(self) -> None:
        auth.register("one@example.com", "password123", username="Reader")
        with self.assertRaises(ValueError) as ctx:
            auth.register("two@example.com", "password123", username="reader")
        self.assertIn("用户名已被使用", str(ctx.exception))

    def test_login_by_username(self) -> None:
        auth.register("who@example.com", "password123", username="SkyWalker")
        # 用户名登录(ASCII 大小写不敏感)
        user = auth.login("skywalker", "password123")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "SkyWalker")
        self.assertEqual(user["email"], "who@example.com")
        # 邮箱登录不受影响
        self.assertIsNotNone(auth.login("WHO@example.com", "password123"))
        # 错误密码统一 None
        self.assertIsNone(auth.login("SkyWalker", "wrong-password"))

    def test_update_me_nickname_and_bio(self) -> None:
        user = auth.register("profile@test.local", "password123")
        token = auth.create_session(user["id"])
        req = _FakeRequest(headers={}, cookies={auth.SESSION_COOKIE: token})
        result = auth.update_me(
            {"nickname": "新昵称", "bio": "这里是我的简介。"}, req
        )
        self.assertEqual(result["user"]["nickname"], "新昵称")
        self.assertEqual(result["user"]["bio"], "这里是我的简介。")
        # 简介过长 -> 400
        with self.assertRaises(HTTPException) as ctx:
            auth.update_me({"bio": "长" * 501}, req)
        self.assertEqual(ctx.exception.status_code, 400)
        # 用户名不可自行修改 -> 400
        with self.assertRaises(HTTPException) as ctx:
            auth.update_me({"username": "hacker"}, req)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_bootstrap_email_registers_as_admin_and_claims_rows(self) -> None:
        with patch.object(auth, "BOOTSTRAP_EMAIL", "boss@test.local"):
            sqlite_store.rewrite_all(
                [{"id": "01a00000-0000-7000-8000-000000000001", "originalName": "X", "Name_CN": "甲"}],
                [],
                [],
            )
            user = auth.register("Boss@Test.local", "password123")
            self.assertEqual(user["role"], "admin")
            with db_sqlite._db() as conn:
                row = conn.execute(
                    "SELECT owner_id FROM authors WHERE id = ?",
                    ("01a00000-0000-7000-8000-000000000001",),
                ).fetchone()
            self.assertEqual(row["owner_id"], user["id"])

    def test_bootstrap_admin_promotes_existing_user_and_claims(self) -> None:
        with patch.object(auth, "BOOTSTRAP_EMAIL", ""):
            user = auth.register("boss@test.local", "password123")
            self.assertEqual(user["role"], "user")
        sqlite_store.rewrite_all(
            [{"id": "01a00000-0000-7000-8000-000000000002", "originalName": "X", "Name_CN": "甲"}],
            [],
            [],
        )
        with patch.object(auth, "BOOTSTRAP_EMAIL", "boss@test.local"):
            result = auth.bootstrap_admin()
            self.assertEqual(result["role"], "admin")
            with db_sqlite._db() as conn:
                row = conn.execute("SELECT owner_id FROM authors").fetchone()
            self.assertEqual(row["owner_id"], user["id"])

    def test_require_admin_enforces_role(self) -> None:
        with patch.object(auth, "BOOTSTRAP_EMAIL", "boss@test.local"):
            boss = auth.register("boss@test.local", "password123")
            joe = auth.register("joe@test.local", "password123")
            boss_token = auth.create_session(boss["id"])
            joe_token = auth.create_session(joe["id"])
        with self.assertRaises(HTTPException) as ctx:
            auth.require_admin(_FakeRequest(headers={}, cookies={}))
        self.assertEqual(ctx.exception.status_code, 401)
        with self.assertRaises(HTTPException) as ctx:
            auth.require_admin(_FakeRequest(headers={}, cookies={auth.SESSION_COOKIE: joe_token}))
        self.assertEqual(ctx.exception.status_code, 403)
        result = auth.require_admin(
            _FakeRequest(headers={}, cookies={auth.SESSION_COOKIE: boss_token})
        )
        self.assertEqual(result["role"], "admin")


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

"""账号体系测试:注册/登录/会话/Cookie/Turnstile/限流(SQLite 临时库)。"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
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
        user = auth.register("  Test@Example.com ", "password123", username="tester")
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
            auth.register("not-an-email", "password123", username="tester")
        with self.assertRaises(ValueError):
            auth.register("a@b.com", "short", username="tester")
        auth.register("dup@example.com", "password123", username="dupper")
        with self.assertRaises(ValueError):
            auth.register("DUP@example.com", "password123", username="dupper2")  # 邮箱大小写归一后判重

    def test_vip_flag_roundtrip(self) -> None:
        """users.vip:注册默认 False;标记后 login/me 返回 True;require_admin_or_vip 放行 VIP。"""
        user = auth.register("vip@example.com", "password123", username="vipuser")
        self.assertFalse(user["vip"])
        with db_sqlite._db() as conn:
            conn.execute("UPDATE users SET vip = 1 WHERE id = ?", (user["id"],))
        logged = auth.login("vip@example.com", "password123")
        self.assertTrue(logged["vip"])
        req = _FakeRequest(cookies={auth.SESSION_COOKIE: auth.create_session(user["id"])})
        self.assertEqual(auth.require_admin_or_vip(req)["id"], user["id"])

        # 普通用户 403
        plain = auth.register("plain@example.com", "password123", username="plainuser")
        req2 = _FakeRequest(cookies={auth.SESSION_COOKIE: auth.create_session(plain["id"])})
        with self.assertRaises(HTTPException) as ctx:
            auth.require_admin_or_vip(req2)
        self.assertEqual(ctx.exception.status_code, 403)

        # 未登录 401
        with self.assertRaises(HTTPException) as ctx2:
            auth.require_admin_or_vip(_FakeRequest())
        self.assertEqual(ctx2.exception.status_code, 401)

    def test_login(self) -> None:
        auth.register("user@example.com", "password123", username="user01")
        user = auth.login("USER@example.com", "password123")
        self.assertEqual(user["email"], "user@example.com")
        self.assertIsNone(auth.login("user@example.com", "wrong"))
        self.assertIsNone(auth.login("nobody@example.com", "password123"))
        self.assertIsNone(auth.login("", ""))

    def test_session_flow_and_token_hashed(self) -> None:
        user = auth.register("session@example.com", "password123", username="session")
        token = auth.create_session(user["id"])
        with db_sqlite._db() as conn:
            row = conn.execute("SELECT * FROM sessions").fetchone()
            created = conn.execute(
                "SELECT createdAt FROM users WHERE id = ?", (user["id"],)
            ).fetchone()["createdAt"]
        self.assertEqual(row["token_hash"], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotEqual(row["token_hash"], token)
        self.assertEqual(auth.current_user(token), {
            "id": user["id"], "email": "session@example.com",
            "username": "session", "nickname": None, "bio": None,
            "role": "user", "space_visibility": "public", "vip": False,
            "email_verified_at": created,
        })
        auth.delete_session(token)
        self.assertIsNone(auth.current_user(token))
        self.assertIsNone(auth.current_user(None))

    def test_expired_session_rejected_and_cleaned(self) -> None:
        user = auth.register("expire@example.com", "password123", username="expirer")
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
                {"email": "a@b.com", "password": "password123", "username": "abcomer"},
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
        auth.register("x@example.com", "password123", username="xample")
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

    def test_turnstile_fail_closed_without_secret(self) -> None:
        """生产漏配密钥:注册人机验证默认失败(fail-closed,不再静默跳过)。"""
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(auth.verify_turnstile(None, "127.0.0.1"))

    def test_turnstile_skip_only_when_explicitly_allowed(self) -> None:
        """仅 TURNSTILE_ALLOW_SKIP=1(本地开发)时跳过验证。"""
        with patch.dict(os.environ, {"TURNSTILE_ALLOW_SKIP": "1"}, clear=True):
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
        user = auth.register("me@example.com", "password123", username="memail")
        token = auth.create_session(user["id"])
        result = auth.me(_FakeRequest(headers={}, cookies={auth.SESSION_COOKIE: token}))
        self.assertEqual(result["user"]["email"], "me@example.com")

    def test_update_me_space_visibility(self) -> None:
        """PATCH /api/auth/me:星云可见性自服务切换。"""
        user = auth.register("vis@test.local", "password123", username="visitor")
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

    def test_register_requires_username(self) -> None:
        """用户名必填:不再从邮箱推导,缺省直接报错。"""
        with self.assertRaises(ValueError) as ctx:
            auth.register("John.Doe+tag@example.com", "password123")
        self.assertIn("用户名不能为空", str(ctx.exception))
        with self.assertRaises(ValueError):
            auth.register("john.doe@example.com", "password123", username="   ")

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
        user = auth.register("profile@test.local", "password123", username="profilr")
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

    def test_bootstrap_email_registers_as_admin(self) -> None:
        with patch.object(auth, "BOOTSTRAP_EMAIL", "boss@test.local"):
            user = auth.register("Boss@Test.local", "password123", username="bigboss")
            self.assertEqual(user["role"], "admin")

    def test_bootstrap_admin_promotes_existing_user(self) -> None:
        with patch.object(auth, "BOOTSTRAP_EMAIL", ""):
            user = auth.register("boss@test.local", "password123", username="boss01")
            self.assertEqual(user["role"], "user")
        with patch.object(auth, "BOOTSTRAP_EMAIL", "boss@test.local"):
            result = auth.bootstrap_admin()
            self.assertEqual(result["role"], "admin")

    def test_require_admin_enforces_role(self) -> None:
        with patch.object(auth, "BOOTSTRAP_EMAIL", "boss@test.local"):
            boss = auth.register("boss@test.local", "password123", username="boss01")
            joe = auth.register("joe@test.local", "password123", username="joey01")
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

    # ---- 邮箱验证与密码重置(2026-08-28,DirectMail/SMTP 邮件) ----

    MAIL_ENV = {
        "EMAIL_VERIFY_REQUIRED": "1",
        "MAILER": "api",
        "ALIYUN_DM_ACCESS_KEY_ID": "ak-id",
        "ALIYUN_DM_ACCESS_KEY_SECRET": "ak-secret",
        "ALIYUN_DM_ACCOUNT_NAME": "no-reply@example.com",
        "SITE_BASE_URL": "https://litnebula.test",
    }

    def _capture_mail(self, sent: dict):
        def fake_send(to, subject, text, html):
            sent["to"] = to
            sent["subject"] = subject
            sent["text"] = text
            sent["html"] = html or ""
        return fake_send

    def test_register_requires_verification_email_and_verify_flow(self) -> None:
        """开启邮箱验证:注册不自动登录、发送验证邮件,验证后登录放行。"""
        sent: dict = {}
        with patch.dict(os.environ, self.MAIL_ENV), patch.object(
            auth.mailer, "send_mail", side_effect=self._capture_mail(sent)
        ), patch.object(auth, "verify_turnstile", return_value=True):
            resp = Response()
            result = auth.register_endpoint(
                {"email": "verify@example.com", "password": "password123", "username": "verifier"},
                _FakeRequest(host="127.0.0.1"),
                resp,
            )
        self.assertTrue(result["requiresVerification"])
        self.assertNotIn("echo_graph_session=", resp.headers.get("set-cookie", ""))
        self.assertEqual(sent["to"], "verify@example.com")
        m = re.search(r"#v=verify:([A-Za-z0-9_-]+)", sent["html"])
        self.assertIsNotNone(m)

        # 未验证登录被拒(403)——仍在 EMAIL_VERIFY_REQUIRED=1 配置下校验
        with patch.dict(os.environ, self.MAIL_ENV):
            with self.assertRaises(HTTPException) as ctx:
                auth.login_endpoint(
                    {"email": "verify@example.com", "password": "password123"},
                    _FakeRequest(host="127.0.0.1"),
                    Response(),
                )
            self.assertEqual(ctx.exception.status_code, 403)

        # 验证通过:写 email_verified_at,接口登录放行
        user = auth.verify_email(m.group(1))
        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "user")
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT email_verified_at FROM users WHERE id = ?", (user["id"],)
            ).fetchone()
        self.assertIsNotNone(row["email_verified_at"])
        resp2 = Response()
        result2 = auth.login_endpoint(
            {"email": "verify@example.com", "password": "password123"},
            _FakeRequest(host="127.0.0.1"),
            resp2,
        )
        self.assertTrue(result2["ok"])
        self.assertIn("echo_graph_session=", resp2.headers["set-cookie"])

    def test_register_fails_closed_when_mailer_unconfigured(self) -> None:
        """EMAIL_VERIFY_REQUIRED=1 但邮件服务未配置:注册 503 且回滚用户。"""
        with patch.dict(
            os.environ,
            {"EMAIL_VERIFY_REQUIRED": "1", "MAILER": "log",
             "ALIYUN_DM_ACCESS_KEY_ID": "", "ALIYUN_DM_ACCESS_KEY_SECRET": "",
             "ALIYUN_DM_ACCOUNT_NAME": "", "SMTP_HOST": ""},
        ), patch.object(auth, "verify_turnstile", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                auth.register_endpoint(
                    {"email": "orphan@example.com", "password": "password123", "username": "orphan1"},
                    _FakeRequest(host="127.0.0.1"),
                    Response(),
                )
        self.assertEqual(ctx.exception.status_code, 503)
        with db_sqlite._db() as conn:
            count = conn.execute(
                "SELECT count(*) c FROM users WHERE email = 'orphan@example.com'"
            ).fetchone()["c"]
        self.assertEqual(count, 0)

    def test_resend_verification_invalidates_old_token(self) -> None:
        sent: dict = {}
        with patch.dict(os.environ, self.MAIL_ENV), patch.object(
            auth.mailer, "send_mail", side_effect=self._capture_mail(sent)
        ), patch.object(auth, "verify_turnstile", return_value=True):
            auth.register_endpoint(
                {"email": "resend@example.com", "password": "password123", "username": "resender"},
                _FakeRequest(host="127.0.0.1"),
                Response(),
            )
            first_token = re.search(r"#v=verify:([A-Za-z0-9_-]+)", sent["html"]).group(1)
            result = auth.resend_verification_endpoint(
                {"email": "resend@example.com"}, _FakeRequest(host="127.0.0.1")
            )
        self.assertTrue(result["ok"])
        second_token = re.search(r"#v=verify:([A-Za-z0-9_-]+)", sent["html"]).group(1)
        self.assertNotEqual(first_token, second_token)
        # 旧令牌已作废,新令牌可用
        self.assertIsNone(auth.verify_email(first_token))
        self.assertIsNotNone(auth.verify_email(second_token))

    def test_email_token_one_time_and_expiry(self) -> None:
        user = auth.register("token@example.com", "password123", username="tokener")
        token = auth.create_email_token(user["id"], "verify")
        self.assertEqual(auth.consume_email_token(token, "verify"), user["id"])
        self.assertIsNone(auth.consume_email_token(token, "verify"))  # 一次性
        token2 = auth.create_email_token(user["id"], "reset")
        past = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat(timespec="seconds")
        with db_sqlite._db() as conn:
            conn.execute("UPDATE email_tokens SET expires_at = ? WHERE token_hash = ?",
                         (past, hashlib.sha256(token2.encode()).hexdigest()))
        self.assertIsNone(auth.consume_email_token(token2, "reset"))  # 过期

    def test_forgot_and_reset_password_flow(self) -> None:
        user = auth.register("lost@example.com", "old-password-1", username="lostone")
        old_token = auth.create_session(user["id"])  # 重置后应被吊销
        sent: dict = {}
        with patch.dict(os.environ, self.MAIL_ENV), patch.object(
            auth.mailer, "send_mail", side_effect=self._capture_mail(sent)
        ):
            # 未知邮箱同样返回 ok,不泄露账号是否存在
            ok = auth.forgot_password_endpoint(
                {"email": "nobody@example.com"}, _FakeRequest(host="127.0.0.1")
            )
            self.assertTrue(ok["ok"])
            self.assertEqual(sent, {})  # 未发信
            ok = auth.forgot_password_endpoint(
                {"email": "lost@example.com"}, _FakeRequest(host="127.0.0.1")
            )
        self.assertTrue(ok["ok"])
        m = re.search(r"#v=reset:([A-Za-z0-9_-]+)", sent["html"])
        self.assertIsNotNone(m)
        # 密码过短 400
        with self.assertRaises(HTTPException) as ctx:
            auth.reset_password_endpoint(
                {"token": m.group(1), "password": "short"},
                _FakeRequest(host="127.0.0.1"),
            )
        self.assertEqual(ctx.exception.status_code, 400)
        result = auth.reset_password_endpoint(
            {"token": m.group(1), "password": "new-password-2"},
            _FakeRequest(host="127.0.0.1"),
        )
        self.assertTrue(result["ok"])
        # 旧会话全部吊销
        self.assertIsNone(auth.current_user(old_token))
        # 新密码可登录,旧密码失效
        self.assertIsNotNone(auth.login("lost@example.com", "new-password-2"))
        self.assertIsNone(auth.login("lost@example.com", "old-password-1"))
        # 令牌一次性
        with self.assertRaises(HTTPException) as ctx:
            auth.reset_password_endpoint(
                {"token": m.group(1), "password": "another-pass-3"},
                _FakeRequest(host="127.0.0.1"),
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_bootstrap_admin_promoted_only_after_verification(self) -> None:
        """引导管理员:开启邮箱验证后,注册阶段不提权,验证通过才提权。"""
        with patch.dict(os.environ, self.MAIL_ENV), patch.object(
            auth, "BOOTSTRAP_EMAIL", "boss@test.local"
        ):
            user = auth.register("boss@test.local", "password123", username="bigboss")
            self.assertEqual(user["role"], "user")
            # 启动补角色也只认已验证用户
            self.assertIsNone(auth.bootstrap_admin())
            token = auth.create_email_token(user["id"], "verify")
            verified = auth.verify_email(token)
        self.assertEqual(verified["role"], "admin")
        with patch.object(auth, "BOOTSTRAP_EMAIL", "boss@test.local"):
            self.assertEqual(auth.bootstrap_admin()["role"], "admin")


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

    def test_client_ip_from_right_to_left_skipping_trusted(self) -> None:
        """可信对端:从右向左跳过可信代理段,取第一个不可信 IP(左侧伪造值无效)。"""
        req = _FakeRequest(
            host="127.0.0.1",
            headers={"x-forwarded-for": "6.6.6.6, 203.0.113.9"},
        )
        self.assertEqual(ratelimit.client_ip(req), "203.0.113.9")

    def test_client_ip_all_trusted_hops_falls_back_leftmost(self) -> None:
        """全部为可信代理时回退最左值(与 uvicorn 语义一致)。"""
        req = _FakeRequest(
            host="127.0.0.1",
            headers={"x-forwarded-for": "127.0.0.1, ::1"},
        )
        self.assertEqual(ratelimit.client_ip(req), "127.0.0.1")

    def test_client_ip_skips_invalid_hops(self) -> None:
        """非法 IP 跳被跳过,不影响取到有效客户端 IP。"""
        req = _FakeRequest(
            host="127.0.0.1",
            headers={"x-forwarded-for": "not-an-ip, 198.51.100.7"},
        )
        self.assertEqual(ratelimit.client_ip(req), "198.51.100.7")

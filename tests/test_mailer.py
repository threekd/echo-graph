"""邮件发送器测试:DirectMail 签名/请求构造/错误处理 + SMTP 备用通道(不真正联网)。"""

from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qsl

from app import mailer


class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self.body


class DirectMailTest(unittest.TestCase):
    DM_ENV = {
        "MAILER": "api",
        "ALIYUN_DM_ACCESS_KEY_ID": "ak-id",
        "ALIYUN_DM_ACCESS_KEY_SECRET": "ak-secret",
        "ALIYUN_DM_ACCOUNT_NAME": "no-reply@example.com",
        "ALIYUN_DM_REGION": "ap-southeast-1",
    }

    def test_percent_encode_rfc3986(self) -> None:
        self.assertEqual(mailer._percent_encode("a b"), "a%20b")
        self.assertEqual(mailer._percent_encode("a/b"), "a%2Fb")
        self.assertEqual(mailer._percent_encode("a~b"), "a~b")
        self.assertEqual(mailer._percent_encode("a*b"), "a%2Ab")
        self.assertEqual(mailer._percent_encode("中文"), "%E4%B8%AD%E6%96%87")

    def test_signature_deterministic(self) -> None:
        params = {"Action": "SingleSendMail", "ToAddress": "a@b.com", "SignatureVersion": "1.0"}
        sig1 = mailer._dm_signature(params, "secret")
        sig2 = mailer._dm_signature(dict(params), "secret")
        self.assertEqual(sig1, sig2)
        # 密钥或参数变化签名必变
        self.assertNotEqual(sig1, mailer._dm_signature(params, "other"))
        self.assertNotEqual(sig1, mailer._dm_signature({**params, "Subject": "x"}, "secret"))

    def test_send_directmail_builds_signed_request(self) -> None:
        captured: dict = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["data"] = req.data
            return _FakeResp(b'{"EnvId":"e1","RequestId":"r1"}')

        with patch.dict(os.environ, self.DM_ENV), patch.object(
            mailer.urllib.request, "urlopen", fake_urlopen
        ):
            mailer.send_mail("user@example.com", "验证主题", "纯文本正文", "<b>html</b>")
        self.assertIn("dm.ap-southeast-1.aliyuncs.com", captured["url"])
        data = dict(parse_qsl(captured["data"].decode("utf-8")))
        self.assertEqual(data["Action"], "SingleSendMail")
        self.assertEqual(data["ToAddress"], "user@example.com")
        self.assertEqual(data["HtmlBody"], "<b>html</b>")
        self.assertEqual(data["RegionId"], "ap-southeast-1")
        self.assertEqual(data["AddressType"], "1")
        # 签名与服务器端算法一致(可复算验证)
        params = {k: v for k, v in data.items() if k != "Signature"}
        self.assertEqual(data["Signature"], mailer._dm_signature(params, "ak-secret"))

    def test_send_directmail_text_body(self) -> None:
        captured: dict = {}

        def fake_urlopen(req, timeout=None):
            captured["data"] = req.data
            return _FakeResp(b'{"EnvId":"e1"}')

        with patch.dict(os.environ, self.DM_ENV), patch.object(
            mailer.urllib.request, "urlopen", fake_urlopen
        ):
            mailer.send_mail("user@example.com", "主题", "纯文本正文")
        data = dict(parse_qsl(captured["data"].decode("utf-8")))
        self.assertEqual(data["TextBody"], "纯文本正文")
        self.assertNotIn("HtmlBody", data)

    def test_directmail_api_error_raises(self) -> None:
        def fake_urlopen(req, timeout=None):
            return _FakeResp(
                b'{"Code":"InvalidAccessKeyId.NotFound","Message":"invalid key",'
                b'"RequestId":"req-1"}'
            )

        with patch.dict(os.environ, self.DM_ENV), patch.object(
            mailer.urllib.request, "urlopen", fake_urlopen
        ):
            with self.assertRaises(mailer.MailSendError):
                mailer.send_mail("user@example.com", "主题", "正文")

    def test_directmail_http_error_exposes_code(self) -> None:
        """4xx/5xx 响应体里的 Code/Message 必须透传,不能只报 HTTP 400。"""

        def fake_urlopen(req, timeout=None):
            raise HTTPError(
                req.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(
                    b'{"Code":"Forbidden","Message":"not authorized","RequestId":"r-1"}'
                ),
            )

        with patch.dict(os.environ, self.DM_ENV), patch.object(
            mailer.urllib.request, "urlopen", fake_urlopen
        ):
            with self.assertRaises(mailer.MailSendError) as ctx:
                mailer.send_mail("user@example.com", "主题", "正文")
        self.assertIn("Forbidden", str(ctx.exception))
        self.assertIn("not authorized", str(ctx.exception))

    def test_send_mail_log_mode(self) -> None:
        """未配置 MAILER:日志模式不抛异常(本地开发)。"""
        with patch.dict(os.environ, {"MAILER": "log"}, clear=False):
            mailer.send_mail("a@b.com", "s", "t")
        with patch.dict(os.environ, {"MAILER": ""}, clear=False):
            mailer.send_mail("a@b.com", "s", "t")

    def test_mailer_configured(self) -> None:
        with patch.dict(os.environ, self.DM_ENV, clear=False):
            self.assertTrue(mailer.mailer_configured())
        with patch.dict(os.environ, {"MAILER": "log"}, clear=False):
            self.assertFalse(mailer.mailer_configured())
        with patch.dict(
            os.environ,
            {"MAILER": "api", "ALIYUN_DM_ACCESS_KEY_ID": "", "ALIYUN_DM_ACCESS_KEY_SECRET": "",
             "ALIYUN_DM_ACCOUNT_NAME": ""},
            clear=False,
        ):
            self.assertFalse(mailer.mailer_configured())
        with patch.dict(
            os.environ,
            {"MAILER": "smtp", "SMTP_HOST": "smtp.example.com", "SMTP_USER": "u",
             "SMTP_PASS": "p"},
            clear=False,
        ):
            self.assertTrue(mailer.mailer_configured())


class SmtpTest(unittest.TestCase):
    SMTP_ENV = {
        "MAILER": "smtp",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "465",
        "SMTP_USER": "user@example.com",
        "SMTP_PASS": "secret",
        "SMTP_FROM": "litnebula@example.com",
        "SMTP_TLS": "0",
    }

    def test_send_smtp_ssl(self) -> None:
        sent: dict = {}

        class FakeServer:
            def __init__(self, *args, **kwargs):
                sent["init"] = (args, kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def login(self, user, pwd):
                sent["login"] = (user, pwd)

            def sendmail(self, sender, to, msg):
                sent["send"] = (sender, to, msg)

        with patch.dict(os.environ, self.SMTP_ENV), patch.object(
            mailer.smtplib, "SMTP_SSL", FakeServer
        ):
            mailer.send_mail("b@c.com", "主题", "正文")
        self.assertEqual(sent["init"][0][:2], ("smtp.example.com", 465))
        self.assertEqual(sent["login"], ("user@example.com", "secret"))
        self.assertEqual(sent["send"][0], "litnebula@example.com")
        self.assertIn("b@c.com", sent["send"][1])
        # 中文标题/正文走 MIME UTF-8 编码(不会原样出现在原始报文中)
        self.assertIn("=?utf-8?b?", sent["send"][2])

    def test_send_smtp_starttls(self) -> None:
        called: dict = {}

        class FakeServer:
            def __init__(self, *args, **kwargs):
                called["init"] = (args, kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def starttls(self):
                called["starttls"] = True

            def login(self, user, pwd):
                pass

            def sendmail(self, sender, to, msg):
                pass

        env = {**self.SMTP_ENV, "SMTP_PORT": "587", "SMTP_TLS": "1"}
        with patch.dict(os.environ, env), patch.object(
            mailer.smtplib, "SMTP", FakeServer
        ):
            mailer.send_mail("b@c.com", "主题", "正文")
        self.assertEqual(called["init"][0][:2], ("smtp.example.com", 587))
        self.assertTrue(called["starttls"])


if __name__ == "__main__":
    unittest.main()

"""邮件发送:可插拔发送器(阿里云邮件推送 DirectMail API / SMTP / 本地日志)。

- MAILER=api:阿里云邮件推送 DirectMail 的 SingleSendMail RPC API。
  纯标准库实现(HMAC-SHA1 签名),不引入新依赖;中国大陆(杭州)与
  新加坡等区域共用同一协议,仅 endpoint / RegionId 不同。
- MAILER=smtp:标准 SMTP(smtplib,465 SSL 或 587 STARTTLS),作为备用通道。
- 未配置 MAILER:日志模式(log),本地开发不真正发信;需要真实送达的接口
  (邮箱验证 / 忘记密码)在未配置发送器时由调用方 fail-closed(503)。

阿里云 DirectMail 签名要点(与官方文档一致):
1. 参数按 key 字典序排序,每个 key/value 做 RFC 3986 百分号编码;
2. 待签字符串 = HTTP方法 + "&" + 编码后的 "/" + "&" + 编码后的规范化参数串;
3. HMAC-SHA1 签名,密钥 = AccessKeySecret + "&",输出 Base64。
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import smtplib
import urllib.parse
import urllib.request
import uuid
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

logger = logging.getLogger("echo_graph")

# DirectMail 区域 → 公网 endpoint(https://help.aliyun.com/zh/direct-mail/api-endpoints)
DM_ENDPOINTS: dict[str, str] = {
    "cn-hangzhou": "dm.aliyuncs.com",
    "ap-southeast-1": "dm.ap-southeast-1.aliyuncs.com",
}
DM_API_VERSION = "2015-11-23"
DM_TIMEOUT_SECONDS = 10


class MailNotConfigured(RuntimeError):
    """邮件发送器未配置(邮箱验证 / 密码重置在生产环境必须配置)。"""


class MailSendError(RuntimeError):
    """邮件发送失败(网络 / 服务商 API 返回错误)。"""


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _flag(name: str) -> bool:
    return _env(name).lower() in ("1", "true", "yes", "on")


def mailer_mode() -> str:
    """发送器模式:api / smtp / log(默认 log,仅本地开发)。"""
    mode = _env("MAILER").lower()
    return mode if mode in ("api", "smtp") else "log"


def mailer_configured() -> bool:
    """真实发送器所需配置是否齐全(api 或 smtp);log 模式不算已配置。"""
    mode = mailer_mode()
    if mode == "api":
        return bool(
            _env("ALIYUN_DM_ACCESS_KEY_ID")
            and _env("ALIYUN_DM_ACCESS_KEY_SECRET")
            and _env("ALIYUN_DM_ACCOUNT_NAME")
        )
    if mode == "smtp":
        return bool(_env("SMTP_HOST") and _env("SMTP_USER") and _env("SMTP_PASS"))
    return False


def site_base_url() -> str:
    """站外链接(邮件深链)使用的外部地址;未配置时回退本地开发地址。"""
    return _env("SITE_BASE_URL") or "http://localhost:8000"


def send_mail(to: str, subject: str, text: str, html: str | None = None) -> None:
    """按 MAILER 配置发送邮件;未配置时仅写日志(本地开发)。"""
    mode = mailer_mode()
    if mode == "api":
        _send_directmail(to, subject, text, html)
        return
    if mode == "smtp":
        _send_smtp(to, subject, text, html)
        return
    logger.info("MAILER=log 模式,不真正发信:to=%s subject=%s", to, subject)


# ---- DirectMail SingleSendMail(RPC + HMAC-SHA1)----


def _dm_endpoint() -> str:
    override = _env("ALIYUN_DM_ENDPOINT")
    if override:
        return override
    region = _env("ALIYUN_DM_REGION") or "cn-hangzhou"
    return DM_ENDPOINTS.get(region, DM_ENDPOINTS["cn-hangzhou"])


def _percent_encode(value: str) -> str:
    """RFC 3986 百分号编码:空格 → %20(而非表单的 +),~ 不转义。"""
    return urllib.parse.quote(str(value), safe="-_.~")


def _dm_canonical_query(params: dict[str, str]) -> str:
    return "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted(params.items())
    )


def _dm_signature(params: dict[str, str], access_key_secret: str) -> str:
    string_to_sign = (
        "POST&" + _percent_encode("/") + "&" + _percent_encode(_dm_canonical_query(params))
    )
    key = (access_key_secret + "&").encode("utf-8")
    digest = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _send_directmail(to: str, subject: str, text: str, html: str | None) -> None:
    access_key_id = _env("ALIYUN_DM_ACCESS_KEY_ID")
    access_key_secret = _env("ALIYUN_DM_ACCESS_KEY_SECRET")
    account_name = _env("ALIYUN_DM_ACCOUNT_NAME")
    if not (access_key_id and access_key_secret and account_name):
        raise MailNotConfigured(
            "DirectMail 未配置完整:需要 ALIYUN_DM_ACCESS_KEY_ID / "
            "ALIYUN_DM_ACCESS_KEY_SECRET / ALIYUN_DM_ACCOUNT_NAME"
        )
    body_field = "HtmlBody" if html else "TextBody"
    body_value = html if html is not None else text
    # 控制台未配置回信地址时需置 false,否则 SingleSendMail 会报错;
    # 已配置回信地址时保持 true(收件人回复走控制台地址)。
    reply_to = _env("ALIYUN_DM_REPLY_TO") or "true"
    if reply_to not in ("true", "false"):
        reply_to = "true"
    params: dict[str, str] = {
        "AccessKeyId": access_key_id,
        "AccountName": account_name,
        "Action": "SingleSendMail",
        "AddressType": "1",  # 1 = 使用发信地址(管理控制台配置),0 = 随机账号
        "Format": "JSON",
        "RegionId": _env("ALIYUN_DM_REGION") or "cn-hangzhou",
        "ReplyToAddress": reply_to,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": str(uuid.uuid4()),
        "SignatureVersion": "1.0",
        "Subject": subject,
        "Timestamp": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ToAddress": to,
        "Version": DM_API_VERSION,
        body_field: body_value,
    }
    params["Signature"] = _dm_signature(params, access_key_secret)

    url = "https://" + _dm_endpoint() + "/"
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=DM_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - 网络/解析失败统一转为 MailSendError
        raise MailSendError(f"DirectMail 请求失败:{exc}") from exc
    if isinstance(payload, dict) and payload.get("Code") not in (None, "", "OK", "Success"):
        raise MailSendError(
            f"DirectMail 返回错误:Code={payload.get('Code')} Message={payload.get('Message')}"
        )
    logger.info("DirectMail 发送成功:to=%s RequestId=%s", to, payload.get("RequestId"))


# ---- SMTP 备用通道 ----


def _send_smtp(to: str, subject: str, text: str, html: str | None) -> None:
    host = _env("SMTP_HOST")
    user = _env("SMTP_USER")
    password = _env("SMTP_PASS")
    if not (host and user and password):
        raise MailNotConfigured("SMTP 未配置完整:需要 SMTP_HOST / SMTP_USER / SMTP_PASS")
    sender = _env("SMTP_FROM") or user
    use_starttls = _flag("SMTP_TLS")
    if use_starttls:
        server = smtplib.SMTP(host, int(_env("SMTP_PORT") or "587"), timeout=15)
        server.starttls()
    else:
        server = smtplib.SMTP_SSL(host, int(_env("SMTP_PORT") or "465"), timeout=15)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr(("Litnebula", sender))
    msg["To"] = to
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    if html:
        msg.attach(MIMEText(html, "html", "utf-8"))
    with server:
        server.login(user, password)
        server.sendmail(sender, [to], msg.as_string())
    logger.info("SMTP 发送成功:to=%s subject=%s", to, subject)

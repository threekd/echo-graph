"""账号体系:邮箱+密码注册/登录,Argon2 密码哈希,httpOnly Cookie 会话。

- 密码:argon2id(依赖 argon2-cffi),库中只存哈希,不存明文。
- 会话:随机 token 只放在 httpOnly + SameSite=Lax Cookie 中;数据库只存其
  SHA-256 哈希,泄露 DB 也无法伪造会话;30 天过期,登出立即失效。
- 注册人机验证:Cloudflare Turnstile(服务端 siteverify)。生产环境必须配置
  TURNSTILE_SECRET_KEY——未配置且未显式设置 TURNSTILE_ALLOW_SKIP=1 时注册
  按失败处理(fail-closed),避免生产漏配导致机器人可随意注册;仅本地开发
  用 TURNSTILE_ALLOW_SKIP=1 临时放行。
- 限流:注册/登录按 IP 滑动窗口,复用 app.ratelimit(单 worker 精确)。
- 邮箱验证与密码找回:可插拔邮件发送器(app/mailer.py,阿里云 DirectMail /
  SMTP);EMAIL_VERIFY_REQUIRED=1 时新注册需点击邮件验证链接才能登录,
  引导管理员在验证通过后才提权;忘记密码走一次性 reset 令牌,重置后吊销全部会话。
- CSRF:SameSite=Lax 之外的补充防线由全局中间件(app/security.py)统一执行——
  所有状态变更请求(含本模块的 register/login/logout/PATCH /me)带 Origin 头时
  必须同源,否则 403;此处不再逐端点重复校验。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import urllib.parse
import urllib.request

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, HTTPException, Request, Response

from app import db_sqlite, mailer
from app.ratelimit import client_ip, sliding_limited

logger = logging.getLogger("echo_graph")

SESSION_COOKIE = "echo_graph_session"
SESSION_DAYS = 30
# 引导管理员邮箱:该邮箱注册自动提权为 admin(首个管理员引导机制)。
# 公共星云/官方图谱概念已于 2026-08-28 移除:admin 的星云与其他用户星云
# 数据语义完全一致,不再作为默认视图。
BOOTSTRAP_EMAIL = os.getenv("ADMIN_BOOTSTRAP_EMAIL", "").strip().lower()
# 每 IP 每小时注册 / 登录尝试上限(与贡献限流同一套进程内滑动窗口)
REGISTER_LIMIT = 10
LOGIN_LIMIT = 30
VERIFY_LIMIT = 10
RESEND_LIMIT = 5
FORGOT_LIMIT = 5
RESET_LIMIT = 10
RATE_WINDOW_SECONDS = 3600.0
# 邮箱验证/密码重置一次性令牌有效期(小时)
TOKEN_TTL_HOURS = 24
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# 用户名:仅 ASCII 英文字母/数字/下划线,5-32 位;唯一性对 ASCII 大小写不敏感(DB 索引 COLLATE NOCASE)
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")
NICKNAME_MAX = 32
BIO_MAX = 500

_ph = PasswordHasher()


_now = db_sqlite.now_iso
_new_id = db_sqlite.new_uuid


def _expires_at() -> str:
    return (
        dt.datetime.now(dt.UTC) + dt.timedelta(days=SESSION_DAYS)
    ).isoformat(timespec="seconds")


def bootstrap_email() -> str:
    return BOOTSTRAP_EMAIL


def is_bootstrap_email(email: str) -> bool:
    return bool(BOOTSTRAP_EMAIL) and normalize_email(email) == BOOTSTRAP_EMAIL


def admin_user_id() -> str | None:
    """引导管理员(ADMIN_BOOTSTRAP_EMAIL)的用户 id;尚未注册时为 None。"""
    if not BOOTSTRAP_EMAIL:
        return None
    with db_sqlite._db() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (BOOTSTRAP_EMAIL,)).fetchone()
    return row["id"] if row else None


def bootstrap_admin() -> dict | None:
    """启动时执行引导:为 ADMIN_BOOTSTRAP_EMAIL 补 admin 角色(首个管理员引导)。

    开启邮箱验证(EMAIL_VERIFY_REQUIRED=1)时,只提权已通过邮箱验证的用户,
    防止引导管理员邮箱被抢先注册后不经验证直接获得 admin 权限。
    """
    if not BOOTSTRAP_EMAIL:
        return None
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? AND email_verified_at IS NOT NULL",
            (BOOTSTRAP_EMAIL,),
        ).fetchone()
        if row is None:
            return None
        if row["role"] != "admin":
            conn.execute(
                "UPDATE users SET role = 'admin', updatedAt = ? WHERE id = ?",
                (_now(), row["id"]),
            )
    return {"id": row["id"], "email": row["email"], "role": "admin"}


# ---- 密码与邮箱 ----


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerificationError:
        return False


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def validate_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value)) and len(value) <= 254


def email_verify_flag() -> bool:
    """EMAIL_VERIFY_REQUIRED 开关原值(即使邮件服务未配置也返回 True)。"""
    return os.getenv("EMAIL_VERIFY_REQUIRED", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def email_verify_required() -> bool:
    """邮箱验证是否实际生效:开关打开且邮件发送器已配置。"""
    return email_verify_flag() and mailer.mailer_configured()


def validate_password(value: str) -> str | None:
    """返回 None 表示合法,否则返回错误文案。"""
    if not value:
        return "密码不能为空"
    if len(value) < 8:
        return "密码至少 8 位"
    if len(value) > 128:
        return "密码过长(最多 128 位)"
    return None


def normalize_username(value: str | None) -> str:
    """规范化用户名:去首尾空白;必填(空值报错);校验格式与长度。"""
    value = str(value or "").strip()
    if not value:
        raise ValueError("用户名不能为空")
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("用户名仅支持 5-32 位英文字母/数字/下划线")
    return value


def normalize_nickname(value) -> str | None:
    """规范化昵称:去首尾空白;空串归一为 None。"""
    value = str(value or "").strip()
    if not value:
        return None
    if len(value) > NICKNAME_MAX:
        raise ValueError(f"昵称过长(最多 {NICKNAME_MAX} 字)")
    return value


def normalize_bio(value) -> str | None:
    """规范化简介(长文本):去首尾空白;空串归一为 None。"""
    value = str(value or "").strip()
    if not value:
        return None
    if len(value) > BIO_MAX:
        raise ValueError(f"简介过长(最多 {BIO_MAX} 字)")
    return value


# ---- Cloudflare Turnstile ----


def _turnstile_siteverify(secret: str, token: str, remote_ip: str) -> bool:
    """调用 Turnstile siteverify 接口;验证服务不可达时保守拒绝。

    remoteip 为可选参数且必须与 Cloudflare 侧的访客 IP 一致——本地开发/内网环境下
    client_ip 是回环或私有地址,传入反而可能导致校验失败,因此仅对公网 IP 传该字段。
    """
    fields = {"secret": secret, "response": token}
    try:
        addr = ipaddress.ip_address(remote_ip)
        if not (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        ):
            fields["remoteip"] = remote_ip
    except ValueError:
        pass  # 无法解析的 IP 一律不传 remoteip
    data = urllib.parse.urlencode(fields).encode("utf-8")
    try:
        with urllib.request.urlopen(TURNSTILE_VERIFY_URL, data=data, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 网络/解析失败按未通过处理
        logger.warning("Turnstile siteverify 请求失败:%s", exc)
        return False
    if not payload.get("success"):
        logger.warning("Turnstile 校验失败:error-codes=%s", payload.get("error-codes"))
    return bool(payload.get("success"))


def verify_turnstile(token: str | None, remote_ip: str) -> bool:
    """校验人机验证 token。

    未配置 TURNSTILE_SECRET_KEY 时默认拒绝(fail-closed);仅当显式设置
    TURNSTILE_ALLOW_SKIP=1(本地开发)时才跳过验证。
    """
    secret = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
    if not secret:
        if os.getenv("TURNSTILE_ALLOW_SKIP", "").strip().lower() in (
            "1", "true", "yes", "on",
        ):
            logger.warning(
                "TURNSTILE_SECRET_KEY 未配置,且 TURNSTILE_ALLOW_SKIP=1,"
                "注册人机验证已跳过(仅限本地开发)"
            )
            return True
        logger.error(
            "TURNSTILE_SECRET_KEY 未配置,注册人机验证按失败处理(fail-closed)"
        )
        return False
    if not token:
        return False
    return _turnstile_siteverify(secret, token, remote_ip)


# ---- 会话 ----


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _email_token_expires_at() -> str:
    return (
        dt.datetime.now(dt.UTC) + dt.timedelta(hours=TOKEN_TTL_HOURS)
    ).isoformat(timespec="seconds")


def create_email_token(user_id: str, purpose: str) -> str:
    """为指定用户创建一次性邮件令牌(verify/reset),返回原始令牌。

    库里只存 SHA-256 哈希;同一用户同用途的旧未用令牌作废(重发即失效)。
    """
    token = secrets.token_urlsafe(32)
    now = _now()
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        # 顺手清理过期令牌,防止表无限增长
        conn.execute("DELETE FROM email_tokens WHERE expires_at < ?", (now,))
        conn.execute(
            "DELETE FROM email_tokens WHERE user_id = ? AND purpose = ? AND used_at IS NULL",
            (user_id, purpose),
        )
        conn.execute(
            "INSERT INTO email_tokens (id, token_hash, user_id, purpose, expires_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (_new_id(), _token_hash(token), user_id, purpose, _email_token_expires_at(), now),
        )
    return token


def consume_email_token(token: str, purpose: str) -> str | None:
    """校验并消费一次性邮件令牌;成功返回 user_id,失败/过期/已用返回 None。"""
    if not token:
        return None
    now = _now()
    token_hash = _token_hash(token)
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT user_id FROM email_tokens"
            " WHERE token_hash = ? AND purpose = ? AND used_at IS NULL AND expires_at >= ?",
            (token_hash, purpose, now),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE email_tokens SET used_at = ? WHERE token_hash = ?", (now, token_hash)
        )
    return row["user_id"]


def _verification_link(token: str) -> str:
    return f"{mailer.site_base_url().rstrip('/')}/#v=verify:{token}"


def _reset_link(token: str) -> str:
    return f"{mailer.site_base_url().rstrip('/')}/#v=reset:{token}"


def send_verification_email(user: dict) -> None:
    """发送注册邮箱验证邮件(创建并写入一次性 verify 令牌)。"""
    token = create_email_token(user["id"], "verify")
    url = _verification_link(token)
    subject = "验证你的邮箱 · Litnebula 回声图谱"
    text = (
        "欢迎加入 Litnebula 回声图谱!\n\n"
        f"请点击以下链接完成邮箱验证({TOKEN_TTL_HOURS} 小时内有效):\n{url}\n\n"
        "如非本人操作,请忽略本邮件。"
    )
    html_body = (
        "<p>欢迎加入 Litnebula 回声图谱!</p>"
        f'<p>请点击 <a href="{html.escape(url)}">此链接</a> 完成邮箱验证'
        f"({TOKEN_TTL_HOURS} 小时内有效)。</p>"
        "<p>如非本人操作,请忽略本邮件。</p>"
    )
    mailer.send_mail(user["email"], subject, text, html_body)


def send_reset_email(user: dict) -> None:
    """发送密码重置邮件(创建并写入一次性 reset 令牌)。"""
    token = create_email_token(user["id"], "reset")
    url = _reset_link(token)
    subject = "重置密码 · Litnebula 回声图谱"
    text = (
        "我们收到了你的密码重置请求。\n\n"
        f"请点击以下链接设置新密码({TOKEN_TTL_HOURS} 小时内有效):\n{url}\n\n"
        "如非本人操作,请忽略本邮件,你的密码不会被修改。"
    )
    html_body = (
        "<p>我们收到了你的密码重置请求。</p>"
        f'<p>请点击 <a href="{html.escape(url)}">此链接</a> 设置新密码'
        f"({TOKEN_TTL_HOURS} 小时内有效)。</p>"
        "<p>如非本人操作,请忽略本邮件,你的密码不会被修改。</p>"
    )
    mailer.send_mail(user["email"], subject, text, html_body)


def create_session(user_id: str) -> str:
    """创建会话并返回原始 token(仅此返回值可设置 Cookie)。"""
    token = secrets.token_urlsafe(32)
    now = _now()
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        # 每次创建时顺手清理过期会话,防止 sessions 表无限增长
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO sessions (id, token_hash, user_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (_new_id(), _token_hash(token), user_id, now, _expires_at()),
        )
    return token


def delete_session(token: str | None) -> None:
    if not token:
        return
    with db_sqlite._db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def _user_payload(row) -> dict:
    """用户行 → 接口返回的用户对象(me / login / 会话共用,字段口径一致)。"""
    return {
        "id": row["id"],
        "email": row["email"],
        "username": row["username"],
        "nickname": row["nickname"],
        "bio": row["bio"],
        "role": row["role"],
        "space_visibility": row["space_visibility"],
        "vip": bool(row["vip"]),
        "email_verified_at": row["email_verified_at"],
    }


def _user_from_session(conn, token: str | None) -> dict | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT u.id, u.email, u.username, u.nickname, u.role, u.space_visibility,"
        " u.bio, u.status, u.vip, u.email_verified_at, s.expires_at"
        " FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE s.token_hash = ?",
        (_token_hash(token),),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < _now():
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
        return None
    if row["status"] != "active":
        return None
    return _user_payload(row)


def current_user(token: str | None) -> dict | None:
    with db_sqlite._db() as conn:
        return _user_from_session(conn, token)


def require_user(request: Request) -> dict:
    """FastAPI 依赖:登录用户(未登录 401)。"""
    user = current_user(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_admin(request: Request) -> dict:
    """FastAPI 依赖:管理员(未登录 401,非 admin 403)。"""
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_admin_or_vip(request: Request) -> dict:
    """FastAPI 依赖:管理员或 VIP 用户(未登录 401,普通用户 403)。"""
    user = require_user(request)
    if user["role"] != "admin" and not user.get("vip"):
        raise HTTPException(status_code=403, detail="需要管理员或 VIP 权限")
    return user


# ---- 注册 / 登录 ----


def register(
    email: str,
    password: str,
    username: str | None = None,
    nickname: str | None = None,
    bio: str | None = None,
) -> dict:
    """创建用户;校验失败抛 ValueError。密码哈希在写锁外计算。"""
    email = normalize_email(email)
    if not validate_email(email):
        raise ValueError("邮箱格式不正确")
    password_error = validate_password(password)
    if password_error:
        raise ValueError(password_error)
    username = normalize_username(username)
    nickname = normalize_nickname(nickname)
    bio = normalize_bio(bio)
    password_hash = hash_password(password)
    now = _now()
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        if exists:
            raise ValueError("该邮箱已注册,请直接登录")
        taken = conn.execute(
            "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if taken:
            raise ValueError("用户名已被使用,请换一个")
        user_id = _new_id()
        # 开启邮箱验证时,引导管理员在验证通过后提权(verify_email 内处理);
        # 未开启时保持「注册即 admin」的旧引导语义。
        role = (
            "admin"
            if is_bootstrap_email(email) and not email_verify_flag()
            else "user"
        )
        # EMAIL_VERIFY_REQUIRED=0 时注册即信任:email_verified_at 标记为注册时间
        # (与存量用户迁移回填 createdAt 的策略一致;=1 时保持 NULL,须验证通过)
        verified_at = None if email_verify_flag() else now
        conn.execute(
            "INSERT INTO users (id, email, password_hash, username, nickname, bio, role,"
            " status, email_verified_at, createdAt, updatedAt)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
            (user_id, email, password_hash, username, nickname, bio, role, verified_at, now, now),
        )
    return {
        "id": user_id,
        "email": email,
        "username": username,
        "nickname": nickname,
        "bio": bio,
        "role": role,
        "space_visibility": "public",
        "vip": False,
        "email_verified_at": verified_at,
    }


def login(identifier: str, password: str) -> dict | None:
    """按邮箱或用户名(ASCII 大小写不敏感)校验密码;失败统一返回 None,避免泄露账号存在性。"""
    identifier = normalize_email(identifier)  # 去首尾空白 + 小写(用户名按 NOCASE 匹配)
    if not identifier or not password:
        return None
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? OR username = ? COLLATE NOCASE",
            (identifier, identifier),
        ).fetchone()
    if row is None or row["status"] != "active":
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return _user_payload(row)


# ---- HTTP 路由 ----


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    secure = os.getenv("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes", "on")
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/config")
def auth_config() -> dict:
    """前端登录/注册所需配置(站点密钥;未配置时前端不渲染 Turnstile)。

    landingSpace:游客落地星云用户名(.env LANDING_SPACE,可空)——用户名只作为
    服务端配置,不出现在 URL / 界面,避免暴露可用作登录的账号标识。
    """
    return {
        "turnstileSiteKey": os.getenv("TURNSTILE_SITE_KEY", "").strip(),
        "landingSpace": os.getenv("LANDING_SPACE", "").strip() or None,
    }


@router.post("/register")
def register_endpoint(body: dict, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    if sliding_limited(f"register:{ip}", REGISTER_LIMIT, RATE_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="注册过于频繁,请稍后再试")
    turnstile_token = (body or {}).get("turnstile") or None
    if not verify_turnstile(turnstile_token, ip):
        raise HTTPException(status_code=400, detail="人机验证失败,请重试")
    try:
        user = register(
            str((body or {}).get("email") or ""),
            str((body or {}).get("password") or ""),
            username=(body or {}).get("username"),
            nickname=(body or {}).get("nickname"),
            bio=(body or {}).get("bio"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    requires_verification = False
    if email_verify_flag():
        if not mailer.mailer_configured():
            # fail-closed:开关已打开但邮件服务未配置,回滚刚创建的用户并明确报错,
            # 避免留下无法收到验证邮件、永远登录不了的孤儿账号。
            _delete_user(user["id"])
            raise HTTPException(
                status_code=503,
                detail="邮件服务未配置,暂时无法注册新账号,请联系管理员",
            )
        try:
            send_verification_email(user)
        except Exception as exc:  # noqa: BLE001 - 发送失败回滚并提示重试
            logger.error("注册验证邮件发送失败:%s", exc)
            _delete_user(user["id"])
            raise HTTPException(
                status_code=502, detail="验证邮件发送失败,请稍后再试"
            ) from exc
        requires_verification = True
    if not requires_verification:
        _set_session_cookie(response, create_session(user["id"]))
    return {"ok": True, "user": user, "requiresVerification": requires_verification}


def _delete_user(user_id: str) -> None:
    """回滚注册失败时刚创建的用户(邮箱验证未开启时不会走到这里)。"""
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        conn.execute("DELETE FROM email_tokens WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


@router.post("/login")
def login_endpoint(body: dict, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    if sliding_limited(f"login:{ip}", LOGIN_LIMIT, RATE_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="登录尝试过于频繁,请稍后再试")
    identifier = str((body or {}).get("email") or "")  # 兼容前端字段名:可为邮箱或用户名
    password = str((body or {}).get("password") or "")
    if not identifier or not password:
        raise HTTPException(status_code=400, detail="请输入邮箱/用户名和密码")
    user = login(identifier, password)
    if user is None:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if email_verify_required() and not user.get("email_verified_at"):
        raise HTTPException(status_code=403, detail="邮箱尚未验证,请先查收验证邮件")
    _set_session_cookie(response, create_session(user["id"]))
    return {"ok": True, "user": user}


@router.post("/verify-email")
def verify_email_endpoint(body: dict, request: Request, response: Response) -> dict:
    """邮箱验证深链:消费一次性 verify 令牌,验证通过即登录。"""
    ip = client_ip(request)
    if sliding_limited(f"verify:{ip}", VERIFY_LIMIT, RATE_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="验证请求过于频繁,请稍后再试")
    token = str((body or {}).get("token") or "")
    user = verify_email(token)
    if user is None:
        raise HTTPException(status_code=400, detail="验证链接无效或已过期,请重新发送")
    _set_session_cookie(response, create_session(user["id"]))
    return {"ok": True, "user": user}


def verify_email(token: str) -> dict | None:
    """核心:消费 verify 令牌,置 email_verified_at;引导管理员同步提权。"""
    user_id = consume_email_token(token, "verify")
    if user_id is None:
        return None
    now = _now()
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND status = 'active'", (user_id,)
        ).fetchone()
        if row is None:
            return None
        if not row["email_verified_at"]:
            conn.execute(
                "UPDATE users SET email_verified_at = ?, updatedAt = ? WHERE id = ?",
                (now, now, user_id),
            )
        # 引导管理员在邮箱验证通过后提权(未开启验证时注册阶段已提权,
        # 这里保持幂等兜底)。
        if is_bootstrap_email(row["email"]) and row["role"] != "admin":
            conn.execute(
                "UPDATE users SET role = 'admin', updatedAt = ? WHERE id = ?",
                (now, user_id),
            )
    with db_sqlite._db() as conn:
        fresh = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return _user_payload(fresh) if fresh else None


@router.post("/resend-verification")
def resend_verification_endpoint(body: dict, request: Request) -> dict:
    """重发验证邮件(仅 EMAIL_VERIFY_REQUIRED 开启时有效;返回不区分账号是否存在)。"""
    ip = client_ip(request)
    if sliding_limited(f"resend:{ip}", RESEND_LIMIT, RATE_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="发送过于频繁,请稍后再试")
    if not email_verify_flag():
        return {"ok": True}
    if not mailer.mailer_configured():
        raise HTTPException(status_code=503, detail="邮件服务未配置,请联系管理员")
    email = normalize_email((body or {}).get("email"))
    if email:
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ? AND status = 'active'",
                (email,),
            ).fetchone()
        if row and not row["email_verified_at"]:
            try:
                send_verification_email(dict(row))
            except Exception as exc:  # noqa: BLE001 - 发送失败给出明确错误
                logger.error("重发验证邮件失败:%s", exc)
                raise HTTPException(
                    status_code=502, detail="验证邮件发送失败,请稍后再试"
                ) from exc
    return {"ok": True}


@router.post("/forgot-password")
def forgot_password_endpoint(body: dict, request: Request) -> dict:
    """忘记密码:向已注册邮箱发送重置链接;返回不区分账号是否存在。"""
    ip = client_ip(request)
    if sliding_limited(f"forgot:{ip}", FORGOT_LIMIT, RATE_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="发送过于频繁,请稍后再试")
    if not mailer.mailer_configured():
        raise HTTPException(status_code=503, detail="邮件服务未配置,请联系管理员")
    email = normalize_email((body or {}).get("email"))
    if email:
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ? AND status = 'active'",
                (email,),
            ).fetchone()
        if row:
            try:
                send_reset_email(dict(row))
            except Exception as exc:  # noqa: BLE001 - 发送失败给出明确错误
                logger.error("密码重置邮件发送失败:%s", exc)
                raise HTTPException(
                    status_code=502, detail="重置邮件发送失败,请稍后再试"
                ) from exc
    return {"ok": True}


@router.post("/reset-password")
def reset_password_endpoint(body: dict, request: Request) -> dict:
    """密码重置:消费一次性 reset 令牌,更新密码并吊销该用户全部会话。"""
    ip = client_ip(request)
    if sliding_limited(f"reset:{ip}", RESET_LIMIT, RATE_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="重置请求过于频繁,请稍后再试")
    token = str((body or {}).get("token") or "")
    password = str((body or {}).get("password") or "")
    password_error = validate_password(password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)
    user_id = consume_email_token(token, "reset")
    if user_id is None:
        raise HTTPException(status_code=400, detail="重置链接无效或已过期,请重新申请")
    password_hash = hash_password(password)
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, updatedAt = ? WHERE id = ?",
            (password_hash, _now(), user_id),
        )
        # 重置密码后吊销全部会话(含可能已泄露的旧会话)
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return {"ok": True}


@router.post("/logout")
def logout_endpoint(request: Request, response: Response) -> dict:
    delete_session(request.cookies.get(SESSION_COOKIE))
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    user = current_user(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return {"user": user}


@router.patch("/me")
def update_me(body: dict, request: Request) -> dict:
    """用户资料更新:nickname / bio / space_visibility(至少一项)。用户名不可自行修改。"""
    user = current_user(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    payload = body or {}
    updates: dict[str, str | None] = {}
    if "username" in payload:
        raise HTTPException(status_code=400, detail="用户名不可自行修改")
    visibility = payload.get("space_visibility")
    if visibility is not None:
        if visibility not in ("public", "private"):
            raise HTTPException(status_code=400, detail="space_visibility 仅支持 public / private")
        updates["space_visibility"] = visibility
    if "nickname" in payload:
        try:
            updates["nickname"] = normalize_nickname(payload.get("nickname"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "bio" in payload:
        try:
            updates["bio"] = normalize_bio(payload.get("bio"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updates:
        return {"ok": True, "user": user}
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        sets = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE users SET {sets}, updatedAt = ? WHERE id = ?",
            [*updates.values(), _now(), user["id"]],
        )
    user.update(updates)
    return {"ok": True, "user": user}

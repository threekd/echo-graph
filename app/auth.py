"""账号体系:邮箱+密码注册/登录,Argon2 密码哈希,httpOnly Cookie 会话。

- 密码:argon2id(依赖 argon2-cffi),库中只存哈希,不存明文。
- 会话:随机 token 只放在 httpOnly + SameSite=Lax Cookie 中;数据库只存其
  SHA-256 哈希,泄露 DB 也无法伪造会话;30 天过期,登出立即失效。
- 注册人机验证:Cloudflare Turnstile(服务端 siteverify)。未配置
  TURNSTILE_SECRET_KEY 时跳过验证(便于本地开发),生产环境务必配置。
- 限流:注册/登录按 IP 滑动窗口,复用 app.ratelimit(单 worker 精确)。
- CSRF:SameSite=Lax 之外的补充防线——带 Origin 头的状态变更请求必须同源。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import secrets
import urllib.parse
import urllib.request
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, HTTPException, Request, Response

from app import db_sqlite
from app.ratelimit import client_ip, sliding_limited

logger = logging.getLogger("echo_graph")

SESSION_COOKIE = "echo_graph_session"
SESSION_DAYS = 30
# 引导管理员邮箱:该邮箱注册自动提权为 admin,并认领全部未归属数据(公共星云)
BOOTSTRAP_EMAIL = os.getenv("ADMIN_BOOTSTRAP_EMAIL", "").strip().lower()
# 每 IP 每小时注册 / 登录尝试上限(与贡献限流同一套进程内滑动窗口)
REGISTER_LIMIT = 10
LOGIN_LIMIT = 30
RATE_WINDOW_SECONDS = 3600.0
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_ph = PasswordHasher()


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _new_id() -> str:
    try:
        return str(uuid.uuid7())
    except AttributeError:
        return str(uuid.uuid4())


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


def claim_public_rows(conn, admin_id: str) -> int:
    """把尚未认领(owner_id 为空)的业务行划归引导管理员(公共星云)。"""
    total = 0
    for table in ("authors", "works", "edges"):
        cur = conn.execute(
            f"UPDATE {table} SET owner_id = ? WHERE owner_id IS NULL", (admin_id,)
        )
        total += cur.rowcount
    return total


def bootstrap_admin() -> dict | None:
    """启动时执行引导:补 admin 角色并认领未归属数据。返回管理员用户(若有)。"""
    if not BOOTSTRAP_EMAIL:
        return None
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (BOOTSTRAP_EMAIL,)
        ).fetchone()
        if row is None:
            return None
        if row["role"] != "admin":
            conn.execute(
                "UPDATE users SET role = 'admin', updatedAt = ? WHERE id = ?",
                (_now(), row["id"]),
            )
        claim_public_rows(conn, row["id"])
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


def validate_password(value: str) -> str | None:
    """返回 None 表示合法,否则返回错误文案。"""
    if not value:
        return "密码不能为空"
    if len(value) < 8:
        return "密码至少 8 位"
    if len(value) > 128:
        return "密码过长(最多 128 位)"
    return None


# ---- Cloudflare Turnstile ----


def _turnstile_siteverify(secret: str, token: str, remote_ip: str) -> bool:
    """调用 Turnstile siteverify 接口;验证服务不可达时保守拒绝。"""
    data = urllib.parse.urlencode(
        {"secret": secret, "response": token, "remoteip": remote_ip}
    ).encode("utf-8")
    try:
        with urllib.request.urlopen(TURNSTILE_VERIFY_URL, data=data, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 网络/解析失败按未通过处理
        logger.warning("Turnstile siteverify 请求失败:%s", exc)
        return False
    return bool(payload.get("success"))


def verify_turnstile(token: str | None, remote_ip: str) -> bool:
    """校验人机验证 token。未配置密钥时跳过(仅限本地开发)。"""
    secret = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
    if not secret:
        logger.warning("TURNSTILE_SECRET_KEY 未配置,注册人机验证已跳过")
        return True
    if not token:
        return False
    return _turnstile_siteverify(secret, token, remote_ip)


# ---- 会话 ----


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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


def _user_from_session(conn, token: str | None) -> dict | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT u.id, u.email, u.role, u.space_visibility, u.status, s.expires_at"
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
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "space_visibility": row["space_visibility"],
    }


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


# ---- 注册 / 登录 ----


def register(email: str, password: str) -> dict:
    """创建用户;校验失败抛 ValueError。密码哈希在写锁外计算。"""
    email = normalize_email(email)
    if not validate_email(email):
        raise ValueError("邮箱格式不正确")
    password_error = validate_password(password)
    if password_error:
        raise ValueError(password_error)
    password_hash = hash_password(password)
    now = _now()
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        if exists:
            raise ValueError("该邮箱已注册,请直接登录")
        user_id = _new_id()
        role = "admin" if is_bootstrap_email(email) else "user"
        conn.execute(
            "INSERT INTO users (id, email, password_hash, role, status, createdAt, updatedAt)"
            " VALUES (?, ?, ?, ?, 'active', ?, ?)",
            (user_id, email, password_hash, role, now, now),
        )
        if role == "admin":
            claim_public_rows(conn, user_id)
    return {"id": user_id, "email": email, "role": role, "space_visibility": "public"}


def login(email: str, password: str) -> dict | None:
    """校验邮箱与密码;失败(不存在/禁用/密码错误)统一返回 None,避免泄露账号存在性。"""
    email = normalize_email(email)
    if not email or not password:
        return None
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    if row is None or row["status"] != "active":
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "space_visibility": row["space_visibility"],
    }


# ---- HTTP 路由 ----


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _check_same_origin(request: Request) -> None:
    """CSRF 补充防线:带 Origin 头的状态变更请求必须与本站同源。"""
    origin = request.headers.get("origin")
    if not origin:
        return
    expected = str(request.base_url).rstrip("/")
    if origin.rstrip("/") != expected:
        raise HTTPException(status_code=403, detail="跨站请求被拒绝")


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
    """前端注册页所需配置(站点密钥;未配置时前端不渲染 Turnstile)。"""
    return {"turnstileSiteKey": os.getenv("TURNSTILE_SITE_KEY", "").strip()}


@router.post("/register")
def register_endpoint(body: dict, request: Request, response: Response) -> dict:
    _check_same_origin(request)
    ip = client_ip(request)
    if sliding_limited(f"register:{ip}", REGISTER_LIMIT, RATE_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="注册过于频繁,请稍后再试")
    turnstile_token = (body or {}).get("turnstile") or None
    if not verify_turnstile(turnstile_token, ip):
        raise HTTPException(status_code=400, detail="人机验证失败,请重试")
    try:
        user = register(str((body or {}).get("email") or ""), str((body or {}).get("password") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_session_cookie(response, create_session(user["id"]))
    return {"ok": True, "user": user}


@router.post("/login")
def login_endpoint(body: dict, request: Request, response: Response) -> dict:
    _check_same_origin(request)
    ip = client_ip(request)
    if sliding_limited(f"login:{ip}", LOGIN_LIMIT, RATE_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="登录尝试过于频繁,请稍后再试")
    email = str((body or {}).get("email") or "")
    password = str((body or {}).get("password") or "")
    if not email or not password:
        raise HTTPException(status_code=400, detail="请输入邮箱和密码")
    user = login(email, password)
    if user is None:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    _set_session_cookie(response, create_session(user["id"]))
    return {"ok": True, "user": user}


@router.post("/logout")
def logout_endpoint(request: Request, response: Response) -> dict:
    _check_same_origin(request)
    delete_session(request.cookies.get(SESSION_COOKIE))
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    user = current_user(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return {"user": user}

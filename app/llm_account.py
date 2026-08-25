"""system_llm 专用账号(AI 数据管线写入空间)。

- 邮箱/用户名固定,role='user'、status='active'、space_visibility='private';
- 密码为随机值且不暴露:机器账号不用于登录,审核由 admin 在管理端完成
  (见 app/llm_review.py),避免共享凭证与审计失真。
- 账号创建/查询收敛在本模块,CLI(app/ai_assistant/tools/llm_space.py)与管理端共用。
"""

from __future__ import annotations

import secrets

from app import db_sqlite
from app.auth import hash_password

SYSTEM_LLM_EMAIL = "system_llm@echo.local"
SYSTEM_LLM_USERNAME = "system_llm"
SYSTEM_LLM_NICKNAME = "AI 数据管道"
SYSTEM_LLM_BIO = "AI 数据提取管线专用写入空间(草稿,待 admin 审核发布)"

now_iso = db_sqlite.now_iso


def ensure_system_llm() -> str:
    """确保 system_llm 账号存在并返回其用户 id(不存在则创建)。"""
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ? OR username = ? COLLATE NOCASE",
            (SYSTEM_LLM_EMAIL, SYSTEM_LLM_USERNAME),
        ).fetchone()
        if row:
            return row["id"]
        user_id = db_sqlite.new_uuid()
        password_hash = hash_password(secrets.token_urlsafe(32))
        now = now_iso()
        conn.execute(
            "INSERT INTO users (id, email, password_hash, username, nickname, bio, role,"
            " status, space_visibility, createdAt, updatedAt)"
            " VALUES (?, ?, ?, ?, ?, ?, 'user', 'active', 'private', ?, ?)",
            (
                user_id,
                SYSTEM_LLM_EMAIL,
                password_hash,
                SYSTEM_LLM_USERNAME,
                SYSTEM_LLM_NICKNAME,
                SYSTEM_LLM_BIO,
                now,
                now,
            ),
        )
        return user_id


def get_system_llm_id() -> str | None:
    """返回 system_llm 用户 id;账号不存在时返回 None。"""
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", (SYSTEM_LLM_EMAIL,)
        ).fetchone()
    return row["id"] if row else None

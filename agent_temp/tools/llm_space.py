#!/usr/bin/env python3

"""system_llm 专用账号与批次登记簿公共工具。

- 确保 system_llm 账号存在（AI 数据写入空间，space_visibility=private）
- 批次登记簿：每次 ingest 生成一个批次 JSON（agent_temp/output/batches/<id>.json），
  记录该批的作者/作品/涟漪草稿与映射，供 review_publish.py 审核与发布。
"""

from __future__ import annotations

import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
_AGENT_TEMP_DIR = _TOOLS_DIR.parent
_REPO_ROOT = _AGENT_TEMP_DIR.parent
for _path in (_TOOLS_DIR, _AGENT_TEMP_DIR, _REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app import db_sqlite  # noqa: E402
from app.auth import hash_password  # noqa: E402

SYSTEM_LLM_EMAIL = "system_llm@echo.local"
SYSTEM_LLM_USERNAME = "system_llm"
SYSTEM_LLM_NICKNAME = "AI 数据管道"
BATCH_DIR = _AGENT_TEMP_DIR / "output" / "batches"


def now_iso() -> str:
    """UTC 秒级 ISO-8601 时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_system_llm() -> str:
    """确保 system_llm 账号存在并返回其用户 id（不存在则创建）。"""
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
                "AI 数据提取管线专用写入空间",
                now,
                now,
            ),
        )
        return user_id


def get_system_llm_id() -> str | None:
    """返回 system_llm 用户 id；账号不存在时返回 None。"""
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", (SYSTEM_LLM_EMAIL,)
        ).fetchone()
    return row["id"] if row else None


# ----------------------------------------------------------------------
# 批次登记簿
# ----------------------------------------------------------------------
def batch_path(batch_id: str) -> Path:
    return BATCH_DIR / f"{batch_id}.json"


def save_batch(registry: dict[str, Any]) -> Path:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    path = batch_path(registry["batch_id"])
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_batch(batch_id: str) -> dict[str, Any]:
    path = batch_path(batch_id)
    if not path.exists():
        raise FileNotFoundError(f"批次不存在：{batch_id}（{path}）")
    return json.loads(path.read_text(encoding="utf-8"))


def list_batches() -> list[dict[str, Any]]:
    if not BATCH_DIR.exists():
        return []
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(BATCH_DIR.glob("*.json"))
    ]

#!/usr/bin/env python3

"""system_llm 专用账号与批次登记簿公共工具。

- 账号本身(ensure_system_llm / get_system_llm_id)收敛在 app/llm_account.py,
  本模块仅为 CLI 实验脚本保留入口并继续提供批次登记簿:
  - 每次 ingest 生成一个批次 JSON(agent_temp/output/batches/<id>.json),
    记录该批的作者/作品/涟漪草稿与映射,供 review_publish.py 审核与发布。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.llm_account import (  # noqa: F401  - 复用账号逻辑,CLI 旧调用不破坏
    SYSTEM_LLM_BIO,
    SYSTEM_LLM_EMAIL,
    SYSTEM_LLM_NICKNAME,
    SYSTEM_LLM_USERNAME,
    ensure_system_llm,
    get_system_llm_id,
)

_AGENT_TEMP_DIR = Path(__file__).resolve().parent.parent
BATCH_DIR = _AGENT_TEMP_DIR / "output" / "batches"


def now_iso() -> str:
    """UTC 秒级 ISO-8601 时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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

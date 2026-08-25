#!/usr/bin/env python3
"""一次性回填:为已入库批次补插缺失的 作品-作者 关联(work_authors)。

背景(2026-08-26):build_batch 早期按涟漪原文作者字符串精确匹配批内作者条目,
「中文（English Name）」格式(如「蕾切尔·卡森（Rachel Carson）」)匹配不到补全后
的作者条目(如 Name_CN=蕾切尔·卡逊),导致目标作品 work_authors 缺失、AI 草稿页
目标作者为空。本脚本按与修复后 build_batch 相同的多字段匹配逻辑回填:
    - 对每个 author_refs 为空、但 payload.author 非空的作品条目,在批内作者条目
      中按 Name_CN / Name_EN / originalName 与 原文/中文名/英文名 的交集匹配;
    - 匹配成功后补插 work_authors(work_id=条目 resolved_id, author_id=作者 resolved_id);
    - 幂等:已存在或作品行已删除则跳过;仅新增,不删除、不覆盖。

用法:
    uv run python scripts/backfill_ripple_work_authors.py          # 预演,不写库
    uv run python scripts/backfill_ripple_work_authors.py --apply  # 实际回填
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db_sqlite  # noqa: E402
from app.ai_assistant.tools import llm_space  # noqa: E402
from app.ai_assistant.tools.review_publish import _norm, _split_author_name  # noqa: E402


def _match_author_item(author_name: str, author_items: list[dict]) -> str | None:
    """在批内作者条目中按多字段交集匹配涟漪原文作者,返回 item_id 或 None。"""
    cn, en = _split_author_name(author_name)
    wanted = {_norm(x) for x in (author_name, cn, en) if x}
    for it in author_items:
        p = it.get("payload") or {}
        have = {_norm(p.get(k)) for k in ("Name_CN", "Name_EN", "originalName") if p.get(k)}
        if wanted & have:
            return it.get("item_id")
    return None


def backfill(apply: bool = False) -> dict:
    counts = {"batches": 0, "works_fixed": 0, "inserted": 0, "skipped": 0}
    with db_sqlite._db() as conn:
        for path in sorted(llm_space.BATCH_DIR.glob("*.json")):
            batch = llm_space.read_json(path)
            author_items = [it for it in batch.get("items", []) if it.get("kind") == "author"]
            changed = False
            for it in batch.get("items", []):
                if it.get("kind") != "work" or it.get("author_refs"):
                    continue
                payload = it.get("payload") or {}
                author_name = (payload.get("author") or "").strip()
                if not author_name:
                    continue
                author_item_id = _match_author_item(author_name, author_items)
                if not author_item_id:
                    counts["skipped"] += 1
                    continue
                work_id = it.get("resolved_id")
                author_id = next(
                    (a.get("resolved_id") for a in author_items if a.get("item_id") == author_item_id),
                    None,
                )
                if not work_id or not author_id:
                    counts["skipped"] += 1
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM works WHERE id = ? AND deletedAt IS NULL", (work_id,)
                ).fetchone()
                if not exists:
                    counts["skipped"] += 1
                    continue
                dup = conn.execute(
                    "SELECT 1 FROM work_authors WHERE work_id = ? AND author_id = ?",
                    (work_id, author_id),
                ).fetchone()
                if dup:
                    continue
                if apply:
                    conn.execute(
                        "INSERT INTO work_authors (work_id, author_id) VALUES (?, ?)",
                        (work_id, author_id),
                    )
                it.setdefault("author_refs", []).append(author_item_id)
                counts["inserted"] += 1
                counts["works_fixed"] += 1
                changed = True
            if changed:
                counts["batches"] += 1
                if apply:
                    llm_space.save_batch(batch)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="回填缺失的涟漪作品-作者关联(work_authors)")
    parser.add_argument("--apply", action="store_true", help="实际写库(默认只预演)")
    args = parser.parse_args()
    counts = backfill(apply=args.apply)
    print(
        f"{'已回填' if args.apply else '预演(未写库)'}:"
        f"批次 {counts['batches']} · 补链作品 {counts['works_fixed']}"
        f" · 新增关联 {counts['inserted']} · 跳过(无作者/未匹配/已删除) {counts['skipped']}"
    )


if __name__ == "__main__":
    main()

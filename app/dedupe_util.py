"""去重共享原语:标题/姓名规范与相似度,以及库内活跃行读取。

agent_temp 管线(dedupe_check)与 app 管理端(llm_review)共用,
避免各自维护一份 normalize/bigrams/jaccard 与行查询 SQL。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from app import db_sqlite
from app.auth import admin_user_id


def normalize_title(text: str | None) -> str:
    """标题/姓名规范化:全角→半角、去书名号/标点/空白、拉丁转小写。"""
    if not text:
        return ""
    s = str(text).strip().lower()
    s = s.translate(
        str.maketrans(
            "０１２３４５６７８９ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
            "0123456789abcdefghijklmnopqrstuvwxyz",
        )
    )
    return re.sub(r"[\W_]+", "", s, flags=re.UNICODE)


def char_bigrams(s: str) -> set[str]:
    """字符二元组集合;长度 1 时返回自身。"""
    if not s:
        return set()
    if len(s) == 1:
        return {s}
    return {s[i : i + 2] for i in range(len(s) - 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard 相似度。"""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_rows(
    db_path: str | None = None,
    *,
    public_only: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """读取库内活跃(未软删除)的作者/作品/涟漪。

    public_only=False:全部行(去重管线视角,含个人空间);
    public_only=True:公共星云(admin 认领 + 未认领历史行),复用/发布只认公共空间。
    作品带 author_names(中文作者名串)用于同名异书消歧;涟漪同时带两端作品标题。
    """
    path = Path(db_path) if db_path else db_sqlite.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if public_only:
            admin_id = admin_user_id()
            if admin_id:
                owner_scope = "owner_id IN (?, NULL)"
                works_owner_scope = "w.owner_id IN (?, NULL)"
                owner_params: tuple = (admin_id,)
            else:
                owner_scope = "owner_id IS NULL"
                works_owner_scope = "w.owner_id IS NULL"
                owner_params = ()
        else:
            owner_scope = ""
            works_owner_scope = ""
            owner_params = ()
        authors = [
            dict(r)
            for r in conn.execute(
                "SELECT id, originalName, Name_CN, Name_EN, nationality, birthYear,"
                " deathYear, note, owner_id, created_by"
                " FROM authors WHERE deletedAt IS NULL"
                + (" AND " + owner_scope if owner_scope else ""),
                owner_params,
            )
        ]
        works = [
            dict(r)
            for r in conn.execute(
                "SELECT w.id, w.language, w.originalTitle, w.Title_CN, w.Title_EN,"
                " w.Title_Other, w.publicationYear, w.genre, w.note, w.owner_id,"
                " w.created_by, COALESCE(GROUP_CONCAT(DISTINCT a.Name_CN), '')"
                "   AS author_names"
                " FROM works w"
                " LEFT JOIN work_authors wa ON wa.work_id = w.id"
                " LEFT JOIN authors a ON a.id = wa.author_id"
                " WHERE w.deletedAt IS NULL"
                + (" AND " + works_owner_scope if works_owner_scope else "")
                + " GROUP BY w.id",
                owner_params,
            )
        ]
        edges_owner_scope = "e." + owner_scope if owner_scope else ""
        edges = [
            dict(r)
            for r in conn.execute(
                "SELECT e.id, e.source_work_id, e.target_work_id, e.evidence,"
                " e.evidenceSource, e.note, e.owner_id, e.created_by,"
                " ws.Title_CN AS src_Title_CN, ws.originalTitle AS src_originalTitle,"
                " ws.Title_EN AS src_Title_EN, ws.Title_Other AS src_Title_Other,"
                " wt.Title_CN AS tgt_Title_CN, wt.originalTitle AS tgt_originalTitle,"
                " wt.Title_EN AS tgt_Title_EN, wt.Title_Other AS tgt_Title_Other"
                " FROM edges e"
                " LEFT JOIN works ws ON ws.id = e.source_work_id AND ws.deletedAt IS NULL"
                " LEFT JOIN works wt ON wt.id = e.target_work_id AND wt.deletedAt IS NULL"
                " WHERE e.deletedAt IS NULL"
                + (" AND " + edges_owner_scope if edges_owner_scope else ""),
                owner_params,
            )
        ]
    finally:
        conn.close()
    return {"authors": authors, "works": works, "edges": edges}

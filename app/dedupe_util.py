"""去重共享原语:标题/姓名规范与相似度,以及库内活跃行读取。

ai_assistant 管线(dedupe_check)与 app 管理端(llm_review)共用,
避免各自维护一份 normalize/bigrams/jaccard 与行查询 SQL。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from app import db_sqlite

# 作者名相似度阈值:规范化后不相等,但二元组 Jaccard >= 此值视为同一人
# (处理同人异译,如 蕾切尔·卡逊 vs 蕾切尔·卡森、村上春树 vs 村上春樹),
# 不触发「同名异书」降级。
AUTHOR_SIM_SAME = 0.5


def authors_clearly_different(name_a: str | None, name_b: str | None) -> bool:
    """判断两个作者名是否「明显不同」(用于同名异书的 exact 降级)。

    任意一侧为空 → 不判定不同(无作者信息时宁可按 exact 复用);
    规范化后相等 / 一方包含另一方 / 二元组相似度 >= AUTHOR_SIM_SAME
    都视为同一人。返回 True 才降级为 exact_diff_author。
    """
    a = normalize_title(name_a)
    b = normalize_title(name_b)
    if not a or not b:
        return False
    if a == b:
        return False
    if len(a) >= 2 and len(b) >= 2 and (a in b or b in a):
        return False
    return jaccard(char_bigrams(a), char_bigrams(b)) < AUTHOR_SIM_SAME


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
    owner_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """读取库内活跃(未软删除)的作者/作品/涟漪。

    owner_id=某用户:该用户空间的行(判重目标库),AI 草稿一律排除;
    owner_id=None:全部行(去重管线视角,含所有空间)。
    作品带 author_names(中文作者名串)用于同名异书消歧;涟漪同时带两端作品标题。
    """
    path = Path(db_path) if db_path else db_sqlite.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if owner_id is not None:
            owner_scope = "owner_id = ?"
            works_owner_scope = "w.owner_id = ?"
            edges_owner_scope = "e.owner_id = ?"
            owner_params = (owner_id,)
        else:
            owner_scope = ""
            works_owner_scope = ""
            edges_owner_scope = ""
            owner_params = ()
        # 判重目标(某用户空间):AI 草稿一律不参与
        if owner_scope:
            owner_scope = owner_scope + f" AND {db_sqlite.ai_draft_clause(negate=True)}"
            works_owner_scope = works_owner_scope + f" AND {db_sqlite.ai_draft_clause('w', negate=True)}"
            edges_owner_scope = edges_owner_scope + f" AND {db_sqlite.ai_draft_clause('e', negate=True)}"
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


def load_user_rows(user_id: str, db_path: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """判重目标库:某用户自己空间的活跃行(所有用户口径一致)。"""
    return load_rows(db_path, owner_id=user_id)

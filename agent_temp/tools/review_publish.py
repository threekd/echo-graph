#!/usr/bin/env python3

"""书籍解析数据审核 / 发布 CLI（system_llm 管线配套工具）。

职责链（agent_temp 实验管线）：
    extract_source_book.py（提取 作者/作品/涟漪）
      → dedupe_check.py（基础 + 语义去重报告）
      → 本脚本 make-batch：把提取结果 + 去重报告合并为「批次登记簿」
      → 本脚本 review：批内逐条 批准新建 / 批准复用 / 驳回（rejected 保留）
      → 本脚本 publish：把 approved 条目写入公共星云（admin 空间，created_by=llm）

批次文件：agent_temp/output/batches/<batch_id>.json（llm_space.BATCH_DIR）
批次是审核的单一事实来源：驳回记录原样保留，可反复 review 改判；
publish 幂等，已 published / reused 的条目不会重复写入。

去重语义（与 dedupe_check 一致）：
    likely_duplicate → 默认复用现有记录（resolved_id = 库内已有 id）
    possible         → 默认新建，但展示现有候选供人工选择复用
    new              → 默认新建

发布目标 = 公共星云（ADMIN_BOOTSTRAP_EMAIL 引导管理员的空间，owner_id=admin）；
复用目标只接受公共空间内未软删除的行，避免把个人空间数据牵连进公共星云。
"""

from __future__ import annotations

import argparse
import re
import secrets
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent_temp.tools import dedupe_check, llm_space  # noqa: E402
from agent_temp.tools.common import log, now_iso, read_json, utf8_stdout  # noqa: E402
from app import db_sqlite, sqlite_store  # noqa: E402
from app.auth import admin_user_id  # noqa: E402
from app.data_store import clean_row  # noqa: E402
from app.space_crud import create_row, validate_row  # noqa: E402

BATCH_DIR = llm_space.BATCH_DIR
SCHEMA_VERSION = 1
PUBLISH_ACTOR = "system_llm"  # 审计 actor：数据来源为 AI 管线专用账号

# 条目状态机
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
PUBLISHED = "published"
REUSED = "reused"
SKIPPED = "skipped"
FAILED = "failed"

REVIEWABLE = (PENDING, REJECTED, SKIPPED, FAILED)
DONE = (PUBLISHED, REUSED)


# ======================================================================
# 基础工具
# ======================================================================


def _label(item: dict[str, Any]) -> str:
    p = item.get("payload") or {}
    if item["kind"] == "author":
        return p.get("Name_CN") or p.get("Name_EN") or p.get("originalName") or item.get("label") or "?"
    if item["kind"] == "work":
        return p.get("Title_CN") or p.get("originalTitle") or item.get("label") or "?"
    return item.get("label") or "?"


def _existing_label(existing: dict[str, Any] | None) -> str:
    if not existing:
        return "?"
    return (
        existing.get("Title_CN")
        or existing.get("originalTitle")
        or existing.get("Name_CN")
        or existing.get("Name_EN")
        or existing.get("id")
        or "?"
    )


def _dedupe_default_action(dedupe: dict[str, Any]) -> str:
    """去重命中（likely_duplicate 且存在可复用目标）默认复用，其余默认新建。"""
    if dedupe.get("decision") == "likely_duplicate" and dedupe.get("existing_id"):
        return "reuse"
    return "create"


def _split_author_name(raw: str | None) -> tuple[str, str | None]:
    """拆「中文名（English Name）」或「English Name（中文名）」。

    返回 (Name_CN, Name_EN)；拆不出括号时整串视为中文名/原名
    （库内 Name_CN 非空，纯英文作者也以英文串填充）。
    """
    raw = (raw or "").strip()
    if not raw:
        return raw, None
    m = re.match(r"^(.*?)[（(]([^（）()]+)[)）]$", raw)
    if m:
        first, second = m.group(1).strip(), m.group(2).strip()
        second_has_latin = bool(re.search(r"[A-Za-z]", second))
        if second_has_latin:
            if re.search(r"[A-Za-z]", first) and not re.search(r"[\u4e00-\u9fff]", first):
                return second, first  # 前半是英文名 → 后半作中文名
            return first, second or None
        # 括号内无拉丁字母（如「毗耶娑（相传）」）→ 视为注解，不进入英名字段
        return first, None
    return raw, None

# ======================================================================
# 公共空间数据读取（去重 / 复用只认公共星云）
# ======================================================================
def load_public_rows(db_path: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """读取公共空间（admin 认领 + 尚未认领的历史行）内未软删除的作者/作品/涟漪。"""
    path = Path(db_path) if db_path else db_sqlite.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    admin_id = admin_user_id()
    try:
        if admin_id:
            owner_scope = "owner_id IN (?, NULL)"
            works_owner_scope = "w.owner_id IN (?, NULL)"
            owner_params: tuple = (admin_id,)
        else:
            owner_scope = "owner_id IS NULL"
            works_owner_scope = "w.owner_id IS NULL"
            owner_params = ()
        authors = [
            dict(r)
            for r in conn.execute(
                "SELECT id, originalName, Name_CN, Name_EN, nationality, birthYear,"
                " deathYear, note, owner_id, created_by"
                " FROM authors WHERE deletedAt IS NULL AND " + owner_scope,
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
                " WHERE w.deletedAt IS NULL AND " + works_owner_scope + " GROUP BY w.id",
                owner_params,
            )
        ]
        edges = [
            dict(r)
            for r in conn.execute(
                "SELECT id, source_work_id, target_work_id, evidence, evidenceSource,"
                " note, owner_id, created_by"
                " FROM edges WHERE deletedAt IS NULL AND " + owner_scope,
                owner_params,
            )
        ]
    finally:
        conn.close()
    return {"authors": authors, "works": works, "edges": edges}


# ======================================================================
# 去重结论合成（基础匹配 + 复用 dedupe_report 的语义结果）
# ======================================================================
def _norm(text: str | None) -> str:
    return dedupe_check.normalize_title(text)


def _public_id_set(rows: list[dict[str, Any]]) -> set[str]:
    return {r["id"] for r in rows}


def _match_report_author(
    report: dict[str, Any], cand: dict[str, Any]
) -> dict[str, Any] | None:
    """在去重报告的作者列表里找同名候选（避免依赖报告顺序）。"""
    keys = [cand.get("Name_CN"), cand.get("Name_EN"), cand.get("originalName")]
    wanted = {_norm(k) for k in keys if k}
    for entry in report.get("authors") or []:
        c = entry.get("candidate") or {}
        have = {_norm(c.get("Name_CN")), _norm(c.get("Name_EN")), _norm(c.get("originalName"))}
        if wanted & have:
            return entry
    return None


def _match_report_work(report: dict[str, Any], cand: dict[str, Any]) -> dict[str, Any] | None:
    """在去重报告的作品列表里找同名候选；同名校对作者进一步消歧。"""
    cand_titles = {_norm(cand.get("Title_CN")), _norm(cand.get("originalTitle"))}
    cand_author = _norm(cand.get("author") or cand.get("_author_names"))
    for entry in report.get("works") or []:
        c = entry.get("candidate") or {}
        titles = {_norm(c.get("Title_CN")), _norm(c.get("originalTitle"))}
        if not (cand_titles & titles):
            continue
        entry_author = _norm(c.get("author") or c.get("_author_names"))
        if cand_author and entry_author and cand_author != entry_author:
            continue
        return entry
    return None


def _semantic_match_from_report(
    report_entry: dict[str, Any] | None, public_ids: set[str]
) -> dict[str, Any] | None:
    """取报告语义结果；命中目标不属于公共空间时丢弃（防止牵连个人空间数据）。"""
    if not report_entry:
        return None
    sem = report_entry.get("semantic") or {}
    top = (sem.get("top_matches") or [])[:1]
    if not top:
        return sem if sem.get("error") else None
    existing = top[0].get("existing") or {}
    if existing.get("id") and existing["id"] in public_ids:
        return sem
    return None


def build_dedupe_info(
    kind: str,
    cand: dict[str, Any],
    report_entry: dict[str, Any] | None,
    public: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """合成单条去重结论：{decision, existing_id, existing_label, reason, basic, semantic}。"""
    public_ids = _public_id_set(public["works"] if kind == "work" else public["authors"])
    if kind == "work":
        basic = dedupe_check.basic_match_work(cand, public["works"])
    else:
        basic = dedupe_check.basic_match_author(cand, public["authors"])
    semantic = _semantic_match_from_report(report_entry, public_ids)

    level = basic.get("level")
    decision: str
    reason: str
    existing_id: str | None = None
    existing: dict[str, Any] | None = None

    if level == "exact":
        decision, reason = "likely_duplicate", "基础匹配：标题/姓名完全相同"
        existing = basic.get("existing")
    elif level == "exact_diff_author":
        decision, reason = "possible", "基础匹配：标题相同但作者不同（疑似同名异书）"
        existing = basic.get("existing")
    elif semantic and semantic.get("best_score", 0.0) >= dedupe_check.SEMANTIC_STRONG:
        decision = "likely_duplicate"
        reason = f"语义相似度 {semantic['best_score']}（阈值 {dedupe_check.SEMANTIC_STRONG}）"
        top = (semantic.get("top_matches") or [])[:1]
        existing = top[0]["existing"] if top else None
    elif level in ("contained", "token"):
        decision, reason = "possible", f"基础匹配：{level}"
        existing = basic.get("existing")
    elif semantic and semantic.get("best_score", 0.0) >= dedupe_check.SEMANTIC_POSSIBLE:
        decision = "possible"
        reason = f"语义相似度 {semantic['best_score']}（阈值 {dedupe_check.SEMANTIC_POSSIBLE}）"
        top = (semantic.get("top_matches") or [])[:1]
        existing = top[0]["existing"] if top else None
    else:
        decision = "new"
        reason = "无匹配"
        if semantic and semantic.get("best_score"):
            reason += f"（语义最高 {semantic['best_score']}）"

    if existing and existing.get("id"):
        existing_id = existing["id"]
    return {
        "decision": decision,
        "existing_id": existing_id,
        "existing_label": _existing_label(existing) if existing else None,
        "default_action": "reuse" if decision == "likely_duplicate" and existing_id else "create",
        "reason": reason,
        "basic": basic,
        "semantic": semantic,
    }


# ======================================================================
# 批次构建（make-batch）
# ======================================================================
def _author_payload(a: dict[str, Any]) -> dict[str, Any]:
    return {
        k: a.get(k)
        for k in ("originalName", "Name_CN", "Name_EN", "nationality", "birthYear", "deathYear", "note")
    }


def _work_payload(w: dict[str, Any], author_name: str | None = None) -> dict[str, Any]:
    payload = {
        k: w.get(k)
        for k in ("language", "originalTitle", "Title_CN", "Title_EN", "Title_Other",
                  "publicationYear", "genre", "note")
    }
    if author_name:
        payload["author"] = author_name
    return payload


def _add_author_item(
    items: list[dict[str, Any]],
    payload: dict[str, Any],
    report: dict[str, Any],
    public: dict[str, list[dict[str, Any]]],
) -> str:
    """新增作者条目（批内同名去重），返回 item_id。"""
    norm_key = _norm(payload.get("Name_CN")) or _norm(payload.get("originalName"))
    for it in items:
        if it["kind"] != "author":
            continue
        p = it["payload"]
        if (_norm(p.get("Name_CN")) or _norm(p.get("originalName"))) == norm_key and norm_key:
            return it["item_id"]
    item_id = f"a{len([i for i in items if i['kind'] == 'author']) + 1}"
    cand = {k: v for k, v in payload.items() if v is not None}
    report_entry = _match_report_author(report, cand)
    dedupe = build_dedupe_info("author", cand, report_entry, public)
    items.append(
        {
            "item_id": item_id,
            "kind": "author",
            "label": payload.get("Name_CN") or payload.get("Name_EN") or payload.get("originalName") or "?",
            "payload": payload,
            "author_refs": [],
            "source_ref": None,
            "target_ref": None,
            "dedupe": dedupe,
            "status": PENDING,
            "action": None,
            "resolved_id": None,
            "reviewed_at": None,
            "review_note": None,
            "error": None,
        }
    )
    return item_id


def _add_work_item(
    items: list[dict[str, Any]],
    payload: dict[str, Any],
    author_refs: list[str],
    report: dict[str, Any],
    public: dict[str, list[dict[str, Any]]],
) -> str:
    """新增作品条目（批内同名去重），返回 item_id。"""
    norm_key = _norm(payload.get("Title_CN")) or _norm(payload.get("originalTitle"))
    author_key = _norm(payload.get("author"))
    for it in items:
        if it["kind"] != "work":
            continue
        p = it["payload"]
        same_title = (_norm(p.get("Title_CN")) or _norm(p.get("originalTitle"))) == norm_key
        same_author = (_norm(p.get("author")) == author_key) if author_key else True
        if norm_key and same_title and same_author:
            return it["item_id"]
    item_id = f"w{len([i for i in items if i['kind'] == 'work']) + 1}"
    cand = {k: v for k, v in payload.items() if v is not None}
    report_entry = _match_report_work(report, cand)
    dedupe = build_dedupe_info("work", cand, report_entry, public)
    items.append(
        {
            "item_id": item_id,
            "kind": "work",
            "label": payload.get("Title_CN") or payload.get("originalTitle") or "?",
            "payload": payload,
            "author_refs": author_refs,
            "source_ref": None,
            "target_ref": None,
            "dedupe": dedupe,
            "status": PENDING,
            "action": None,
            "resolved_id": None,
            "reviewed_at": None,
            "review_note": None,
            "error": None,
        }
    )
    return item_id


def _add_edge_item(
    items: list[dict[str, Any]],
    source_ref: str,
    target_ref: str,
    evidence: dict[str, Any],
    public: dict[str, list[dict[str, Any]]],
) -> None:
    """新增涟漪条目（源 → 目标）。端点在批内已确定（可能对应现有记录）。"""
    item_id = f"e{len([i for i in items if i['kind'] == 'edge']) + 1}"
    payload = {
        "evidence": evidence.get("evidence"),
        "evidenceSource": evidence.get("evidenceSource"),
        "note": None,
    }
    # 端点在批内都判定为复用现有作品时，提前查一次公共空间是否已有该涟漪
    dedupe: dict[str, Any] = {
        "decision": "new",
        "existing_id": None,
        "existing_label": None,
        "default_action": "create",
        "reason": "涟漪以证据内容创建，端点为新建作品",
        "basic": None,
        "semantic": None,
    }
    work_items = {it["item_id"]: it for it in items if it["kind"] == "work"}
    src = work_items.get(source_ref)
    tgt = work_items.get(target_ref)
    if src and tgt and src["dedupe"].get("existing_id") and tgt["dedupe"].get("existing_id"):
        sid = src["dedupe"]["existing_id"]
        tid = tgt["dedupe"]["existing_id"]
        dup = next(
            (e for e in public["edges"] if e["source_work_id"] == sid and e["target_work_id"] == tid),
            None,
        )
        if dup:
            dedupe = {
                "decision": "likely_duplicate",
                "existing_id": dup["id"],
                "existing_label": f"{_existing_label(src['dedupe'])} → {_existing_label(tgt['dedupe'])}",
                "default_action": "reuse",
                "reason": "公共空间已存在相同源→目标涟漪",
                "basic": None,
                "semantic": None,
            }
    items.append(
        {
            "item_id": item_id,
            "kind": "edge",
            "label": f"{_label(src) if src else source_ref} → {_label(tgt) if tgt else target_ref}",
            "payload": payload,
            "author_refs": [],
            "source_ref": source_ref,
            "target_ref": target_ref,
            "dedupe": dedupe,
            "meta": {"mention_type": evidence.get("mention_type")},
            "status": PENDING,
            "action": None,
            "resolved_id": None,
            "reviewed_at": None,
            "review_note": None,
            "error": None,
        }
    )


def build_batch(
    extract: dict[str, Any],
    report: dict[str, Any] | None,
    db_path: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """把 extract_source_book.py 输出 + dedupe_check 报告合并成批次登记簿。

    本函数只读数据库（公共空间去重），不做任何写入；system_llm 账号的创建
    由 CLI 命令层（cmd_make_batch）负责，便于纯只读地生成/预览批次。
    """
    public = load_public_rows(db_path)
    report = report or {"authors": [], "works": []}

    items: list[dict[str, Any]] = []

    # 1) 作者：源书作者优先，随后是涟漪提及作品的作者（拆中文名/英文名）
    source_author_ids: list[str] = []
    for a in extract.get("authors") or []:
        source_author_ids.append(_add_author_item(items, _author_payload(a), report, public))

    for r in extract.get("ripples") or []:
        w = r.get("work") or {}
        author_name = (w.get("author") or "").strip()
        if not author_name:
            continue
        cn, en = _split_author_name(author_name)
        payload = {"originalName": author_name, "Name_CN": cn, "Name_EN": en}
        _add_author_item(items, payload, report, public)

    # 2) 作品：源书 + 涟漪提及作品
    src_work = extract.get("work") or {}
    source_work_id: str | None = None
    if src_work.get("Title_CN") or src_work.get("originalTitle"):
        source_author_names = [
            a.get("Name_CN") or a.get("Name_EN") or a.get("originalName")
            for a in extract.get("authors") or []
        ]
        payload = _work_payload(src_work, " ".join(n for n in source_author_names if n) or None)
        source_work_id = _add_work_item(items, payload, source_author_ids, report, public)

    if source_work_id is None:
        raise ValueError("提取结果缺少源书 work 字段，无法构建涟漪（涟漪需源书作品）")

    ripple_work_ids: list[str] = []
    for r in extract.get("ripples") or []:
        w = r.get("work") or {}
        if not (w.get("Title_CN") or w.get("originalTitle")):
            continue
        author_name = (w.get("author") or "").strip()
        author_ref: list[str] = []
        if author_name:
            # 批内作者条目已按同名去重，这里直接按名找回
            for it in items:
                if it["kind"] == "author" and (
                    _norm(it["payload"].get("Name_CN")) == _norm(author_name)
                    or _norm(it["payload"].get("originalName")) == _norm(author_name)
                ):
                    author_ref = [it["item_id"]]
                    break
        payload = _work_payload(w, author_name or None)
        wid = _add_work_item(items, payload, author_ref, report, public)
        # 涟漪目标与源书同名同作者时，直接复用源书作品条目
        ripple_work_ids.append(wid)

    # 3) 涟漪边：源书作品 → 提及作品
    for idx, r in enumerate(extract.get("ripples") or []):
        w = r.get("work") or {}
        if not (w.get("Title_CN") or w.get("originalTitle")):
            continue
        target = ripple_work_ids[idx]
        _add_edge_item(items, source_work_id, target, r.get("evidence") or {}, public)

    batch_id = f"batch-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
    return {
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "owner_id": owner_id,
        "source": {
            "input_file": None,
            "dedupe_file": None,
            "source_book": extract.get("source_book"),
            "public_counts": {
                "authors": len(public["authors"]),
                "works": len(public["works"]),
                "edges": len(public["edges"]),
            },
        },
        "items": items,
    }

# ======================================================================
# 展示
# ======================================================================
def _dep_status(item: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    """作品/涟漪的依赖条目状态摘要（发布时依赖未就绪会被跳过）。"""
    refs: list[tuple[str, str]] = []
    if item["kind"] == "work":
        refs = [(r, "作者") for r in item.get("author_refs") or []]
    elif item["kind"] == "edge":
        refs = [
            (item.get("source_ref"), "源作品"),
            (item.get("target_ref"), "目标作品"),
        ]
    parts = []
    for ref, role in refs:
        dep = by_id.get(ref)
        if dep is None:
            parts.append(f"{role} {ref}(缺)")
            continue
        state = dep.get("status")
        if state == REUSED:
            state += f"→#{dep.get('resolved_id', '')[:8]}"
        elif state == PUBLISHED:
            state += f"→#{dep.get('resolved_id', '')[:8]}"
        parts.append(f"{role} {ref}({state})")
    return " · ".join(parts) if parts else ""


def _show_item(item: dict[str, Any], idx: int = 0, total: int = 0) -> None:
    kind_cn = {"author": "作者", "work": "作品", "edge": "涟漪"}.get(item["kind"], item["kind"])
    prefix = f"[{idx}/{total}] " if total else ""
    print(f"{prefix}{kind_cn}：{_label(item)}")
    p = item["payload"]
    if item["kind"] == "author":
        extra = " · ".join(
            str(v)
            for v in (
                p.get("originalName"),
                f"英 {p['Name_EN']}" if p.get("Name_EN") else None,
                f"国籍 {p['nationality']}" if p.get("nationality") else None,
                f"{p.get('birthYear')}-{p.get('deathYear') or ''}" if p.get("birthYear") else None,
            )
            if v
        )
        if extra:
            print(f"  {extra}")
        if p.get("note"):
            print(f"  简介：{str(p['note'])[:120]}")
    elif item["kind"] == "work":
        extra = " · ".join(
            str(v)
            for v in (
                f"语言 {p.get('language')}" if p.get("language") else None,
                f"原题 {p['originalTitle']}" if p.get("originalTitle") else None,
                f"英名 {p['Title_EN']}" if p.get("Title_EN") else None,
                f"年份 {p.get('publicationYear')}" if p.get("publicationYear") else None,
                f"体裁 {p.get('genre')}" if p.get("genre") else None,
                f"作者 {p.get('author')}" if p.get("author") else None,
            )
            if v
        )
        if extra:
            print(f"  {extra}")
    elif item["kind"] == "edge":
        print(f"  证据：{str(p.get('evidence') or '')[:100]}")
        if p.get("evidenceSource"):
            print(f"  出处：{p['evidenceSource']}")

    d = item.get("dedupe") or {}
    dedupe_line = f"  去重：{d.get('decision')}（{d.get('reason')}）"
    if d.get("existing_id"):
        dedupe_line += f" → {d.get('existing_label')} (#{d['existing_id']})"
    print(dedupe_line)
    if item.get("review_note"):
        print(f"  备注：{item['review_note']}")
    if item.get("error"):
        print(f"  错误：{item['error']}")
    print(f"  状态：{item.get('status')}（默认动作：{d.get('default_action', 'create')}）")


def _status_counts(batch: dict[str, Any]) -> dict[str, int]:
    counts = {s: 0 for s in (PENDING, APPROVED, REJECTED, PUBLISHED, REUSED, SKIPPED, FAILED)}
    for it in batch.get("items") or []:
        counts[it.get("status", PENDING)] = counts.get(it.get("status", PENDING), 0) + 1
    return counts


# ======================================================================
# list / show
# ======================================================================
def cmd_list(_args: argparse.Namespace) -> None:
    batches = llm_space.list_batches()
    if not batches:
        print("暂无批次（agent_temp/output/batches/ 为空）")
        return
    print(f"{'batch_id':<28} 总  待审  已批  驳回  已发  复用  跳过  失败")
    for b in batches:
        c = _status_counts(b)
        print(
            f"{b.get('batch_id'):<28} "
            f"{len(b.get('items') or []):<4}{c[PENDING]:<4}{c[APPROVED]:<4}"
            f"{c[REJECTED]:<4}{c[PUBLISHED]:<4}{c[REUSED]:<4}{c[SKIPPED]:<4}{c[FAILED]:<3}"
            f"  {b.get('created_at', '')[:19]}"
        )


def cmd_show(args: argparse.Namespace) -> None:
    batch = llm_space.load_batch(args.batch_id)
    c = _status_counts(batch)
    print(
        f"批次 {batch['batch_id']}（{batch.get('created_at', '')[:19]}）"
        f" 总 {len(batch['items'])} · 待审 {c[PENDING]} · 已批 {c[APPROVED]}"
        f" · 驳回 {c[REJECTED]} · 已发 {c[PUBLISHED] + c[REUSED]} · 失败 {c[FAILED]}"
    )
    if batch["source"].get("source_book"):
        sb = batch["source"]["source_book"]
        print(f"源书：{sb.get('title')}（{'、'.join(sb.get('authors') or [])}）")
    by_id = {it["item_id"]: it for it in batch["items"]}
    for idx, it in enumerate(batch["items"], 1):
        _show_item(it, idx, len(batch["items"]))
        dep = _dep_status(it, by_id)
        if dep:
            print(f"  依赖：{dep}")
        print()


# ======================================================================
# review：批内逐条批准 / 驳回 / 跳过
# ======================================================================
def _parse_review_input(raw: str, item: dict[str, Any]) -> tuple[str, str | None]:
    """解析单条审核输入，返回 (command, note)。command ∈ a/u/r/s/q/help。"""
    text = raw.strip().lower()
    if text in ("a", "approve", "批准", "新建"):
        return "a", None
    if text in ("u", "use", "reuse", "复用"):
        return "u", None
    if text in ("r", "reject", "驳回"):
        return "r", None
    if text in ("s", "skip", "跳过"):
        return "s", None
    if text in ("q", "quit", "exit", "退出"):
        return "q", None
    if text in ("h", "help", "?"):
        return "help", None
    return "", None


def cmd_review(args: argparse.Namespace) -> None:
    batch = llm_space.load_batch(args.batch_id)
    by_id = {it["item_id"]: it for it in batch["items"]}
    queue = [it for it in batch["items"] if it.get("status") in REVIEWABLE]
    if not queue:
        print(f"批次 {batch['batch_id']} 没有待审核条目（全部已处理）")
        return
    print(f"批次 {batch['batch_id']}：共 {len(queue)} 条待审核（驳回条目保留可改判）")
    print("操作说明：a=批准新建  u=批准复用现有  r=驳回  s=跳过  q=保存并退出  回车=默认")
    print()

    for idx, item in enumerate(queue, 1):
        _show_item(item, idx, len(queue))
        dep = _dep_status(item, by_id)
        if dep:
            print(f"  依赖：{dep}")
        d = item.get("dedupe") or {}
        default = d.get("default_action") or "create"
        default_hint = "复用" if default == "reuse" else "新建"
        if default == "reuse" and not d.get("existing_id"):
            default = "create"
            default_hint = "新建"
        while True:
            raw = input(f"  > a=新建 u=复用 r=驳回 s=跳过 q=退出 [回车={default_hint}]：")
            cmd, _note = _parse_review_input(raw, item)
            if cmd == "help":
                print("    a=批准并新建  u=批准并复用现有记录  r=驳回（保留记录） s=跳过（稍后再审） q=保存并退出")
                continue
            if cmd == "":
                cmd = "u" if default == "reuse" else "a"
            if cmd == "u" and not d.get("existing_id"):
                print("    ⚠ 该条目没有可复用的现有记录，请选择 a 或 r")
                continue
            if cmd == "q":
                batch["updated_at"] = now_iso()
                llm_space.save_batch(batch)
                print(f"已保存，退出（驳回 {sum(1 for i in batch['items'] if i.get('status') == REJECTED)} 条保留）")
                return
            break
        if cmd == "a":
            item["status"] = APPROVED
            item["action"] = "create"
            item["resolved_id"] = None
        elif cmd == "u":
            item["status"] = APPROVED
            item["action"] = "reuse"
            item["resolved_id"] = d.get("existing_id")
        elif cmd == "r":
            item["status"] = REJECTED
            item["action"] = None
            item["resolved_id"] = None
        elif cmd == "s":
            item["status"] = SKIPPED
            item["action"] = None
            item["resolved_id"] = None
        item["error"] = None  # 改判后清除上次发布的错误
        item["reviewed_at"] = now_iso()
        batch["updated_at"] = now_iso()
        llm_space.save_batch(batch)

    c = _status_counts(batch)
    print(
        f"\n审核完成：待审 {c[PENDING]} · 已批 {c[APPROVED]}"
        f" · 驳回 {c[REJECTED]}（保留）· 跳过 {c[SKIPPED]}"
    )

# ======================================================================
# publish：把 approved 条目写入公共星云
# ======================================================================
def _active_in_public(kind: str, row_id: str, admin_id: str | None) -> bool:
    table = {"author": "authors", "work": "works", "edge": "edges"}[kind]
    with db_sqlite._db() as conn:
        if admin_id:
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE id = ? AND deletedAt IS NULL"
                " AND (owner_id = ? OR owner_id IS NULL)",
                (row_id, admin_id),
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE id = ? AND deletedAt IS NULL"
                " AND owner_id IS NULL",
                (row_id,),
            ).fetchone()
    return row is not None


def _resolve_ref(ref: str | None, by_id: dict[str, dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None]:
    """把批内 item_id 解析为库内 id；若是库内 id 直接返回。"""
    if not ref:
        return None, None
    dep = by_id.get(ref)
    if dep is not None:
        return dep.get("resolved_id"), dep
    return ref, None


def _publish_author(item: dict[str, Any], admin_id: str) -> str:
    row = {k: v for k, v in item["payload"].items() if v is not None}
    row["created_by"] = "llm"
    result = create_row("authors", row, admin_id, actor=PUBLISH_ACTOR)
    return result["row"]["id"]


def _publish_work(
    item: dict[str, Any], admin_id: str, by_id: dict[str, dict[str, Any]]
) -> str:
    author_ids: list[str] = []
    for ref in item.get("author_refs") or []:
        rid, dep = _resolve_ref(ref, by_id)
        if not rid:
            raise RuntimeError(f"作者依赖 {ref} 未就绪（{dep.get('status') if dep else '未知'}）")
        author_ids.append(rid)
    # 安全网：批准为新建，但发布时公共空间已存在完全同名作品 → 拒绝并提示改为复用
    public = load_public_rows()
    cand = {k: v for k, v in item["payload"].items() if v is not None}
    hit = dedupe_check.basic_match_work(cand, public["works"])
    if hit.get("level") == "exact":
        ex = hit.get("existing")
        raise RuntimeError(
            "发布时公共空间已存在完全同名作品"
            f"（{_existing_label(ex)} #{ex['id'] if ex else ''}），请在 review 中改为复用"
        )
    row = {k: v for k, v in item["payload"].items() if k != "author" and v is not None}
    row["author_id"] = ",".join(author_ids)
    row["created_by"] = "llm"
    result = create_row("works", row, admin_id, actor=PUBLISH_ACTOR)
    return result["row"]["id"]


def _publish_edge(
    item: dict[str, Any], admin_id: str, by_id: dict[str, dict[str, Any]]
) -> str:
    src, src_dep = _resolve_ref(item.get("source_ref"), by_id)
    tgt, tgt_dep = _resolve_ref(item.get("target_ref"), by_id)
    if not src:
        raise RuntimeError(f"源作品 {item.get('source_ref')} 未就绪（{src_dep.get('status') if src_dep else '未知'}）")
    if not tgt:
        raise RuntimeError(f"目标作品 {item.get('target_ref')} 未就绪（{tgt_dep.get('status') if tgt_dep else '未知'}）")
    row = {k: v for k, v in item["payload"].items() if v is not None}
    row["source_work_id"] = src
    row["target_work_id"] = tgt
    row["created_by"] = "llm"
    result = create_row("edges", row, admin_id, actor=PUBLISH_ACTOR)
    return result["row"]["id"]


def cmd_publish(args: argparse.Namespace) -> None:
    if args.db:
        db_sqlite.DB_PATH = Path(args.db).resolve()
    admin_id = admin_user_id()
    if not admin_id:
        raise SystemExit(
            "公共星云管理员不存在：请先用 ADMIN_BOOTSTRAP_EMAIL 注册并登录引导管理员账号"
        )
    llm_space.ensure_system_llm()

    batch = llm_space.load_batch(args.batch_id)
    by_id = {it["item_id"]: it for it in batch["items"]}
    order = {"author": 0, "work": 1, "edge": 2}
    items = sorted(
        batch["items"],
        key=lambda it: (order.get(it.get("kind"), 9), str(it.get("item_id"))),
    )
    pending = [it for it in items if it.get("status") == APPROVED]
    if not pending:
        print(f"批次 {batch['batch_id']} 没有已批准待发布的条目")
        return

    counts = {"published": 0, "reused": 0, "not_approved": 0, "failed": 0, "already": 0}
    print(f"发布目标：公共星云（admin #{admin_id}），共 {len(pending)} 条已批准条目\n")
    for item in items:
        if item.get("status") in DONE:
            counts["already"] += 1
            continue
        if item.get("status") != APPROVED:
            counts["not_approved"] += 1
            continue
        kind_cn = {"author": "作者", "work": "作品", "edge": "涟漪"}[item["kind"]]
        label = _label(item)
        action = item.get("action") or "create"
        if args.dry_run:
            print(f"  [预演] {kind_cn}「{label}」→ {action}")
            if item["kind"] == "work":
                for ref in item.get("author_refs") or []:
                    rid, dep = _resolve_ref(ref, by_id)
                    print(f"    作者 {ref} → {rid or dep.get('status') if dep else '未知'}")
            continue
        try:
            if action == "reuse":
                existing_id = item.get("resolved_id")
                if not existing_id:
                    raise RuntimeError("未记录可复用的现有 id")
                if not _active_in_public(item["kind"], existing_id, admin_id):
                    raise RuntimeError("可复用的现有记录在公共空间不存在或已软删除")
                item["resolved_id"] = existing_id
                item["status"] = REUSED
                counts["reused"] += 1
                print(f"  ✓ 复用 {kind_cn}「{label}」→ #{existing_id}")
            elif item["kind"] == "author":
                rid = _publish_author(item, admin_id)
                item["resolved_id"] = rid
                item["status"] = PUBLISHED
                counts["published"] += 1
                print(f"  ✓ 发布 {kind_cn}「{label}」→ #{rid}")
            elif item["kind"] == "work":
                rid = _publish_work(item, admin_id, by_id)
                item["resolved_id"] = rid
                item["status"] = PUBLISHED
                counts["published"] += 1
                print(f"  ✓ 发布 {kind_cn}「{label}」→ #{rid}")
            else:
                rid = _publish_edge(item, admin_id, by_id)
                item["resolved_id"] = rid
                item["status"] = PUBLISHED
                counts["published"] += 1
                print(f"  ✓ 发布 {kind_cn}「{label}」→ #{rid}")
            item["error"] = None
        except Exception as exc:  # noqa: BLE001 - CLI 逐条容错，不中断整批
            item["status"] = FAILED
            item["error"] = f"{type(exc).__name__}: {exc}"
            counts["failed"] += 1
            print(f"  ✗ 失败 {kind_cn}「{label}」：{item['error']}")
        item["reviewed_at"] = item.get("reviewed_at") or now_iso()
        batch["updated_at"] = now_iso()
        if not args.dry_run:
            llm_space.save_batch(batch)

    if args.dry_run:
        print("\n[预演模式] 未写入任何数据")
        return
    print(
        f"\n完成：发布 {counts['published']} · 复用 {counts['reused']}"
        f" · 未批准跳过 {counts['not_approved']} · 失败 {counts['failed']}"
        f" · 已处理跳过 {counts['already']}"
    )
    if counts["failed"]:
        print("失败条目保留 approved 状态并记录 error，修复后重跑 publish 即可重试")


# ======================================================================
# make-batch：提取结果 + 去重报告 → 批次登记簿
# ======================================================================
def cmd_make_batch(args: argparse.Namespace) -> None:
    if args.db:
        db_sqlite.DB_PATH = Path(args.db).resolve()
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"提取结果不存在：{input_path}")
    extract = read_json(input_path)
    report = None
    if args.dedupe:
        report_path = Path(args.dedupe)
        if not report_path.exists():
            raise SystemExit(f"去重报告不存在：{report_path}")
        report = read_json(report_path)

    owner_id = llm_space.ensure_system_llm()  # 批次归属 system_llm 专用账号（缺失则创建）
    batch = build_batch(extract, report, db_path=args.db, owner_id=owner_id)
    batch["source"]["input_file"] = str(input_path)
    batch["source"]["dedupe_file"] = str(report_path) if report else None
    if args.batch_id:
        batch["batch_id"] = args.batch_id

    path = llm_space.save_batch(batch)
    log(f"批次 {batch['batch_id']} 已保存：{path}")
    kinds = {}
    for it in batch["items"]:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    log(
        f"  条目：作者 {kinds.get('author', 0)} · 作品 {kinds.get('work', 0)}"
        f" · 涟漪 {kinds.get('edge', 0)}"
    )
    log(
        f"  去重：新建 {sum(1 for i in batch['items'] if i['dedupe'].get('default_action') == 'create')}"
        f" · 默认复用 {sum(1 for i in batch['items'] if i['dedupe'].get('default_action') == 'reuse')}"
    )
    print("  下一步：python agent_temp/tools/review_publish.py review " + batch["batch_id"])



# ======================================================================
# ingest：批次草稿 → system_llm 私有空间（reviewStatus=draft）
# ======================================================================
def _author_id_list(value) -> list[str]:
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def _stage_row(conn, kind: str, payload: dict, owner: str) -> str:
    """在 system_llm 空间创建一条草稿行,返回新行 id。

    校验与落盘对齐 space_crud.create_row(created_by='llm', reviewStatus='draft'),
    与批内其他草稿在同一事务内完成,保证作品↔作者、涟漪↔作品引用完整。
    """
    row = clean_row({k: v for k, v in payload.items() if v is not None})
    now = db_sqlite.now_iso()
    row.setdefault("id", db_sqlite.new_uuid())
    row["reviewStatus"] = "draft"
    row["createdAt"] = now
    row["updatedAt"] = now
    errors = validate_row(conn, kind, row, owner_id=owner)
    if errors:
        raise ValueError("；".join(errors))
    sqlite_store.insert_row(conn, kind, row, owner_id=owner, extra={"created_by": "llm"})
    if kind == "works":
        sqlite_store.set_work_authors(conn, row["id"], _author_id_list(row.get("author_id")))
    db_sqlite.audit(
        conn, "llm_ingest", kind, row["id"],
        f"AI 提取草稿入库「{row.get('Name_CN') or row.get('Title_CN') or row['id']}」",
        after=row,
        actor="system_llm",
    )
    return row["id"]


def stage_batch(batch: dict[str, Any], owner: str) -> dict[str, int]:
    """把批次内全部条目作为草稿写入指定空间(默认 system_llm),返回计数。

    单事务落盘,作品↔作者、涟漪↔作品引用在批内解析;已发布/已入库条目跳过。
    """
    by_id = {it["item_id"]: it for it in batch["items"]}
    order = {"author": 0, "work": 1, "edge": 2}
    items = sorted(
        batch["items"],
        key=lambda it: (order.get(it.get("kind"), 9), str(it.get("item_id"))),
    )
    counts = {"staged": 0, "already": 0, "failed": 0}
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        for item in items:
            if item.get("status") in DONE:
                counts["already"] += 1
                continue
            if item.get("status") == "staged" and item.get("resolved_id"):
                counts["already"] += 1
                continue
            try:
                if item["kind"] == "author":
                    rid = _stage_row(conn, "authors", item["payload"], owner)
                elif item["kind"] == "work":
                    payload = {k: v for k, v in item["payload"].items() if k != "author"}
                    author_ids = []
                    for ref in item.get("author_refs") or []:
                        dep = by_id.get(ref)
                        rid_dep = dep.get("resolved_id") if dep else None
                        if not rid_dep:
                            raise ValueError(f"作者依赖 {ref} 未入库")
                        author_ids.append(rid_dep)
                    payload["author_id"] = ",".join(author_ids)
                    rid = _stage_row(conn, "works", payload, owner)
                else:
                    payload = dict(item["payload"])
                    src = by_id.get(item.get("source_ref"))
                    tgt = by_id.get(item.get("target_ref"))
                    payload["source_work_id"] = src.get("resolved_id") if src else None
                    payload["target_work_id"] = tgt.get("resolved_id") if tgt else None
                    if not payload["source_work_id"] or not payload["target_work_id"]:
                        raise ValueError("涟漪端点作品未入库")
                    rid = _stage_row(conn, "edges", payload, owner)
                item["resolved_id"] = rid
                item["status"] = "staged"
                counts["staged"] += 1
            except Exception as exc:  # noqa: BLE001 - 单条失败不中断整批
                item["status"] = "failed"
                item["error"] = f"{type(exc).__name__}: {exc}"
                counts["failed"] += 1
        batch["updated_at"] = now_iso()
    return counts


def cmd_ingest(args: argparse.Namespace) -> None:
    """把批次内全部条目作为草稿写入 system_llm 空间(公共星云不可见)。

    之后的审核/批准在 admin 管理端「AI 草稿」页完成
    (GET/POST /api/admin/llm/drafts/*,见 app/llm_review.py)。
    """
    if args.db:
        db_sqlite.DB_PATH = Path(args.db).resolve()
    owner = llm_space.ensure_system_llm()
    batch = llm_space.load_batch(args.batch_id)
    counts = stage_batch(batch, owner)
    llm_space.save_batch(batch)
    log(
        f"ingest 完成:入库 {counts['staged']} · 跳过(已处理) {counts['already']}"
        f" · 失败 {counts['failed']}"
    )
    if counts["failed"]:
        log("失败条目保留 error,修复批次后重跑 ingest 即可重试")
    log("下一步:admin 登录后在管理端「AI 草稿」页审核/批准(发布到公共星云)")
# ======================================================================
# CLI 入口
# ======================================================================
def main() -> None:
    utf8_stdout()
    parser = argparse.ArgumentParser(
        description="书籍解析数据审核 / 发布 CLI（system_llm 管线）",
        epilog="示例：\n"
               "  python review_publish.py make-batch --input ../output/source_book_result.json"
               " --dedupe ../output/dedupe_report.json\n"
               "  python review_publish.py list\n"
               "  python review_publish.py review <batch_id>\n"
               "  python review_publish.py publish <batch_id> --dry-run\n"
               "  python review_publish.py publish <batch_id>",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("make-batch", help="由提取结果+去重报告生成批次登记簿")
    p.add_argument("--input", required=True, help="extract_source_book.py 输出 JSON")
    p.add_argument("--dedupe", help="dedupe_check.py 输出报告 JSON（可选）")
    p.add_argument("--batch-id", help="自定义批次 id（默认自动生成）")
    p.add_argument("--db", default=None, help="SQLite 数据库路径（默认 data/echo-graph.db）")
    p.set_defaults(func=cmd_make_batch)

    p = sub.add_parser("list", help="列出全部批次")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="查看批次全部条目与状态")
    p.add_argument("batch_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("review", help="批内逐条审核：a/u/r/s/q")
    p.add_argument("batch_id")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("ingest", help="把批次全部条目作为草稿写入 system_llm 空间(admin 管理端审核)")
    p.add_argument("batch_id")
    p.add_argument("--db", default=None, help="SQLite 数据库路径（默认 data/echo-graph.db）")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("publish", help="把已批准条目发布到公共星云")
    p.add_argument("batch_id")
    p.add_argument("--dry-run", action="store_true", help="只预演，不写数据库")
    p.add_argument("--db", default=None, help="SQLite 数据库路径（默认 data/echo-graph.db）")
    p.set_defaults(func=cmd_publish)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

"""批次登记簿构建与 AI 草稿入库工具(pipeline_ingest / book_import 共用)。

职责链(ai_assistant 实验管线):
    extract_source_book.py(提取 作者/作品/涟漪)
      → dedupe_check.py(基础 + 语义去重报告)
      → build_batch:提取结果 + 去重报告 → 「批次登记簿」(只读库,不写)
      → stage_batch:批次 → 上传者空间草稿(owner_id=上传者, created_by='llm')

审核/批准已收敛到管理端「AI 草稿」页(app/llm_review.py);make-batch / review /
publish 等 legacy CLI 已于 2026-08-27 移除。批次文件仍由
app/ai_assistant/tools/llm_space.py 读写(BATCH_DIR)。

去重语义(与 dedupe_check 一致):
    likely_duplicate → 默认复用现有记录(resolved_id = 库内已有 id)
    possible         → 默认新建,但展示现有候选供人工选择复用
    new              → 默认新建
"""

from __future__ import annotations

import re
import secrets
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from app import db_sqlite, sqlite_store  # noqa: E402
from app.ai_assistant.tools import dedupe_check  # noqa: E402
from app.ai_assistant.tools.common import now_iso  # noqa: E402
from app.data_store import clean_row  # noqa: E402
from app.dedupe_util import load_rows  # noqa: E402
from app.space_crud import validate_row  # noqa: E402

SCHEMA_VERSION = 1

# 条目状态机
PENDING = "pending"
PUBLISHED = "published"
REUSED = "reused"
SKIPPED = "skipped"
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


def _ripple_author_key(w: dict[str, Any]) -> str | None:
    """涟漪作者在批内作者条目中的查找键(与建条目时的载荷来源一致)。

    已补全(author_info)时用其 Name_CN/originalName;未补全时拆
    「中文名（English Name）」后取中文名/英文名。返回 None 表示无作者。
    """
    info = w.get("author_info")
    if isinstance(info, dict) and (info.get("Name_CN") or info.get("originalName")):
        return _norm(info.get("Name_CN")) or _norm(info.get("originalName"))
    name = (w.get("author") or "").strip()
    if not name:
        return None
    cn, en = _split_author_name(name)
    return _norm(cn) or _norm(en) or _norm(name)



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


def _match_report_edge(
    report: dict[str, Any], src_payload: dict[str, Any], tgt_payload: dict[str, Any]
) -> dict[str, Any] | None:
    """在去重报告的涟漪列表里找两端标题都命中的条目(用于未命中端点级检查时的提示)。"""
    if not report:
        return None
    src_wanted = {
        x for x in (_norm(src_payload.get("Title_CN")), _norm(src_payload.get("originalTitle"))) if x
    }
    tgt_wanted = {
        x for x in (_norm(tgt_payload.get("Title_CN")), _norm(tgt_payload.get("originalTitle"))) if x
    }
    if not src_wanted or not tgt_wanted:
        return None
    for entry in report.get("edges") or []:
        cand = entry.get("candidate") or {}
        src = cand.get("source") or {}
        tgt = cand.get("target") or {}
        src_have = {
            x for x in (_norm(src.get("Title_CN")), _norm(src.get("originalTitle"))) if x
        }
        tgt_have = {
            x for x in (_norm(tgt.get("Title_CN")), _norm(tgt.get("originalTitle"))) if x
        }
        if src_wanted & src_have and tgt_wanted & tgt_have:
            return entry
    return None


def _semantic_match_from_report(
    report_entry: dict[str, Any] | None, public_ids: set[str]
) -> dict[str, Any] | None:
    """取报告语义结果；命中目标不属于 admin 空间时丢弃（防止牵连个人空间数据）。"""
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

    # LLM 兜底确认(报告 confidence > 阈值且目标在 admin 空间)→ 直接按重复处理
    llm = (report_entry or {}).get("llm") or {}
    if (
        llm.get("confidence") is not None
        and llm["confidence"] > dedupe_check.LLM_CONFIRM_THRESHOLD
        and llm.get("existing_id") in public_ids
    ):
        decision = "likely_duplicate"
        reason = (
            f"LLM 确认：与现有{'作品' if kind == 'work' else '作者'}为同一"
            f"{'本书' if kind == 'work' else '作者'}"
            f"（置信度 {llm['confidence']:.2f} > {dedupe_check.LLM_CONFIRM_THRESHOLD}）"
        )
        existing_id = llm["existing_id"]
        if existing is None:
            existing = {"id": existing_id}

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
# 批次构建(build_batch)
# ======================================================================
# authors 表字段白名单(涟漪作者补全与 _author_payload 共用)
AUTHOR_FIELDS = (
    "originalName",
    "Name_CN",
    "Name_EN",
    "nationality",
    "birthYear",
    "deathYear",
    "note",
)


def _author_payload(a: dict[str, Any]) -> dict[str, Any]:
    return {k: a.get(k) for k in AUTHOR_FIELDS}


def _work_payload(w: dict[str, Any], author_name: str | None = None) -> dict[str, Any]:
    payload = {
        k: w.get(k)
        for k in ("language", "originalTitle", "Title_CN", "Title_EN", "Title_Other",
                  "publicationYear", "genre", "note")
    }
    if author_name:
        payload["author"] = author_name
    return payload


def _dedupe_result(
    decision: str,
    existing_id: str | None,
    existing_label: str | None,
    default_action: str,
    reason: str,
    basic: dict[str, Any] | None = None,
    semantic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造去重结论块(批次条目 dedupe 字段的统一形状)。"""
    return {
        "decision": decision,
        "existing_id": existing_id,
        "existing_label": existing_label,
        "default_action": default_action,
        "reason": reason,
        "basic": basic,
        "semantic": semantic,
    }


def _new_item(
    *,
    item_id: str,
    kind: str,
    label: str,
    payload: dict[str, Any],
    dedupe: dict[str, Any],
    status: str = PENDING,
    author_refs: list[str] | None = None,
    source_ref: str | None = None,
    target_ref: str | None = None,
    meta: dict[str, Any] | None = None,
    review_note: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """构造批次条目(统一 13 字段结构,避免三处构造器各自维护)。"""
    return {
        "item_id": item_id,
        "kind": kind,
        "label": label,
        "payload": payload,
        "author_refs": author_refs or [],
        "source_ref": source_ref,
        "target_ref": target_ref,
        "dedupe": dedupe,
        "meta": meta,
        "status": status,
        "action": None,
        "resolved_id": None,
        "reviewed_at": None,
        "review_note": review_note,
        "error": error,
    }


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
        _new_item(
            item_id=item_id,
            kind="author",
            label=payload.get("Name_CN") or payload.get("Name_EN") or payload.get("originalName") or "?",
            payload=payload,
            dedupe=dedupe,
        )
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
        _new_item(
            item_id=item_id,
            kind="work",
            label=payload.get("Title_CN") or payload.get("originalTitle") or "?",
            payload=payload,
            author_refs=author_refs,
            dedupe=dedupe,
        )
    )
    return item_id


def _add_edge_item(
    items: list[dict[str, Any]],
    source_ref: str,
    target_ref: str,
    evidence: dict[str, Any],
    public: dict[str, list[dict[str, Any]]],
    report: dict[str, Any] | None = None,
) -> str | None:
    """新增涟漪条目（源 → 目标）。端点在批内已确定（可能对应现有记录）。

    涟漪去重：
    - 批内同源同目标 → 合并证据出处并复用条目（避免撞 DB UNIQUE(source,target)）；
    - 源 == 目标（自我提及）→ 标记 SKIPPED，不进入默认发布；
    - 两端都复用现有作品 → 检查 admin 空间是否已有同源同目标涟漪；
    - 否则回退到去重报告的涟漪命中作为人工核对提示。
    """
    # 批内去重:与已有涟漪同源同目标 → 合并证据
    for it in items:
        if it["kind"] != "edge":
            continue
        if it.get("source_ref") == source_ref and it.get("target_ref") == target_ref:
            p = it["payload"]
            cur_parts = [x for x in (p.get("evidenceSource") or "").split("；") if x]
            add = (evidence.get("evidenceSource") or "").strip()
            if add and add not in cur_parts:
                p["evidenceSource"] = "；".join([*cur_parts, add])
            if not p.get("evidence") and evidence.get("evidence"):
                p["evidence"] = evidence.get("evidence")
            return it["item_id"]

    item_id = f"e{len([i for i in items if i['kind'] == 'edge']) + 1}"
    payload = {
        "evidence": evidence.get("evidence"),
        "evidenceSource": evidence.get("evidenceSource"),
        "note": None,
    }
    work_items = {it["item_id"]: it for it in items if it["kind"] == "work"}
    src = work_items.get(source_ref)
    tgt = work_items.get(target_ref)
    label = f"{_label(src) if src else source_ref} → {_label(tgt) if tgt else target_ref}"

    # 自我提及:目标作品 == 源书作品 → DB 约束禁止自环,默认跳过(可复核后改判)
    if source_ref == target_ref:
        items.append(
            _new_item(
                item_id=item_id,
                kind="edge",
                label=label,
                payload=payload,
                source_ref=source_ref,
                target_ref=target_ref,
                dedupe=_dedupe_result(
                    "possible", None, None, "create",
                    "涟漪目标与源书为同一作品（自我提及），无法建边",
                ),
                meta={"mention_type": evidence.get("mention_type")},
                status=SKIPPED,
                review_note="自动跳过:目标作品 == 源书作品",
                error="涟漪目标与源书为同一作品，DB 约束禁止自环",
            )
        )
        return item_id

    # 两端都判定为复用现有作品 → 查 admin 空间是否已有该涟漪
    dedupe: dict[str, Any] = _dedupe_result(
        "new", None, None, "create", "涟漪以证据内容创建，端点为新建作品"
    )
    if src and tgt and src["dedupe"].get("existing_id") and tgt["dedupe"].get("existing_id"):
        sid = src["dedupe"]["existing_id"]
        tid = tgt["dedupe"]["existing_id"]
        dup = next(
            (e for e in public["edges"] if e["source_work_id"] == sid and e["target_work_id"] == tid),
            None,
        )
        if dup:
            dedupe = _dedupe_result(
                "likely_duplicate",
                dup["id"],
                f"{_existing_label(src['dedupe'])} → {_existing_label(tgt['dedupe'])}",
                "reuse",
                "admin 空间已存在相同源→目标涟漪",
            )
    # 未命中端点级检查时,回退到去重报告的涟漪命中作为提示
    if dedupe["decision"] == "new" and src and tgt:
        report_entry = _match_report_edge(report, src.get("payload") or {}, tgt.get("payload") or {})
        if report_entry and report_entry.get("decision") != "new":
            ex = (report_entry.get("basic") or {}).get("existing")
            dedupe = _dedupe_result(
                "possible",
                ex.get("id") if ex else None,
                f"{ex.get('src_label')} → {ex.get('tgt_label')}" if ex else None,
                "create",
                f"去重报告:admin 空间已有相似涟漪({report_entry.get('reason')}),请确认端点后再决定复用",
                basic=report_entry.get("basic"),
            )
    items.append(
        _new_item(
            item_id=item_id,
            kind="edge",
            label=label,
            payload=payload,
            source_ref=source_ref,
            target_ref=target_ref,
            dedupe=dedupe,
            meta={"mention_type": evidence.get("mention_type")},
        )
    )
    return item_id


def build_batch(
    extract: dict[str, Any],
    report: dict[str, Any] | None,
    db_path: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """把 extract_source_book.py 输出 + dedupe_check 报告合并成批次登记簿。

    本函数只读数据库（上传者空间去重），不做任何写入,便于纯只读地生成/预览批次。
    """
    if owner_id:
        public = load_rows(db_path, owner_id=owner_id)
    else:
        public = load_rows(db_path)  # 未指定 owner 时管线视角全库
    report = report or {"authors": [], "works": [], "edges": []}

    items: list[dict[str, Any]] = []

    # 1) 作者：源书作者优先，随后是涟漪提及作品的作者（拆中文名/英文名）
    # 源书作者 = extract["authors"]（A1 阶段输出）。enrich_ripple_authors 把
    # 涟漪作者单独存放在 extract["ripple_authors"] / work.author_info；对旧版
    # 提取结果（涟漪作者曾混入 extract["authors"]）做容错:优先按 source_book
    # 元数据作者匹配，匹配不到的再剔除与任一涟漪作者同名的条目，避免把全书
    # 提及作者误挂到源书作品。
    source_meta = [_norm(x) for x in (extract.get("source_book") or {}).get("authors") or [] if x]
    ripple_author_keys: set[str] = set()
    for r in extract.get("ripples") or []:
        info = (r.get("work") or {}).get("author_info")
        if isinstance(info, dict):
            for key in ("Name_CN", "originalName", "Name_EN"):
                if info.get(key):
                    ripple_author_keys.add(_norm(info[key]))
    for a in extract.get("ripple_authors") or []:
        for key in ("Name_CN", "originalName", "Name_EN"):
            if a.get(key):
                ripple_author_keys.add(_norm(a[key]))

    def _is_source_author(a: dict[str, Any]) -> bool:
        norm_keys = {
            _norm(a.get(key)) for key in ("Name_CN", "originalName", "Name_EN") if a.get(key)
        }
        norm_keys.discard("")
        if source_meta and any(nk in meta or meta in nk for nk in norm_keys for meta in source_meta):
            return True
        if norm_keys & ripple_author_keys:
            return False
        return True

    source_authors = [a for a in extract.get("authors") or [] if _is_source_author(a)]
    source_author_ids = list(
        dict.fromkeys(_add_author_item(items, _author_payload(a), report, public) for a in source_authors)
    )

    # 涟漪作者条目注册表:键 = _ripple_author_key(work),值 = 批内作者条目 id。
    # 作品阶段直接按键引用,避免用原文「中文名（English Name）」硬匹配失败
    # (如文本写「蕾切尔·卡森（Rachel Carson）」而补全后的 Name_CN 是「蕾切尔·卡逊」)。
    ripple_author_items: dict[str, str] = {}
    for r in extract.get("ripples") or []:
        w = r.get("work") or {}
        author_name = (w.get("author") or "").strip()
        if not author_name:
            continue
        info = w.get("author_info")
        if isinstance(info, dict) and (info.get("Name_CN") or info.get("originalName")):
            # enrich_ripple_authors 已补全(国籍/生卒年/英文名等):直接使用完整记录
            payload = {k: info.get(k) for k in AUTHOR_FIELDS}
        else:
            # 未补全(离线/兼容路径):仅拆中文名/英文名
            cn, en = _split_author_name(author_name)
            payload = {"originalName": author_name, "Name_CN": cn, "Name_EN": en}
        item_id = _add_author_item(items, payload, report, public)
        key = _ripple_author_key(w)
        if key:
            ripple_author_items[key] = item_id

    # 2) 作品：源书 + 涟漪提及作品
    src_work = extract.get("work") or {}
    source_work_id: str | None = None
    if src_work.get("Title_CN") or src_work.get("originalTitle"):
        source_author_names = [
            a.get("Name_CN") or a.get("Name_EN") or a.get("originalName")
            for a in source_authors
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
        key = _ripple_author_key(w)
        if key and key in ripple_author_items:
            author_ref = [ripple_author_items[key]]
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
        _add_edge_item(items, source_work_id, target, r.get("evidence") or {}, public, report)

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

def _author_id_list(value) -> list[str]:
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def _stage_row(conn, kind: str, payload: dict, owner: str) -> str:
    """在指定空间创建一条 AI 草稿行,返回新行 id。

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
    """把批次内全部条目作为草稿写入指定空间(owner_id=owner),返回计数。

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

#!/usr/bin/env python3

"""
新增数据前的去重查询工具(两步校验)。

第一步:基础去重(本地 SQLite,无网络)
    - 规范化标题/作者名(全角→半角、去标点/书名号、拉丁转小写)
    - 精确匹配 / 包含匹配 / 字符二元组 Jaccard 相似
第二步:向量语义校验(阿里云百炼 Embedding,需网络与 ALIYUN_* 配置)
    - 候选与库内现有条目的标题文本做余弦相似度
    - 库内条目向量落库缓存(embeddings 表):model + VECTOR_VERSION + 文本
      hash 命中即复用;仅新行/文本变更/换模型/--rebuild-vectors 时调接口
    - 高分提示疑似重复,供人工确认后决定是复用已有记录还是新增
第三步:LLM 兜底确认(DeepSeek,需 DEEPSEEK_* 配置)
    - 基础/语义判定为「可能重复」时,把候选与库内命中条目的描述交给
      deepseek-v4-flash 判断是否同一实体,仅要求输出 0~1 置信度
    - 置信度 > 0.8 直接按重复处理(无需人工确认);否则维持人工确认

输入:
    - --input:extract_source_book.py 的输出 JSON(自动检查 authors / work / ripples)
    - 或直接传 --title-cn / --title-en / --original-title / --author 做单条检查

核心入口:run_dedupe() 供 pipeline_ingest 进程内复用;CLI 只做参数解析与落盘。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from app import db_sqlite  # noqa: E402
from app.ai_assistant import prompts  # noqa: E402
from app.ai_assistant.tools import llm_client  # noqa: E402
from app.ai_assistant.tools.common import load_dotenv_once, log, now_iso, utf8_stdout  # noqa: E402
from app.dedupe_util import char_bigrams, jaccard, load_rows, normalize_title  # noqa: E402

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "output" / "dedupe_report.json"
EMBED_BATCH = 16  # 阿里云百炼 embedding 单批上限为 20,留余量取 16
VECTOR_VERSION = 1  # embeddings 缓存版本;嵌入文本格式或模型语义变化时 +1(配合 --rebuild-vectors)
LLM_CONFIRM_THRESHOLD = 0.8  # LLM 兜底确认置信度 > 此值视为重复,无需人工确认
# 阈值按 qwen3.7-text-embedding 实测标定(2026-08-24,"原文名|中文名|作者"
# 三字段嵌入格式):
#   真重复(圣经,production 三字段文本)≈ 0.735
#   非重复最高分 ≈ 0.537
# 故 strong=0.70、possible=0.60,两侧各留约 0.06 余量。
SEMANTIC_STRONG = 0.70  # 语义余弦相似度 >= 此值视为疑似重复
SEMANTIC_POSSIBLE = 0.60  # 语义余弦相似度 >= 此值视为可能重复
TOKEN_JACCARD = 0.45  # 基础层字符二元组相似阈值


# ======================================================================
# 基础工具
# ======================================================================
def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """只保留指定键且值非 None 的字段。"""
    return {k: row[k] for k in keys if row.get(k) is not None}


# ======================================================================
# 数据库读取
# ======================================================================
def load_existing(db_path: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """读取库内全部活跃(未软删除)的作者/作品/涟漪(含个人空间)。"""
    return load_rows(db_path)


def _summarize_work(row: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        row,
        (
            "id",
            "Title_CN",
            "Title_EN",
            "originalTitle",
            "Title_Other",
            "publicationYear",
            "genre",
            "author_names",
            "owner_id",
            "created_by",
        ),
    )


def _summarize_author(row: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        row,
        (
            "id",
            "originalName",
            "Name_CN",
            "Name_EN",
            "nationality",
            "birthYear",
            "deathYear",
            "owner_id",
            "created_by",
        ),
    )


# ======================================================================
# 第一步:基础去重
# ======================================================================
def _title_variants(row: dict[str, Any]) -> list[str]:
    return [
        normalize_title(row.get("Title_CN")),
        normalize_title(row.get("Title_EN")),
        normalize_title(row.get("originalTitle")),
        normalize_title(row.get("Title_Other")),
    ]


def basic_match_work(
    cand: dict[str, Any], existing: list[dict[str, Any]]
) -> dict[str, Any]:
    """作品基础去重,返回 {level, score, existing, matched}。"""
    c_variants = _title_variants(cand)
    c_author = normalize_title(cand.get("author") or cand.get("_author_names"))
    best: dict[str, Any] = {
        "level": "none",
        "score": 0.0,
        "existing": None,
        "matched": [],
    }
    for row in existing:
        row_author = normalize_title(row.get("author_names"))
        for cv in c_variants:
            if not cv:
                continue
            for ev in _title_variants(row):
                if not ev:
                    continue
                level, score = _score_variant_pair(cv, ev)
                if level == "none":
                    continue
                # 标题完全相同但作者明显不同 → 同名异书,降级提示人工确认
                if level == "exact" and c_author and row_author and c_author != row_author:
                    level, score = "exact_diff_author", 0.5
                if score > best["score"]:
                    best = {
                        "level": level,
                        "score": score,
                        "existing": _summarize_work(row),
                        "matched": [cv, ev],
                    }
    return best


def basic_match_author(
    cand: dict[str, Any], existing: list[dict[str, Any]]
) -> dict[str, Any]:
    """作者基础去重,返回 {level, score, existing, matched}。"""
    c_variants = [
        normalize_title(cand.get("Name_CN")),
        normalize_title(cand.get("Name_EN")),
        normalize_title(cand.get("originalName")),
    ]
    best: dict[str, Any] = {
        "level": "none",
        "score": 0.0,
        "existing": None,
        "matched": [],
    }
    for row in existing:
        e_variants = [
            normalize_title(row.get("Name_CN")),
            normalize_title(row.get("Name_EN")),
            normalize_title(row.get("originalName")),
        ]
        for cv in c_variants:
            if not cv:
                continue
            for ev in e_variants:
                if not ev:
                    continue
                level, score = _score_variant_pair(cv, ev)
                if level == "none":
                    continue
                if score > best["score"]:
                    best = {
                        "level": level,
                        "score": score,
                        "existing": _summarize_author(row),
                        "matched": [cv, ev],
                    }
    return best


def _score_variant_pair(cv: str, ev: str) -> tuple[str, float]:
    """单对标题变体匹配级别:(exact|contained|token|none, score)。"""
    if cv == ev:
        return "exact", 1.0
    if len(cv) >= 2 and len(ev) >= 2 and (cv in ev or ev in cv):
        return "contained", 0.7
    sim = jaccard(char_bigrams(cv), char_bigrams(ev))
    if sim < TOKEN_JACCARD:
        return "none", 0.0
    return "token", round(sim, 3)


def _variant_similarity(
    c_variants: list[str], e_variants: list[str]
) -> tuple[str, float]:
    """两组标题变体的最佳匹配级别:(exact|contained|token|none, score)。"""
    best_level, best_score = "none", 0.0
    for cv in c_variants:
        if not cv:
            continue
        for ev in e_variants:
            if not ev:
                continue
            level, score = _score_variant_pair(cv, ev)
            if score > best_score or (score == best_score and level == "exact"):
                best_level, best_score = level, score
    return best_level, best_score


def _combine_edge_level(
    s_level: str, t_level: str, s_score: float, t_score: float
) -> tuple[str, float]:
    """涟漪两端匹配级别合成:整体取较低一侧;两侧都精确命中才是 exact。"""
    score = round(min(s_score, t_score), 3)
    if s_level == "exact" and t_level == "exact":
        return "exact", score
    if s_level in ("exact", "contained") and t_level in ("exact", "contained"):
        return "contained", score
    return "token", score


def basic_match_edge(
    cand: dict[str, Any], existing: list[dict[str, Any]]
) -> dict[str, Any]:
    """涟漪基础去重:候选的 源作品 与 目标作品 标题同时命中同一条现有涟漪。"""
    best: dict[str, Any] = {
        "level": "none",
        "score": 0.0,
        "existing": None,
        "matched": [],
    }
    c_src_variants = [v for v in _title_variants(cand.get("source") or {}) if v]
    c_tgt_variants = [v for v in _title_variants(cand.get("target") or {}) if v]
    if not c_src_variants or not c_tgt_variants:
        return best
    for row in existing:
        e_src = {
            "Title_CN": row.get("src_Title_CN"),
            "Title_EN": row.get("src_Title_EN"),
            "originalTitle": row.get("src_originalTitle"),
            "Title_Other": row.get("src_Title_Other"),
        }
        e_tgt = {
            "Title_CN": row.get("tgt_Title_CN"),
            "Title_EN": row.get("tgt_Title_EN"),
            "originalTitle": row.get("tgt_originalTitle"),
            "Title_Other": row.get("tgt_Title_Other"),
        }
        s_level, s_score = _variant_similarity(c_src_variants, _title_variants(e_src))
        t_level, t_score = _variant_similarity(c_tgt_variants, _title_variants(e_tgt))
        if s_level == "none" or t_level == "none":
            continue
        level, score = _combine_edge_level(s_level, t_level, s_score, t_score)
        if score > best["score"]:
            best = {
                "level": level,
                "score": score,
                "existing": {
                    "id": row.get("id"),
                    "source_work_id": row.get("source_work_id"),
                    "target_work_id": row.get("target_work_id"),
                    "evidenceSource": row.get("evidenceSource"),
                    "src_label": e_src.get("Title_CN") or e_src.get("originalTitle"),
                    "tgt_label": e_tgt.get("Title_CN") or e_tgt.get("originalTitle"),
                },
                "matched": [s_level, t_level],
            }
    return best


def _decide_edge(basic: dict[str, Any]) -> tuple[str, str]:
    """涟漪去重结论:两端都精确命中才算 likely_duplicate。"""
    level = basic.get("level")
    if level == "exact":
        return "likely_duplicate", "涟漪两端标题与现有涟漪完全相同"
    if level in ("contained", "token"):
        return "possible", f"涟漪两端与现有涟漪存在相似匹配({level} {basic.get('score')})"
    return "new", "无匹配"


# ======================================================================
# 第二步:向量语义校验(阿里云百炼 Embedding)
# ======================================================================
def _load_aliyun() -> tuple[OpenAI, str]:
    """加载 ALIYUN_* 配置并创建 OpenAI 兼容客户端,返回 (client, model)。"""
    load_dotenv_once()
    api_key = os.getenv("ALIYUN_API_KEY")
    base_url = os.getenv("ALIYUN_BASE_URL")
    model = os.getenv("ALIYUN_MODEL") or "text-embedding-v4"
    if not api_key or not base_url:
        raise RuntimeError("缺少 ALIYUN_API_KEY / ALIYUN_BASE_URL,请在项目根目录 .env 配置")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=2)
    return client, model


def _embed(client: OpenAI, model: str, texts: list[str]) -> list[list[float]]:
    """分批调用 embedding 接口,返回与输入等长的向量列表。"""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        chunk = texts[start : start + EMBED_BATCH]
        resp = client.embeddings.create(model=model, input=chunk)
        ordered = sorted(resp.data, key=lambda d: d.index)
        vectors.extend([d.embedding for d in ordered])
    return vectors


def _text_hash(text: str) -> str:
    """嵌入文本的 SHA-256,用于感知标题/作者字段变更。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _open_vector_conn(db_path: str | None) -> sqlite3.Connection:
    """打开 SQLite 连接并确保 embeddings 缓存表存在(幂等迁移)。"""
    path = Path(db_path) if db_path else db_sqlite.DB_PATH
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    db_sqlite._migrate(conn)
    return conn


def _load_vector_cache(
    conn: sqlite3.Connection, entity_type: str, model: str
) -> dict[str, tuple[str, list[float]]]:
    """读取当前版本/模型的全部缓存:{entity_id: (text_hash, vector)}。"""
    out: dict[str, tuple[str, list[float]]] = {}
    rows = conn.execute(
        "SELECT entity_id, text_hash, vector FROM embeddings"
        " WHERE entity_type = ? AND model = ? AND version = ?",
        (entity_type, model, VECTOR_VERSION),
    ).fetchall()
    for r in rows:
        try:
            out[r["entity_id"]] = (r["text_hash"], json.loads(r["vector"]))
        except (TypeError, ValueError):
            continue
    return out


def _save_vector_cache(
    conn: sqlite3.Connection,
    entity_type: str,
    model: str,
    entity_id: str,
    text: str,
    vector: list[float],
) -> None:
    """写入/覆盖一条向量缓存;键含 model + VECTOR_VERSION。"""
    conn.execute(
        "INSERT OR REPLACE INTO embeddings"
        " (entity_type, entity_id, model, version, text_hash, vector, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            entity_type,
            entity_id,
            model,
            VECTOR_VERSION,
            _text_hash(text),
            json.dumps(vector),
            now_iso(),
        ),
    )


def _load_vectors_cached(
    client: OpenAI,
    model: str,
    conn: sqlite3.Connection,
    entity_type: str,
    rows: list[dict[str, Any]],
    text_fn: Any,
    *,
    rebuild: bool = False,
) -> tuple[list[str], list[list[float] | None]]:
    """库内行向量:缓存命中复用,未命中(新行/文本变更/换模型/rebuild)才调 embedding。

    缓存键 = entity_type + entity_id + model + VECTOR_VERSION,命中还要求
    text_hash 与当前嵌入文本一致。返回与 rows 对齐的 (texts, vectors);
    空文本行向量为 None 且不入缓存。
    """
    texts = [text_fn(r) for r in rows]
    vectors: list[list[float] | None] = [None] * len(texts)
    cache: dict[str, tuple[str, list[float]]] = (
        {} if rebuild else _load_vector_cache(conn, entity_type, model)
    )
    missing: list[tuple[int, str]] = []
    for i, (row, text) in enumerate(zip(rows, texts, strict=False)):
        if not text:
            continue
        entity_id = row.get("id")
        cached = cache.get(entity_id) if entity_id else None
        if cached is not None and cached[0] == _text_hash(text):
            vectors[i] = cached[1]
        else:
            missing.append((i, text))
    if not missing:
        log(f"{entity_type} 向量:全部命中缓存({len(rows)} 条)")
        return texts, vectors
    embedded = _embed(client, model, [t for _, t in missing])
    with conn:
        for (i, text), vec in zip(missing, embedded, strict=False):
            vectors[i] = vec
            if rows[i].get("id"):
                _save_vector_cache(conn, entity_type, model, rows[i]["id"], text, vec)
    mode = "重建" if rebuild else "增量"
    log(f"{entity_type} 向量:{mode}嵌入 {len(missing)} 条,缓存命中 {len(rows) - len(missing)} 条")
    return texts, vectors


def semantic_match(
    client: OpenAI,
    model: str,
    cand_text: str,
    existing_rows: list[dict[str, Any]],
    existing_texts: list[str],
    existing_vectors: list[list[float] | None],
    summarize: Any,
    top: int,
) -> dict[str, Any]:
    """候选文本与库内文本做余弦相似度,返回 top 列表与最高分。"""
    if not cand_text:
        return {"error": "候选文本为空", "top_matches": [], "best_score": 0.0}
    try:
        cand_vec = _embed(client, model, [cand_text])[0]
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "top_matches": [], "best_score": 0.0}

    scored = [
        (summarize(row), cosine(cand_vec, vec))
        for row, vec in zip(existing_rows, existing_vectors, strict=False)
        if vec
    ]
    scored.sort(key=lambda t: t[1], reverse=True)
    return {
        "top_matches": [
            {"existing": row, "score": round(score, 4)} for row, score in scored[:top]
        ],
        "best_score": round(scored[0][1], 4) if scored else 0.0,
    }


def _work_embed_text(c: dict[str, Any]) -> str:
    """作品嵌入文本:按"原文名 | 中文名 | 作者"三字段拼接,与库内文本同构。

    仅用于语义匹配;Title_EN / Title_Other 仍参与基础去重(_title_variants)。
    """
    parts = [
        c.get("originalTitle"),
        c.get("Title_CN"),
        c.get("author"),
        c.get("_author_names"),
        c.get("author_names"),
    ]
    return " | ".join(str(p) for p in parts if p)


def _author_embed_text(c: dict[str, Any]) -> str:
    parts = [c.get("Name_CN"), c.get("Name_EN"), c.get("originalName")]
    return " | ".join(str(p) for p in parts if p)


# ======================================================================
# 第三步:LLM 兜底确认(DeepSeek)
# ======================================================================
def _load_deepseek() -> tuple[OpenAI, str]:
    """加载 DeepSeek 客户端与模型(作者/作品重复 LLM 确认)。"""
    api_key, base_url = llm_client.load_environment()
    return llm_client.create_client(api_key, base_url), llm_client.MODEL


def _llm_messages(kind: str, text_a: str, text_b: str) -> list[dict[str, str]]:
    """构造 LLM 兜底确认消息:系统提示词(定义在 prompts.py)+ A/B 实体描述。"""
    entity = "同一本书" if kind == "作品" else "同一个作者"
    return [
        {"role": "system", "content": prompts.DEDUPE_CONFIRM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": prompts.DEDUPE_CONFIRM_USER_PROMPT.format(
                entity=entity, text_a=text_a, text_b=text_b
            ),
        },
    ]


def llm_duplicate_confidence(
    client: OpenAI,
    model: str,
    kind: str,
    text_a: str,
    text_b: str,
) -> float | None:
    """询问 LLM 判断 A/B 是否为同一实体,返回 0~1 置信度;失败/无法解析返回 None。"""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=_llm_messages(kind, text_a, text_b),
            temperature=0,
            max_tokens=16,
            # 数值判断题不需要深度思考;deepseek-v4-flash 默认会先推理,
            # 小 max_tokens 下正文为空(finish_reason=length),故显式关闭
            extra_body={"thinking": {"type": "disabled"}},
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        log(f"LLM 重复确认调用失败:{type(exc).__name__}: {exc}")
        return None
    match = re.search(r"-?\d+(?:\.\d+)?|\.\d+", raw)
    if not match:
        log(f"LLM 重复确认输出无法解析:{raw!r}")
        return None
    value = float(match.group())
    if not 0.0 <= value <= 1.0:
        log(f"LLM 重复确认输出越界:{raw!r}")
        return None
    return value


def _work_compare_text(c: dict[str, Any]) -> str:
    """LLM 比对用的作品描述:尽量带全可区分字段。"""
    parts: list[str] = []
    for label, key in (
        ("中文名", "Title_CN"),
        ("原名", "originalTitle"),
        ("英文名", "Title_EN"),
        ("其他译名", "Title_Other"),
        ("语言", "language"),
        ("年份", "publicationYear"),
        ("体裁", "genre"),
    ):
        value = c.get(key)
        if value:
            parts.append(f"{label}:{value}")
    author = c.get("author") or c.get("author_names") or c.get("_author_names")
    if author:
        parts.append(f"作者:{author}")
    return "；".join(parts)


def _author_compare_text(c: dict[str, Any]) -> str:
    """LLM 比对用的作者描述。"""
    parts: list[str] = []
    for label, key in (
        ("中文名", "Name_CN"),
        ("英文名", "Name_EN"),
        ("原名", "originalName"),
        ("国籍", "nationality"),
        ("生年", "birthYear"),
        ("卒年", "deathYear"),
    ):
        value = c.get(key)
        if value:
            parts.append(f"{label}:{value}")
    return "；".join(parts)


def _semantic_top_existing(sem: dict[str, Any] | None) -> dict[str, Any] | None:
    """语义最高匹配的库内条目(去重报告 summarize 形式);无则 None。"""
    if not sem:
        return None
    top = sem.get("top_matches") or []
    return top[0]["existing"] if top else None


def _maybe_llm_confirm(
    ds_client: OpenAI | None,
    ds_model: str,
    kind: str,
    cand: dict[str, Any],
    basic: dict[str, Any],
    sem: dict[str, Any] | None,
    compare_text: Any,
    decision: str,
    reason: str,
) -> tuple[str, str, dict[str, Any] | None]:
    """possible 判定时询问 LLM 是否同一实体;置信度 > 阈值升级为重复。

    返回 (decision, reason, llm_info);llm_info 落报告供审核追溯。
    """
    if ds_client is None or decision != "possible":
        return decision, reason, None
    target = basic.get("existing") or _semantic_top_existing(sem)
    if not target:
        return decision, reason, None
    text_a = compare_text(cand)
    text_b = compare_text(target)
    conf = llm_duplicate_confidence(ds_client, ds_model, kind, text_a, text_b)
    entity = "本书" if kind == "作品" else "作者"
    info: dict[str, Any] = {
        "kind": kind,
        "model": ds_model,
        "confidence": conf,
        "threshold": LLM_CONFIRM_THRESHOLD,
        "existing_id": target.get("id"),
        "compared": {"a": text_a, "b": text_b},
    }
    if conf is not None and conf > LLM_CONFIRM_THRESHOLD:
        return (
            "likely_duplicate",
            f"LLM 确认:与现有{kind}为同一{entity}"
            f"(置信度 {conf:.2f} > {LLM_CONFIRM_THRESHOLD})",
            info,
        )
    if conf is not None:
        reason = f"{reason};LLM 判定非重复(置信度 {conf:.2f})"
    return decision, reason, info


# ======================================================================
# 判定与报告
# ======================================================================
def decide(
    basic: dict[str, Any],
    semantic: dict[str, Any] | None,
    *,
    strong: float,
    possible: float,
) -> tuple[str, str]:
    """综合基础/语义结果,返回 (decision, reason)。"""
    level = basic.get("level")
    if level == "exact":
        return "likely_duplicate", "基础匹配:标题完全相同"
    if level == "exact_diff_author":
        return "possible", "基础匹配:标题相同但作者不同(疑似同名异书)"
    if semantic and semantic.get("best_score", 0.0) >= strong:
        return "likely_duplicate", f"语义相似度 {semantic['best_score']}(阈值 {strong})"
    if level in ("contained", "token"):
        return "possible", f"基础匹配:{level}"
    if semantic and semantic.get("best_score", 0.0) >= possible:
        return "possible", f"语义相似度 {semantic['best_score']}(阈值 {possible})"
    if semantic is not None:
        return "new", f"无匹配(语义最高 {semantic.get('best_score', 0.0)})"
    return "new", "无匹配"


def _clean_candidate(cand: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in cand.items() if not k.startswith("_")}


def _print_summary(report: dict[str, Any]) -> None:
    """打印人类可读的摘要。"""

    def line(kind: str, item: dict[str, Any]) -> None:
        c = item["candidate"]
        label = (
            c.get("Title_CN")
            or c.get("originalTitle")
            or c.get("Name_CN")
            or c.get("Name_EN")
            or "?"
        )
        print(f"[{kind}] {label} → {item.get('decision')}({item.get('reason')})")
        basic = item.get("basic") or {}
        if basic.get("level") != "none" and basic.get("existing"):
            ex = basic["existing"]
            ex_label = ex.get("Title_CN") or ex.get("originalTitle") or ex.get("Name_CN") or "?"
            print(
                f"    基础匹配: {basic['level']} ({basic['score']})"
                f" → {ex_label} (#{ex.get('id')})"
            )
        sem = item.get("semantic")
        if sem and sem.get("top_matches"):
            top = sem["top_matches"][0]
            ex = top["existing"]
            ex_label = ex.get("Title_CN") or ex.get("originalTitle") or ex.get("Name_CN") or "?"
            print(f"    语义最高: {top['score']} → {ex_label} (#{ex.get('id')})")
        elif sem and sem.get("error"):
            print(f"    语义: 失败({sem['error']})")
        llm = item.get("llm")
        if llm:
            conf = llm.get("confidence")
            if conf is not None:
                verdict = "重复" if conf > LLM_CONFIRM_THRESHOLD else "非重复"
                print(f"    LLM 确认({llm.get('model')}): {conf:.2f} → {verdict}")
            else:
                print("    LLM 确认: 调用失败/输出无法解析")

    for item in report.get("authors", []):
        line("作者", item)
    for item in report.get("works", []):
        line("作品", item)
    for item in report.get("edges", []):
        c = item.get("candidate") or {}
        src = c.get("source") or {}
        tgt = c.get("target") or {}
        src_label = src.get("Title_CN") or src.get("originalTitle") or "?"
        tgt_label = tgt.get("Title_CN") or tgt.get("originalTitle") or "?"
        print(f"[涟漪] {src_label} → {tgt_label} → {item.get('decision')}({item.get('reason')})")
        basic = item.get("basic") or {}
        if basic.get("level") != "none" and basic.get("existing"):
            ex = basic["existing"]
            print(
                f"    基础匹配: {basic['level']} ({basic['score']})"
                f" → {ex.get('src_label')} → {ex.get('tgt_label')} (#{ex.get('id')})"
            )


# ======================================================================
# 候选收集
# ======================================================================
def _work_candidate_from_result(
    w: dict[str, Any], author_names: list[str] | None = None
) -> dict[str, Any]:
    """从 extract 结果的作品对象构造候选(附作者字符串用于消歧)。"""
    cand = _pick(
        w,
        ("Title_CN", "Title_EN", "originalTitle", "Title_Other", "language", "publicationYear", "genre", "author"),
    )
    names = " ".join(n for n in (author_names or []) if n)
    if names:
        cand["_author_names"] = names
    return cand


def collect_candidates_from_extract(
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """从 extract_source_book 的输出 JSON 收集待检查的作者/作品候选。"""
    work_cands: list[dict[str, Any]] = []
    author_cands: list[dict[str, Any]] = []
    for a in data.get("authors") or []:
        author_cands.append(
            _pick(
                a,
                ("originalName", "Name_CN", "Name_EN", "nationality", "birthYear", "deathYear", "note"),
            )
        )
    src_work = data.get("work")
    if src_work:
        src_author_names = [
            a.get("Name_CN") or a.get("Name_EN") or a.get("originalName")
            for a in data.get("authors") or []
        ]
        work_cands.append(_work_candidate_from_result(src_work, src_author_names))
    for r in data.get("ripples") or []:
        w = r.get("work") or {}
        if w.get("Title_CN") or w.get("originalTitle"):
            work_cands.append(_work_candidate_from_result(w, [w.get("author")]))
    return work_cands, author_cands


def collect_edge_candidates_from_extract(
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    """从 extract 输出收集涟漪候选:source = 源书作品, target = 提及作品。"""
    src = data.get("work") or {}
    if not (src.get("Title_CN") or src.get("originalTitle")):
        return []
    edge_cands: list[dict[str, Any]] = []
    for r in data.get("ripples") or []:
        w = r.get("work") or {}
        if not (w.get("Title_CN") or w.get("originalTitle")):
            continue
        edge_cands.append(
            {
                "source": _work_candidate_from_result(src),
                "target": _work_candidate_from_result(w, [w.get("author")]),
            }
        )
    return edge_cands


def _collect_candidates(
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """从 --input JSON 或命令行参数收集待检查的作者/作品/涟漪候选。"""
    if args.input:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        work_cands, author_cands = collect_candidates_from_extract(data)
        return work_cands, author_cands, collect_edge_candidates_from_extract(data)
    work_cands: list[dict[str, Any]] = []
    author_cands: list[dict[str, Any]] = []
    if args.title_cn or args.title_en or args.original_title:
        work_cands.append(
            {
                "Title_CN": args.title_cn,
                "Title_EN": args.title_en,
                "originalTitle": args.original_title,
                "language": args.language,
                "publicationYear": args.publication_year,
                "genre": args.genre,
                "author": args.author,
            }
        )
    if args.author and not (args.title_cn or args.title_en or args.original_title):
        author_cands.append({"Name_CN": args.author})
    if not work_cands and not author_cands:
        raise SystemExit("请提供 --input,或 --title-cn/--title-en/--original-title/--author 等参数")
    return work_cands, author_cands, []


# ======================================================================
# 主流程
# ======================================================================
def _dedupe_candidate(
    *,
    kind: str,
    cand: dict[str, Any],
    basic: dict[str, Any],
    client: OpenAI | None,
    model: str,
    embed_text: Any,
    existing_rows: list[dict[str, Any]],
    texts: list[str],
    vectors: list[list[float] | None],
    summarize: Any,
    ds_client: OpenAI | None,
    ds_model: str,
    compare_text: Any,
    force_semantic: bool,
    top: int,
    strong: float,
    possible: float,
    semantic_skip_levels: tuple[str, ...],
) -> dict[str, Any]:
    """单条候选去重:基础匹配 + 语义 + LLM 兜底,返回报告条目。"""
    sem = None
    if client is not None and (
        basic.get("level") not in semantic_skip_levels or force_semantic
    ):
        sem = semantic_match(
            client,
            model,
            embed_text(cand),
            existing_rows,
            texts,
            vectors,
            summarize,
            top,
        )
    decision, reason = decide(basic, sem, strong=strong, possible=possible)
    decision, reason, llm = _maybe_llm_confirm(
        ds_client, ds_model, kind, cand, basic, sem, compare_text,
        decision, reason,
    )
    return {
        "candidate": _clean_candidate(cand),
        "basic": basic,
        "semantic": sem,
        "llm": llm,
        "decision": decision,
        "reason": reason,
    }


def run_dedupe(
    work_cands: list[dict[str, Any]],
    author_cands: list[dict[str, Any]],
    *,
    edge_cands: list[dict[str, Any]] | None = None,
    db_path: str | None = None,
    basic_only: bool = False,
    force_semantic: bool = False,
    rebuild_vectors: bool = False,
    llm_confirm: bool = True,
    top: int = 5,
    strong: float = SEMANTIC_STRONG,
    possible: float = SEMANTIC_POSSIBLE,
) -> dict[str, Any]:
    """执行去重并返回报告 dict(CLI 与 pipeline_ingest 共用)。

    rebuild_vectors=True 时忽略 embeddings 缓存全量重嵌(换模型/阈值调整后重建)。
    llm_confirm=True 时对「可能重复」条目调 DeepSeek 兜底确认,置信度 > 0.8 直接按重复处理。
    """
    utf8_stdout()
    existing = load_existing(db_path)
    log(f"库内活跃数据:作品 {len(existing['works'])},作者 {len(existing['authors'])}")
    log(f"待检查:作品 {len(work_cands)},作者 {len(author_cands)},涟漪 {len(edge_cands or [])}")

    client: OpenAI | None = None
    model = ""
    if not basic_only:
        try:
            client, model = _load_aliyun()
            log(f"语义校验启用:模型 {model}")
        except RuntimeError as exc:
            log(f"⚠ 未启用语义校验:{exc}")
            client = None

    ds_client: OpenAI | None = None
    ds_model = ""
    if not basic_only and llm_confirm:
        try:
            ds_client, ds_model = _load_deepseek()
            log(f"LLM 兜底确认启用:模型 {ds_model}")
        except RuntimeError as exc:
            log(f"⚠ 未启用 LLM 兜底确认:{exc}")
            ds_client = None

    work_texts, work_vectors, author_texts, author_vectors = [], [], [], []
    if client is not None:
        log("生成库内标题向量(复用 embeddings 缓存)...")
        conn = _open_vector_conn(db_path)
        try:
            work_texts, work_vectors = _load_vectors_cached(
                client, model, conn, "work", existing["works"], _work_embed_text,
                rebuild=rebuild_vectors,
            )
            author_texts, author_vectors = _load_vectors_cached(
                client, model, conn, "author", existing["authors"], _author_embed_text,
                rebuild=rebuild_vectors,
            )
        finally:
            conn.close()

    report: dict[str, Any] = {
        "checked_at": now_iso(),
        "db_path": str(db_path or db_sqlite.DB_PATH),
        "existing_counts": {
            "works": len(existing["works"]),
            "authors": len(existing["authors"]),
            "edges": len(existing["edges"]),
        },
        "semantic": {
            "enabled": client is not None,
            "model": model,
            "vector_version": VECTOR_VERSION,
            "rebuild": rebuild_vectors,
        },
        "llm_confirm": {
            "enabled": ds_client is not None,
            "model": ds_model,
            "threshold": LLM_CONFIRM_THRESHOLD,
        },
        "authors": [],
        "works": [],
        "edges": [],
    }

    for cand in author_cands:
        basic = basic_match_author(cand, existing["authors"])
        report["authors"].append(
            _dedupe_candidate(
                kind="作者",
                cand=cand,
                basic=basic,
                client=client,
                model=model,
                embed_text=_author_embed_text,
                existing_rows=existing["authors"],
                texts=author_texts,
                vectors=author_vectors,
                summarize=_summarize_author,
                ds_client=ds_client,
                ds_model=ds_model,
                compare_text=_author_compare_text,
                force_semantic=force_semantic,
                top=top,
                strong=strong,
                possible=possible,
                semantic_skip_levels=("exact",),
            )
        )

    for cand in work_cands:
        basic = basic_match_work(cand, existing["works"])
        report["works"].append(
            _dedupe_candidate(
                kind="作品",
                cand=cand,
                basic=basic,
                client=client,
                model=model,
                embed_text=_work_embed_text,
                existing_rows=existing["works"],
                texts=work_texts,
                vectors=work_vectors,
                summarize=_summarize_work,
                ds_client=ds_client,
                ds_model=ds_model,
                compare_text=_work_compare_text,
                force_semantic=force_semantic,
                top=top,
                strong=strong,
                possible=possible,
                semantic_skip_levels=("exact", "exact_diff_author"),
            )
        )

    for cand in edge_cands or []:
        basic = basic_match_edge(cand, existing["edges"])
        decision, reason = _decide_edge(basic)
        report["edges"].append(
            {
                "candidate": cand,
                "basic": basic,
                "semantic": None,
                "llm": None,
                "decision": decision,
                "reason": reason,
            }
        )

    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="新增数据前的去重查询(基础匹配 + 向量语义校验)",
        epilog="示例:\n"
               "  uv run python -m app.ai_assistant.tools.dedupe_check --input app/ai_assistant/output/source_book_result.json\n"
               "  uv run python -m app.ai_assistant.tools.dedupe_check --input ... --basic-only\n"
               "  uv run python -m app.ai_assistant.tools.dedupe_check --title-cn 三体 --author 刘慈欣\n"
               "  uv run python -m app.ai_assistant.tools.dedupe_check --title-en \"The Stranger\" --author \"Albert Camus\"",
    )
    parser.add_argument("--input", help="extract_source_book.py 的输出 JSON 路径")
    parser.add_argument("--title-cn", help="候选作品中文名")
    parser.add_argument("--title-en", help="候选作品英文名")
    parser.add_argument("--original-title", help="候选作品原名")
    parser.add_argument("--author", help="候选作者名(作品候选的消歧/作者候选)")
    parser.add_argument("--language", help="候选作品语言代码(如 zh/en)")
    parser.add_argument("--publication-year", type=int, help="候选作品出版年份")
    parser.add_argument("--genre", help="候选作品体裁(Fiction/Non-fiction/Poetry/Drama)")
    parser.add_argument("--basic-only", action="store_true", help="只做基础去重,不调用 embedding")
    parser.add_argument(
        "--force-semantic",
        action="store_true",
        help="即使基础精确命中也执行语义校验(默认精确命中后跳过)",
    )
    parser.add_argument(
        "--rebuild-vectors",
        action="store_true",
        help="忽略 embeddings 缓存,全量重新嵌入库内作品/作者(换模型或阈值调整后重建)",
    )
    parser.add_argument(
        "--no-llm-confirm",
        action="store_true",
        help="对「可能重复」条目跳过 DeepSeek 兜底确认(默认开启)",
    )
    parser.add_argument("--top", type=int, default=5, help="语义最高匹配展示条数(默认 5)")
    parser.add_argument("--threshold-strong", type=float, default=SEMANTIC_STRONG)
    parser.add_argument("--threshold-possible", type=float, default=SEMANTIC_POSSIBLE)
    parser.add_argument("--db", default=None, help=f"SQLite 数据库路径(默认 {db_sqlite.DB_PATH})")
    parser.add_argument("--output", default=None, help=f"报告保存路径(默认 {DEFAULT_OUTPUT})")
    parser.add_argument("--json", action="store_true", help="stdout 同时输出完整 JSON 报告")
    return parser.parse_args()


def main() -> None:
    utf8_stdout()
    args = _parse_args()
    work_cands, author_cands, edge_cands = _collect_candidates(args)
    report = run_dedupe(
        work_cands,
        author_cands,
        edge_cands=edge_cands,
        db_path=args.db,
        basic_only=args.basic_only,
        force_semantic=args.force_semantic,
        rebuild_vectors=args.rebuild_vectors,
        llm_confirm=not args.no_llm_confirm,
        top=args.top,
        strong=args.threshold_strong,
        possible=args.threshold_possible,
    )
    _print_summary(report)

    out_path = Path(args.output) if args.output else DEFAULT_OUTPUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"报告已保存到:{out_path}")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

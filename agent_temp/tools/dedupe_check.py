#!/usr/bin/env python3

"""
新增数据前的去重查询工具（两步校验）。

第一步：基础去重（本地 SQLite，无网络）
    - 规范化标题/作者名（全角→半角、去标点/书名号、拉丁转小写）
    - 精确匹配 / 包含匹配 / 字符二元组 Jaccard 相似
第二步：向量语义校验（阿里云百炼 Embedding，需网络与 ALIYUN_* 配置）
    - 候选与库内现有条目的标题文本做余弦相似度
    - 高分提示疑似重复，供人工确认后决定是复用已有记录还是新增

输入：
    - --input：extract_source_book.py 的输出 JSON（自动检查 authors / work / ripples）
    - 或直接传 --title-cn / --title-en / --original-title / --author 做单条检查
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 保证同目录模块、agent_temp 根目录与项目根目录都能被导入
_TOOLS_DIR = Path(__file__).resolve().parent
_AGENT_TEMP_DIR = _TOOLS_DIR.parent
_REPO_ROOT = _AGENT_TEMP_DIR.parent
for _path in (_TOOLS_DIR, _AGENT_TEMP_DIR, _REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from dotenv import load_dotenv  # noqa: E402
from openai import OpenAI  # noqa: E402

from app import db_sqlite  # noqa: E402

DEFAULT_OUTPUT = _AGENT_TEMP_DIR / "output" / "dedupe_report.json"
EMBED_BATCH = 32
SEMANTIC_STRONG = 0.82  # 语义余弦相似度 >= 此值视为疑似重复
SEMANTIC_POSSIBLE = 0.68  # 语义余弦相似度 >= 此值视为可能重复
TOKEN_JACCARD = 0.45  # 基础层字符二元组相似阈值


# ======================================================================
# 基础工具
# ======================================================================
def log(msg: str) -> None:
    """带时间戳的立即输出，避免 stdout 缓冲导致看不到进度。"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def normalize_title(text: str | None) -> str:
    """标题/姓名规范化：全角→半角、去书名号/标点/空白、拉丁转小写。"""
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
    """字符二元组集合；长度 1 时返回自身。"""
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
    """读取库内全部活跃（未软删除）的作者与作品。"""
    path = Path(db_path) if db_path else db_sqlite.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        authors = [
            dict(r)
            for r in conn.execute(
                "SELECT id, originalName, Name_CN, Name_EN, nationality, birthYear,"
                " deathYear, note, owner_id, created_by"
                " FROM authors WHERE deletedAt IS NULL"
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
                " GROUP BY w.id"
            )
        ]
    finally:
        conn.close()
    return {"authors": authors, "works": works}


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
# 第一步：基础去重
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
    """作品基础去重，返回 {level, score, existing, matched}。"""
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
                if cv == ev:
                    level, score = "exact", 1.0
                elif len(cv) >= 2 and len(ev) >= 2 and (cv in ev or ev in cv):
                    level, score = "contained", 0.7
                else:
                    sim = jaccard(char_bigrams(cv), char_bigrams(ev))
                    if sim < TOKEN_JACCARD:
                        continue
                    level, score = "token", round(sim, 3)
                # 标题完全相同但作者明显不同 → 同名异书，降级提示人工确认
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
    """作者基础去重，返回 {level, score, existing, matched}。"""
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
                if cv == ev:
                    level, score = "exact", 1.0
                elif len(cv) >= 2 and len(ev) >= 2 and (cv in ev or ev in cv):
                    level, score = "contained", 0.7
                else:
                    sim = jaccard(char_bigrams(cv), char_bigrams(ev))
                    if sim < TOKEN_JACCARD:
                        continue
                    level, score = "token", round(sim, 3)
                if score > best["score"]:
                    best = {
                        "level": level,
                        "score": score,
                        "existing": _summarize_author(row),
                        "matched": [cv, ev],
                    }
    return best


# ======================================================================
# 第二步：向量语义校验（阿里云百炼 Embedding）
# ======================================================================
def _load_aliyun() -> tuple[OpenAI, str]:
    """加载 ALIYUN_* 配置并创建 OpenAI 兼容客户端，返回 (client, model)。"""
    load_dotenv(_REPO_ROOT / ".env")
    api_key = os.getenv("ALIYUN_API_KEY")
    base_url = os.getenv("ALIYUN_BASE_URL")
    model = os.getenv("ALIYUN_MODEL") or "text-embedding-v4"
    if not api_key or not base_url:
        raise RuntimeError("缺少 ALIYUN_API_KEY / ALIYUN_BASE_URL，请在项目根目录 .env 配置")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=2)
    return client, model


def _embed(client: OpenAI, model: str, texts: list[str]) -> list[list[float]]:
    """分批调用 embedding 接口，返回与输入等长的向量列表。"""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        chunk = texts[start : start + EMBED_BATCH]
        resp = client.embeddings.create(model=model, input=chunk)
        ordered = sorted(resp.data, key=lambda d: d.index)
        vectors.extend([d.embedding for d in ordered])
    return vectors


def _embed_rows(
    client: OpenAI,
    model: str,
    rows: list[dict[str, Any]],
    text_fn: Any,
) -> tuple[list[str], list[list[float] | None]]:
    """为库内行批量生成嵌入；空文本对应的向量为 None。"""
    texts = [text_fn(r) for r in rows]
    vectors: list[list[float] | None] = [None] * len(texts)
    indices = [i for i, t in enumerate(texts) if t]
    if indices:
        embedded = _embed(client, model, [texts[i] for i in indices])
        for i, vec in zip(indices, embedded, strict=False):
            vectors[i] = vec
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
    """候选文本与库内文本做余弦相似度，返回 top 列表与最高分。"""
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
    parts = [
        c.get("Title_CN"),
        c.get("Title_EN"),
        c.get("originalTitle"),
        c.get("Title_Other"),
        c.get("author"),
        c.get("_author_names"),
        c.get("author_names"),
    ]
    return " | ".join(str(p) for p in parts if p)


def _author_embed_text(c: dict[str, Any]) -> str:
    parts = [c.get("Name_CN"), c.get("Name_EN"), c.get("originalName")]
    return " | ".join(str(p) for p in parts if p)


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
    """综合基础/语义结果，返回 (decision, reason)。"""
    level = basic.get("level")
    if level == "exact":
        return "likely_duplicate", "基础匹配：标题完全相同"
    if level == "exact_diff_author":
        return "possible", "基础匹配：标题相同但作者不同（疑似同名异书）"
    if semantic and semantic.get("best_score", 0.0) >= strong:
        return "likely_duplicate", f"语义相似度 {semantic['best_score']}（阈值 {strong}）"
    if level in ("contained", "token"):
        return "possible", f"基础匹配：{level}"
    if semantic and semantic.get("best_score", 0.0) >= possible:
        return "possible", f"语义相似度 {semantic['best_score']}（阈值 {possible}）"
    if semantic is not None:
        return "new", f"无匹配（语义最高 {semantic.get('best_score', 0.0)}）"
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
        print(f"[{kind}] {label} → {item.get('decision')}（{item.get('reason')}）")
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
            print(f"    语义: 失败（{sem['error']}）")

    for item in report.get("authors", []):
        line("作者", item)
    for item in report.get("works", []):
        line("作品", item)


# ======================================================================
# 候选收集
# ======================================================================
def _work_candidate_from_result(
    w: dict[str, Any], author_names: list[str] | None = None
) -> dict[str, Any]:
    """从 extract 结果的作品对象构造候选（附作者字符串用于消歧）。"""
    cand = _pick(
        w,
        ("Title_CN", "Title_EN", "originalTitle", "Title_Other", "language", "publicationYear", "genre", "author"),
    )
    names = " ".join(n for n in (author_names or []) if n)
    if names:
        cand["_author_names"] = names
    return cand


def _collect_candidates(
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """从 --input JSON 或命令行参数收集待检查的作者/作品候选。"""
    work_cands: list[dict[str, Any]] = []
    author_cands: list[dict[str, Any]] = []

    if args.input:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
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
    else:
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
            raise SystemExit("请提供 --input，或 --title-cn/--title-en/--original-title/--author 等参数")
    return work_cands, author_cands


# ======================================================================
# 主流程
# ======================================================================
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="新增数据前的去重查询（基础匹配 + 向量语义校验）",
        epilog="示例：\n"
               "  python dedupe_check.py --input ../output/source_book_result.json\n"
               "  python dedupe_check.py --input ../output/source_book_result.json --basic-only\n"
               "  python dedupe_check.py --title-cn 三体 --author 刘慈欣\n"
               "  python dedupe_check.py --title-en \"The Stranger\" --author \"Albert Camus\"",
    )
    parser.add_argument("--input", help="extract_source_book.py 的输出 JSON 路径")
    parser.add_argument("--title-cn", help="候选作品中文名")
    parser.add_argument("--title-en", help="候选作品英文名")
    parser.add_argument("--original-title", help="候选作品原名")
    parser.add_argument("--author", help="候选作者名（作品候选的消歧/作者候选）")
    parser.add_argument("--language", help="候选作品语言代码（如 zh/en）")
    parser.add_argument("--publication-year", type=int, help="候选作品出版年份")
    parser.add_argument("--genre", help="候选作品体裁（Fiction/Non-fiction/Poetry/Drama）")
    parser.add_argument("--basic-only", action="store_true", help="只做基础去重，不调用 embedding")
    parser.add_argument(
        "--force-semantic",
        action="store_true",
        help="即使基础精确命中也执行语义校验（默认精确命中后跳过）",
    )
    parser.add_argument("--top", type=int, default=5, help="语义最高匹配展示条数（默认 5）")
    parser.add_argument("--threshold-strong", type=float, default=SEMANTIC_STRONG)
    parser.add_argument("--threshold-possible", type=float, default=SEMANTIC_POSSIBLE)
    parser.add_argument("--db", default=None, help=f"SQLite 数据库路径（默认 {db_sqlite.DB_PATH}）")
    parser.add_argument("--output", default=None, help=f"报告保存路径（默认 {DEFAULT_OUTPUT}）")
    parser.add_argument("--json", action="store_true", help="stdout 同时输出完整 JSON 报告")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    existing = load_existing(args.db)
    log(f"库内活跃数据：作品 {len(existing['works'])}，作者 {len(existing['authors'])}")

    work_cands, author_cands = _collect_candidates(args)
    log(f"待检查：作品 {len(work_cands)}，作者 {len(author_cands)}")

    client: OpenAI | None = None
    model = ""
    if not args.basic_only:
        try:
            client, model = _load_aliyun()
            log(f"语义校验启用：模型 {model}")
        except RuntimeError as exc:
            log(f"⚠ 未启用语义校验：{exc}")
            client = None

    work_texts, work_vectors, author_texts, author_vectors = [], [], [], []
    if client is not None:
        log("生成库内标题向量...")
        work_texts, work_vectors = _embed_rows(client, model, existing["works"], _work_embed_text)
        author_texts, author_vectors = _embed_rows(
            client, model, existing["authors"], _author_embed_text
        )

    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "db_path": str(args.db or db_sqlite.DB_PATH),
        "existing_counts": {
            "works": len(existing["works"]),
            "authors": len(existing["authors"]),
        },
        "semantic": {"enabled": client is not None, "model": model},
        "authors": [],
        "works": [],
    }

    for cand in author_cands:
        basic = basic_match_author(cand, existing["authors"])
        sem = None
        if client is not None and (basic.get("level") != "exact" or args.force_semantic):
            sem = semantic_match(
                client,
                model,
                _author_embed_text(cand),
                existing["authors"],
                author_texts,
                author_vectors,
                _summarize_author,
                args.top,
            )
        decision, reason = decide(
            basic, sem, strong=args.threshold_strong, possible=args.threshold_possible
        )
        report["authors"].append(
            {
                "candidate": _clean_candidate(cand),
                "basic": basic,
                "semantic": sem,
                "decision": decision,
                "reason": reason,
            }
        )

    for cand in work_cands:
        basic = basic_match_work(cand, existing["works"])
        sem = None
        if client is not None and (basic.get("level") not in ("exact", "exact_diff_author") or args.force_semantic):
            sem = semantic_match(
                client,
                model,
                _work_embed_text(cand),
                existing["works"],
                work_texts,
                work_vectors,
                _summarize_work,
                args.top,
            )
        decision, reason = decide(
            basic, sem, strong=args.threshold_strong, possible=args.threshold_possible
        )
        report["works"].append(
            {
                "candidate": _clean_candidate(cand),
                "basic": basic,
                "semantic": sem,
                "decision": decision,
                "reason": reason,
            }
        )

    _print_summary(report)

    out_path = Path(args.output) if args.output else DEFAULT_OUTPUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"报告已保存到：{out_path}")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

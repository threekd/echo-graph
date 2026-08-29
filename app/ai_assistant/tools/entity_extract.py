#!/usr/bin/env python3

"""单实体 LLM 补全工具:给定作者/作品的零散名称,输出符合 data_schema.md 的结构化记录。

场景:
- 数据管理 / AI 草稿审核时,补全某位作者、某部作品缺失的字段
  (原著文字、国籍、生卒年、出版年份等);
- 任何「名字 → 结构化实体」的复用点(如涟漪作者补全、草稿字段校正)。

接口(任一或多个名称参数,至少一个;调用 DeepSeek 补全,不确定的字段留空不编造):
    extract_author(original_name=..., name_cn=..., name_en=...) -> authors 表形状 dict
    extract_work(original_title=..., title_cn=..., title_en=..., author=...) -> works 表形状 dict

复用 ai_assistant.tools.llm_client(同一套 DeepSeek 客户端、超时重试、流式进度与 JSON 解析);
输出字段白名单与 docs/data_schema.md 的 authors / works 表一致。

CLI 示例:
    uv run python -m app.ai_assistant.tools.entity_extract --kind author --name-cn 村上春树
    uv run python -m app.ai_assistant.tools.entity_extract --kind work --title-cn 且听风吟 --author 村上春树
    uv run python -m app.ai_assistant.tools.entity_extract --kind work --original-title ノルウェイの森 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from app.ai_assistant import prompts  # noqa: E402
from app.ai_assistant.tools import llm_client  # noqa: E402
from app.ai_assistant.tools.common import log, utf8_stdout  # noqa: E402

# 输出字段白名单:对齐 data_schema.md 的 authors / works 表
AUTHOR_FIELDS = (
    "originalName",
    "Name_CN",
    "Name_EN",
    "nationality",
    "birthYear",
    "deathYear",
    "note",
)
WORK_FIELDS = (
    "language",
    "originalTitle",
    "Title_CN",
    "Title_EN",
    "Title_Other",
    "publicationYear",
    "genre",
    "note",
)


def _clean_fields(raw: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """只保留白名单字段并剔除 None,输出对齐 data_schema.md 的形状。"""
    return {k: v for k, v in raw.items() if k in fields and v is not None}


def build_author_payload(
    *,
    original_name: str | None = None,
    name_cn: str | None = None,
    name_en: str | None = None,
    work_title: str | None = None,
    work_original_title: str | None = None,
    work_language: str | None = None,
) -> dict[str, str]:
    """构造作者补全载荷(只含非空输入);至少一个名称参数,否则抛 ValueError。

    work_* 为可选的「作者所著作品」参考(涟漪作者补全时传入作品标题/语言,
    帮助模型消歧同名作者、判断原著文字与国籍),不作为必填。
    """
    payload = {
        k: v.strip()
        for k, v in {
            "original_name": original_name,
            "name_cn": name_cn,
            "name_en": name_en,
            "work_title": work_title,
            "work_original_title": work_original_title,
            "work_language": work_language,
        }.items()
        if v and str(v).strip()
    }
    if not any(k in payload for k in ("original_name", "name_cn", "name_en")):
        raise ValueError("至少提供一个作者名称参数(original_name / name_cn / name_en)")
    return payload


def build_work_payload(
    *,
    original_title: str | None = None,
    title_cn: str | None = None,
    title_en: str | None = None,
    author: str | None = None,
) -> dict[str, str]:
    """构造作品补全载荷(只含非空输入);至少一个标题参数,否则抛 ValueError。"""
    payload = {
        k: v.strip()
        for k, v in {
            "original_title": original_title,
            "title_cn": title_cn,
            "title_en": title_en,
            "author": author,
        }.items()
        if v and str(v).strip()
    }
    if not any(k in payload for k in ("original_title", "title_cn", "title_en")):
        raise ValueError("至少提供一个作品标题参数(original_title / title_cn / title_en)")
    return payload


def _call_llm(
    system_prompt: str,
    payload: dict[str, str],
    *,
    model: str | None,
    stage: str,
    on_log: Callable[[str], None] | None,
) -> dict[str, Any]:
    """调用一次 DeepSeek 并解析 JSON(空正文/解析失败自动有界重试)。"""
    api_key, base_url = llm_client.load_environment()
    client = llm_client.create_client(api_key, base_url)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    model_name = model or llm_client.MODEL
    log(
        f"阶段 {stage}:调用 DeepSeek(模型 {model_name},"
        f"深度思考 {'开' if llm_client.THINKING else '关'})..."
    )
    return llm_client.call_json_completion(
        client,
        messages,
        model=model_name,
        thinking=llm_client.THINKING,
        on_log=on_log,
        stage_label=f"阶段 {stage}",
    )


def extract_author(
    *,
    original_name: str | None = None,
    name_cn: str | None = None,
    name_en: str | None = None,
    work_title: str | None = None,
    work_original_title: str | None = None,
    work_language: str | None = None,
    model: str | None = None,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """给定作者姓名的任一/多个形式(+ 可选所著作品参考),补全为 authors 表记录。"""
    payload = build_author_payload(
        original_name=original_name,
        name_cn=name_cn,
        name_en=name_en,
        work_title=work_title,
        work_original_title=work_original_title,
        work_language=work_language,
    )
    raw = _call_llm(
        prompts.ENTITY_AUTHOR_SYSTEM_PROMPT,
        payload,
        model=model,
        stage="实体作者",
        on_log=on_log,
    )
    return _clean_fields(raw, AUTHOR_FIELDS)


def extract_work(
    *,
    original_title: str | None = None,
    title_cn: str | None = None,
    title_en: str | None = None,
    author: str | None = None,
    model: str | None = None,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """给定作品标题的任一/多个形式 + 可选作者,调用 LLM 补全为符合 works 表结构的记录。"""
    payload = build_work_payload(
        original_title=original_title,
        title_cn=title_cn,
        title_en=title_en,
        author=author,
    )
    raw = _call_llm(
        prompts.ENTITY_WORK_SYSTEM_PROMPT,
        payload,
        model=model,
        stage="实体作品",
        on_log=on_log,
    )
    return _clean_fields(raw, WORK_FIELDS)


def _name_key(author: dict[str, Any]) -> str:
    """作者去重键:Name_CN 或 originalName 去空白后小写。"""
    return "".join((author.get("Name_CN") or author.get("originalName") or "").split()).lower()


def enrich_ripple_authors(
    extract: dict[str, Any],
    *,
    model: str | None = None,
    on_log: Callable[[str], None] | None = None,
) -> int:
    """为涟漪提及作品的作者补全结构化字段(国籍/生卒年/英文名等)。

    对每个涟漪的 work.author 调用 extract_author 补全,结果:
    1) 写回该涟漪 work["author_info"],build_batch 建作者条目时优先使用,
       使进入草稿区的作者记录包含完整字段;
    2) 追加到 extract["ripple_authors"]:与源书作者 extract["authors"] 分开存放,
       避免 build_batch 把涟漪作者误当成源书作者挂到源书作品上;
       collect_candidates_from_extract 会同时收集两处,入草稿前与上传者星云
       做基础+语义去重。

    返回本次补全的作者数(空名 / 已补全 / 同名已存在跳过)。
    """
    enriched = 0
    for ripple in extract.get("ripples") or []:
        work = ripple.get("work") or {}
        author_name = (work.get("author") or "").strip()
        if not author_name or work.get("author_info"):
            continue
        authors = extract.setdefault("ripple_authors", [])
        name_key = _name_key({"Name_CN": author_name})
        all_authors = [*authors, *extract.get("authors", [])]
        if name_key and any(_name_key(a) == name_key for a in all_authors):
            continue  # 同名作者已在候选(源书作者或另一涟漪已补全),不重复调用
        # 把涟漪作品信息一并传入:作品标题/语言是作者身份判定的强线索
        # (同名作者消歧、原著文字与国籍判断),见 ENTITY_AUTHOR_SYSTEM_PROMPT。
        info = extract_author(
            name_cn=author_name,
            work_title=work.get("Title_CN"),
            work_original_title=work.get("originalTitle"),
            work_language=work.get("language"),
            model=model,
            on_log=on_log,
        )
        if not info:
            continue
        work["author_info"] = info
        authors.append(info)
        enriched += 1
    return enriched


def _parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="单实体 LLM 补全:给定作者/作品零散名称,输出符合 data_schema.md 的结构化记录",
        epilog="示例:\n"
               "  uv run python -m app.ai_assistant.tools.entity_extract --kind author --name-cn 村上春树\n"
               "  uv run python -m app.ai_assistant.tools.entity_extract --kind work --title-cn 且听风吟 --author 村上春树\n"
               "  uv run python -m app.ai_assistant.tools.entity_extract --kind work --original-title ノルウェイの森 --dry-run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--kind", choices=("author", "work"), required=True, help="实体类型:author 或 work")
    parser.add_argument("--original-name", help="作者原名(作者本国文字)")
    parser.add_argument("--name-cn", help="作者中文名")
    parser.add_argument("--name-en", help="作者英文名")
    parser.add_argument("--original-title", help="作品原著标题(原著语言文字)")
    parser.add_argument("--title-cn", help="作品中文标题")
    parser.add_argument("--title-en", help="作品英文标题")
    parser.add_argument("--author", help="作品作者(消歧用,可选)")
    parser.add_argument("--model", default=None, help="覆盖 DeepSeek 模型名")
    parser.add_argument("--dry-run", action="store_true", help="只打印将发送给 LLM 的载荷,不调用 API")
    return parser.parse_args()


def main() -> None:
    utf8_stdout()
    args = _parse_args()
    if args.kind == "author":
        payload = build_author_payload(
            original_name=args.original_name,
            name_cn=args.name_cn,
            name_en=args.name_en,
        )
        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        result = extract_author(
            original_name=args.original_name,
            name_cn=args.name_cn,
            name_en=args.name_en,
            model=args.model,
        )
    else:
        payload = build_work_payload(
            original_title=args.original_title,
            title_cn=args.title_cn,
            title_en=args.title_en,
            author=args.author,
        )
        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        result = extract_work(
            original_title=args.original_title,
            title_cn=args.title_cn,
            title_en=args.title_en,
            author=args.author,
            model=args.model,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

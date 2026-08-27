#!/usr/bin/env python3

"""
从源电子书中一次性提取三张表所需的结构化信息,输出可对齐 Echo Graph
authors / works / edges 表结构(见 docs/data_schema.md)的 JSON:

- authors:源书作者
- work:源书作品
- ripples:源书在正文中提及的其他真实作品(每一条 = 目标作品 + 证据,
  入库时转换为 edges(source → target),证据对齐 evidence / evidenceSource)

流程:
1. 用 read_book.ReadBook.read_book_info() 读取 EPUB 元数据(书名、作者、语言)
2. 用 read_book 识别书内正文提到的其他书名(带上下文与章节;仅正文,
   前言/尾记等非正文章节的提及在代码层直接过滤,涟漪只取正文)
3. (可选)截取正文开头样本,帮助作者/作品提取确认内容与语言
4. 阶段 A1/A2:分别调用 DeepSeek 输出源书作者(A1)与源书作品(A2),
   作品阶段附带作者结果辅助判断原著语言
5. 阶段 B:调用 DeepSeek 把书内提及分类为真实作品并输出涟漪(含证据)

核心入口:run_extract() 供 pipeline_ingest 进程内复用;CLI 只做参数解析与落盘。

依赖:
    - dotenv, openai(同目录 read_book / llm_client 模块)
    - 环境变量 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL(配置在项目根目录 .env)
    - 模型:DEEPSEEK_MODEL(默认 deepseek-v4-flash)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from app.ai_assistant import prompts  # noqa: E402
from app.ai_assistant.tools.common import DEFAULT_BOOK, log, utf8_stdout, write_json  # noqa: E402
from app.ai_assistant.tools.llm_client import (  # noqa: E402
    MODEL,
    THINKING,
    create_client,
    load_environment,
    parse_json,
    stream_completion,
)
from app.ai_assistant.tools.read_book import ReadBook  # noqa: E402

_AI_ASSISTANT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = _AI_ASSISTANT_DIR / "output" / "source_book_result.json"
DEFAULT_CONTENT_CHARS = 1500  # 送入模型的正文样本字符数
DEFAULT_CONTEXT_CHARS = 300  # 书内提及的上下文前后截取字符数
# 非拉丁文字系统检测:用于核对「原文名/原著标题」是否使用了对应国籍/语言的文字。
# 命中其中一个字符即视为「已使用非拉丁文字」,可覆盖日文假名、CJK、谚文、
# 西里尔、希腊、希伯来、阿拉伯、天城文、泰文等常见原著语言。
_NON_LATIN_SCRIPT_RE = re.compile(
    "["
    "\u3040-\u30ff"  # 日文假名
    "\u3400-\u4dbf\u4e00-\u9fff"  # CJK 统一表意文字
    "\uac00-\ud7af\u1100-\u11ff"  # 韩文谚文
    "\u0400-\u04ff"  # 西里尔字母
    "\u0370-\u03ff"  # 希腊字母
    "\u0590-\u05ff"  # 希伯来字母
    "\u0600-\u06ff"  # 阿拉伯字母
    "\u0900-\u097f"  # 天城文
    "\u0e00-\u0e7f"  # 泰文
    "\u10a0-\u10ff"  # 格鲁吉亚字母
    "\u0530-\u058f"  # 亚美尼亚字母
    "\u1200-\u137f"  # 埃塞俄比亚音节文字
    "\u1780-\u17ff"  # 高棉文
    "\u0e80-\u0eff"  # 老挝文
    "]"
)

# 应使用非拉丁文字系统的语言码(ISO 639,原始小写)与国籍码(ISO 3166,大写)。
# 俄语/乌克兰语等同时作为语言码与国籍码存在,统一转大写后并入同一集合。
_NON_LATIN_LANG_CODES = {
    "zh", "ja", "ko", "ru", "uk", "bg", "sr", "mk", "be",
    "el", "he", "yi", "ar", "fa", "ur", "hi", "mr", "ne",
    "th", "ka", "hy", "am", "my", "km", "lo", "mn", "bo",
    "dv", "ps", "sd", "si", "ta", "te", "kn", "ml", "bn",
    "gu", "pa",
}
_NON_LATIN_NATION_CODES = {
    "CN", "TW", "HK", "MO", "JP", "KR", "KP", "RU", "UA", "BY",
    "BG", "RS", "MK", "BA", "ME", "GR", "CY", "IL", "SA", "AE",
    "EG", "IQ", "SY", "JO", "LB", "KW", "QA", "BH", "OM", "YE",
    "IR", "AF", "PK", "IN", "NP", "BD", "LK", "MM", "TH", "KH",
    "LA", "MN", "GE", "AM", "ET", "BT",
}
_NON_LATIN_CODES = {c.upper() for c in _NON_LATIN_LANG_CODES} | _NON_LATIN_NATION_CODES


def _warn_if_latin_only(
    warnings: list[str],
    text: Any,
    code: str | None,
    field_label: str,
    scope_label: str,
) -> None:
    """若字段只有拉丁字符、而该国籍/语言本应使用非拉丁文字,追加一条告警。"""
    if not text or not code:
        return
    code = str(code).strip().upper()
    if code not in _NON_LATIN_CODES:
        return
    value = str(text).strip()
    if not value:
        return
    if _NON_LATIN_SCRIPT_RE.search(value):
        return
    if re.fullmatch(r"[A-Za-z0-9]{1,5}", value):
        return  # 短拉丁词/符号(如 1Q84)可能是原著真名,不告警
    warnings.append(
        f"{field_label}「{value}」仅有拉丁字符,疑似未使用对应{scope_label}"
        f"({code})的原文字(如西里尔/日文/中文),请人工核对"
    )


def check_native_script(result: dict[str, Any]) -> list[str]:
    """核对 LLM 提取结果:作者原文名应随国籍、作品原著标题应随原文语言使用对应文字。

    仅告警不阻断,返回告警文案列表并打印,供人工复核。
    """
    warnings: list[str] = []
    for author in result.get("authors") or []:
        _warn_if_latin_only(
            warnings,
            author.get("originalName"),
            author.get("nationality"),
            "作者原文名",
            "国籍",
        )
    work = result.get("work") or {}
    _warn_if_latin_only(
        warnings,
        work.get("originalTitle"),
        work.get("language"),
        "作品原著标题",
        "语言",
    )
    for ripple in result.get("ripples") or []:
        ripple_work = (ripple or {}).get("work") or {}
        _warn_if_latin_only(
            warnings,
            ripple_work.get("originalTitle"),
            ripple_work.get("language"),
            "涟漪作品原著标题",
            "语言",
        )
    for warning in warnings:
        log(warning)
    return warnings

def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="从源电子书提取作者/作品/涟漪(对齐 Echo Graph authors/works/edges 表结构)",
        epilog="示例:\n"
               "  uv run python -m app.ai_assistant.tools.extract_source_book app/ai_assistant/books/三体.epub --dry-run\n"
               "  uv run python -m app.ai_assistant.tools.extract_source_book app/ai_assistant/books/三体.epub\n"
               "  uv run python -m app.ai_assistant.tools.extract_source_book app/ai_assistant/books/且听风吟.epub --no-ripples\n"
               "  uv run python -m app.ai_assistant.tools.extract_source_book app/ai_assistant/books/1Q84.mobi --title 1Q84 --author 村上春树",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(DEFAULT_BOOK),
        help=f"电子书文件路径(默认:{DEFAULT_BOOK})",
    )
    parser.add_argument("--title", help="覆盖元数据中的书名(元数据缺失/错误时使用)")
    parser.add_argument(
        "--author",
        action="append",
        help="覆盖元数据中的作者(可多次指定)",
    )
    parser.add_argument(
        "--content-chars",
        type=int,
        default=DEFAULT_CONTENT_CHARS,
        help=f"送入模型的正文样本字符数,0 表示不带正文(默认 {DEFAULT_CONTENT_CHARS})",
    )
    parser.add_argument(
        "--no-ripples",
        action="store_true",
        help="只提取作者/作品,跳过书内提及识别与涟漪提取",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只读取/组装各阶段 payload,不调用 LLM(调试用)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"结果保存路径(默认:{DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="覆盖模型名(默认取 DEEPSEEK_MODEL)",
    )
    parser.add_argument(
        "--calibre-path",
        default=None,
        help="ebook-convert 的完整路径(可选,mobi/azw 转换时需要)",
    )
    return parser.parse_args()


def build_author_payload(
    source_info: dict[str, object], content_sample: str
) -> dict[str, object]:
    """阶段 A1 payload:源书元信息 + 可选正文样本(提取作者)。"""
    payload: dict[str, object] = {"source_book": source_info}
    if content_sample:
        payload["content_sample"] = content_sample
    return payload


def build_work_payload(
    source_info: dict[str, object],
    content_sample: str,
    authors: list[dict[str, object]],
) -> dict[str, object]:
    """阶段 A2 payload:源书元信息 + 可选正文样本 + 已提取作者记录(辅助判断原著语言)。"""
    payload: dict[str, object] = {"source_book": source_info}
    if content_sample:
        payload["content_sample"] = content_sample
    if authors:
        payload["author_info"] = authors
    return payload


def build_ripple_payload(
    source_info: dict[str, object], mentions: list[dict[str, str]]
) -> dict[str, object]:
    """阶段 B payload:源书元信息 + 书内提及记录。"""
    return {"source_book": source_info, "mentions": mentions}


def call_llm(
    client: Any,
    system_prompt: str,
    payload: dict[str, object],
    *,
    model: str,
    stage: str,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """调用一次 LLM 并解析 JSON 结果。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    log(f"阶段 {stage}:调用 DeepSeek(模型 {model},深度思考 {'开' if THINKING else '关'})...")
    try:
        content, reasoning_content = stream_completion(
            client, messages, model=model, thinking=THINKING, on_log=on_log
        )
    except Exception as exc:
        log(f"阶段 {stage} API 调用失败:{type(exc).__name__}: {exc}")
        raise

    log(
        f"阶段 {stage} 响应接收完成(content {len(content)} 字符,"
        f"reasoning {len(reasoning_content)} 字符)"
    )
    return parse_json(content)


def run_extract(
    book_path: str | Path,
    *,
    title: str | None = None,
    authors: list[str] | None = None,
    no_ripples: bool = False,
    content_chars: int = DEFAULT_CONTENT_CHARS,
    model: str | None = None,
    calibre_path: str | None = None,
    dry_run: bool = False,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """执行完整提取流程,返回结果 dict(不写文件;CLI 与 pipeline_ingest 共用)。

    on_log 可选:LLM 推理进度(「思考中... 已接收 N 字符」)回调,供
    app/book_import 写入任务日志在前端展示。
    """
    reader = ReadBook(calibre_convert_path=calibre_path)

    # 1. 源书元信息(支持人工覆盖)
    log(f"读取源书元信息:{book_path}")
    source_info = reader.read_book_info(str(book_path))
    if title:
        source_info["title"] = title
    if authors:
        source_info["authors"] = authors
    log(
        f"源书:《{source_info['title']}》 "
        f"作者:{'、'.join(source_info['authors']) or '未知'}"
    )

    # 2. 书内提及(涟漪阶段输入;--no-ripples 时跳过)
    #    涟漪只取正文:find_book_titles_with_context(body_only=True) 在聚合前
    #    剔除前言/序言/尾记/附录等非正文章节的提及,不依赖 LLM 判断。
    mentions: list[dict[str, str]] = []
    if not no_ripples:
        log("识别书内正文提及(已剔除前言/尾记等非正文章节)...")
        mentions = reader.find_book_titles_with_context(
            str(book_path),
            context_chars=DEFAULT_CONTEXT_CHARS,
            body_only=True,
        )
        log(f"识别到 {len(mentions)} 条书内正文提及")

    # 3. 可选正文样本(作者/作品阶段输入)
    content_sample = ""
    if content_chars > 0:
        log(f"提取正文样本(前 {content_chars} 字符)...")
        content_sample = reader.read(str(book_path), max_chars=content_chars)

    author_payload = build_author_payload(source_info, content_sample)
    ripple_payload = build_ripple_payload(source_info, mentions) if not no_ripples else None

    if dry_run:
        preview: dict[str, object] = {"source_book": source_info}
        preview["author_payload"] = author_payload
        preview["work_payload"] = build_work_payload(source_info, content_sample, [])
        if ripple_payload is not None:
            preview["ripple_payload"] = ripple_payload
            preview["ripple_payload"]["mentions_count"] = len(mentions)
        log("dry-run:未调用 LLM。去掉 --dry-run 执行完整提取。")
        return preview

    # 4. 初始化 API 客户端
    api_key, base_url = load_environment()
    client = create_client(api_key, base_url)
    model_name = model or MODEL

    # 5. 阶段 A1:作者(单独提取,输出 authors 数组)
    author_result = call_llm(
        client,
        prompts.AUTHOR_SYSTEM_PROMPT,
        author_payload,
        model=model_name,
        stage="A1 作者",
        on_log=on_log,
    )

    # 6. 阶段 A2:作品(附带已提取作者,辅助判断原著语言)
    authors = author_result.get("authors", [])
    work_payload = build_work_payload(source_info, content_sample, authors)
    work_result = call_llm(
        client,
        prompts.WORK_SYSTEM_PROMPT,
        work_payload,
        model=model_name,
        stage="A2 作品",
        on_log=on_log,
    )

    # 7. 阶段 B:涟漪(书内提及 → 真实作品 + 证据)
    result: dict[str, Any] = {
        "source_book": source_info,
        "authors": authors,
        "work": work_result.get("work", {}),
        "ripples": [],
    }
    if ripple_payload is not None:
        ripple_result = call_llm(
            client,
            prompts.RIPPLE_SYSTEM_PROMPT,
            ripple_payload,
            model=model_name,
            stage="B 涟漪",
            on_log=on_log,
        )
        result["ripples"] = ripple_result.get("ripples", [])
        result["ripple_skipped"] = ripple_result.get("skipped", {})
    check_native_script(result)
    return result


def main() -> None:
    utf8_stdout()
    args = _parse_args()
    result = run_extract(
        args.input,
        title=args.title,
        authors=args.author,
        no_ripples=args.no_ripples,
        content_chars=args.content_chars,
        model=args.model,
        calibre_path=args.calibre_path,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    out_path = Path(args.output) if args.output else DEFAULT_OUTPUT
    write_json(out_path, result)
    log(f"结果已保存到:{out_path}")


if __name__ == "__main__":
    main()

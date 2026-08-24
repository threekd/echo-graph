#!/usr/bin/env python3

"""
从源电子书中一次性提取三张表所需的结构化信息，输出可对齐 Echo Graph
authors / works / edges 表结构（见 docs/data_schema.md）的 JSON：

- authors：源书作者
- work：源书作品
- ripples：源书在正文中提及的其他真实作品（每一条 = 目标作品 + 证据，
  入库时转换为 edges(source → target)，证据对齐 evidence / evidenceSource）

流程：
1. 用 read_book.ReadBook.read_book_info() 读取 EPUB 元数据（书名、作者、语言）
2. 用 read_book 识别书内提到的其他书名（带上下文与章节）
3. （可选）截取正文开头样本，帮助作者/作品提取确认内容与语言
4. 阶段 A：调用 DeepSeek 输出源书作者 + 作品
5. 阶段 B：调用 DeepSeek 把书内提及分类为真实作品并输出涟漪（含证据）

依赖：
    - dotenv, openai（同目录 read_book / llm_client 模块）
    - 环境变量 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL（配置在项目根目录 .env）
    - 模型：DEEPSEEK_MODEL（默认 deepseek-chat）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 保证同目录模块与 agent_temp 根目录下的 prompts.py 都能被导入
_TOOLS_DIR = Path(__file__).resolve().parent
_AGENT_TEMP_DIR = _TOOLS_DIR.parent
for _path in (_TOOLS_DIR, _AGENT_TEMP_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from llm_client import (  # noqa: E402
    MODEL,
    THINKING,
    create_client,
    load_environment,
    log,
    parse_json,
    stream_completion,
)
from prompts import AUTHOR_WORK_SYSTEM_PROMPT, RIPPLE_SYSTEM_PROMPT  # noqa: E402
from read_book import ReadBook  # noqa: E402

DEFAULT_BOOK = _AGENT_TEMP_DIR / "books" / "三体.epub"
DEFAULT_OUTPUT = _AGENT_TEMP_DIR / "output" / "source_book_result.json"
DEFAULT_CONTENT_CHARS = 1500  # 送入模型的正文样本字符数
DEFAULT_CONTEXT_CHARS = 300  # 书内提及的上下文前后截取字符数


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="从源电子书提取作者/作品/涟漪（对齐 Echo Graph authors/works/edges 表结构）",
        epilog="示例：\n"
               "  python extract_source_book.py books/三体.epub --dry-run\n"
               "  python extract_source_book.py books/三体.epub\n"
               "  python extract_source_book.py books/且听风吟.epub --no-ripples\n"
               "  python extract_source_book.py books/1Q84.mobi --title 1Q84 --author 村上春树",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(DEFAULT_BOOK),
        help=f"电子书文件路径（默认：{DEFAULT_BOOK}）",
    )
    parser.add_argument("--title", help="覆盖元数据中的书名（元数据缺失/错误时使用）")
    parser.add_argument(
        "--author",
        action="append",
        help="覆盖元数据中的作者（可多次指定）",
    )
    parser.add_argument(
        "--content-chars",
        type=int,
        default=DEFAULT_CONTENT_CHARS,
        help=f"送入模型的正文样本字符数，0 表示不带正文（默认 {DEFAULT_CONTENT_CHARS}）",
    )
    parser.add_argument(
        "--no-ripples",
        action="store_true",
        help="只提取作者/作品，跳过书内提及识别与涟漪提取",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只读取/组装各阶段 payload，不调用 LLM（调试用）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"结果保存路径（默认：{DEFAULT_OUTPUT}）",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="覆盖模型名（默认取 DEEPSEEK_MODEL，未设置时为 deepseek-chat）",
    )
    parser.add_argument(
        "--calibre-path",
        default=None,
        help="ebook-convert 的完整路径（可选，mobi/azw 转换时需要）",
    )
    return parser.parse_args()


def build_author_work_payload(
    source_info: dict[str, object], content_sample: str
) -> dict[str, object]:
    """阶段 A payload：源书元信息 + 可选正文样本。"""
    payload: dict[str, object] = {"source_book": source_info}
    if content_sample:
        payload["content_sample"] = content_sample
    return payload


def build_ripple_payload(
    source_info: dict[str, object], mentions: list[dict[str, str]]
) -> dict[str, object]:
    """阶段 B payload：源书元信息 + 书内提及记录。"""
    return {"source_book": source_info, "mentions": mentions}


def call_llm(
    client: Any,
    system_prompt: str,
    payload: dict[str, object],
    *,
    model: str,
    stage: str,
) -> dict[str, Any]:
    """调用一次 LLM 并解析 JSON 结果。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    log(f"阶段 {stage}：调用 DeepSeek（模型 {model}，深度思考 {'开' if THINKING else '关'}）...")
    try:
        content, reasoning_content = stream_completion(
            client, messages, model=model, thinking=THINKING
        )
    except Exception as exc:
        log(f"阶段 {stage} API 调用失败：{type(exc).__name__}: {exc}")
        raise

    log(
        f"阶段 {stage} 响应接收完成（content {len(content)} 字符，"
        f"reasoning {len(reasoning_content)} 字符）"
    )
    return parse_json(content)


def main() -> None:
    args = _parse_args()
    reader = ReadBook(calibre_convert_path=args.calibre_path)

    # 1. 源书元信息（支持人工覆盖）
    log(f"读取源书元信息：{args.input}")
    source_info = reader.read_book_info(args.input)
    if args.title:
        source_info["title"] = args.title
    if args.author:
        source_info["authors"] = args.author
    log(
        f"源书：《{source_info['title']}》 "
        f"作者：{'、'.join(source_info['authors']) or '未知'}"
    )

    # 2. 书内提及（涟漪阶段输入；--no-ripples 时跳过）
    mentions: list[dict[str, str]] = []
    if not args.no_ripples:
        log("识别书内提到的书名...")
        mentions = reader.find_book_titles_with_context(
            args.input, context_chars=DEFAULT_CONTEXT_CHARS
        )
        log(f"识别到 {len(mentions)} 条书内提及")

    # 3. 可选正文样本（作者/作品阶段输入）
    content_sample = ""
    if args.content_chars > 0:
        log(f"提取正文样本（前 {args.content_chars} 字符）...")
        content_sample = reader.read(args.input, max_chars=args.content_chars)

    author_work_payload = build_author_work_payload(source_info, content_sample)
    ripple_payload = (
        build_ripple_payload(source_info, mentions) if not args.no_ripples else None
    )

    if args.dry_run:
        preview: dict[str, object] = {"source_book": source_info}
        preview["author_work_payload"] = author_work_payload
        if ripple_payload is not None:
            preview["ripple_payload"] = ripple_payload
            preview["ripple_payload"]["mentions_count"] = len(mentions)
        print(json.dumps(preview, ensure_ascii=False, indent=2), flush=True)
        log("dry-run：未调用 LLM。去掉 --dry-run 执行完整提取。")
        return

    # 4. 初始化 API 客户端
    api_key, base_url = load_environment()
    client = create_client(api_key, base_url)
    model = args.model or MODEL

    # 5. 阶段 A：作者 + 作品
    author_work = call_llm(
        client,
        AUTHOR_WORK_SYSTEM_PROMPT,
        author_work_payload,
        model=model,
        stage="A 作者/作品",
    )

    # 6. 阶段 B：涟漪（书内提及 → 真实作品 + 证据）
    result: dict[str, Any] = {
        "source_book": source_info,
        "authors": author_work.get("authors", []),
        "work": author_work.get("work", {}),
        "ripples": [],
    }
    if ripple_payload is not None:
        ripple_result = call_llm(
            client,
            RIPPLE_SYSTEM_PROMPT,
            ripple_payload,
            model=model,
            stage="B 涟漪",
        )
        result["ripples"] = ripple_result.get("ripples", [])
        result["ripple_skipped"] = ripple_result.get("skipped", {})

    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)

    out_path = Path(args.output) if args.output else DEFAULT_OUTPUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"结果已保存到：{out_path}")


if __name__ == "__main__":
    main()

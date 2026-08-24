#!/usr/bin/env python3
"""一键管线：源电子书 → AI 提取 → 去重校验 → system_llm 草稿区（admin 审核）。

把三段既有工具串成一条命令：
    1) extract_source_book.py   读取书籍信息 + 调用 LLM 提取 作者/作品/涟漪
    2) dedupe_check.py          与库内现有数据做基础 + 语义去重
    3) review_publish.py        make-batch 生成批次登记簿 → ingest 写入
                                system_llm 私有空间（reviewStatus=draft,
                                created_by='llm'，公共星云不可见）

发布后的审核在 admin 管理端「AI 草稿」页完成（批准 → 公共星云）。

依赖（配置在项目根目录 .env）：
    - DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL（书籍解析 LLM，可选 DEEPSEEK_MODEL）
    - ALIYUN_DASHSCOPE_API_KEY 等（语义去重 embedding；未配置时自动降级为基础匹配）

示例：
    uv run python agent_temp/tools/pipeline_ingest.py agent_temp/books/三体.epub
    uv run python agent_temp/tools/pipeline_ingest.py agent_temp/books/1Q84.mobi --title 1Q84 --author 村上春树
    uv run python agent_temp/tools/pipeline_ingest.py agent_temp/books/某书.epub --basic-only --dry-run
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
_AGENT_TEMP_DIR = _TOOLS_DIR.parent
DEFAULT_BOOK = _AGENT_TEMP_DIR / "books" / "三体.epub"
DEFAULT_WORK_DIR = _AGENT_TEMP_DIR / "output"

# 批次 id 会作为文件名（agent_temp/output/batches/<id>.json），只允许安全字符
_BATCH_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="一键管线：书籍 → AI 提取(作者/作品/涟漪) → 去重 → 发布到 system_llm 草稿区",
        epilog="示例：\n"
               "  uv run python agent_temp/tools/pipeline_ingest.py agent_temp/books/三体.epub\n"
               "  uv run python agent_temp/tools/pipeline_ingest.py agent_temp/books/1Q84.mobi "
               "--title 1Q84 --author 村上春树\n"
               "  uv run python agent_temp/tools/pipeline_ingest.py agent_temp/books/某书.epub "
               "--basic-only --dry-run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(DEFAULT_BOOK),
        help=f"电子书文件路径（默认：{DEFAULT_BOOK}；支持 epub/txt/mobi 等，"
             "mobi/azw 需 --calibre-path；可省略参数直接使用默认书籍）",
    )
    parser.add_argument("--title", help="覆盖元数据中的书名（元数据缺失/错误时使用）")
    parser.add_argument(
        "--author",
        action="append",
        help="覆盖元数据中的作者（可多次指定）",
    )
    parser.add_argument(
        "--no-ripples",
        action="store_true",
        help="只提取作者/作品，跳过书内提及识别与涟漪提取",
    )
    parser.add_argument(
        "--basic-only",
        action="store_true",
        help="去重只做基础匹配，不调用阿里云百炼 embedding（省 API 调用）",
    )
    parser.add_argument(
        "--force-semantic",
        action="store_true",
        help="即使基础精确命中也执行语义校验（默认精确命中后跳过）",
    )
    parser.add_argument("--top", type=int, default=5, help="语义最高匹配展示条数（默认 5）")
    parser.add_argument("--model", default=None, help="覆盖解析用的 DeepSeek 模型名")
    parser.add_argument(
        "--calibre-path",
        default=None,
        help="ebook-convert 的完整路径（可选，mobi/azw 转换时需要）",
    )
    parser.add_argument("--db", default=None, help=f"SQLite 数据库路径（默认 {_AGENT_TEMP_DIR.parent / 'data' / 'echo-graph.db'}）")
    parser.add_argument("--batch-id", default=None, help="自定义批次 id（仅字母/数字/_-；默认按时间自动生成）")
    parser.add_argument(
        "--work-dir",
        default=None,
        help=f"中间产物目录（提取结果/去重报告；默认 {DEFAULT_WORK_DIR}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只执行 提取+去重+生成批次，不 ingest 进 system_llm 空间（调试用）",
    )
    return parser.parse_args()


def _run_step(label: str, cmd: list[str]) -> None:
    """执行一个子步骤；失败立即中止整条管线。"""
    print(f"\n[{label}]\n  $ {' '.join(cmd)}")
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise SystemExit(f"[{label}] 失败（exit={proc.returncode}），管线已中止")


def main() -> None:
    args = _parse_args()
    book = Path(args.input)
    if not book.exists():
        hint = ""
        books_dir = _AGENT_TEMP_DIR / "books"
        if books_dir.is_dir():
            names = sorted(f.name for f in books_dir.iterdir() if f.is_file())
            if names:
                hint = "\n可用书籍（agent_temp/books/）：\n  " + "\n  ".join(names)
        raise SystemExit(f"电子书不存在：{book}{hint}")

    batch_id = args.batch_id or datetime.now(UTC).strftime("book-%Y%m%dT%H%M%S")
    if not _BATCH_ID_RE.match(batch_id):
        raise SystemExit(f"batch-id 只允许字母/数字/_-：{batch_id!r}")

    work_dir = Path(args.work_dir) if args.work_dir else DEFAULT_WORK_DIR
    work_dir.mkdir(parents=True, exist_ok=True)
    extract_out = work_dir / f"{batch_id}_source_book_result.json"
    dedupe_out = work_dir / f"{batch_id}_dedupe_report.json"

    python = sys.executable
    print("=" * 70)
    print(f"开始管线：{book.name}  → 批次 {batch_id}")
    print("=" * 70)

    # 1) AI 提取：作者 / 作品 / 涟漪
    cmd_extract = [python, str(_TOOLS_DIR / "extract_source_book.py"), str(book)]
    if args.title:
        cmd_extract += ["--title", args.title]
    for author in args.author or []:
        cmd_extract += ["--author", author]
    if args.no_ripples:
        cmd_extract += ["--no-ripples"]
    if args.model:
        cmd_extract += ["--model", args.model]
    if args.calibre_path:
        cmd_extract += ["--calibre-path", args.calibre_path]
    cmd_extract += ["--output", str(extract_out)]
    _run_step("1/4 AI 提取（DeepSeek）", cmd_extract)

    # 2) 去重校验：基础匹配 + 语义辅助
    cmd_dedupe = [
        python,
        str(_TOOLS_DIR / "dedupe_check.py"),
        "--input", str(extract_out),
        "--top", str(args.top),
        "--output", str(dedupe_out),
    ]
    if args.basic_only:
        cmd_dedupe += ["--basic-only"]
    if args.force_semantic:
        cmd_dedupe += ["--force-semantic"]
    if args.db:
        cmd_dedupe += ["--db", args.db]
    _run_step("2/4 去重校验", cmd_dedupe)

    # 3) 生成批次登记簿（make-batch 内部会确保 system_llm 账号存在）
    cmd_batch = [
        python,
        str(_TOOLS_DIR / "review_publish.py"),
        "make-batch",
        "--input", str(extract_out),
        "--dedupe", str(dedupe_out),
        "--batch-id", batch_id,
    ]
    if args.db:
        cmd_batch += ["--db", args.db]
    _run_step("3/4 生成批次登记簿", cmd_batch)

    # 4) 发布到 system_llm 空间（草稿区，待 admin 审核）
    if args.dry_run:
        print("\n[dry-run] 未 ingest；批次登记簿已生成，可随时执行：")
        print(f"  uv run python agent_temp/tools/review_publish.py ingest {batch_id}")
        return

    cmd_ingest = [python, str(_TOOLS_DIR / "review_publish.py"), "ingest", batch_id]
    if args.db:
        cmd_ingest += ["--db", args.db]
    _run_step("4/4 发布到 system_llm 草稿区", cmd_ingest)

    print("\n" + "=" * 70)
    print(f"完成：批次 {batch_id} 已进入 system_llm 私有空间（draft）")
    print("下一步：admin 登录后在管理端「AI 草稿」页审核/批准（发布到公共星云）")
    print(f"  提取结果：{extract_out}")
    print(f"  去重报告：{dedupe_out}")
    print("=" * 70)


if __name__ == "__main__":
    main()

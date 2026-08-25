#!/usr/bin/env python3
"""一键管线:源电子书 → AI 提取 → 去重校验 → system_llm 草稿区(admin 审核)。

把三段既有工具串成一条命令(进程内直接调用,不再 subprocess 拼命令):
    1) extract_source_book.run_extract  读取书籍信息 + 调用 LLM 提取 作者/作品/涟漪
    2) dedupe_check.run_dedupe         与库内现有数据做基础 + 语义去重
    3) review_publish.build_batch      生成批次登记簿 → stage_batch 写入
                                       system_llm 私有空间(reviewStatus=draft,
                                       created_by='llm',公共星云不可见)

发布后的审核在 admin 管理端「AI 草稿」页完成(批准 → 公共星云)。

依赖(配置在项目根目录 .env):
    - DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL(书籍解析 LLM,可选 DEEPSEEK_MODEL)
    - ALIYUN_API_KEY / ALIYUN_BASE_URL(语义去重 embedding;未配置时自动降级为基础匹配)

示例:
    uv run python -m app.ai_assistant.tools.pipeline_ingest app/ai_assistant/books/三体.epub
    uv run python -m app.ai_assistant.tools.pipeline_ingest app/ai_assistant/books/1Q84.mobi --title 1Q84 --author 村上春树
    uv run python -m app.ai_assistant.tools.pipeline_ingest app/ai_assistant/books/某书.epub --basic-only --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from app import db_sqlite  # noqa: E402
from app.ai_assistant.tools import (  # noqa: E402
    dedupe_check,
    entity_extract,
    extract_source_book,
    llm_space,
    review_publish,
)
from app.ai_assistant.tools.common import DEFAULT_BOOK, log, write_json  # noqa: E402

_TOOLS_DIR = Path(__file__).resolve().parent
_AI_ASSISTANT_DIR = _TOOLS_DIR.parent
DEFAULT_WORK_DIR = _AI_ASSISTANT_DIR / "output"

# 批次 id 会作为文件名(app/ai_assistant/output/batches/<id>.json),只允许安全字符
_BATCH_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="一键管线:书籍 → AI 提取(作者/作品/涟漪) → 去重 → 发布到 system_llm 草稿区",
        epilog="示例:\n"
               "  uv run python -m app.ai_assistant.tools.pipeline_ingest app/ai_assistant/books/三体.epub\n"
               "  uv run python -m app.ai_assistant.tools.pipeline_ingest app/ai_assistant/books/1Q84.mobi "
               "--title 1Q84 --author 村上春树\n"
               "  uv run python -m app.ai_assistant.tools.pipeline_ingest app/ai_assistant/books/某书.epub "
               "--basic-only --dry-run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(DEFAULT_BOOK),
        help=f"电子书文件路径(默认:{DEFAULT_BOOK};支持 epub/txt/mobi 等,"
             "mobi/azw 需 --calibre-path;可省略参数直接使用默认书籍)",
    )
    parser.add_argument("--title", help="覆盖元数据中的书名(元数据缺失/错误时使用)")
    parser.add_argument(
        "--author",
        action="append",
        help="覆盖元数据中的作者(可多次指定)",
    )
    parser.add_argument(
        "--no-ripples",
        action="store_true",
        help="只提取作者/作品,跳过书内提及识别与涟漪提取",
    )
    parser.add_argument(
        "--basic-only",
        action="store_true",
        help="去重只做基础匹配,不调用阿里云百炼 embedding(省 API 调用)",
    )
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
    parser.add_argument("--model", default=None, help="覆盖解析用的 DeepSeek 模型名")
    parser.add_argument(
        "--calibre-path",
        default=None,
        help="ebook-convert 的完整路径(可选,mobi/azw 转换时需要)",
    )
    parser.add_argument(
        "--db", default=None,
        help=f"SQLite 数据库路径(默认 {_AI_ASSISTANT_DIR.parent.parent / 'data' / 'echo-graph.db'})",
    )
    parser.add_argument("--batch-id", default=None, help="自定义批次 id(仅字母/数字/_-;默认按时间自动生成)")
    parser.add_argument(
        "--work-dir",
        default=None,
        help=f"中间产物目录(提取结果/去重报告;默认 {DEFAULT_WORK_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只执行 提取+去重+生成批次,不 ingest 进 system_llm 空间(调试用)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    book = Path(args.input)
    if not book.exists():
        hint = ""
        books_dir = _AI_ASSISTANT_DIR / "books"
        if books_dir.is_dir():
            names = sorted(f.name for f in books_dir.iterdir() if f.is_file())
            if names:
                hint = "\n可用书籍(app/ai_assistant/books/):\n  " + "\n  ".join(names)
        raise SystemExit(f"电子书不存在:{book}{hint}")

    batch_id = args.batch_id or datetime.now(UTC).strftime("book-%Y%m%dT%H%M%S")
    if not _BATCH_ID_RE.match(batch_id):
        raise SystemExit(f"batch-id 只允许字母/数字/_-:{batch_id!r}")

    work_dir = Path(args.work_dir) if args.work_dir else DEFAULT_WORK_DIR
    work_dir.mkdir(parents=True, exist_ok=True)
    extract_out = work_dir / f"{batch_id}_source_book_result.json"
    dedupe_out = work_dir / f"{batch_id}_dedupe_report.json"
    db_path = args.db

    print("=" * 70)
    print(f"开始管线:{book.name}  → 批次 {batch_id}")
    print("=" * 70)

    # 1) AI 提取:作者 / 作品 / 涟漪
    log("1/4 AI 提取(DeepSeek)")
    result = extract_source_book.run_extract(
        book,
        title=args.title,
        authors=args.author,
        no_ripples=args.no_ripples,
        model=args.model,
        calibre_path=args.calibre_path,
    )
    try:
        n_auth = entity_extract.enrich_ripple_authors(result)
        if n_auth:
            log(f"涟漪作者补全:{n_auth} 位(国籍/生卒年等),并入去重候选")
    except Exception as exc:  # noqa: BLE001 - 补全失败降级为未补全作者,不阻断管线
        log(f"⚠ 涟漪作者补全失败(以未补全状态继续):{type(exc).__name__}: {exc}")
    write_json(extract_out, result)
    log(
        f"提取结果:作者 {len(result.get('authors') or [])} "
        f"· 涟漪 {len(result.get('ripples') or [])} → {extract_out}"
    )

    # 2) 去重校验:基础匹配 + 语义辅助
    log("2/4 去重校验")
    work_cands, author_cands = dedupe_check.collect_candidates_from_extract(result)
    edge_cands = dedupe_check.collect_edge_candidates_from_extract(result)
    report = dedupe_check.run_dedupe(
        work_cands,
        author_cands,
        edge_cands=edge_cands,
        db_path=db_path,
        basic_only=args.basic_only,
        force_semantic=args.force_semantic,
        rebuild_vectors=args.rebuild_vectors,
        llm_confirm=not args.no_llm_confirm,
        top=args.top,
    )
    write_json(dedupe_out, report)
    log(f"去重报告 → {dedupe_out}")

    # 3) 生成批次登记簿(make-batch 内部会确保 system_llm 账号存在)
    log("3/4 生成批次登记簿")
    owner = llm_space.draft_owner_id()
    batch = review_publish.build_batch(result, report, db_path=db_path, owner_id=owner)
    batch["batch_id"] = batch_id
    batch["source"]["input_file"] = str(book)
    batch["source"]["dedupe_file"] = str(dedupe_out)
    llm_space.save_batch(batch)
    kinds: dict[str, int] = {}
    for it in batch["items"]:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    log(
        f"批次 {batch_id}:作者 {kinds.get('author', 0)} "
        f"· 作品 {kinds.get('work', 0)} · 涟漪 {kinds.get('edge', 0)}"
    )

    # 4) 发布到 system_llm 空间(草稿区,待 admin 审核)
    if args.dry_run:
        print("\n[dry-run] 未 ingest;批次登记簿已生成,可随时执行:")
        print(f"  uv run python -m app.ai_assistant.tools.review_publish ingest {batch_id}")
        return

    log("4/4 发布到 system_llm 草稿区")
    if db_path:
        db_sqlite.DB_PATH = Path(db_path).resolve()
    counts = review_publish.stage_batch(batch, owner)
    llm_space.save_batch(batch)
    log(
        f"ingest 完成:入库 {counts['staged']} · 跳过(已处理) {counts['already']}"
        f" · 失败 {counts['failed']}"
    )
    if counts["failed"]:
        log("失败条目保留 error,修复批次后重跑 ingest 即可重试")

    print("\n" + "=" * 70)
    print(f"完成:批次 {batch_id} 已进入 system_llm 私有空间(draft)")
    print("下一步:admin 登录后在管理端「AI 草稿」页审核/批准(发布到公共星云)")
    print(f"  提取结果:{extract_out}")
    print(f"  去重报告:{dedupe_out}")
    print("=" * 70)


if __name__ == "__main__":
    main()

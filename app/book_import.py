"""书籍导入 API(admin 角色):上传电子书 → AI 提取 → 去重 → system_llm AI 草稿区。

复用 ai_assistant 一键管线(pipeline_ingest.py)的三个阶段:
    1) extract_source_book.run_extract  读取书籍元信息 + LLM 提取 作者/作品/涟漪
    2) dedupe_check.run_dedupe          与库内现有数据做基础 + 语义去重
    3) review_publish.build_batch → stage_batch  写入 system_llm 私有空间
       (reviewStatus='draft'、created_by='llm',即「AI 草稿」,公共星云不可见)

导入是耗时任务(DeepSeek LLM 提取 + 可选语义嵌入,单本书可能数分钟),
采用「提交任务 + 轮询状态」模式:
    POST /api/admin/import-book  请求体为文件原始字节,立即返回 {task_id}
    GET  /api/admin/import-book/{task_id}  查询进度/结果/错误
任务状态保存在进程内存(uvicorn 单 worker),服务重启后丢失,需重新导入。

上传协议(避免引入 python-multipart 依赖):
    POST /api/admin/import-book?title=&authors=&no_ripples=&basic_only=
    Content-Type: 任意(文件原始字节作为请求体)
    X-Filename: URL 编码的原始文件名
"""

from __future__ import annotations

import shutil
import threading
import traceback
import urllib.parse
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.ai_assistant.tools import (
    dedupe_check,
    entity_extract,
    extract_source_book,
    llm_space,
    review_publish,
)
from app.auth import require_admin

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-import"],
    dependencies=[Depends(require_admin)],
)

ROOT = Path(__file__).resolve().parent.parent
IMPORT_DIR = ROOT / "app" / "ai_assistant" / "output" / "imports"
MAX_BOOK_BYTES = 200 * 1024 * 1024  # 200MB 防滥用上限
ALLOWED_SUFFIXES = {".epub", ".txt", ".mobi", ".azw", ".azw3", ".fb2", ".html", ".htm"}
KEEP_TASKS = 100  # 内存中最多保留的任务数(最旧 done/error 先清理)

_TASKS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _make_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:4]}"


def _update_task(task_id: str, **changes: Any) -> None:
    with _LOCK:
        task = _TASKS.get(task_id)
        if task is None:
            return
        task.update(changes)
        task["updated_at"] = _now_iso()
        if "log" in changes:
            task["log"] = changes["log"][-50:]  # 只保留最近 50 条日志


def _append_log(task_id: str, line: str) -> None:
    with _LOCK:
        task = _TASKS.get(task_id)
        if task is None:
            return
        task["log"] = (task.get("log") or [])[-49:]
        task["log"].append(line)
        task["updated_at"] = _now_iso()


def _task_log_hook(task_id: str) -> Any:
    """返回写入任务日志的回调,供 run_extract 的 on_log(LLM 推理进度)使用。"""

    def hook(line: str) -> None:
        _append_log(task_id, line)

    return hook


def _prune_tasks() -> None:
    """清理最旧的 done/error 任务,避免内存无限增长。"""
    with _LOCK:
        for tid in list(_TASKS):
            if len(_TASKS) <= KEEP_TASKS:
                break
            if _TASKS[tid]["status"] in ("done", "error"):
                _TASKS.pop(tid)


def _run_import(
    task_id: str,
    book_path: Path,
    *,
    title: str | None,
    authors: list[str] | None,
    no_ripples: bool,
    basic_only: bool,
) -> None:
    """后台线程:完整执行 提取 → 去重 → 批次 → 草稿,逐步更新任务状态。"""
    batch_id = _make_id("book")
    try:
        # 1) AI 提取
        _update_task(task_id, status="running", stage="1/4 AI 提取书籍信息与内容(DeepSeek)")
        _append_log(task_id, f"开始解析:{book_path.name}")
        extracted = extract_source_book.run_extract(
            book_path,
            title=title,
            authors=authors,
            no_ripples=no_ripples,
            on_log=_task_log_hook(task_id),
        )
        try:
            n_enriched = entity_extract.enrich_ripple_authors(
                extracted, on_log=lambda line: _append_log(task_id, line)
            )
            if n_enriched:
                _append_log(task_id, f"涟漪作者补全:{n_enriched} 位(国籍/生卒年等),并入去重候选")
        except Exception as exc:  # noqa: BLE001 - 补全失败降级为未补全作者,不阻断管线
            _append_log(task_id, f"⚠ 涟漪作者补全失败:{type(exc).__name__}: {exc}")
        n_auth = len(extracted.get("authors") or [])
        n_ripple = len(extracted.get("ripples") or [])
        src = extracted.get("work") or {}
        n_work = 1 if (src.get("Title_CN") or src.get("originalTitle")) else 0
        _append_log(task_id, f"提取结果:作者 {n_auth} · 作品 {n_work} · 涟漪 {n_ripple}")

        # 2) 去重校验
        _update_task(task_id, stage="2/4 去重校验(基础匹配 + 语义辅助)")
        work_cands, author_cands = dedupe_check.collect_candidates_from_extract(extracted)
        edge_cands = dedupe_check.collect_edge_candidates_from_extract(extracted)
        report = dedupe_check.run_dedupe(
            work_cands,
            author_cands,
            edge_cands=edge_cands,
            basic_only=basic_only,
            llm_confirm=False,  # Web 导入不额外调 LLM 兜底确认(审核页有实时去重提示)
        )
        _append_log(task_id, "去重校验完成")

        # 3) 批次登记簿
        _update_task(task_id, stage="3/4 生成批次登记簿")
        owner = llm_space.ensure_system_llm()
        batch = review_publish.build_batch(extracted, report, owner_id=owner)
        batch["batch_id"] = batch_id
        batch["source"]["input_file"] = str(book_path)
        llm_space.save_batch(batch)
        kinds: dict[str, int] = {}
        for it in batch["items"]:
            kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
        _append_log(
            task_id,
            f"批次 {batch_id}:作者 {kinds.get('author', 0)} · "
            f"作品 {kinds.get('work', 0)} · 涟漪 {kinds.get('edge', 0)}",
        )

        # 4) 写入 AI 草稿(system_llm 私有空间)
        _update_task(task_id, stage="4/4 写入 AI 草稿(system_llm)")
        counts = review_publish.stage_batch(batch, owner)
        llm_space.save_batch(batch)
        _append_log(
            task_id,
            f"ingest 完成:入库 {counts['staged']} · 跳过(已处理) {counts['already']}"
            f" · 失败 {counts['failed']}",
        )

        _update_task(
            task_id,
            status="done",
            stage="完成",
            result={
                "batch_id": batch_id,
                "extracted": {"authors": n_auth, "works": n_work, "edges": n_ripple},
                "counts": counts,
            },
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务必须把错误写回任务状态
        _append_log(task_id, f"导入失败:{type(exc).__name__}: {exc}")
        _update_task(
            task_id,
            status="error",
            stage="失败",
            error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
        )


def submit_import(
    book_path: str | Path,
    *,
    title: str | None = None,
    authors: list[str] | None = None,
    no_ripples: bool = False,
    basic_only: bool = False,
) -> dict[str, str]:
    """创建导入任务并立即返回 {task_id}(后台线程执行;测试与 HTTP 端点共用)。"""
    path = Path(book_path)
    if not path.is_file():
        raise ValueError(f"电子书文件不存在:{path}")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(
            f"不支持的文件类型:{path.suffix or '未知'}"
            f"(支持:{', '.join(sorted(ALLOWED_SUFFIXES))})"
        )
    _prune_tasks()
    task_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _TASKS[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "stage": "排队中",
            "log": [f"任务已创建:{path.name}"],
            "result": None,
            "error": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
    thread = threading.Thread(
        target=_run_import,
        args=(task_id, path),
        kwargs={
            "title": title,
            "authors": authors,
            "no_ripples": no_ripples,
            "basic_only": basic_only,
        },
        daemon=True,
    )
    thread.start()
    return {"task_id": task_id}


def get_import_task(task_id: str) -> dict[str, Any] | None:
    """读取任务快照;不存在返回 None。"""
    with _LOCK:
        task = _TASKS.get(task_id)
        return dict(task) if task else None


async def _drain_body(request: Request) -> bytes:
    """流式读取请求体,超过上限抛 413(避免整块读入内存)。"""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BOOK_BYTES:
            raise HTTPException(status_code=413, detail="电子书文件过大(上限 200MB)")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/import-book")
async def import_book(
    request: Request,
    title: str | None = Query(None, description="覆盖元数据中的书名"),
    authors: str | None = Query(None, description="覆盖元数据中的作者,多个用逗号分隔"),
    no_ripples: bool = Query(False, description="只提取作者/作品,跳过书内提及与涟漪"),
    basic_only: bool = Query(False, description="去重只做基础匹配,不调用语义 embedding"),
) -> dict:
    """上传电子书并创建导入任务(耗时任务,立即返回 task_id 供轮询)。"""
    filename = urllib.parse.unquote(request.headers.get("X-Filename") or "")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型:{suffix or '未知'}"
            f"(支持:{', '.join(sorted(ALLOWED_SUFFIXES))})",
        )

    task_id = uuid.uuid4().hex[:12]
    target_dir = IMPORT_DIR / task_id
    target_dir.mkdir(parents=True, exist_ok=True)
    # 文件名去除路径成分,避免 ../ 穿越;保留原始文件名便于识别
    target = target_dir / Path(filename).name

    body = await _drain_body(request)
    if not body:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        target.write_bytes(body)
    except Exception as exc:  # noqa: BLE001 - 写盘失败统一转 500
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"保存上传文件失败:{exc}") from exc

    author_list = [a.strip() for a in (authors or "").split(",") if a.strip()]
    try:
        return submit_import(
            target,
            title=title or None,
            authors=author_list or None,
            no_ripples=no_ripples,
            basic_only=basic_only,
        )
    except ValueError as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/import-book/{task_id}")
def get_import(task_id: str) -> dict:
    """查询导入任务进度/结果/错误(供前端轮询)。"""
    task = get_import_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="导入任务不存在(服务可能已重启)")
    return task

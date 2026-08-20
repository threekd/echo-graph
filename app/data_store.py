"""数据访问层:SQLite 为策展数据唯一权威,CSV 为确定性导出产物(git 审计)。"""

from __future__ import annotations

import csv
import datetime as dt
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from app import sqlite_store

ROOT = Path(__file__).resolve().parent.parent
REAL_DIR = ROOT / "data" / "real"
VERSIONS_DIR = ROOT / "data" / "versions"
KEEP_SNAPSHOTS = 20  # 每个 prefix 保留的最近快照份数

AUTHOR_HEADER = [
    "id", "originalName", "Name_CN", "Name_EN", "nationality",
    "birthYear", "deathYear", "reviewStatus", "createdAt", "updatedAt", "deletedAt",
]
WORK_HEADER = [
    "id", "language", "originalTitle", "Title_CN", "Title_EN",
    "Title_Other", "author_id", "publicationYear", "creationYear", "genre", "reviewStatus",
    "createdAt", "updatedAt", "deletedAt",
]
EDGE_HEADER = [
    "id", "source_work_id", "target_work_id", "evidence", "evidenceSource",
    "note", "reviewStatus", "createdAt", "updatedAt", "deletedAt",
]

# 不可见格式字符:网页复制文本常带入零宽空格(U+200B)等,录入时统一移除
INVISIBLE_CHARS = "\u200b\u200c\u200d\u2060\ufeff"  # 零宽空格/连接符/不换行零宽等


def remove_invisible_chars(value: str) -> str:
    """移除零宽空格等不可见格式字符,不触碰普通空格与换行。"""
    return value.translate(str.maketrans("", "", INVISIBLE_CHARS))


def clean_row(raw: dict) -> dict:
    """基础数据清洗:去首尾空白、移除零宽/不可见字符,空串归一为 None。所有落盘数据先过这里。"""
    out: dict = {}
    for k, v in raw.items():
        if isinstance(v, str):
            v = remove_invisible_chars(v).strip() or None
        out[k] = v
    return out


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [clean_row(r) for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow({h: (r.get(h) if r.get(h) is not None else "") for h in header})
        os.replace(tmp, path)  # 原子替换
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_csv_rows() -> tuple[list[dict], list[dict], list[dict]]:
    """从 data/real/*.csv 读取(迁移 / 恢复用,权威来源是 SQLite)。"""
    return (
        _read_csv(REAL_DIR / "authors.csv"),
        _read_csv(REAL_DIR / "works.csv"),
        _read_csv(REAL_DIR / "edges.csv"),
    )


def load_rows() -> tuple[list[dict], list[dict], list[dict]]:
    """读取策展数据(权威来源:SQLite)。"""
    data = sqlite_store.list_all()
    return data["authors"], data["works"], data["edges"]


def save_rows(authors: list[dict], works: list[dict], edges: list[dict]) -> None:
    """事务写入 SQLite 并刷新确定性 CSV 导出。"""
    sqlite_store.rewrite_all(authors, works, edges)
    export_csv_files()


def export_csv_files(target_dir: Path | None = None) -> None:
    """按 id 排序导出三份 CSV(确定性,UTF-8 BOM);默认写入 data/real/。"""
    data = sqlite_store.list_all()
    out = Path(target_dir) if target_dir is not None else REAL_DIR
    _write_csv(out / "authors.csv", AUTHOR_HEADER, data["authors"])
    _write_csv(out / "works.csv", WORK_HEADER, data["works"])
    _write_csv(out / "edges.csv", EDGE_HEADER, data["edges"])


def snapshot(prefix: str = "admin") -> str | None:
    """保存前备份:SQLite 备份 + CSV 导出到 data/versions/<时间戳>-<prefix>/。"""
    if not sqlite_store.DB_PATH.exists():
        return None
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = VERSIONS_DIR / f"{ts}-{prefix}"
    target.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(sqlite_store.DB_PATH)
    try:
        dst = sqlite3.connect(target / "echo-graph.db")
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    export_csv_files(target)
    _prune_snapshots(prefix)
    return str(target)


def _prune_snapshots(prefix: str) -> None:
    """按目录名(时间戳)排序,每个 prefix 只保留最近 KEEP_SNAPSHOTS 份。"""
    dirs = sorted(
        (d for d in VERSIONS_DIR.iterdir() if d.is_dir() and d.name.endswith(f"-{prefix}")),
        key=lambda d: d.name,
    )
    for old in dirs[:-KEEP_SNAPSHOTS]:
        shutil.rmtree(old, ignore_errors=True)

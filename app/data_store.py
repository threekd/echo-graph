"""数据文件存储层:data/real/*.csv 的读取、原子写入与版本快照。"""

from __future__ import annotations

import csv
import datetime as dt
import os
import shutil
import tempfile
from pathlib import Path

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


def _clean_row(raw: dict) -> dict:
    out: dict = {}
    for k, v in raw.items():
        if isinstance(v, str):
            v = v.strip() or None
        out[k] = v
    return out


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [_clean_row(r) for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]


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


def load_rows() -> tuple[list[dict], list[dict], list[dict]]:
    return (
        _read_csv(REAL_DIR / "authors.csv"),
        _read_csv(REAL_DIR / "works.csv"),
        _read_csv(REAL_DIR / "edges.csv"),
    )


def save_rows(authors: list[dict], works: list[dict], edges: list[dict]) -> None:
    _write_csv(REAL_DIR / "authors.csv", AUTHOR_HEADER, authors)
    _write_csv(REAL_DIR / "works.csv", WORK_HEADER, works)
    _write_csv(REAL_DIR / "edges.csv", EDGE_HEADER, edges)


def snapshot(prefix: str = "admin") -> str | None:
    """保存前备份当前三份 CSV 到 data/versions/<时间戳>-<prefix>/。"""
    files = [REAL_DIR / "authors.csv", REAL_DIR / "works.csv", REAL_DIR / "edges.csv"]
    if not any(f.exists() for f in files):
        return None
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = VERSIONS_DIR / f"{ts}-{prefix}"
    target.mkdir(parents=True, exist_ok=True)
    for f in files:
        if f.exists():
            (target / f.name).write_bytes(f.read_bytes())
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

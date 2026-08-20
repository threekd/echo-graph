"""快照/备份的列举与恢复(管理端入口)。

可恢复的快照来源(两种类型):
- `db`:`backups/echo-graph-*.db`(deploy.sh 用 sqlite3 .backup 生成的权威库备份)
  或 `data/versions/<dir>/echo-graph.db`(历史版本库副本)——直接原子替换当前库;
- `csv`:`data/versions/<dir>/` 下含三份 CSV 的历史目录——校验后复制进 data/export
  并重建 SQLite。

恢复是危险操作:恢复前会自动为当前库先做一次安全备份;db 恢复会原子替换并清理
WAL 残留;csv 恢复会重建策展表(贡献/审计表保留);成功后由调用方触发 CSV 重新导出。
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from app import db_sqlite
from app.data_models import parse_rows
from app.data_store import EXPORT_DIR, load_csv_rows_from

ROOT = Path(__file__).resolve().parent.parent
BACKUPS_DIR = ROOT / "backups"
VERSIONS_DIR = ROOT / "data" / "versions"


def list_snapshots() -> list[dict]:
    """列举全部可恢复快照(按修改时间倒序),含 db / csv 两种类型。"""
    entries: list[dict] = []
    if BACKUPS_DIR.is_dir():
        for f in sorted(BACKUPS_DIR.glob("echo-graph-*.db")):
            entries.append(_entry(f, "db"))
    if VERSIONS_DIR.is_dir():
        for d in sorted(VERSIONS_DIR.iterdir()):
            if not d.is_dir():
                continue
            if (d / "echo-graph.db").is_file():
                entries.append(_entry(d / "echo-graph.db", "db"))
            elif all((d / n).is_file() for n in ("authors.csv", "works.csv", "edges.csv")):
                entries.append(_entry(d, "csv"))
    return sorted(entries, key=lambda e: e["mtime"], reverse=True)


def _entry(path: Path, kind: str) -> dict:
    if path.is_file():
        st = path.stat()
        size, mtime = st.st_size, st.st_mtime
    else:
        size = sum(p.stat().st_size for p in path.iterdir() if p.is_file())
        mtime = max(
            (p.stat().st_mtime for p in path.iterdir() if p.is_file()), default=0
        )
    return {
        "name": path.relative_to(ROOT).as_posix(),
        "size": size,
        "mtime": dt.datetime.fromtimestamp(mtime, dt.UTC).isoformat(timespec="seconds"),
        "kind": kind,
    }


def create_snapshot() -> dict:
    """为当前权威库创建一份快照(backups/echo-graph-<ts>.db)。"""
    db_path = Path(db_sqlite.DB_PATH)
    if not db_path.exists():
        raise ValueError("当前库不存在,无法创建快照")
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    name = "echo-graph-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"
    target = BACKUPS_DIR / name
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return {"ok": True, "name": target.relative_to(ROOT).as_posix()}


def _resolve_allowed(name: str) -> Path:
    """校验快照路径:必须位于 backups/ 或 data/versions/ 下。"""
    if not name or ".." in Path(name).parts:
        raise ValueError("非法的快照名称")
    target = (ROOT / name).resolve()
    allowed = [BACKUPS_DIR.resolve(), VERSIONS_DIR.resolve()]
    if not any(target.is_relative_to(base) for base in allowed):
        raise ValueError("快照必须位于 backups/ 或 data/versions/ 下")
    return target


def _safety_backup() -> str | None:
    """恢复前为当前库做一次安全备份;返回相对路径,库不存在时返回 None。"""
    db_path = Path(db_sqlite.DB_PATH)
    if not db_path.exists():
        return None
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    safety_path = BACKUPS_DIR / (
        "echo-graph-pre-restore-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"
    )
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(safety_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return safety_path.relative_to(ROOT).as_posix()


def _replace_db_from_file(target: Path) -> None:
    """把 .db 快照原子替换到权威库,并清理 WAL 残留。"""
    db_path = Path(db_sqlite.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(db_path.parent), suffix=".restore.tmp")
    os.close(fd)
    try:
        shutil.copyfile(target, tmp)
        os.replace(tmp, db_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    for suffix in ("-wal", "-shm"):
        stale = Path(str(db_path) + suffix)
        if stale.exists():
            stale.unlink()


def restore_snapshot(name: str) -> dict:
    """把指定快照恢复到当前权威库;返回安全备份路径与恢复类型。"""
    target = _resolve_allowed(name)
    safety = _safety_backup()

    if target.is_file() and target.name.endswith(".db"):
        _replace_db_from_file(target)
        return {"ok": True, "restored": name, "safety_backup": safety, "kind": "db"}

    if target.is_dir() and all((target / n).is_file() for n in ("authors.csv", "works.csv", "edges.csv")):
        # 先校验再落盘:坏快照不污染 data/export
        authors, works, edges = load_csv_rows_from(target)
        parse_rows(authors, works, edges)
        for csv_name in ("authors.csv", "works.csv", "edges.csv"):
            shutil.copyfile(target / csv_name, EXPORT_DIR / csv_name)
        from app.sqlite_store import migrate_from_csv

        migrate_from_csv(Path(db_sqlite.DB_PATH), check=True)
        return {"ok": True, "restored": name, "safety_backup": safety, "kind": "csv"}

    raise ValueError("快照既不是 .db 文件,也不是含三份 CSV 的目录")

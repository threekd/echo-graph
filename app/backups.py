"""快照/备份的列举与恢复(管理端入口)。

可恢复的快照来源(两种类型):
- `db`:`backups/echo-graph-*.db`(deploy.sh 用 sqlite3 .backup 生成的权威库备份)
  或 `data/versions/<dir>/echo-graph.db`(历史版本库副本)——直接原子替换当前库;
- `csv`:`data/versions/<dir>/` 下含三份 CSV 的历史目录——校验后复制进 data/export
  并重建 SQLite。

恢复是危险操作:恢复前会自动为当前库先做一次安全备份;db 恢复通过 SQLite backup API
覆盖当前库(不依赖文件替换与 WAL 清理);csv 恢复会重建策展表(贡献/审计表保留);
成功后由调用方触发 CSV 重新导出。

db 恢复通过 SQLite backup API 覆盖当前库(不依赖文件替换与 WAL 清理),恢复期间
持有 db_sqlite._write_lock,与 admin 写事务/贡献提交互斥。
"""

from __future__ import annotations

import datetime as dt
import shutil
import sqlite3
import threading
from pathlib import Path

from app import db_sqlite
from app.data_models import parse_rows
from app.data_store import EXPORT_DIR, load_csv_rows_from

ROOT = Path(__file__).resolve().parent.parent
BACKUPS_DIR = ROOT / "backups"
VERSIONS_DIR = ROOT / "data" / "versions"
# 应用侧快照保留上限(deploy.sh 另有自己的 14 份裁剪)
SNAPSHOT_RETENTION = 30
_restore_lock = threading.Lock()


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
    _prune_backups()
    return {"ok": True, "name": target.relative_to(ROOT).as_posix()}


def _prune_backups() -> None:
    """保留最近 SNAPSHOT_RETENTION 份 backups/ 下的 .db 快照(含 pre-restore 安全备份)。"""
    if not BACKUPS_DIR.is_dir():
        return
    snapshots = sorted(
        BACKUPS_DIR.glob("echo-graph-*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in snapshots[SNAPSHOT_RETENTION:]:
        try:
            stale.unlink()
        except OSError:
            pass


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
    """把 .db 快照内容恢复到权威库(用 SQLite backup API)。

    相比文件替换,backup API 由 SQLite 管理目标库的页复制与 WAL,不依赖删除
    -wal/-shm 残留,也不会因目标文件被其他连接占用而失败。
    """
    db_path = Path(db_sqlite.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(target)
    try:
        dst = sqlite3.connect(db_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def restore_snapshot(name: str) -> dict:
    """把指定快照恢复到当前权威库;返回安全备份路径与恢复类型。

    恢复期间持有 db_sqlite._write_lock,与 admin 写事务/贡献提交互斥;
    文档建议恢复期间避免编辑数据。
    """
    with _restore_lock, db_sqlite._write_lock:
        return _restore_snapshot_locked(name)


def _restore_snapshot_locked(name: str) -> dict:
    target = _resolve_allowed(name)
    safety = _safety_backup()

    if target.is_file() and target.name.endswith(".db"):
        _replace_db_from_file(target)
        return {"ok": True, "restored": name, "safety_backup": safety, "kind": "db"}

    if target.is_dir() and all((target / n).is_file() for n in ("authors.csv", "works.csv", "edges.csv")):
        # 先校验再落盘:坏快照不污染 data/export;CSV 只含公共数据,恢复时保留用户星云
        authors, works, edges = load_csv_rows_from(target)
        models = parse_rows(authors, works, edges)
        for csv_name in ("authors.csv", "works.csv", "edges.csv"):
            shutil.copyfile(target / csv_name, EXPORT_DIR / csv_name)
        from app.auth import admin_user_id
        from app.sqlite_store import replace_public_rows

        admin = admin_user_id()
        if admin is None:
            raise ValueError("引导管理员尚未注册,无法执行 CSV 恢复(请先注册管理员账号)")
        replace_public_rows(*models, owner_id=admin)
        return {"ok": True, "restored": name, "safety_backup": safety, "kind": "csv"}

    raise ValueError("快照既不是 .db 文件,也不是含三份 CSV 的目录")

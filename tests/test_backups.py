"""快照列举与恢复测试(临时目录,不触碰真实数据)。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.backups as backups
from app import db_sqlite


class BackupsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.backups_dir = self.root / "backups"
        self.versions_dir = self.root / "versions"
        self.backups_dir.mkdir()
        self.versions_dir.mkdir()
        patch.object(backups, "BACKUPS_DIR", self.backups_dir).start()
        patch.object(backups, "VERSIONS_DIR", self.versions_dir).start()
        patch.object(backups, "ROOT", self.root).start()
        patch.object(db_sqlite, "DB_PATH", self.root / "echo-graph.db").start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.tmp.cleanup)

    @staticmethod
    def _make_db(path: Path, marker: str) -> None:
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('marker', ?)", (marker,))
        conn.commit()
        conn.close()

    def test_list_snapshots_includes_backups_and_versions(self) -> None:
        self._make_db(self.backups_dir / "echo-graph-20260821-030000.db", "b1")
        vdir = self.versions_dir / "20260820-120000-admin"
        vdir.mkdir()
        self._make_db(vdir / "echo-graph.db", "v1")
        items = backups.list_snapshots()
        names = {i["name"] for i in items}
        self.assertEqual(names, {
            "backups/echo-graph-20260821-030000.db",
            "versions/20260820-120000-admin/echo-graph.db",
        })
        kinds = {i["name"]: i["kind"] for i in items}
        self.assertEqual(kinds["backups/echo-graph-20260821-030000.db"], "db")
        self.assertEqual(kinds["versions/20260820-120000-admin/echo-graph.db"], "db")
        self.assertTrue(all(i["size"] > 0 for i in items))

    def test_restore_replaces_db_and_creates_safety_backup(self) -> None:
        self._make_db(db_sqlite.DB_PATH, "current")
        snap = self.backups_dir / "echo-graph-snap.db"
        self._make_db(snap, "snapshot")
        result = backups.restore_snapshot("backups/echo-graph-snap.db")
        self.assertTrue(result["ok"])
        self.assertTrue(result["safety_backup"])

        def marker(path: Path) -> str:
            conn = sqlite3.connect(path)
            try:
                return conn.execute("SELECT value FROM meta WHERE key='marker'").fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(marker(db_sqlite.DB_PATH), "snapshot")
        self.assertEqual(marker(self.root / result["safety_backup"]), "current")

    def test_restore_works_without_existing_db(self) -> None:
        snap = self.backups_dir / "echo-graph-snap.db"
        self._make_db(snap, "snapshot")
        result = backups.restore_snapshot("backups/echo-graph-snap.db")
        self.assertIsNone(result["safety_backup"])
        conn = sqlite3.connect(db_sqlite.DB_PATH)
        marker = conn.execute("SELECT value FROM meta WHERE key='marker'").fetchone()[0]
        conn.close()
        self.assertEqual(marker, "snapshot")

    def test_create_snapshot_backs_up_current_db(self) -> None:
        self._make_db(db_sqlite.DB_PATH, "current")
        result = backups.create_snapshot()
        self.assertTrue(result["ok"])
        self.assertTrue(result["name"].startswith("backups/echo-graph-"))
        conn = sqlite3.connect(self.root / result["name"])
        try:
            marker = conn.execute("SELECT value FROM meta WHERE key='marker'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(marker, "current")

    def test_create_snapshot_requires_db(self) -> None:
        with self.assertRaises(ValueError):
            backups.create_snapshot()

    def test_restore_rejects_invalid_names(self) -> None:
        for bad in ("../pyproject.toml", "echo-graph.db", "data/echo-graph.db", "unknown.db"):
            with self.assertRaises(ValueError):
                backups.restore_snapshot(bad)

    def test_snapshot_retention_prunes_old(self) -> None:
        """快照保留上限:只保留最近 SNAPSHOT_RETENTION 份 db 快照。"""
        for i in range(backups.SNAPSHOT_RETENTION + 5):
            p = self.backups_dir / f"echo-graph-{i:04d}.db"
            p.write_bytes(b"x")
            os.utime(p, (i + 1, i + 1))
        backups._prune_backups()
        remaining = sorted(p.name for p in self.backups_dir.glob("echo-graph-*.db"))
        self.assertEqual(len(remaining), backups.SNAPSHOT_RETENTION)
        self.assertNotIn("echo-graph-0000.db", remaining)  # 最旧的 5 份被删除
        self.assertIn(f"echo-graph-{backups.SNAPSHOT_RETENTION + 4:04d}.db", remaining)


if __name__ == "__main__":
    unittest.main()

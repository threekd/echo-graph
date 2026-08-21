"""快照列举与恢复测试(临时目录,不触碰真实数据)。"""

from __future__ import annotations

import csv
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.backups as backups
import app.data_store as ds
from app import auth, db_sqlite, sqlite_store


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
        self.addCleanup(self.tmp.cleanup)

    @staticmethod
    def _make_db(path: Path, marker: str) -> None:
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('marker', ?)", (marker,))
        conn.commit()
        conn.close()

    @staticmethod
    def _write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    def test_list_snapshots_includes_backups_and_versions(self) -> None:
        self._make_db(self.backups_dir / "echo-graph-20260821-030000.db", "b1")
        vdir = self.versions_dir / "20260820-120000-admin"
        vdir.mkdir()
        self._make_db(vdir / "echo-graph.db", "v1")
        csvdir = self.versions_dir / "20260819-100000-hygiene"
        csvdir.mkdir()
        for n in ("authors.csv", "works.csv", "edges.csv"):
            (csvdir / n).write_text("id\n", encoding="utf-8")
        items = backups.list_snapshots()
        names = {i["name"] for i in items}
        self.assertEqual(names, {
            "backups/echo-graph-20260821-030000.db",
            "versions/20260820-120000-admin/echo-graph.db",
            "versions/20260819-100000-hygiene",
        })
        kinds = {i["name"]: i["kind"] for i in items}
        self.assertEqual(kinds["backups/echo-graph-20260821-030000.db"], "db")
        self.assertEqual(kinds["versions/20260820-120000-admin/echo-graph.db"], "db")
        self.assertEqual(kinds["versions/20260819-100000-hygiene"], "csv")
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

    def test_restore_csv_snapshot_rebuilds_db(self) -> None:
        with patch.object(auth, "BOOTSTRAP_EMAIL", "admin@test.local"):
            auth.register("admin@test.local", "admin-password-123")
        vdir = self.versions_dir / "20260820-120000-admin"
        vdir.mkdir()
        export_dir = self.root / "export"
        export_dir.mkdir()
        patch.object(backups, "EXPORT_DIR", export_dir).start()
        patch.object(ds, "EXPORT_DIR", export_dir).start()  # migrate_from_csv 内部读取 data_store.EXPORT_DIR

        a1 = "01a013e6-e885-766b-b9db-315d518adeeb"
        w1 = "01a013e8-907e-77f3-83c6-bce355a36268"
        authors = [{"id": a1, "originalName": "Albert Camus", "Name_CN": "加缪", "nationality": "FR"}]
        works = [{
            "id": w1, "language": "fr", "originalTitle": "L'Étranger",
            "Title_CN": "局外人", "author_id": a1,
        }]
        self._write_csv(vdir / "authors.csv", ds.AUTHOR_HEADER, authors)
        self._write_csv(vdir / "works.csv", ds.WORK_HEADER, works)
        self._write_csv(vdir / "edges.csv", ds.EDGE_HEADER, [])

        self._make_db(db_sqlite.DB_PATH, "current")
        # 用户私有行:CSV 恢复后必须原样保留
        user = auth.register("user@test.local", "user-password-123")
        sqlite_store.rewrite_all(
            [{
                "id": "01a013e6-e885-766b-b9db-315d518adeec",
                "originalName": "私有作者",
                "Name_CN": "私有作者",
                "owner_id": user["id"],
            }],
            [],
            [],
        )
        result = backups.restore_snapshot("versions/20260820-120000-admin")
        self.assertEqual(result["kind"], "csv")
        self.assertTrue(result["safety_backup"])
        conn = sqlite3.connect(db_sqlite.DB_PATH)
        try:
            # 1 条公共(来自 CSV)+ 1 条用户私有(保留)
            self.assertEqual(conn.execute("SELECT count(*) FROM authors").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM works").fetchone()[0], 1)
            user_rows = conn.execute(
                "SELECT count(*) FROM authors WHERE owner_id = ?", (user["id"],)
            ).fetchone()[0]
            self.assertEqual(user_rows, 1)
        finally:
            conn.close()
        self.assertTrue((export_dir / "authors.csv").exists())

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

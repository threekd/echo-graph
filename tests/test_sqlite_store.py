"""SQLite 策展存储层测试(迁移 Phase 1,使用临时数据库文件)。"""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.sqlite_store as store
from app import db_sqlite
from app.data_models import parse_rows


def _fixture():
    a1 = "01a013e6-e885-766b-b9db-315d518adeeb"
    a2 = "01a013e6-e885-766b-b9db-315d518adeec"
    a3 = "01a013e6-e885-766b-b9db-315d518adeed"
    w1 = "01a013e8-907e-77f3-83c6-bce355a36268"
    w2 = "01a013e8-907e-77f3-83c6-bce48f19b60d"
    e1 = "01a0155e-33a7-772a-8efc-4ad2766bc830"
    authors = [
        {"id": a1, "originalName": "Albert Camus", "Name_CN": "加缪", "nationality": "fr", "birthYear": "1913"},
        {"id": a2, "originalName": "鲁迅", "Name_CN": "鲁迅", "nationality": "CN"},
        {"id": a3, "originalName": "旧作者", "Name_CN": "旧作者", "deletedAt": "2026-01-01T00:00:00+00:00"},
    ]
    works = [
        {"id": w1, "language": "FR", "originalTitle": "L'Étranger", "Title_CN": "局外人", "author_id": a1},
        {"id": w2, "language": "zh", "originalTitle": "朝花夕拾", "Title_CN": "朝花夕拾", "author_id": f"{a1},{a2}"},
    ]
    edges = [{"id": e1, "source_work_id": w1, "target_work_id": w2, "evidence": "提及", "reviewStatus": "reviewed"}]
    return authors, works, edges


class SqliteStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "echo-graph.db"
        patcher = patch.object(db_sqlite, "DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def _migrate(self):
        a, w, e = _fixture()
        am, wm, em, wa = parse_rows(a, w, e)
        store.replace_all(am, wm, em, wa)
        return a, w, e

    def test_replace_and_list(self) -> None:
        a, w, e = self._migrate()
        data = store.list_all()
        self.assertEqual(len(data["authors"]), 3)
        self.assertEqual(len(data["works"]), 2)
        self.assertEqual(len(data["edges"]), 1)
        # 多作者:author_id 重组为排序后的逗号串,work_authors 拆开
        w2 = next(r for r in data["works"] if r["Title_CN"] == "朝花夕拾")
        self.assertEqual(w2["author_id"], "01a013e6-e885-766b-b9db-315d518adeeb,01a013e6-e885-766b-b9db-315d518adeec")
        self.assertEqual(data["work_authors"][w2["id"]], [
            "01a013e6-e885-766b-b9db-315d518adeeb",
            "01a013e6-e885-766b-b9db-315d518adeec",
        ])
        # 软删除行保留
        deleted = [r for r in data["authors"] if r.get("deletedAt")]
        self.assertEqual(len(deleted), 1)

    def test_roundtrip_payload(self) -> None:
        a, w, e = self._migrate()
        self.assertEqual(store.sync_payload(), store.canonical_payload(a, w, e))

    def test_migrate_from_csv(self) -> None:
        with patch("app.data_store.load_csv_rows", return_value=_fixture()):
            stats = store.migrate_from_csv(self.db_path)
        self.assertEqual(stats["authors"], 3)
        self.assertEqual(stats["works"], 2)
        self.assertEqual(stats["echoes"], 1)
        self.assertEqual(stats["authored_links"], 3)

    def test_prune_audit(self) -> None:
        """按天裁剪审计记录:dry_run 只统计,实际删除后不可再查到。"""
        old_ts = (dt.datetime.now(dt.UTC) - dt.timedelta(days=200)).isoformat(timespec="seconds")
        with db_sqlite._db() as conn:
            db_sqlite.audit(conn, "create", "authors", "a-new", detail="new")
            conn.execute(
                "INSERT INTO audit_log (ts, actor, action, kind, row_id, detail)"
                " VALUES (?, 'admin', 'create', 'authors', 'a-old', 'old')",
                (old_ts,),
            )
        self.assertEqual(store.prune_audit(days=90, dry_run=True), 1)
        self.assertEqual(store.prune_audit(days=90), 1)
        self.assertEqual(store.prune_audit(days=90, dry_run=True), 0)


if __name__ == "__main__":
    unittest.main()

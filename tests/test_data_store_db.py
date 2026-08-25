"""data_store 切换到 SQLite 后的行为测试(临时库 + 临时导出目录)。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.data_store as ds
from app import auth, db_sqlite, sqlite_store
from tests._helpers import rewrite_all


def _rows():
    a1 = "01a013e6-e885-766b-b9db-315d518adeeb"
    a2 = "01a013e6-e885-766b-b9db-315d518adeec"
    w1 = "01a013e8-907e-77f3-83c6-bce355a36268"
    w2 = "01a013e8-907e-77f3-83c6-bce48f19b60d"
    authors = [
        {"id": a1, "originalName": "Albert Camus", "Name_CN": "加缪", "nationality": "FR"},
        {"id": a2, "originalName": "鲁迅", "Name_CN": "鲁迅", "nationality": "CN"},
    ]
    works = [
        {"id": w1, "language": "fr", "originalTitle": "L'Étranger", "Title_CN": "局外人", "author_id": a1},
        {"id": w2, "language": "zh", "originalTitle": "朝花夕拾", "Title_CN": "朝花夕拾", "author_id": f"{a1},{a2}"},
    ]
    edges = [{
        "id": "01a0155e-33a7-772a-8efc-4ad2766bc830",
        "source_work_id": w1, "target_work_id": w2,
        "evidence": "提及", "reviewStatus": "reviewed",
    }]
    return authors, works, edges


class DataStoreDbTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "echo-graph.db"
        self.export = Path(self.tmp.name) / "export"
        self.export.mkdir()
        patch.object(db_sqlite, "DB_PATH", self.db).start()
        patch.object(ds, "EXPORT_DIR", self.export).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.tmp.cleanup)

    def test_save_then_load_roundtrip(self) -> None:
        a, w, e = _rows()
        rewrite_all(a, w, e)
        ds.export_csv_files()
        a2, w2, e2 = sqlite_store.load_rows()
        self.assertEqual(len(a2), 2)
        self.assertEqual(len(w2), 2)
        self.assertEqual(len(e2), 1)
        multi = next(r for r in w2 if r["Title_CN"] == "朝花夕拾")
        self.assertEqual(multi["author_id"], f"{a[0]['id']},{a[1]['id']}")
        # 保存后自动导出 CSV 到 data/export
        self.assertTrue((self.export / "authors.csv").exists())
        self.assertTrue((self.export / "works.csv").exists())
        self.assertTrue((self.export / "edges.csv").exists())

    def test_export_is_deterministic(self) -> None:
        a, w, e = _rows()
        rewrite_all(a, w, e)
        ds.export_csv_files()
        content = (self.export / "authors.csv").read_bytes()
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        ds.export_csv_files(other)
        self.assertEqual(content, (other / "authors.csv").read_bytes())

    def test_load_csv_rows_reads_export_files(self) -> None:
        a, w, e = _rows()
        rewrite_all(a, w, e)
        ds.export_csv_files()
        a2, w2, e2 = ds.load_csv_rows()
        self.assertEqual(len(a2), 2)
        self.assertEqual(len(w2), 2)
        self.assertEqual(len(e2), 1)

    def test_export_excludes_user_private_rows(self) -> None:
        """CSV 只导出公共星云(admin 认领),用户私有空间不得进 git 审计产物。"""
        with patch.object(auth, "BOOTSTRAP_EMAIL", "admin@test.local"):
            admin = auth.register("admin@test.local", "admin-password-123", username="admin")
            user = auth.register("user@test.local", "user-password-123", username="user01")
            a1 = "01a013e6-e885-766b-b9db-315d518adeeb"
            a2 = "01a013e6-e885-766b-b9db-315d518adeec"
            rewrite_all(
                [
                    {"id": a1, "originalName": "公共", "Name_CN": "公共", "owner_id": admin["id"]},
                    {"id": a2, "originalName": "私有", "Name_CN": "私有", "owner_id": user["id"]},
                ],
                [],
                [],
            )
            ds.export_csv_files()
            exported_authors, _, _ = ds.load_csv_rows()
            self.assertEqual([r["id"] for r in exported_authors], [a1])


if __name__ == "__main__":
    unittest.main()

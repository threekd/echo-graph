"""数据管理页「导出 CSV」端点测试(/api/me/export、/api/admin/export)。"""

from __future__ import annotations

import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main  # noqa: E402
from app import auth, db_sqlite  # noqa: E402
from tests._helpers import rewrite_all  # noqa: E402


class ExportTest(unittest.TestCase):
    ADMIN = "admin@test.local"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "export.db").start()
        patch.object(auth, "BOOTSTRAP_EMAIL", self.ADMIN).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.tmp.cleanup)
        self.admin = auth.register(self.ADMIN, "admin-password-123", username="admin")
        self.user = auth.register("user@test.local", "user-password-123", username="user01")

        a1 = "01a013e6-e885-766b-b9db-315d518adeeb"
        w1 = "01a013e8-907e-77f3-83c6-bce355a36268"
        rewrite_all(
            [
                {
                    "id": a1,
                    "originalName": "Albert Camus",
                    "Name_CN": "加缪",
                    "nationality": "FR",
                    "owner_id": self.user["id"],
                },
            ],
            [
                {
                    "id": w1,
                    "language": "fr",
                    "originalTitle": "L'Étranger",
                    "Title_CN": "局外人",
                    "author_id": a1,
                    "readingStatus": "read",
                    "owner_id": self.user["id"],
                },
            ],
            [],
        )
        # rewrite_all 只写 WORK_COLS 主列;个人字段 readingStatus 单独补列
        with db_sqlite._db() as conn:
            conn.execute("UPDATE works SET readingStatus = 'read' WHERE id = ?", (w1,))
        self.client = TestClient(main.app)

    def _login(self, email: str, password: str) -> None:
        resp = self.client.post("/api/auth/login", json={"email": email, "password": password})
        self.assertEqual(resp.status_code, 200)

    def _zip_names_and_csv(self, resp) -> tuple[list[str], dict[str, list[dict]]]:
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/zip", resp.headers["content-type"])
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = sorted(zf.namelist())
            parsed = {
                n: list(csv.DictReader(io.StringIO(zf.read(n).decode("utf-8-sig"))))
                for n in names
            }
        return names, parsed

    def test_export_requires_login(self) -> None:
        resp = self.client.get("/api/me/export")
        self.assertEqual(resp.status_code, 401)

    def test_me_export_contains_own_space_csv(self) -> None:
        self._login("user@test.local", "user-password-123")
        resp = self.client.get("/api/me/export")
        names, parsed = self._zip_names_and_csv(resp)
        self.assertEqual(names, ["authors.csv", "edges.csv", "works.csv"])
        self.assertEqual(len(parsed["authors.csv"]), 1)
        self.assertEqual(parsed["authors.csv"][0]["Name_CN"], "加缪")
        self.assertEqual(len(parsed["works.csv"]), 1)
        self.assertEqual(parsed["works.csv"][0]["Title_CN"], "局外人")
        # 个人语义字段保留(阅读状态)
        self.assertIn("readingStatus", parsed["works.csv"][0])
        self.assertEqual(parsed["works.csv"][0]["readingStatus"], "read")
        self.assertEqual(parsed["edges.csv"], [])

    def test_export_scoped_to_own_space(self) -> None:
        """用户导出不含其他空间(admin 星云)的数据。"""
        self._login("user@test.local", "user-password-123")
        _, parsed = self._zip_names_and_csv(self.client.get("/api/me/export"))
        self.assertEqual(len(parsed["authors.csv"]), 1)  # 只有自己的作者

    def test_admin_export_forbidden_for_normal_user(self) -> None:
        self._login("user@test.local", "user-password-123")
        resp = self.client.get("/api/admin/export")
        self.assertEqual(resp.status_code, 403)

    def test_admin_export_public_space(self) -> None:
        self._login(self.ADMIN, "admin-password-123")
        resp = self.client.get("/api/admin/export")
        names, parsed = self._zip_names_and_csv(resp)
        self.assertEqual(names, ["authors.csv", "edges.csv", "works.csv"])
        # admin 空间无数据(用户行归属 user),导出只有表头
        self.assertEqual(parsed["authors.csv"], [])
        self.assertEqual(parsed["works.csv"], [])


if __name__ == "__main__":
    unittest.main()

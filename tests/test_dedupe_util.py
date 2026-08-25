"""dedupe_util.load_rows 公共空间口径测试(admin 已注册时未认领行也须包含)。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import auth, db_sqlite
from app.dedupe_util import authors_clearly_different, load_rows
from tests._helpers import rewrite_all


class AuthorsClearlyDifferentTest(unittest.TestCase):
    """authors_clearly_different:同人异译不降级,真正不同作者才判不同。"""

    def test_same_name_not_different(self) -> None:
        self.assertFalse(authors_clearly_different("蕾切尔·卡逊", "蕾切尔·卡逊"))

    def test_variant_translation_not_different(self) -> None:
        # 同人异译:卡逊/卡森、村上春树/村上春樹(繁简)、阿瑟/亚瑟
        self.assertFalse(authors_clearly_different("蕾切尔·卡逊", "蕾切尔·卡森"))
        self.assertFalse(authors_clearly_different("村上春树", "村上春樹"))
        self.assertFalse(authors_clearly_different("阿瑟·克拉克", "亚瑟·克拉克"))

    def test_containment_not_different(self) -> None:
        self.assertFalse(authors_clearly_different("卡逊", "蕾切尔·卡逊（Rachel Carson）"))

    def test_clearly_different_authors(self) -> None:
        self.assertTrue(authors_clearly_different("蕾切尔·卡逊", "另一位作者"))
        self.assertTrue(authors_clearly_different("刘慈欣", "罗贯中"))

    def test_missing_side_never_different(self) -> None:
        self.assertFalse(authors_clearly_different("蕾切尔·卡逊", None))
        self.assertFalse(authors_clearly_different("", "蕾切尔·卡逊"))


class LoadRowsPublicOnlyTest(unittest.TestCase):
    ADMIN = "boss@test.local"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "dedupe.db").start()
        patch.object(auth, "BOOTSTRAP_EMAIL", self.ADMIN).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.tmp.cleanup)
        self.admin = auth.register(self.ADMIN, "admin-password-123", username="admin")
        self.alice = auth.register("alice@test.local", "password123", username="alice")

    def _author(self, suffix: str, owner_id) -> dict:
        return {
            "id": f"01a00000-0000-7000-8000-0000000000{suffix}",
            "originalName": f"Name{suffix}",
            "Name_CN": f"作者{suffix}",
            "owner_id": owner_id,
        }

    def test_public_only_includes_claimed_and_unclaimed(self) -> None:
        """admin 已注册:已认领行与未认领行(owner_id IS NULL)都应算公共数据。"""
        rewrite_all(
            [
                self._author("01", self.admin["id"]),
                self._author("02", None),
                self._author("03", self.alice["id"]),  # 他人私有空间,不应出现在公共口径
            ],
            [],
            [],
        )
        data = load_rows(public_only=True)
        ids = {r["id"] for r in data["authors"]}
        self.assertEqual(
            ids,
            {
                "01a00000-0000-7000-8000-000000000001",
                "01a00000-0000-7000-8000-000000000002",
            },
        )

    def test_public_only_without_admin_falls_back_to_unclaimed(self) -> None:
        """admin 未注册时公共口径 = 未认领行(owner_id IS NULL)。"""
        with patch.object(auth, "BOOTSTRAP_EMAIL", ""):
            rewrite_all(
                [self._author("11", self.admin["id"]), self._author("12", None)],
                [],
                [],
            )
            data = load_rows(public_only=True)
            ids = {r["id"] for r in data["authors"]}
            self.assertEqual(ids, {"01a00000-0000-7000-8000-000000000012"})

    def test_non_public_only_returns_everything(self) -> None:
        """非公共口径(管线视角)返回全部活跃行。"""
        rewrite_all(
            [self._author("21", self.admin["id"]), self._author("22", self.alice["id"])],
            [],
            [],
        )
        data = load_rows()
        self.assertEqual(len(data["authors"]), 2)


if __name__ == "__main__":
    unittest.main()

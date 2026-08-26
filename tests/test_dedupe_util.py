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


class LoadRowsOwnerScopeTest(unittest.TestCase):
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

    def test_owner_scope_filters_by_owner(self) -> None:
        """owner_id 精确匹配:只返回该用户的行,不含其他用户空间数据。"""
        rewrite_all(
            [
                self._author("01", self.admin["id"]),
                self._author("02", self.admin["id"]),
                self._author("03", self.alice["id"]),  # 他人私有空间,不应出现在 admin 口径
            ],
            [],
            [],
        )
        data = load_rows(owner_id=self.admin["id"])
        ids = {r["id"] for r in data["authors"]}
        self.assertEqual(
            ids,
            {
                "01a00000-0000-7000-8000-000000000001",
                "01a00000-0000-7000-8000-000000000002",
            },
        )

    def test_without_owner_returns_everything(self) -> None:
        """不带 owner_id(管线视角)返回全部活跃行。"""
        rewrite_all(
            [self._author("21", self.admin["id"]), self._author("22", self.alice["id"])],
            [],
            [],
        )
        data = load_rows()
        self.assertEqual(len(data["authors"]), 2)


if __name__ == "__main__":
    unittest.main()

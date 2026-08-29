"""dedupe_util.load_rows 公共空间口径测试(admin 已注册时未认领行也须包含)。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import auth, db_sqlite
from app.ai_assistant.tools.dedupe_check import basic_match_work
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

    def test_mid_name_single_char_variant_not_different(self) -> None:
        """名字中段一字之差的长名字:伊凡/伊万·屠格涅夫是同一人(编辑距离兜底)。"""
        self.assertFalse(authors_clearly_different("伊凡·屠格涅夫", "伊万·屠格涅夫"))
        self.assertFalse(authors_clearly_different("约翰·克里斯托夫", "约翰·克里斯多夫"))

    def test_short_name_single_char_diff_still_different(self) -> None:
        """短名字一字之差仍是不同人(长度低于兜底下限,防止小仲马/大仲马误并)。"""
        self.assertTrue(authors_clearly_different("小仲马", "大仲马"))
        self.assertTrue(authors_clearly_different("杜甫", "杜牧"))

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

    def test_works_carry_author_three_name_forms(self) -> None:
        """作品行带出作者 中文/原文/英文 三种名称,供同名异书消歧使用。"""
        author = {
            "id": "01a00000-0000-7000-8000-0000000000aa",
            "originalName": "Иван Тургенев",
            "Name_CN": "伊万·屠格涅夫",
            "Name_EN": "Ivan Turgenev",
            "owner_id": self.admin["id"],
        }
        work = {
            "id": "01a00000-0000-7000-8000-0000000000bb",
            "language": "ru",
            "originalTitle": "Рудин",
            "Title_CN": "罗亭",
            "author_id": author["id"],
            "owner_id": self.admin["id"],
        }
        rewrite_all([author], [work], [])
        w = load_rows(owner_id=self.admin["id"])["works"][0]
        self.assertEqual(w["author_names"], "伊万·屠格涅夫")
        self.assertEqual(w["author_original_names"], "Иван Тургенев")
        self.assertEqual(w["author_en_names"], "Ivan Turgenev")


class WorkAuthorFormsMatchTest(unittest.TestCase):
    """作品判重:作者 中文/原文/英文 三形式都参与同名异书消歧。"""

    def _existing(self, **overrides) -> dict:
        row = {
            "id": "w-1",
            "Title_CN": "罗亭",
            "originalTitle": "Рудин",
            "Title_EN": "Rudin",
            "author_names": "伊万·屠格涅夫",
            "author_original_names": "",
            "author_en_names": "",
        }
        row.update(overrides)
        return row

    def test_original_name_prevents_exact_diff_author(self) -> None:
        """候选中文名「伊凡·屠格涅夫」与库中「伊万·屠格涅夫」仅译名用字差异,
        但原文名(西里尔)一致 → 不判同名异书,保持 exact。"""
        cand = {"Title_CN": "罗亭", "originalTitle": "Рудин", "author": "伊凡·屠格涅夫"}
        existing = [
            self._existing(
                author_names="伊万·屠格涅夫",
                author_original_names="Иван Сергеевич Тургенев",
                author_en_names="Ivan Turgenev",
            )
        ]
        hit = basic_match_work(cand, existing)
        self.assertEqual(hit["level"], "exact")
        self.assertEqual(hit["score"], 1.0)

    def test_candidate_original_name_matches_existing_chinese(self) -> None:
        """候选带原文名、库中只有中文名:跨形式兜底,不判不同。"""
        cand = {
            "Title_CN": "罗亭",
            "originalTitle": "Рудин",
            "author": "伊凡·屠格涅夫",
            "_author_names_orig": "Иван Тургенев",
        }
        existing = [self._existing(author_names="伊万·屠格涅夫")]
        hit = basic_match_work(cand, existing)
        self.assertEqual(hit["level"], "exact")

    def test_true_same_title_diff_author_still_downgraded(self) -> None:
        """真·同名异书:标题相同、作者三形式都不同 → 仍降级 exact_diff_author。"""
        cand = {"Title_CN": "白鲸", "originalTitle": "Moby Dick", "author": "赫尔曼·梅尔维尔"}
        existing = [
            self._existing(
                Title_CN="白鲸",
                originalTitle="Moby Dick",
                author_names="另一位作者",
                author_original_names="Other Author",
            )
        ]
        hit = basic_match_work(cand, existing)
        self.assertEqual(hit["level"], "exact_diff_author")


if __name__ == "__main__":
    unittest.main()

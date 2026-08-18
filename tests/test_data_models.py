"""数据模型与导入校验测试(parse_rows)。"""

from __future__ import annotations

import unittest
import uuid

from app.data_models import parse_rows


def _u() -> str:
    return str(uuid.uuid4())


def _fixture() -> tuple[list[dict], list[dict], list[dict]]:
    a1, w1, w2, e1 = _u(), _u(), _u(), _u()
    authors = [{"id": a1, "originalName": "Author A", "Name_CN": "作家甲"}]
    works = [
        {"id": w1, "language": "en", "originalTitle": "Book One", "Title_CN": "书一", "Author": "Author A"},
        {"id": w2, "language": "fr", "originalTitle": "Livre Deux", "Title_CN": "书二", "Author": "Author A"},
    ]
    edges = [{"id": e1, "source_work_id": w1, "target_work_id": w2, "evidence": "mentions"}]
    return authors, works, edges


class ParseRowsTest(unittest.TestCase):
    def test_valid(self) -> None:
        a, w, e = _fixture()
        am, wm, em, work_authors = parse_rows(a, w, e)
        self.assertEqual(len(am), 1)
        self.assertEqual(len(wm), 2)
        self.assertEqual(len(em), 1)
        self.assertEqual(sum(len(v) for v in work_authors.values()), 2)

    def test_duplicate_work_id_rejected(self) -> None:
        a, w, e = _fixture()
        w.append(dict(w[0]))
        with self.assertRaises(ValueError) as ctx:
            parse_rows(a, w, e)
        self.assertIn("作品 id 重复", str(ctx.exception))

    def test_duplicate_author_id_rejected(self) -> None:
        a, w, e = _fixture()
        a.append(dict(a[0]))
        with self.assertRaises(ValueError) as ctx:
            parse_rows(a, w, e)
        self.assertIn("作者 id 重复", str(ctx.exception))

    def test_self_loop_rejected(self) -> None:
        a, w, e = _fixture()
        e[0]["target_work_id"] = e[0]["source_work_id"]
        with self.assertRaises(ValueError) as ctx:
            parse_rows(a, w, e)
        self.assertIn("自环", str(ctx.exception))

    def test_missing_work_reference_rejected(self) -> None:
        a, w, e = _fixture()
        e[0]["target_work_id"] = _u()
        with self.assertRaises(ValueError) as ctx:
            parse_rows(a, w, e)
        self.assertIn("不存在的目标作品", str(ctx.exception))

    def test_unknown_author_rejected(self) -> None:
        a, w, e = _fixture()
        w[0]["Author"] = "Nobody"
        with self.assertRaises(ValueError) as ctx:
            parse_rows(a, w, e)
        self.assertIn("未在作者表中找到", str(ctx.exception))

    def test_bad_genre_rejected(self) -> None:
        a, w, e = _fixture()
        w[0]["genre"] = "Comedy"
        with self.assertRaises(ValueError) as ctx:
            parse_rows(a, w, e)
        self.assertIn("genre", str(ctx.exception))

    def test_bad_uuid_rejected(self) -> None:
        a, w, e = _fixture()
        w[0]["id"] = "not-a-uuid"
        with self.assertRaises(ValueError) as ctx:
            parse_rows(a, w, e)
        self.assertIn("UUID", str(ctx.exception))

    def test_birth_after_death_rejected(self) -> None:
        a, w, e = _fixture()
        a[0]["birthYear"] = 2000
        a[0]["deathYear"] = 1900
        with self.assertRaises(ValueError) as ctx:
            parse_rows(a, w, e)
        self.assertIn("出生年应早于去世年", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

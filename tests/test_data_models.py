"""数据模型与导入校验测试(parse_rows)。"""

from __future__ import annotations

import unittest
import uuid

from app.data_models import find_duplicates, parse_rows


def _u() -> str:
    return str(uuid.uuid4())


def _fixture() -> tuple[list[dict], list[dict], list[dict]]:
    a1, w1, w2, e1 = _u(), _u(), _u(), _u()
    authors = [{"id": a1, "originalName": "Author A", "Name_CN": "作家甲"}]
    works = [
        {"id": w1, "language": "en", "originalTitle": "Book One", "Title_CN": "书一", "author_id": a1},
        {"id": w2, "language": "fr", "originalTitle": "Livre Deux", "Title_CN": "书二", "author_id": a1},
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
        w[0]["author_id"] = _u()  # 不存在的作者 id
        with self.assertRaises(ValueError) as ctx:
            parse_rows(a, w, e)
        self.assertIn("未在作者表中找到", str(ctx.exception))

    def test_multi_author_ids_accepted(self) -> None:
        a, w, e = _fixture()
        a2 = _u()
        a.append({"id": a2, "originalName": "Author B", "Name_CN": "作家乙"})
        w[0]["author_id"] = f"{a[0]['id']},{a2}"
        am, wm, em, work_authors = parse_rows(a, w, e)
        self.assertEqual(sorted(work_authors[w[0]["id"]]), sorted([a[0]["id"], a2]))

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

    def test_duplicate_edge_pair_rejected(self) -> None:
        a, w, e = _fixture()
        dup = dict(e[0])
        dup["id"] = str(uuid.uuid4())  # 不同 id,但同一对 source->target
        e.append(dup)
        with self.assertRaises(ValueError) as ctx:
            parse_rows(a, w, e)
        self.assertIn("涟漪对 重复", str(ctx.exception))
        self.assertIn("书一", str(ctx.exception))  # 提示用作品标题而非 UUID
        self.assertIn("书二", str(ctx.exception))

    def test_review_status_defaults_to_draft(self) -> None:
        am, wm, em, _ = parse_rows(*_fixture())
        self.assertEqual(am[0].reviewStatus, "draft")
        self.assertEqual(wm[0].reviewStatus, "draft")
        self.assertEqual(em[0].reviewStatus, "draft")

    def test_review_status_blank_value_coerced_to_draft(self) -> None:
        a, w, e = _fixture()
        w[0]["reviewStatus"] = ""  # CSV 空串 -> None 后归一为 draft
        a[0]["reviewStatus"] = None
        am, wm, em, _ = parse_rows(a, w, e)
        self.assertEqual(am[0].reviewStatus, "draft")
        self.assertEqual(wm[0].reviewStatus, "draft")

    def test_bad_language_rejected(self) -> None:
        a, w, e = _fixture()
        w[0]["language"] = "e2"  # 长度合法,但不是字母代码
        with self.assertRaises(ValueError) as ctx:
            parse_rows(a, w, e)
        self.assertIn("语言", str(ctx.exception))

    def test_empty_chinese_title_rejected(self) -> None:
        a, w, e = _fixture()
        w[0]["Title_CN"] = ""
        with self.assertRaises(ValueError):
            parse_rows(a, w, e)

    def test_empty_chinese_name_rejected(self) -> None:
        a, w, e = _fixture()
        a[0]["Name_CN"] = ""
        with self.assertRaises(ValueError):
            parse_rows(a, w, e)

    def test_empty_numeric_fields_coerced_to_none(self) -> None:
        """前端清空数字输入框会发送空串,应归一为 None 而不是 int 解析失败。"""
        a, w, e = _fixture()
        a[0]["birthYear"] = ""
        a[0]["deathYear"] = ""
        w[0]["publicationYear"] = ""
        w[0]["creationYear"] = ""
        am, wm, em, _ = parse_rows(a, w, e)
        self.assertIsNone(am[0].birthYear)
        self.assertIsNone(am[0].deathYear)
        self.assertIsNone(wm[0].publicationYear)
        self.assertIsNone(wm[0].creationYear)

    def test_text_fields_trimmed(self) -> None:
        """自由文本字段保存前应去除首尾空白与零宽/不可见字符。"""
        a, w, e = _fixture()
        a[0]["Name_CN"] = "  作家甲  "
        w[0]["Title_CN"] = "  书一\n"
        e[0]["evidence"] = "  提到《书二》\u200b  \n"
        am, wm, em, _ = parse_rows(a, w, e)
        self.assertEqual(am[0].Name_CN, "作家甲")
        self.assertEqual(wm[0].Title_CN, "书一")
        self.assertEqual(em[0].evidence, "提到《书二》")

    def test_whitespace_only_required_field_rejected(self) -> None:
        a, w, e = _fixture()
        w[0]["Title_CN"] = "   "
        with self.assertRaises(ValueError):
            parse_rows(a, w, e)

    def test_find_duplicates_reports_names_titles_and_pairs(self) -> None:
        a, w, e = _fixture()
        a.append({"id": _u(), "originalName": "  AUTHOR A  ", "Name_CN": "作家乙"})
        w.append({
            "id": _u(), "language": "en", "originalTitle": "book one",
            "Title_CN": "书一", "author_id": a[0]["id"],
        })
        e.append({"id": _u(), "source_work_id": w[0]["id"], "target_work_id": w[1]["id"], "evidence": "x"})
        report = find_duplicates(a, w, e)
        self.assertIn("Author A", report["duplicateAuthorNames"])  # 大小写归一后命中
        self.assertIn("Book One", report["duplicateWorkTitles"])
        self.assertIn("书一", report["duplicateWorkTitles"])
        self.assertEqual(len(report["duplicateEdgePairs"]), 1)
        self.assertIn("书一", report["duplicateEdgePairs"][0])
        self.assertIn("书二", report["duplicateEdgePairs"][0])

    def test_find_duplicates_ignores_same_row_and_deleted(self) -> None:
        a, w, e = _fixture()
        # 同一行内 originalName 与 Name_CN 相同不算重复
        a[0]["originalName"] = a[0]["Name_CN"] = "同名作者"
        # 软删除行不计入
        a.append({"id": _u(), "originalName": "同名作者", "Name_CN": "乙", "deletedAt": "2026-01-01T00:00:00+00:00"})
        report = find_duplicates(a, w, e)
        self.assertEqual(report["duplicateAuthorNames"], [])


if __name__ == "__main__":
    unittest.main()

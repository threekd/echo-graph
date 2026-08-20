"""data_store 基础清洗测试(clean_row / remove_invisible_chars)。"""

from __future__ import annotations

import unittest

from app.data_store import clean_row, remove_invisible_chars


class CleanRowTest(unittest.TestCase):
    def test_strips_whitespace_and_empties_to_none(self) -> None:
        row = clean_row({"name": "  张三  ", "note": "   ", "num": 5, "flag": None})
        self.assertEqual(row["name"], "张三")
        self.assertIsNone(row["note"])
        self.assertEqual(row["num"], 5)
        self.assertIsNone(row["flag"])

    def test_removes_zero_width_and_invisible_chars(self) -> None:
        row = clean_row({
            "evidence": "《瓦尔登湖》\u200b。\u200c文\u2060本",
            "title": "\ufeff标题\u200b",
        })
        self.assertEqual(row["evidence"], "《瓦尔登湖》。文本")
        self.assertEqual(row["title"], "标题")

    def test_invisible_only_becomes_none(self) -> None:
        self.assertIsNone(clean_row({"note": "\u200b\u200b"})["note"])

    def test_preserves_internal_spaces_and_newlines(self) -> None:
        row = clean_row({"evidence": "第一行\n第二行  继续"})
        self.assertEqual(row["evidence"], "第一行\n第二行  继续")

    def test_remove_invisible_chars_idempotent(self) -> None:
        self.assertEqual(remove_invisible_chars("\u200babc\u200b"), "abc")
        self.assertEqual(remove_invisible_chars(remove_invisible_chars("\u200babc\u200b")), "abc")


if __name__ == "__main__":
    unittest.main()

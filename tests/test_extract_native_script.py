"""原文名/原著标题「对应国籍/语言」文字一致性检查的单测。

对应 app/ai_assistant/tools/extract_source_book.py 的 check_native_script:
非拉丁文字系统的国籍/语言,原文名/原著标题应使用其原文字,拉丁转写应告警。
"""

from __future__ import annotations

import unittest

from app.ai_assistant.tools.extract_source_book import check_native_script


class NativeScriptCheckTest(unittest.TestCase):
    def test_russian_author_cyrillic_name_passes(self) -> None:
        result = {
            "authors": [{"originalName": "Лев Толстой", "nationality": "RU"}],
            "work": {},
            "ripples": [],
        }
        self.assertEqual(check_native_script(result), [])

    def test_russian_author_latin_transliteration_warns(self) -> None:
        result = {
            "authors": [{"originalName": "Leo Tolstoy", "nationality": "RU"}],
            "work": {},
            "ripples": [],
        }
        warnings = check_native_script(result)
        self.assertEqual(len(warnings), 1)
        self.assertIn("作者原文名", warnings[0])

    def test_japanese_work_kana_title_passes(self) -> None:
        result = {
            "authors": [],
            "work": {"language": "ja", "originalTitle": "ノルウェイの森"},
            "ripples": [],
        }
        self.assertEqual(check_native_script(result), [])

    def test_japanese_work_english_title_warns(self) -> None:
        result = {
            "authors": [],
            "work": {"language": "ja", "originalTitle": "Norwegian Wood"},
            "ripples": [],
        }
        warnings = check_native_script(result)
        self.assertEqual(len(warnings), 1)
        self.assertIn("作品原著标题", warnings[0])

    def test_ripple_work_title_checked(self) -> None:
        result = {
            "authors": [],
            "work": {},
            "ripples": [
                {"work": {"language": "ru", "originalTitle": "The Brothers Karamazov"}}
            ],
        }
        warnings = check_native_script(result)
        self.assertEqual(len(warnings), 1)
        self.assertIn("涟漪作品原著标题", warnings[0])

    def test_latin_script_languages_never_warn(self) -> None:
        result = {
            "authors": [{"originalName": "Ernest Hemingway", "nationality": "US"}],
            "work": {"language": "en", "originalTitle": "The Old Man and the Sea"},
            "ripples": [],
        }
        self.assertEqual(check_native_script(result), [])

    def test_null_or_unknown_fields_skipped(self) -> None:
        result = {
            "authors": [{"originalName": None, "nationality": None}],
            "work": {"language": None, "originalTitle": None},
            "ripples": [],
        }
        self.assertEqual(check_native_script(result), [])

    def test_lowercase_language_code_also_warns(self) -> None:
        # 语言码/国籍码大小写容错:小写 ru 也应触发告警
        result = {
            "authors": [],
            "work": {"language": "ru", "originalTitle": "War and Peace"},
            "ripples": [],
        }
        self.assertTrue(check_native_script(result))

    def test_short_latin_token_not_warned(self) -> None:
        # 短拉丁词/符号(如 1Q84)可能是原著真名,不告警
        result = {
            "authors": [],
            "work": {"language": "ja", "originalTitle": "1Q84"},
            "ripples": [],
        }
        self.assertEqual(check_native_script(result), [])
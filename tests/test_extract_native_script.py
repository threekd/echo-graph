"""原文名/原著标题「对应国籍/语言」文字一致性检查的单测。

对应 app/ai_assistant/tools/extract_source_book.py 的 check_native_script:
非拉丁文字系统的国籍/语言,原文名/原著标题应使用其原文字,拉丁转写应告警。
"""

from __future__ import annotations

import unittest

from app.ai_assistant.tools.extract_source_book import (
    check_native_script,
    classify_ripples,
    normalize_skipped,
)


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


class NormalizeSkippedTest(unittest.TestCase):
    """normalize_skipped:RIPPLE skipped 归一化为 {分类: [明细条目]}。"""

    def test_normalizes_item_lists(self) -> None:
        raw = {
            "non_books": [{"title": "贼喜鹊", "reason": "歌剧序曲"}],
            "ambiguous": [],
            "self_or_unknown": [{"title": "三体", "reason": "自我提及"}],
            "out_of_body": [{"title": "白鲸", "reason": "译者序"}],
        }
        out = normalize_skipped(raw)
        self.assertEqual(len(out["non_books"]), 1)
        self.assertEqual(out["non_books"][0]["title"], "贼喜鹊")
        self.assertEqual(out["ambiguous"], [])
        self.assertEqual(len(out["self_or_unknown"]), 1)

    def test_handles_malformed_or_missing(self) -> None:
        """计数(旧格式)/缺键/非 dict 条目 → 空数组兜底,四键齐全。"""
        self.assertEqual(normalize_skipped({"non_books": 3})["non_books"], [])
        self.assertEqual(normalize_skipped({})["out_of_body"], [])
        self.assertEqual(normalize_skipped(None)["ambiguous"], [])
        out = normalize_skipped({"non_books": ["string", {"title": "x", "reason": "y"}]})
        self.assertEqual(len(out["non_books"]), 1)  # 只保留 dict 条目
        self.assertEqual(
            set(normalize_skipped({}).keys()),
            {
                "non_books",
                "ambiguous",
                "self_or_unknown",
                "out_of_body",
                "low_confidence",
            },
        )


class ClassifyRipplesTest(unittest.TestCase):
    """classify_ripples:按 confidence 三档分流(高接受/低跳过/中间二次判定)。"""

    def _ripple(self, title: str = "罗亭", confidence: float | None = 0.9) -> dict:
        ripple = {
            "work": {"Title_CN": title, "originalTitle": "Рудин"},
            "evidence": {"evidence": "书中提到了《罗亭》。", "evidenceSource": "15章"},
        }
        if confidence is not None:
            ripple["confidence"] = confidence
        return ripple

    def test_high_confidence_accepted_without_confirm(self) -> None:
        called: list = []

        def confirm(_r) -> bool:
            called.append(True)
            return True

        accepted, skipped = classify_ripples(
            {"ripples": [self._ripple(confidence=0.9)]}, confirm
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(skipped, [])
        self.assertEqual(called, [])

    def test_low_confidence_skipped_without_confirm(self) -> None:
        called: list = []
        accepted, skipped = classify_ripples(
            {"ripples": [self._ripple(confidence=0.2)]}, lambda _r: called.append(True) or True
        )
        self.assertEqual(accepted, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("置信度", skipped[0]["reason"])
        self.assertEqual(skipped[0]["title"], "罗亭")
        self.assertEqual(called, [])

    def test_mid_confidence_confirm_accept(self) -> None:
        accepted, skipped = classify_ripples(
            {"ripples": [self._ripple(confidence=0.6)]}, lambda _r: True
        )
        self.assertEqual(len(accepted), 1)
        self.assertTrue(accepted[0]["_confirmed"])  # 二次判定通过标记
        self.assertEqual(skipped, [])

    def test_mid_confidence_confirm_reject(self) -> None:
        accepted, skipped = classify_ripples(
            {"ripples": [self._ripple(confidence=0.6)]}, lambda _r: False
        )
        self.assertEqual(accepted, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("二次判定未通过", skipped[0]["reason"])

    def test_missing_confidence_triggers_confirm(self) -> None:
        accepted, skipped = classify_ripples(
            {"ripples": [self._ripple(confidence=None)]}, lambda _r: True
        )
        self.assertEqual(len(accepted), 1)
        self.assertTrue(accepted[0]["_confirmed"])
        self.assertEqual(skipped, [])

    def test_malformed_entry_skipped(self) -> None:
        accepted, skipped = classify_ripples(
            {"ripples": ["not-a-dict"]}, lambda _r: True
        )
        self.assertEqual(accepted, [])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["title"], "?")

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

"""dedupe_check LLM 兜底确认单测:置信度解析 / possible 升级 / 失败保底 / 管线传导。

对应 app/ai_assistant/tools/dedupe_check.py 的 llm_duplicate_confidence /
_maybe_llm_confirm / run_dedupe(llm_confirm) 与
review_publish.build_dedupe_info 的 LLM 升级传导。
全部 mock 掉 LLM 与 embedding 接口,不发真实网络请求。
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db_sqlite
from app.ai_assistant.tools import dedupe_check, review_publish


class _FakeChoice:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content})()


class _FakeResp:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content: str):
        self._content = content

    def create(self, **kwargs):
        return _FakeResp(self._content)


class _FakeClient:
    def __init__(self, content: str):
        self.chat = type("C", (), {"completions": _FakeCompletions(content)})()


class LLMConfidenceParseTest(unittest.TestCase):
    """llm_duplicate_confidence 的响应解析。"""

    def test_valid_outputs(self) -> None:
        cases = {
            "0.85": 0.85,
            " 0.9 ": 0.9,
            "1": 1.0,
            "0": 0.0,
            ".75": 0.75,
            "0.5\n": 0.5,
        }
        for raw, expected in cases.items():
            conf = dedupe_check.llm_duplicate_confidence(
                _FakeClient(raw), "deepseek-v4-flash", "作品", "A", "B"
            )
            self.assertEqual(conf, expected, raw)

    def test_invalid_outputs_none(self) -> None:
        for raw in ["", "是的，同一本书", "2.0", "-0.1", "abc"]:
            conf = dedupe_check.llm_duplicate_confidence(
                _FakeClient(raw), "deepseek-v4-flash", "作品", "A", "B"
            )
            self.assertIsNone(conf, raw)

    def test_api_exception_returns_none(self) -> None:
        class _Broken:
            def create(self, **kwargs):
                raise RuntimeError("boom")

        class _BrokenChat:
            completions = _Broken()

        class _BrokenClient:
            chat = _BrokenChat()

        conf = dedupe_check.llm_duplicate_confidence(
            _BrokenClient(), "deepseek-v4-flash", "作品", "A", "B"
        )
        self.assertIsNone(conf)


class MaybeLLMConfirmTest(unittest.TestCase):
    """_maybe_llm_confirm 的判定升级逻辑。"""

    BASE_BASIC = {"level": "contained", "score": 0.7, "existing": {"id": "w-1", "Title_CN": "三体"}}

    def _run(self, conf, decision="possible", reason="基础匹配:contained"):
        with patch.object(
            dedupe_check, "llm_duplicate_confidence", return_value=conf
        ) as mock_conf:
            out = dedupe_check._maybe_llm_confirm(
                object(), "deepseek-v4-flash", "作品",
                {"Title_CN": "三体（全集）", "originalTitle": "三体（全集）"},
                self.BASE_BASIC, None, dedupe_check._work_compare_text,
                decision, reason,
            )
        return out, mock_conf

    def test_high_conf_upgrades_to_duplicate(self) -> None:
        (decision, reason, info), mock_conf = self._run(0.9)
        self.assertEqual(decision, "likely_duplicate")
        self.assertIn("LLM 确认", reason)
        self.assertEqual(info["confidence"], 0.9)
        self.assertEqual(info["existing_id"], "w-1")
        mock_conf.assert_called_once()

    def test_low_conf_keeps_possible(self) -> None:
        (decision, reason, info), _ = self._run(0.5)
        self.assertEqual(decision, "possible")
        self.assertIn("非重复", reason)
        self.assertEqual(info["confidence"], 0.5)

    def test_exact_threshold_not_upgrade(self) -> None:
        (decision, _, _), _ = self._run(0.8)  # 需求是严格 >0.8 才升级
        self.assertEqual(decision, "possible")

    def test_failure_keeps_possible_unchanged(self) -> None:
        (decision, reason, info), _ = self._run(None)
        self.assertEqual(decision, "possible")
        self.assertEqual(reason, "基础匹配:contained")
        self.assertIsNone(info["confidence"])

    def test_likely_decision_skips_llm(self) -> None:
        (decision, _, info), mock_conf = self._run(0.99, decision="likely_duplicate")
        mock_conf.assert_not_called()
        self.assertIsNone(info)
        self.assertEqual(decision, "likely_duplicate")


class RunDedupeLLMTest(unittest.TestCase):
    """run_dedupe 集成:LLM 升级落报告并传导到 review_publish。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "llm.db"
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            db_sqlite._migrate(conn)
            conn.execute(
                "INSERT INTO works (id, language, originalTitle, Title_CN, reviewStatus)"
                " VALUES ('w-1', 'zh', '三体', '三体', 'reviewed')"
            )
            conn.commit()
        finally:
            conn.close()

    def test_possible_work_upgraded_and_propagates(self) -> None:
        cand = [{"Title_CN": "三体（全集）", "originalTitle": "三体（全集）"}]
        with (
            patch.object(dedupe_check, "_load_aliyun", side_effect=RuntimeError("no aliyun")),
            patch.object(
                dedupe_check, "_load_deepseek", return_value=(object(), "deepseek-v4-flash")
            ),
            patch.object(dedupe_check, "llm_duplicate_confidence", return_value=0.93),
        ):
            report = dedupe_check.run_dedupe(cand, [], db_path=str(self.db_path))
        entry = report["works"][0]
        self.assertEqual(entry["decision"], "likely_duplicate")
        self.assertIn("LLM 确认", entry["reason"])
        self.assertEqual(entry["llm"]["confidence"], 0.93)
        self.assertEqual(entry["llm"]["existing_id"], "w-1")
        self.assertTrue(report["llm_confirm"]["enabled"])

        public = {
            "works": [
                {"id": "w-1", "Title_CN": "三体", "originalTitle": "三体", "author_names": "刘慈欣"}
            ],
            "authors": [],
        }
        dedupe = review_publish.build_dedupe_info("work", cand[0], entry, public)
        self.assertEqual(dedupe["decision"], "likely_duplicate")
        self.assertEqual(dedupe["existing_id"], "w-1")
        self.assertEqual(dedupe["default_action"], "reuse")

    def test_llm_confirm_disabled_keeps_possible(self) -> None:
        cand = [{"Title_CN": "三体（全集）", "originalTitle": "三体（全集）"}]
        with (
            patch.object(dedupe_check, "_load_aliyun", side_effect=RuntimeError("no aliyun")),
            patch.object(
                dedupe_check, "_load_deepseek", return_value=(object(), "deepseek-v4-flash")
            ),
            patch.object(dedupe_check, "llm_duplicate_confidence", return_value=0.99) as mock_conf,
        ):
            report = dedupe_check.run_dedupe(
                cand, [], db_path=str(self.db_path), llm_confirm=False
            )
        self.assertEqual(report["works"][0]["decision"], "possible")
        mock_conf.assert_not_called()

    def test_basic_only_never_loads_deepseek(self) -> None:
        with patch.object(dedupe_check, "_load_deepseek") as mock_ds:
            dedupe_check.run_dedupe([], [], db_path=str(self.db_path), basic_only=True)
        mock_ds.assert_not_called()

    def test_llm_target_outside_public_space_ignored(self) -> None:
        entry = {
            "llm": {"confidence": 0.95, "existing_id": "w-private"},
            "basic": {"level": "contained", "existing": {"id": "w-private"}},
            "semantic": None,
        }
        public = {
            "works": [{"id": "w-1", "Title_CN": "三体", "originalTitle": "三体"}],
            "authors": [],
        }
        dedupe = review_publish.build_dedupe_info(
            "work", {"Title_CN": "三体（全集）"}, entry, public
        )
        self.assertEqual(dedupe["decision"], "possible")


if __name__ == "__main__":
    unittest.main()

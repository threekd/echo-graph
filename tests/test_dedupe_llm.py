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

from app import auth, db_sqlite
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
        patcher = patch.object(db_sqlite, "DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        email_patcher = patch.object(auth, "BOOTSTRAP_EMAIL", "admin@test.local")
        email_patcher.start()
        self.addCleanup(email_patcher.stop)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            db_sqlite._migrate(conn)
            admin_id = db_sqlite.new_uuid()
            conn.execute(
                "INSERT INTO users (id, email, username, password_hash, role, status,"
                " space_visibility) VALUES (?, 'admin@test.local', 'admin01', 'x',"
                " 'admin', 'active', 'public')",
                (admin_id,),
            )
            conn.execute(
                "INSERT INTO works (id, language, originalTitle, Title_CN, reviewStatus, owner_id)"
                " VALUES ('w-1', 'zh', '三体', '三体', 'reviewed', ?)",
                (admin_id,),
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


class UserScopeDedupeTest(unittest.TestCase):
    """判重目标严格按用户个人空间:其他用户空间的行不参与。"""

    ADMIN = "boss@test.local"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "scope.db"
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            db_sqlite._migrate(conn)
        finally:
            conn.close()
        self.patch_db = patch.object(db_sqlite, "DB_PATH", self.db_path)
        self.patch_db.start()
        self.addCleanup(self.patch_db.stop)
        self.patch_email = patch.object(auth, "BOOTSTRAP_EMAIL", self.ADMIN)
        self.patch_email.start()
        self.addCleanup(self.patch_email.stop)
        self.admin = auth.register(self.ADMIN, "admin-password-123", username="admin")
        self.user_a = auth.register("a@test.local", "password123", username="usera")
        self.user_b = auth.register("b@test.local", "password123", username="userb")

    def _seed_work(self, owner_id: str | None, title: str = "三体") -> None:
        now = db_sqlite.now_iso()
        with db_sqlite._db() as conn:
            conn.execute(
                "INSERT INTO works (id, language, originalTitle, Title_CN, reviewStatus,"
                " created_by, owner_id, createdAt, updatedAt)"
                " VALUES (?, 'zh', ?, ?, 'reviewed', 'curated', ?, ?, ?)",
                (db_sqlite.new_uuid(), title, title, owner_id, now, now),
            )

    def test_run_dedupe_only_sees_target_user_space(self) -> None:
        """《三体》只在 user_b 空间:对 user_a 判重无命中,对 user_b 判重 exact。"""
        self._seed_work(self.user_b["id"])
        cand = [{"Title_CN": "三体", "originalTitle": "三体"}]
        report_a = dedupe_check.run_dedupe(
            cand, [], db_path=str(self.db_path), user_id=self.user_a["id"],
            basic_only=True, llm_confirm=False,
        )
        report_b = dedupe_check.run_dedupe(
            cand, [], db_path=str(self.db_path), user_id=self.user_b["id"],
            basic_only=True, llm_confirm=False,
        )
        self.assertEqual(report_a["works"][0]["basic"]["level"], "none")
        self.assertEqual(report_b["works"][0]["basic"]["level"], "exact")

    def test_dedupe_entity_work_basic(self) -> None:
        """统一入口 dedupe_entity:work 基础匹配 + 自动复用判定。"""
        self._seed_work(self.admin["id"])  # admin 个人空间即公共星云
        entry = dedupe_check.dedupe_entity(
            "work",
            {"Title_CN": "三体", "originalTitle": "三体"},
            user_id=self.admin["id"],
            db_path=str(self.db_path),
            use_semantic=False,
            use_llm=False,
        )
        self.assertEqual(entry["basic"]["level"], "exact")
        self.assertEqual(entry["decision"], "likely_duplicate")

    def test_dedupe_entity_admin_space(self) -> None:
        """admin 判重目标 = 自己空间(官方图谱),与普通用户口径一致。"""
        self._seed_work(self.admin["id"])
        entry = dedupe_check.dedupe_entity(
            "work",
            {"Title_CN": "三体", "originalTitle": "三体"},
            user_id=self.admin["id"],
            db_path=str(self.db_path),
            use_semantic=False,
            use_llm=False,
        )
        self.assertEqual(entry["basic"]["level"], "exact")


if __name__ == "__main__":
    unittest.main()

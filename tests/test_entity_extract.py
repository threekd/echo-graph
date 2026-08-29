"""entity_extract 单测:单实体 LLM 补全的载荷构造、输出清洗与错误路径。

对应 app/ai_assistant/tools/entity_extract.py:
- build_author_payload / build_work_payload 只携带非空输入,空输入抛 ValueError;
- extract_author / extract_work 调用对应提示词并清洗输出(白名单字段 + 去 None)。
mock llm_client(不触网),验证发送给 LLM 的载荷与提示词选择。
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.ai_assistant import prompts
from app.ai_assistant.tools import entity_extract


class EnrichRippleAuthorsTest(unittest.TestCase):
    """enrich_ripple_authors:涟漪作者补全并存入 extract["ripple_authors"] 候选。"""

    def setUp(self) -> None:
        self.extract = {
            "source_book": {"title": "X", "authors": ["源书作者"], "language": "zh"},
            "authors": [{"originalName": "源书作者", "Name_CN": "源书作者"}],
            "work": {"Title_CN": "X"},
            "ripples": [
                {
                    "work": {
                        "Title_CN": "白鲸",
                        "originalTitle": "Moby-Dick",
                        "language": "en",
                        "author": "赫尔曼·梅尔维尔",
                    },
                    "evidence": {"evidence": "e1"},
                },
                {
                    "work": {
                        "Title_CN": "白鲸2",
                        "author": "赫尔曼·梅尔维尔",
                    },
                    "evidence": {"evidence": "e2"},
                },
                {
                    "work": {
                        "Title_CN": "无作者书",
                    },
                    "evidence": {"evidence": "e3"},
                },
            ],
        }
        self.enriched = {
            "originalName": "Herman Melville",
            "Name_CN": "赫尔曼·梅尔维尔",
            "Name_EN": "Herman Melville",
            "nationality": "US",
            "birthYear": 1819,
            "deathYear": 1891,
            "note": "美国小说家。",
        }

    def test_enrich_writes_author_info_and_candidates(self) -> None:
        """补全结果写回涟漪 author_info,并存入 extract["ripple_authors"] 候选(同名去重)。"""
        captured: dict = {}

        def fake_extract_author(**kwargs):
            captured.update(kwargs)
            return dict(self.enriched)

        with patch.object(entity_extract, "extract_author", side_effect=fake_extract_author), \
             patch.object(entity_extract, "resolve_work_author", return_value={}):
            n = entity_extract.enrich_ripple_authors(self.extract)

        self.assertEqual(n, 1)  # 两个同名涟漪作者只补全一次? -> 见断言
        # 第一个涟漪写入 author_info;第二个涟漪因同名作者已补全(跳过重复调用) -> 见下
        w0 = self.extract["ripples"][0]["work"]
        self.assertEqual(w0["author_info"]["nationality"], "US")
        # 作品信息作为作者身份参考一并传入(消歧线索)
        self.assertEqual(captured["name_cn"], "赫尔曼·梅尔维尔")
        self.assertEqual(captured["work_title"], "白鲸")
        self.assertEqual(captured["work_original_title"], "Moby-Dick")
        self.assertEqual(captured["work_language"], "en")
        # 涟漪作者单独存放,不再混入源书作者 extract["authors"]
        self.assertEqual([a["Name_CN"] for a in self.extract["authors"]], ["源书作者"])
        names = [a["Name_CN"] for a in self.extract["ripple_authors"]]
        self.assertEqual(names.count("赫尔曼·梅尔维尔"), 1)

    def test_enrich_skips_work_fields_when_absent(self) -> None:
        """涟漪作品只有作者名、无标题/语言时,补全调用传入空作品字段
        (build_author_payload 会在载荷层过滤,实际发给 LLM 的 JSON 不含 work_*)。"""
        captured: dict = {}

        def fake_extract_author(**kwargs):
            captured.update(kwargs)
            return dict(self.enriched)

        self.extract["ripples"][0]["work"] = {"author": "赫尔曼·梅尔维尔"}
        with patch.object(entity_extract, "extract_author", side_effect=fake_extract_author), \
             patch.object(entity_extract, "resolve_work_author", return_value={}):
            entity_extract.enrich_ripple_authors(self.extract)
        self.assertEqual(captured["name_cn"], "赫尔曼·梅尔维尔")
        self.assertIsNone(captured["work_title"])
        self.assertIsNone(captured["work_original_title"])
        self.assertIsNone(captured["work_language"])

    def test_skip_when_no_author_or_already_enriched(self) -> None:
        """已补全跳过;作者名缺失时走作品→作者解析(解析无果不计入)。"""
        # 模拟第一次 enrich 后的状态:author_info 已写回 + 补全作者已存入 ripple_authors
        self.extract["ripples"][0]["work"]["author_info"] = dict(self.enriched)
        self.extract.setdefault("ripple_authors", []).append(dict(self.enriched))
        with patch.object(entity_extract, "extract_author", return_value=dict(self.enriched)) as m, \
             patch.object(entity_extract, "resolve_work_author", return_value={}) as mr:
            n = entity_extract.enrich_ripple_authors(self.extract)
        self.assertEqual(n, 0)
        m.assert_not_called()
        mr.assert_called()  # 无作者书(ripples[2])走作品→作者解析

    def test_enrich_resolves_author_when_missing(self) -> None:
        """涟漪作品作者名为空时,用作品信息反向解析作者(resolve_work_author)。"""
        self.extract["ripples"] = [self.extract["ripples"][0]]
        self.extract["ripples"][0]["work"]["author"] = None
        resolved = dict(self.enriched)
        with patch.object(
            entity_extract, "resolve_work_author", return_value=resolved
        ) as m:
            n = entity_extract.enrich_ripple_authors(self.extract)
        self.assertEqual(n, 1)
        m.assert_called_once()
        kwargs = m.call_args.kwargs
        self.assertEqual(kwargs["work_title"], "白鲸")
        self.assertEqual(kwargs["work_original_title"], "Moby-Dick")
        self.assertEqual(kwargs["work_language"], "en")
        self.assertEqual(self.extract["ripples"][0]["work"]["author_info"], resolved)


class EntityExtractTest(unittest.TestCase):

    def _patch_llm(self, content: str):
        """同时 patch 客户端三件套,让 extract_* 走假 LLM。"""
        return [
            patch.object(entity_extract.llm_client, "load_environment", return_value=("k", "u")),
            patch.object(entity_extract.llm_client, "create_client", return_value=object()),
            patch.object(entity_extract.llm_client, "stream_completion", return_value=(content, "")),
        ]

    def test_extract_author_payload_and_prompt(self) -> None:
        """只传 name_cn/name_en:载荷不含空字段,使用 ENTITY_AUTHOR_SYSTEM_PROMPT。"""
        captured: dict = {}

        def fake_stream(client, messages, **kwargs):
            captured["system"] = messages[0]["content"]
            captured["payload"] = json.loads(messages[1]["content"])
            return (
                '{"originalName":"村上春樹","Name_CN":"村上春树","Name_EN":"Haruki Murakami",'
                '"nationality":"JP","birthYear":1949,"deathYear":null,"note":"日本小说家。"}',
                "",
            )

        with patch.object(entity_extract.llm_client, "load_environment", return_value=("k", "u")),              patch.object(entity_extract.llm_client, "create_client", return_value=object()),              patch.object(entity_extract.llm_client, "stream_completion", side_effect=fake_stream):
            result = entity_extract.extract_author(name_cn="村上春树", name_en="Haruki Murakami")

        self.assertEqual(captured["system"], prompts.ENTITY_AUTHOR_SYSTEM_PROMPT)
        self.assertEqual(captured["payload"], {"name_cn": "村上春树", "name_en": "Haruki Murakami"})
        self.assertEqual(result["Name_CN"], "村上春树")
        self.assertEqual(result["nationality"], "JP")

    def test_extract_author_payload_includes_work_ref(self) -> None:
        """传入作品参考时,载荷包含 work_* 字段(供模型消歧同名作者)。"""
        captured: dict = {}

        def fake_stream(client, messages, **kwargs):
            captured["payload"] = json.loads(messages[1]["content"])
            return (
                '{"originalName":"Herman Melville","Name_CN":"赫尔曼·梅尔维尔",'
                '"Name_EN":"Herman Melville","nationality":"US","birthYear":1819,'
                '"deathYear":1891,"note":"美国小说家。"}',
                "",
            )

        with patch.object(entity_extract.llm_client, "load_environment", return_value=("k", "u")), \
             patch.object(entity_extract.llm_client, "create_client", return_value=object()), \
             patch.object(entity_extract.llm_client, "stream_completion", side_effect=fake_stream):
            result = entity_extract.extract_author(
                name_cn="赫尔曼·梅尔维尔",
                work_title="白鲸",
                work_original_title="Moby-Dick",
                work_language="en",
            )

        self.assertEqual(
            captured["payload"],
            {
                "name_cn": "赫尔曼·梅尔维尔",
                "work_title": "白鲸",
                "work_original_title": "Moby-Dick",
                "work_language": "en",
            },
        )
        self.assertEqual(result["nationality"], "US")

    def test_extract_work_payload_and_prompt(self) -> None:
        """作品补全:载荷含标题与作者,使用 ENTITY_WORK_SYSTEM_PROMPT。"""
        captured: dict = {}

        def fake_stream(client, messages, **kwargs):
            captured["system"] = messages[0]["content"]
            captured["payload"] = json.loads(messages[1]["content"])
            return (
                '{"language":"ja","originalTitle":"ノルウェイの森","Title_CN":"挪威的森林",'
                '"Title_EN":"Norwegian Wood","Title_Other":null,"publicationYear":1987,'
                '"genre":"Fiction","note":"代表作。"}',
                "",
            )

        with patch.object(entity_extract.llm_client, "load_environment", return_value=("k", "u")),              patch.object(entity_extract.llm_client, "create_client", return_value=object()),              patch.object(entity_extract.llm_client, "stream_completion", side_effect=fake_stream):
            result = entity_extract.extract_work(title_cn="挪威的森林", author="村上春树")

        self.assertEqual(captured["system"], prompts.ENTITY_WORK_SYSTEM_PROMPT)
        self.assertEqual(captured["payload"], {"title_cn": "挪威的森林", "author": "村上春树"})
        self.assertEqual(result["language"], "ja")
        self.assertEqual(result["originalTitle"], "ノルウェイの森")

    def test_resolve_work_author_payload_and_prompt(self) -> None:
        """作品作者解析:载荷含作品字段,使用 ENTITY_WORK_AUTHOR_SYSTEM_PROMPT。"""
        captured: dict = {}

        def fake_stream(client, messages, **kwargs):
            captured["system"] = messages[0]["content"]
            captured["payload"] = json.loads(messages[1]["content"])
            return (
                '{"originalName":"Norman MacKenzie and Jeanne MacKenzie",'
                '"Name_CN":"诺曼·麦肯齐、珍妮·麦肯齐",'
                '"Name_EN":"Norman and Jeanne MacKenzie","nationality":"GB",'
                '"birthYear":null,"deathYear":null,"note":"传记作者。"}',
                "",
            )

        with patch.object(entity_extract.llm_client, "load_environment", return_value=("k", "u")), \
             patch.object(entity_extract.llm_client, "create_client", return_value=object()), \
             patch.object(entity_extract.llm_client, "stream_completion", side_effect=fake_stream):
            result = entity_extract.resolve_work_author(
                work_title="时间旅人",
                work_original_title="The Time Traveller: The Life of H. G. Wells",
                work_language="en",
                work_genre="Non-fiction",
                work_note="H·G·威尔斯的传记",
            )

        self.assertEqual(captured["system"], prompts.ENTITY_WORK_AUTHOR_SYSTEM_PROMPT)
        self.assertEqual(captured["payload"]["work_title"], "时间旅人")
        self.assertEqual(captured["payload"]["work_original_title"], "The Time Traveller: The Life of H. G. Wells")
        self.assertEqual(captured["payload"]["work_language"], "en")
        self.assertEqual(result["Name_CN"], "诺曼·麦肯齐、珍妮·麦肯齐")
        self.assertEqual(result["nationality"], "GB")
        self.assertNotIn("Title_CN", result)  # 白名单清洗,不含作品字段

    def test_resolve_work_author_requires_title(self) -> None:
        with self.assertRaises(ValueError):
            entity_extract.resolve_work_author(work_language="en")

    def test_output_cleaned_to_whitelist(self) -> None:
        """LLM 返回多余字段 / None:只保留白名单非空字段。"""
        raw = (
            '{"originalName":"Лев Толстой","Name_CN":"列夫·托尔斯泰","Name_EN":"Leo Tolstoy",'
            '"nationality":"RU","birthYear":1828,"deathYear":1910,"note":"俄国作家。",'
            '"hacker_field":"x","Title_CN":"越权字段"}'
        )
        with patch.object(entity_extract.llm_client, "load_environment", return_value=("k", "u")), \
             patch.object(entity_extract.llm_client, "create_client", return_value=object()), \
             patch.object(entity_extract.llm_client, "stream_completion", return_value=(raw, "")):
            result = entity_extract.extract_author(name_cn="列夫·托尔斯泰")
        self.assertNotIn("hacker_field", result)
        self.assertNotIn("Title_CN", result)
        self.assertEqual(result["birthYear"], 1828)

    def test_author_without_input_raises(self) -> None:
        with self.assertRaises(ValueError):
            entity_extract.build_author_payload()

    def test_work_without_title_raises(self) -> None:
        """只有 author 没有标题:拒绝(标题才是作品识别的必需输入)。"""
        with self.assertRaises(ValueError):
            entity_extract.build_work_payload(author="村上春树")

    def test_payload_ignores_blank_inputs(self) -> None:
        payload = entity_extract.build_author_payload(
            name_cn="  村上春树  ", name_en="", work_title="  ", work_language=None
        )
        self.assertEqual(payload, {"name_cn": "村上春树"})


if __name__ == "__main__":
    unittest.main()

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
        with patch.object(
            entity_extract, "extract_author", return_value=dict(self.enriched)
        ):
            n = entity_extract.enrich_ripple_authors(self.extract)

        self.assertEqual(n, 1)  # 两个同名涟漪作者只补全一次? -> 见断言
        # 第一个涟漪写入 author_info;第二个涟漪因同名作者已补全(跳过重复调用) -> 见下
        w0 = self.extract["ripples"][0]["work"]
        self.assertEqual(w0["author_info"]["nationality"], "US")
        # 涟漪作者单独存放,不再混入源书作者 extract["authors"]
        self.assertEqual([a["Name_CN"] for a in self.extract["authors"]], ["源书作者"])
        names = [a["Name_CN"] for a in self.extract["ripple_authors"]]
        self.assertEqual(names.count("赫尔曼·梅尔维尔"), 1)

    def test_skip_when_no_author_or_already_enriched(self) -> None:
        """空作者跳过;已补全(重复运行)不再调用 LLM。"""
        # 模拟第一次 enrich 后的状态:author_info 已写回 + 补全作者已存入 ripple_authors
        self.extract["ripples"][0]["work"]["author_info"] = dict(self.enriched)
        self.extract.setdefault("ripple_authors", []).append(dict(self.enriched))
        with patch.object(entity_extract, "extract_author", return_value=dict(self.enriched)) as m:
            n = entity_extract.enrich_ripple_authors(self.extract)
        self.assertEqual(n, 0)
        m.assert_not_called()


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
        payload = entity_extract.build_author_payload(name_cn="  村上春树  ", name_en="")
        self.assertEqual(payload, {"name_cn": "村上春树"})


if __name__ == "__main__":
    unittest.main()

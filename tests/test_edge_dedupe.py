"""涟漪(edge)去重检查单测:候选收集、基础匹配、批内合并、自我提及跳过。

对应:
- app/ai_assistant/tools/dedupe_check.py 的 collect_edge_candidates_from_extract /
  basic_match_edge / run_dedupe(edge_cands)
- app/ai_assistant/tools/review_publish.py 的 _add_edge_item(批内去重 + SKIPPED)
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import auth, data_store, db_sqlite
from app.ai_assistant.tools import dedupe_check, llm_space, review_publish
from tests._helpers import rewrite_all

_ADMIN_EMAIL = "admin@echo.local"


def _existing_edges() -> list[dict]:
    return [
        {
            "id": "e-1",
            "source_work_id": "w-src",
            "target_work_id": "w-tgt",
            "evidenceSource": "第一章",
            "src_Title_CN": "且听风吟",
            "src_originalTitle": "風の歌を聴け",
            "src_Title_EN": "Hear the Wind Sing",
            "src_Title_Other": None,
            "tgt_Title_CN": "挪威的森林",
            "tgt_originalTitle": "ノルウェイの森",
            "tgt_Title_EN": "Norwegian Wood",
            "tgt_Title_Other": None,
        }
    ]


def _extract_with_ripples() -> dict:
    """源书 + 两条指向同一作品的涟漪(模拟 LLM 未合并的重复提及)。"""
    return {
        "source_book": {"title": "且听风吟", "authors": ["村上春树"], "language": "zh"},
        "authors": [
            {"originalName": "村上春樹", "Name_CN": "村上春树", "Name_EN": "Haruki Murakami"}
        ],
        "work": {
            "language": "ja",
            "originalTitle": "風の歌を聴け",
            "Title_CN": "且听风吟",
            "Title_EN": "Hear the Wind Sing",
        },
        "ripples": [
            {
                "work": {
                    "language": "ja",
                    "originalTitle": "ノルウェイの森",
                    "Title_CN": "挪威的森林",
                    "Title_EN": "Norwegian Wood",
                    "author": "村上春树",
                },
                "evidence": {
                    "evidence": "第一章提到挪威的森林。",
                    "evidenceSource": "第一章",
                    "mention_type": "正文",
                },
            },
            {
                "work": {
                    "language": "ja",
                    "originalTitle": "ノルウェイの森",
                    "Title_CN": "挪威的森林",
                    "Title_EN": "Norwegian Wood",
                    "author": "村上春树",
                },
                "evidence": {
                    "evidence": "第三章再次提到挪威的森林。",
                    "evidenceSource": "第三章",
                    "mention_type": "正文",
                },
            },
        ],
    }


class EdgeMatchTest(unittest.TestCase):
    """基础匹配 / 候选收集(不依赖数据库)。"""

    def test_exact_match_both_ends(self) -> None:
        cand = {
            "source": {"Title_CN": "且听风吟", "originalTitle": "風の歌を聴け"},
            "target": {"Title_CN": "挪威的森林", "originalTitle": "ノルウェイの森"},
        }
        basic = dedupe_check.basic_match_edge(cand, _existing_edges())
        self.assertEqual(basic["level"], "exact")
        self.assertEqual(basic["existing"]["id"], "e-1")

    def test_no_match(self) -> None:
        cand = {
            "source": {"Title_CN": "三体", "originalTitle": "三体"},
            "target": {"Title_CN": "流浪地球", "originalTitle": "流浪地球"},
        }
        basic = dedupe_check.basic_match_edge(cand, _existing_edges())
        self.assertEqual(basic["level"], "none")

    def test_one_side_missing_never_matches(self) -> None:
        cand = {
            "source": {"Title_CN": "且听风吟"},
            "target": {"Title_CN": "完全不存在的书"},
        }
        basic = dedupe_check.basic_match_edge(cand, _existing_edges())
        self.assertEqual(basic["level"], "none")

    def test_collect_edge_candidates(self) -> None:
        cands = dedupe_check.collect_edge_candidates_from_extract(_extract_with_ripples())
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0]["source"]["Title_CN"], "且听风吟")
        self.assertEqual(cands[0]["target"]["Title_CN"], "挪威的森林")


class PipelineEdgeTest(unittest.TestCase):
    """批内合并 / 报告 edges / 自我提及跳过(使用临时 SQLite 库)。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "llm.db"
        self.patch_db = patch.object(db_sqlite, "DB_PATH", self.db_path)
        self.patch_db.start()
        self.addCleanup(self.patch_db.stop)
        self.patch_email = patch.object(auth, "BOOTSTRAP_EMAIL", _ADMIN_EMAIL)
        self.patch_email.start()
        self.addCleanup(self.patch_email.stop)
        self.patch_export = patch.object(data_store, "EXPORT_DIR", Path(self.tmp.name) / "export")
        self.patch_export.start()
        self.addCleanup(self.patch_export.stop)
        self.patch_batch_dir = patch.object(llm_space, "BATCH_DIR", Path(self.tmp.name) / "batches")
        self.patch_batch_dir.start()
        self.addCleanup(self.patch_batch_dir.stop)
        self.admin = auth.register(_ADMIN_EMAIL, "password123", username="admin01")
        self.assertEqual(self.admin["role"], "admin")
        self.owner = llm_space.ensure_system_llm()

    def _seed_existing_edge(self) -> None:
        """造一条公共涟漪:且听风吟 → 挪威的森林。"""
        owner = self.admin["id"]
        rewrite_all(
            [{"id": "a-1", "Name_CN": "村上春树", "originalName": "村上春樹", "owner_id": owner}],
            [
                {
                    "id": "w-src",
                    "language": "ja",
                    "originalTitle": "風の歌を聴け",
                    "Title_CN": "且听风吟",
                    "Title_EN": "Hear the Wind Sing",
                    "owner_id": owner,
                },
                {
                    "id": "w-tgt",
                    "language": "ja",
                    "originalTitle": "ノルウェイの森",
                    "Title_CN": "挪威的森林",
                    "Title_EN": "Norwegian Wood",
                    "owner_id": owner,
                },
            ],
            [
                {
                    "id": "e-1",
                    "source_work_id": "w-src",
                    "target_work_id": "w-tgt",
                    "evidence": "正文提及。",
                    "evidenceSource": "第一章",
                    "owner_id": owner,
                }
            ],
        )

    def test_run_dedupe_reports_existing_ripple(self) -> None:
        self._seed_existing_edge()
        extract = _extract_with_ripples()
        work_cands, author_cands = dedupe_check.collect_candidates_from_extract(extract)
        edge_cands = dedupe_check.collect_edge_candidates_from_extract(extract)
        report = dedupe_check.run_dedupe(
            work_cands, author_cands, edge_cands=edge_cands,
            db_path=str(self.db_path), basic_only=True,
        )
        self.assertIn("edges", report)
        self.assertEqual(len(report["edges"]), 2)
        self.assertEqual(report["edges"][0]["decision"], "likely_duplicate")
        self.assertEqual(report["existing_counts"]["edges"], 1)

    def test_build_batch_merges_duplicate_ripples(self) -> None:
        extract = _extract_with_ripples()
        work_cands, author_cands = dedupe_check.collect_candidates_from_extract(extract)
        edge_cands = dedupe_check.collect_edge_candidates_from_extract(extract)
        report = dedupe_check.run_dedupe(
            work_cands, author_cands, edge_cands=edge_cands,
            db_path=str(self.db_path), basic_only=True,
        )
        batch = review_publish.build_batch(
            extract, report, db_path=str(self.db_path), owner_id=self.owner
        )
        edges = [it for it in batch["items"] if it["kind"] == "edge"]
        # 两条重复涟漪合并为一条,证据出处合并
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["payload"]["evidenceSource"], "第一章；第三章")

    def test_build_batch_skips_self_ripple(self) -> None:
        extract = _extract_with_ripples()
        # 追加一条指向源书自身的涟漪(自我提及)
        extract["ripples"].append(
            {
                "work": {
                    "language": "ja",
                    "originalTitle": "風の歌を聴け",
                    "Title_CN": "且听风吟",
                    "Title_EN": "Hear the Wind Sing",
                    "author": "村上春树",
                },
                "evidence": {
                    "evidence": "书中自指。",
                    "evidenceSource": "后记",
                    "mention_type": "正文",
                },
            }
        )
        work_cands, author_cands = dedupe_check.collect_candidates_from_extract(extract)
        edge_cands = dedupe_check.collect_edge_candidates_from_extract(extract)
        report = dedupe_check.run_dedupe(
            work_cands, author_cands, edge_cands=edge_cands,
            db_path=str(self.db_path), basic_only=True,
        )
        batch = review_publish.build_batch(
            extract, report, db_path=str(self.db_path), owner_id=self.owner
        )
        edges = [it for it in batch["items"] if it["kind"] == "edge"]
        self.assertEqual(len(edges), 2)
        self_edge = next(e for e in edges if e["status"] == review_publish.SKIPPED)
        self.assertIn("自我提及", self_edge["dedupe"]["reason"])
        normal_edge = next(e for e in edges if e["status"] != review_publish.SKIPPED)
        self.assertEqual(normal_edge["payload"]["evidenceSource"], "第一章；第三章")

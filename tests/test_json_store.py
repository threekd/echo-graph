"""JsonStore 兜底存储测试(重点覆盖 path 的 max_hops 边界)。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.db as db


def _chain_seed(n: int = 4) -> dict:
    """构造 n 个作品单向链 w1 -> w2 -> ... -> wn 的 seed。"""
    works = [
        {
            "id": f"w{i}",
            "Title_CN": f"W{i}",
            "Title_EN": "",
            "originalTitle": f"w{i}",
            "language": "en",
            "publicationYear": 1900 + i,
            "creationYear": None,
            "genre": "",
            "summary": "",
            "author_id": "a1",
        }
        for i in range(1, n + 1)
    ]
    edges = [
        {
            "id": f"e{i}",
            "source": f"w{i}",
            "target": f"w{i + 1}",
            "evidence": "x",
            "evidenceSource": "",
            "note": "",
            "reviewStatus": "draft",
        }
        for i in range(1, n)
    ]
    return {
        "meta": {"demo": True},
        "authors": [{"id": "a1", "Name_CN": "A", "Name_EN": "", "originalName": "A"}],
        "works": works,
        "edges": edges,
    }


class JsonStorePathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        seed_file = Path(self.tmp.name) / "seed.json"
        seed_file.write_text(json.dumps(_chain_seed(4)), encoding="utf-8")
        patcher = patch.object(db, "SEED_PATH", seed_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.store = db.JsonStore()

    def test_direct_edge_with_max_hops_1(self) -> None:
        r = self.store.path("w1", "w2", 1)
        self.assertIsNotNone(r)
        self.assertEqual(len(r["edges"]), 1)
        self.assertEqual(r["nodes"], ["w1", "w2"])

    def test_two_hop_blocked_with_max_hops_1(self) -> None:
        self.assertIsNone(self.store.path("w1", "w3", 1))

    def test_two_hop_allowed_with_max_hops_2(self) -> None:
        r = self.store.path("w1", "w3", 2)
        self.assertIsNotNone(r)
        self.assertEqual(len(r["edges"]), 2)

    def test_three_hop_blocked_with_max_hops_2(self) -> None:
        self.assertIsNone(self.store.path("w1", "w4", 2))

    def test_three_hop_allowed_with_max_hops_3(self) -> None:
        r = self.store.path("w1", "w4", 3)
        self.assertIsNotNone(r)
        self.assertEqual(len(r["edges"]), 3)

    def test_same_node_returns_self(self) -> None:
        r = self.store.path("w1", "w1", 5)
        self.assertEqual(r["nodes"], ["w1"])
        self.assertEqual(r["edges"], [])

    def test_missing_node_returns_none(self) -> None:
        self.assertIsNone(self.store.path("w1", "nope", 5))
        self.assertIsNone(self.store.path("nope", "w1", 5))

    def test_graph_shape_uses_shared_serialization(self) -> None:
        g = self.store.graph()
        self.assertEqual(len(g["nodes"]), 5)  # a1 + w1..w4
        work_nodes = [n for n in g["nodes"] if n["type"] == "work"]
        self.assertTrue(all(n["author_id"] == "a1" and n["author"] == "A" for n in work_nodes))
        echo_edges = [e for e in g["edges"] if e["type"] == "echo"]
        self.assertEqual(len(echo_edges), 3)
        self.assertTrue(all(e["type"] == "echo" and "reviewStatus" in e for e in echo_edges))

    def test_path_edges_shape(self) -> None:
        r = self.store.path("w1", "w3", 2)
        self.assertEqual(len(r["edges"]), 2)
        self.assertTrue(all(e["type"] == "echo" and "evidence" in e for e in r["edges"]))

    def test_work_detail_shape(self) -> None:
        d = self.store.work_detail("w1")
        self.assertEqual(d["work"]["id"], "w1")
        self.assertEqual(len(d["authors"]), 1)
        self.assertEqual(d["author"]["name"], "A")
        self.assertEqual(d["mentioned_by"], [])
        self.assertEqual(len(d["mentions"]), 1)
        self.assertEqual(d["mentions"][0]["target"], "w2")
        d4 = self.store.work_detail("w4")
        self.assertEqual(len(d4["mentioned_by"]), 1)
        self.assertEqual(d4["mentions"], [])

    def test_multi_author_work(self) -> None:
        """合著作品:节点带全部 author_ids、作者名合并、详情与搜索均含全部作者。"""
        seed = {
            "meta": {"demo": True},
            "authors": [
                {"id": "a1", "Name_CN": "甲", "Name_EN": "", "originalName": "A"},
                {"id": "a2", "Name_CN": "乙", "Name_EN": "", "originalName": "B"},
            ],
            "works": [{
                "id": "w1",
                "Title_CN": "合著",
                "Title_EN": "",
                "originalTitle": "Coauthored",
                "language": "en",
                "author_id": "a1, a2",  # 逗号+空格,验证归一化
            }],
            "edges": [],
        }
        seed_file = Path(self.tmp.name) / "seed-multi.json"
        seed_file.write_text(json.dumps(seed), encoding="utf-8")
        with patch.object(db, "SEED_PATH", seed_file):
            store = db.JsonStore()

        g = store.graph()
        work = next(n for n in g["nodes"] if n["type"] == "work")
        self.assertEqual(work["author_ids"], ["a1", "a2"])
        self.assertEqual(work["author_id"], "a1")  # 兼容字段:取第一个
        self.assertEqual(work["author"], "甲、乙")
        authored = sorted((e["source"], e["target"]) for e in g["edges"] if e["type"] == "authored")
        self.assertEqual(authored, [("w1", "a1"), ("w1", "a2")])

        d = store.work_detail("w1")
        self.assertEqual([a["id"] for a in d["authors"]], ["a1", "a2"])
        self.assertEqual(d["author"]["id"], "a1")

        hits = store.search("合著")
        self.assertEqual(hits[0]["sub"], "甲、乙")

    def test_search_author_without_nationality_has_no_none(self) -> None:
        hits = self.store.search("A")
        self.assertTrue(any(h["type"] == "author" for h in hits))
        self.assertFalse(any("None" in (h.get("sub") or "") for h in hits))

    def test_search_tolerates_none_optional_fields(self) -> None:
        """可选字段为空(None)或键缺失(Neo4j null 属性不落盘)时搜索不应崩溃。"""
        seed = _chain_seed(2)
        seed["authors"][0].pop("Name_EN", None)
        for w in seed["works"]:
            w.pop("Title_EN", None)
            w.pop("publicationYear", None)
            w.pop("creationYear", None)
        seed_file = Path(self.tmp.name) / "seed-none.json"
        seed_file.write_text(json.dumps(seed), encoding="utf-8")
        with patch.object(db, "SEED_PATH", seed_file):
            store = db.JsonStore()
        author_hits = store.search("A")
        work_hits = store.search("W1")
        self.assertTrue(any(h["type"] == "author" for h in author_hits))
        self.assertTrue(any(h["type"] == "work" for h in work_hits))
        self.assertFalse(any("None" in (h.get("sub") or "") for h in work_hits))

    def test_graph_status_filter_treats_missing_as_draft(self) -> None:
        g_draft = self.store.graph(status="draft")
        self.assertEqual(len(g_draft["nodes"]), 5)  # a1 + w1..w4,均无 reviewStatus -> draft
        g_reviewed = self.store.graph(status="reviewed")
        self.assertEqual(g_reviewed["nodes"], [])
        self.assertEqual(g_reviewed["edges"], [])


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

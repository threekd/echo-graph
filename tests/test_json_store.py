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
            "evidenceLang": "",
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


if __name__ == "__main__":
    unittest.main()

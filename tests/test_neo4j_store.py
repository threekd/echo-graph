"""Neo4jStore 边界行为测试(不依赖真实 Neo4j,通过桩 _query 验证纯逻辑)。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import app.db as db


class Neo4jStorePathTest(unittest.TestCase):
    def _store(self) -> db.Neo4jStore:
        # 跳过 __init__(避免真实连接),只测 path 的短路逻辑
        return db.Neo4jStore.__new__(db.Neo4jStore)

    def test_same_node_returns_self_path(self) -> None:
        store = self._store()
        with patch.object(store, "_query", return_value=[{"c": 1}]) as q:
            result = store.path("w1", "w1", 15)
        self.assertEqual(result, {"nodes": ["w1"], "edges": []})
        q.assert_called_once()  # 只查存在性,不再执行 shortestPath(自环会抛错)

    def test_same_missing_node_returns_none(self) -> None:
        store = self._store()
        with patch.object(store, "_query", return_value=[{"c": 0}]):
            self.assertIsNone(store.path("nope", "nope", 15))

    def test_distinct_nodes_still_queries_shortest_path(self) -> None:
        store = self._store()
        with patch.object(store, "_query", return_value=[]):
            self.assertIsNone(store.path("w1", "w2", 15))


if __name__ == "__main__":
    unittest.main()

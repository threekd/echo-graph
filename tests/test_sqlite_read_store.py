"""SqliteStore 读取层测试(临时库,覆盖 graph / search / path / work_detail / expansion / stats)。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.db as db
from app import db_sqlite, sqlite_store

A1 = "01a013e6-e885-766b-b9db-315d518adeeb"
A2 = "01a013e6-e885-766b-b9db-315d518adeec"
W1 = "01a013e8-907e-77f3-83c6-bce355a36268"
W2 = "01a013e8-907e-77f3-83c6-bce48f19b60d"
W3 = "01a013e8-907e-77f3-83c6-bce355a36269"
W4 = "01a013e8-907e-77f3-83c6-bce355a3626a"


def _fixture() -> tuple[list[dict], list[dict], list[dict]]:
    """w1 -> w2 -> w3 -> w4 单向链,加合著作品,加一条软删除行。"""
    authors = [
        {"id": A1, "originalName": "Albert Camus", "Name_CN": "加缪", "nationality": "FR"},
        {"id": A2, "originalName": "鲁迅", "Name_CN": "鲁迅", "nationality": "CN"},
        {"id": "01a013e6-e885-766b-b9db-315d518adeed", "originalName": "旧作者", "Name_CN": "旧作者",
         "deletedAt": "2026-01-01T00:00:00+00:00"},
    ]
    works = [
        {"id": W1, "language": "fr", "originalTitle": "L'Étranger", "Title_CN": "局外人", "author_id": A1,
         "publicationYear": 1942, "reviewStatus": "reviewed"},
        {"id": W2, "language": "zh", "originalTitle": "朝花夕拾", "Title_CN": "朝花夕拾", "author_id": f"{A1},{A2}"},
        {"id": W3, "language": "zh", "originalTitle": "狂人日记", "Title_CN": "狂人日记", "author_id": A2},
        {"id": W4, "language": "fr", "originalTitle": "Noces", "Title_CN": "婚礼", "author_id": A1},
    ]
    edges = [
        {"id": "01a0155e-33a7-772a-8efc-4ad2766bc830", "source_work_id": W1, "target_work_id": W2,
         "evidence": "x", "evidenceSource": "c1", "reviewStatus": "reviewed"},
        {"id": "01a0155e-33a7-772a-8efc-4ad2766bc831", "source_work_id": W2, "target_work_id": W3, "evidence": "y"},
        {"id": "01a0155e-33a7-772a-8efc-4ad2766bc832", "source_work_id": W3, "target_work_id": W4, "evidence": "z"},
        {"id": "01a0155e-33a7-772a-8efc-4ad2766bc833", "source_work_id": W1, "target_work_id": W4,
         "evidence": "deleted", "deletedAt": "2026-01-01T00:00:00+00:00"},
    ]
    return authors, works, edges


class SqliteStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "echo-graph.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        sqlite_store.rewrite_all(*_fixture())
        self.store = db.SqliteStore()

    def test_graph_shape(self) -> None:
        g = self.store.graph()
        self.assertEqual(len(g["nodes"]), 6)  # 2 活跃作者 + 4 作品(软删除排除)
        work_nodes = [n for n in g["nodes"] if n["type"] == "work"]
        multi = next(n for n in work_nodes if n["id"] == W2)
        self.assertEqual(multi["author_ids"], [A1, A2])
        self.assertEqual(multi["author"], "加缪、鲁迅")
        echo_edges = [e for e in g["edges"] if e["type"] == "echo"]
        self.assertEqual(len(echo_edges), 3)  # 软删除边排除
        authored = sorted(e["target"] for e in g["edges"] if e["type"] == "authored")
        self.assertEqual(authored, [A1, A1, A1, A2, A2])

    def test_graph_status_filter(self) -> None:
        g = self.store.graph(status="reviewed")
        works = [n for n in g["nodes"] if n["type"] == "work"]
        self.assertEqual([n["id"] for n in works], [W1])
        self.assertEqual(len([e for e in g["edges"] if e["type"] == "echo"]), 1)
        g_draft = self.store.graph(status="draft")
        works = [n for n in g_draft["nodes"] if n["type"] == "work"]
        self.assertEqual(len(works), 3)  # W2/W3/W4 默认 draft

    def test_search(self) -> None:
        hits = self.store.search("加缪")
        self.assertTrue(any(h["type"] == "author" for h in hits))
        self.assertFalse(any("None" in (h.get("sub") or "") for h in hits))
        work_hits = self.store.search("局外")
        self.assertTrue(any(h["type"] == "work" for h in work_hits))
        self.assertIn("加缪", work_hits[0]["sub"])
        self.assertEqual(self.store.search("不存在的关键词"), [])

    def test_path_boundaries(self) -> None:
        self.assertIsNone(self.store.path(W1, W3, 1))
        r = self.store.path(W1, W3, 2)
        self.assertEqual(r["nodes"], [W1, W2, W3])
        self.assertEqual(len(r["edges"]), 2)
        self.assertIsNone(self.store.path(W1, "nope", 5))
        self.assertEqual(self.store.path(W1, W1, 5), {"nodes": [W1], "edges": []})

    def test_work_detail(self) -> None:
        d = self.store.work_detail(W1)
        self.assertEqual(d["work"]["id"], W1)
        self.assertEqual(d["author"]["name"], "加缪")
        self.assertEqual(len(d["authors"]), 1)
        self.assertEqual(len(d["mentions"]), 1)  # w1 -> w2
        self.assertEqual(d["mentions"][0]["target_title"], "朝花夕拾")
        self.assertEqual(len(d["mentioned_by"]), 0)
        d2 = self.store.work_detail(W2)
        self.assertEqual([a["id"] for a in d2["authors"]], [A1, A2])
        self.assertEqual(d2["mentioned_by"][0]["source_title"], "局外人")
        self.assertIsNone(self.store.work_detail("nope"))

    def test_expansion(self) -> None:
        r = self.store.expansion(W1, 1)
        self.assertEqual(r["centerId"], W1)
        self.assertEqual(sorted(n["id"] for n in r["nodes"]), [W1, W2])
        self.assertEqual(len(r["edges"]), 1)
        r2 = self.store.expansion(W1, 3)
        self.assertEqual(len(r2["nodes"]), 4)
        self.assertIsNone(self.store.expansion("nope", 2))

    def test_stats(self) -> None:
        s = self.store.stats()
        self.assertEqual(s["store"], "sqlite")
        self.assertEqual(s["authors"], 2)
        self.assertEqual(s["works"], 4)
        self.assertEqual(s["echo_edges"], 3)
        self.assertEqual(s["reviewStatus"]["edges"]["reviewed"], 1)
        self.assertEqual(s["reviewStatus"]["edges"]["draft"], 2)

    def test_reviewed_only_public_filter(self) -> None:
        """公开视图(reviewed_only)只暴露审核通过的内容。"""
        a, w, e = _fixture()
        for row in a:
            row["reviewStatus"] = "reviewed"
        w[0]["reviewStatus"] = "reviewed"  # 只有局外人 reviewed
        sqlite_store.rewrite_all(a, w, e)
        store = db.SqliteStore(reviewed_only=True)

        g = store.graph()
        works = [n["id"] for n in g["nodes"] if n["type"] == "work"]
        self.assertEqual(works, [W1])
        echo_edges = [ed for ed in g["edges"] if ed["type"] == "echo"]
        self.assertEqual(len(echo_edges), 1)  # 只有 e1 是 reviewed

        self.assertEqual(store.search("狂人"), [])  # 草稿作品不可搜索
        self.assertIsNone(store.work_detail(W2))  # 草稿作品详情 404
        d = store.work_detail(W1)
        self.assertEqual(len(d["mentions"]), 1)
        self.assertIsNone(store.path(W1, W2, 5))  # 草稿作品不可作为路径端点

        s = store.stats()
        self.assertEqual(s["authors"], 2)
        self.assertEqual(s["works"], 1)
        self.assertEqual(s["echo_edges"], 1)

    def test_reviewed_only_off_by_default(self) -> None:
        """默认(未开 PUBLIC_REVIEWED_ONLY)仍返回全部状态。"""
        store = db.SqliteStore(reviewed_only=False)
        self.assertEqual(store.stats()["works"], 4)

    def test_close_is_noop(self) -> None:
        self.store.close()  # 无连接池,不应抛错;后续查询仍可用
        self.assertEqual(len(self.store.graph()["nodes"]), 6)


if __name__ == "__main__":
    unittest.main()

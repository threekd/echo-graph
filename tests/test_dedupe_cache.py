"""dedupe_check 向量缓存单测:命中 / 失效 / 模型切换 / 重建 / 空文本。

对应 app/ai_assistant/tools/dedupe_check.py 的 _load_vectors_cached /
_load_vector_cache / _save_vector_cache 与 run_dedupe(rebuild_vectors)。
全部测试 mock 掉 embedding 接口,不发真实网络请求。
"""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import auth, db_sqlite
from app.ai_assistant.tools import dedupe_check


def _fake_embed(client, model, texts):
    """确定性伪向量:同一文本恒返回同一向量(真实接口同文本跨请求有微小抖动,与此无关)。"""
    return [
        [hashlib.sha256(t.encode("utf-8")).digest()[k % 32] / 255.0 for k in range(8)]
        for t in texts
    ]


def _work_rows(*titles):
    return [
        {"id": f"w{i}", "originalTitle": t, "Title_CN": t, "author": None}
        for i, t in enumerate(titles)
    ]


class VectorCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "cache.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        db_sqlite._migrate(self.conn)
        self.addCleanup(self.conn.close)

    def _load(self, rows, model="test-model", rebuild=False):
        with patch.object(
            dedupe_check, "_embed", side_effect=_fake_embed
        ) as mock_embed:
            texts, vectors = dedupe_check._load_vectors_cached(
                object(), model, self.conn, "work", rows,
                dedupe_check._work_embed_text, rebuild=rebuild,
            )
        return texts, vectors, mock_embed

    def test_first_run_embeds_all_and_caches(self) -> None:
        rows = _work_rows("三体", "百年孤独")
        texts, vectors, mock = self._load(rows)
        self.assertEqual(mock.call_count, 1)
        self.assertEqual(len(mock.call_args.args[2]), 2)
        self.assertEqual(vectors, _fake_embed(None, None, texts))
        cached = self.conn.execute(
            "SELECT entity_id, text_hash, vector, model, version FROM embeddings"
        ).fetchall()
        self.assertEqual(len(cached), 2)

    def test_second_run_hits_cache_no_api(self) -> None:
        rows = _work_rows("三体", "百年孤独")
        _, vectors1, _ = self._load(rows)
        _, vectors2, mock2 = self._load(rows)
        mock2.assert_not_called()
        self.assertEqual(vectors1, vectors2)

    def test_text_change_reembeds_only_changed(self) -> None:
        rows = _work_rows("三体", "百年孤独")
        self._load(rows)
        rows[0]["Title_CN"] = "三体(全集)"
        _, vectors, mock = self._load(rows)
        self.assertEqual(mock.call_count, 1)
        self.assertEqual(mock.call_args.args[2], ["三体 | 三体(全集)"])
        self.assertEqual(vectors[1], _fake_embed(None, None, ["百年孤独 | 百年孤独"])[0])

    def test_model_change_reembeds_all(self) -> None:
        rows = _work_rows("三体")
        self._load(rows, model="old-model")
        _, _, mock = self._load(rows, model="new-model")
        self.assertEqual(mock.call_count, 1)

    def test_rebuild_ignores_cache(self) -> None:
        rows = _work_rows("三体")
        self._load(rows)
        _, _, mock = self._load(rows, rebuild=True)
        self.assertEqual(mock.call_count, 1)

    def test_empty_text_not_cached(self) -> None:
        rows = [{"id": "w0", "originalTitle": None, "Title_CN": None}]
        _, vectors, mock = self._load(rows)
        self.assertIsNone(vectors[0])
        mock.assert_not_called()
        count = self.conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        self.assertEqual(count, 0)


class RunDedupeCacheTest(unittest.TestCase):
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

    def test_second_run_embeds_only_candidate(self) -> None:
        cand = [{"Title_CN": "三体", "originalTitle": "三体"}]
        with (
            patch.object(dedupe_check, "_load_aliyun", return_value=(object(), "test-model")),
            patch.object(dedupe_check, "_embed", side_effect=_fake_embed) as mock_embed,
        ):
            kwargs = {"db_path": str(self.db_path), "force_semantic": True}
            dedupe_check.run_dedupe(cand, [], **kwargs)
            first_calls = mock_embed.call_count
            self.assertEqual(first_calls, 2)  # 库内作品 1 条 + 候选 1 条
            report = dedupe_check.run_dedupe(cand, [], **kwargs)
            second_calls = mock_embed.call_count - first_calls
            self.assertEqual(second_calls, 1)  # 第二次仅候选重新嵌入,库内向量命中缓存
        self.assertEqual(report["semantic"]["vector_version"], dedupe_check.VECTOR_VERSION)
        self.assertFalse(report["semantic"]["rebuild"])


if __name__ == "__main__":
    unittest.main()

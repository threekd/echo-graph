"""用户贡献收件箱测试(SQLite,使用临时数据库文件)。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.contributions as c
from app import db_sqlite


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    def __init__(self, host: str | None = None, headers: dict | None = None) -> None:
        self.client = _FakeClient(host) if host is not None else None
        self.headers = headers or {}


class ContributionStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "contrib.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_submit_and_list(self) -> None:
        row = c.submit_contribution({
            "source_work": "《局外人》",
            "target_work": "《鼠疫》",
            "source_author": "加缪",
            "target_author": "加缪",
            "evidence": "  提到《鼠疫》\u200b  ",
            "evidence_source": "chapter1",
            "contact": "a@b.c",
        })
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["evidence"], "提到《鼠疫》")  # 零宽字符与空白被清洗
        self.assertTrue(row["id"])
        result = c.list_contributions("pending")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["source_work"], "《局外人》")
        self.assertEqual(result["items"][0]["source_author"], "加缪")
        self.assertEqual(result["items"][0]["target_author"], "加缪")
        self.assertEqual(result["items"][0]["evidence_source"], "chapter1")
        self.assertEqual(c.list_contributions("approved")["total"], 0)
        self.assertEqual(c.list_contributions()["total"], 1)

    def test_validation_errors(self) -> None:
        with self.assertRaises(ValueError):
            c.submit_contribution({"source_work": "A", "target_work": "B"})  # 缺 evidence
        with self.assertRaises(ValueError):
            c.submit_contribution({"source_work": "", "target_work": "B", "evidence": "x"})
        with self.assertRaises(ValueError):
            c.submit_contribution({"source_work": "A", "target_work": "B", "evidence": "x"})  # 缺出处
        with self.assertRaises(ValueError):
            c.submit_contribution({
                "source_work": "A", "target_work": "B", "source_author": "甲",
                "evidence": "x", "evidence_source": "c1",
            })  # 缺目标作品作者
        with self.assertRaises(ValueError):
            c.submit_contribution({
                "source_work": "A", "target_work": "B", "source_author": "甲", "target_author": "乙",
                "evidence": "x" * 2001, "evidence_source": "c1",
            })

    def test_approve_and_reject(self) -> None:
        row = c.submit_contribution({
            "source_work": "A", "target_work": "B", "source_author": "甲", "target_author": "乙",
            "evidence": "x", "evidence_source": "c1",
        })
        self.assertTrue(c.set_status(row["id"], "approved"))
        items = c.list_contributions("approved")["items"]
        self.assertEqual(len(items), 1)
        self.assertIsNotNone(items[0]["reviewed_at"])
        self.assertFalse(c.set_status("not-exists", "approved"))

    def test_rate_limit(self) -> None:
        c._rate.clear()
        ip = "1.2.3.4"
        for _ in range(c.SUBMIT_LIMIT):
            self.assertFalse(c._rate_limited(ip))
        self.assertTrue(c._rate_limited(ip))

    def test_client_ip_trusted_proxy_uses_forwarded_for(self) -> None:
        req = _FakeRequest("127.0.0.1", {"x-forwarded-for": "203.0.113.9, 10.0.0.2"})
        self.assertEqual(c._client_ip(req), "203.0.113.9")

    def test_client_ip_ipv6_trusted_proxy(self) -> None:
        req = _FakeRequest("::1", {"x-forwarded-for": "2001:db8::1"})
        self.assertEqual(c._client_ip(req), "2001:db8::1")

    def test_client_ip_untrusted_peer_ignores_forwarded_for(self) -> None:
        """直连(或伪造头)时以对端地址为准,防止 XFF 绕过限流。"""
        req = _FakeRequest("203.0.113.9", {"x-forwarded-for": "198.51.100.7"})
        self.assertEqual(c._client_ip(req), "203.0.113.9")

    def test_client_ip_invalid_forwarded_for_falls_back(self) -> None:
        req = _FakeRequest("127.0.0.1", {"x-forwarded-for": "not-an-ip"})
        self.assertEqual(c._client_ip(req), "127.0.0.1")

    def test_client_ip_missing_client_is_unknown(self) -> None:
        self.assertEqual(c._client_ip(_FakeRequest()), "unknown")

    def test_rate_map_pruned_when_large(self) -> None:
        c._rate.clear()
        old = c._MAX_RATE_KEYS
        c._MAX_RATE_KEYS = 2
        try:
            c._rate["a"] = [1.0]
            c._rate["b"] = [2.0]
            c._rate["c"] = [3.0]
            c._rate_limited("d")
            self.assertLessEqual(len(c._rate), 2)
        finally:
            c._MAX_RATE_KEYS = old

    def test_legacy_schema_migrated(self) -> None:
        """旧库(无作者列)打开后自动补列,不影响既有数据。"""
        conn = sqlite3.connect(db_sqlite.DB_PATH)
        conn.execute(
            "CREATE TABLE contributions (id TEXT PRIMARY KEY, source_work TEXT NOT NULL,"
            " target_work TEXT NOT NULL, evidence TEXT NOT NULL, evidence_source TEXT,"
            " note TEXT, contact TEXT, status TEXT NOT NULL DEFAULT 'pending',"
            " created_at TEXT NOT NULL, reviewed_at TEXT)"
        )
        conn.commit()
        conn.close()

        self.assertEqual(c.list_contributions()["total"], 0)
        row = c.submit_contribution({
            "source_work": "A", "target_work": "B",
            "source_author": "甲", "target_author": "乙",
            "evidence": "x", "evidence_source": "c1",
        })
        self.assertEqual(row["source_author"], "甲")
        self.assertEqual(c.list_contributions()["items"][0]["target_author"], "乙")

if __name__ == "__main__":
    unittest.main()

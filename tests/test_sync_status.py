"""CSV 与 Neo4j 同步状态比对测试(规范化逻辑,不触网)。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import app.admin as admin

A1 = "01a013e6-e885-766b-b9db-315d518adeeb"
W1 = "01a013e8-907e-77f3-83c6-bce355a36268"


def _csv_fixture():
    return (
        [{
            "id": A1, "originalName": "Albert Camus", "Name_CN": "加缪",
            "nationality": "fr", "birthYear": "1913", "deathYear": "1960",
            "reviewStatus": "reviewed",
        }],
        [{
            "id": W1, "language": "FR", "originalTitle": "L'Étranger", "Title_CN": "局外人",
            "author_id": A1, "genre": "Fiction", "publicationYear": "1942",
            "reviewStatus": "reviewed",
        }],
        [],
    )


class FakeNeo4j:
    """模拟 Neo4jStore,按查询关键字返回构造的行。"""

    name = "neo4j"

    def __init__(self, authors, works, authored, echoes):
        self.authors = authors
        self.works = works
        self.authored = authored
        self.echoes = echoes

    def _query(self, cypher: str, params=None):
        if "labels(n) AS ls" in cypher:
            rows = []
            for a in self.authors:
                rows.append({"ls": ["Author"], "p": dict(a), "author_ids": [None]})
            for w in self.works:
                rows.append({
                    "ls": ["Work"],
                    "p": dict(w),
                    "author_ids": [aid for (wid, aid) in self.authored if wid == w["id"]],
                })
            return rows
        if "ECHO" in cypher:
            return [{"s": x[0], "t": x[1], "p": dict(x[2])} for x in self.echoes]
        return []


def _fake_store(authors, works, authored, echoes):
    class FakePrimary:
        name = "neo4j"

        def __init__(self):
            self._query = FakeNeo4j(authors, works, authored, echoes)._query

    class FakeStore:
        primary = FakePrimary()

    return FakeStore()


def _neo_fixture():
    """与 _csv_fixture 等价的 Neo4j 行(规范化后应与 CSV 一致)。"""
    authors = [{
        "id": A1, "originalName": "Albert Camus", "Name_CN": "加缪",
        "nationality": "FR", "birthYear": 1913, "deathYear": 1960,
        "reviewStatus": "reviewed", "createdAt": "2026-01-01T00:00:00+00:00",
    }]
    works = [{
        "id": W1, "language": "fr", "originalTitle": "L'Étranger", "Title_CN": "局外人",
        "genre": "Fiction", "publicationYear": 1942, "reviewStatus": "reviewed",
        "createdAt": "2026-01-01T00:00:00+00:00", "updatedAt": "2026-01-01T00:00:00+00:00",
    }]
    authored = [(W1, A1)]
    return authors, works, authored, []


class SyncStatusTest(unittest.TestCase):
    def test_csv_payload_normalizes(self) -> None:
        with patch("app.admin.load_rows", return_value=_csv_fixture()):
            p = admin._csv_sync_payload()
        self.assertEqual(p["authors"][0]["nationality"], "FR")
        self.assertEqual(p["authors"][0]["birthYear"], 1913)
        self.assertEqual(p["works"][0]["language"], "fr")
        self.assertEqual(p["works"][0]["publicationYear"], 1942)
        self.assertEqual(p["works"][0]["author_ids"], [A1])

    def test_synced_when_equal(self) -> None:
        authors, works, authored, echoes = _neo_fixture()
        with (
            patch("app.admin.load_rows", return_value=_csv_fixture()),
            patch("app.admin.get_store", return_value=_fake_store(authors, works, authored, echoes)),
        ):
            d = admin.admin_sync()
        self.assertIs(d["synced"], True)

    def test_unsynced_when_csv_edited(self) -> None:
        authors, works, authored, echoes = _neo_fixture()
        csv = _csv_fixture()
        csv[0][0]["Name_CN"] = "加缪(改名)"  # 只改 CSV,Neo4j 未同步
        with (
            patch("app.admin.load_rows", return_value=csv),
            patch("app.admin.get_store", return_value=_fake_store(authors, works, authored, echoes)),
        ):
            d = admin.admin_sync()
        self.assertIs(d["synced"], False)

    def test_unsynced_when_added(self) -> None:
        authors, works, authored, echoes = _neo_fixture()
        csv = _csv_fixture()
        csv[1][0]["id"] = "01a013e8-907e-77f3-83c6-bce48f19b60d"  # 新增作品,Neo4j 没有
        csv[1][0]["Title_CN"] = "婚礼"
        with (
            patch("app.admin.load_rows", return_value=csv),
            patch("app.admin.get_store", return_value=_fake_store(authors, works, authored, echoes)),
        ):
            d = admin.admin_sync()
        self.assertIs(d["synced"], False)


if __name__ == "__main__":
    unittest.main()

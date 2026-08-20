"""后端应用冒烟:SQLite 读取模式下路由注册、版本与基础接口。"""

from __future__ import annotations

import tempfile
import tomllib
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import app.main as main  # noqa: E402
from app import db_sqlite, sqlite_store  # noqa: E402


class ApiSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        # 管理写入走 SQLite:全部隔离到临时库,且不落盘 CSV/版本目录
        self.tmp = tempfile.TemporaryDirectory()
        patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "echo-graph.db").start()
        patch("app.admin.export_csv_files", lambda: None).start()
        self.addCleanup(self.tmp.cleanup)

    def test_expected_routes_registered(self) -> None:
        paths = {
            getattr(r, "path", None)
            for r in main.app.routes
            if getattr(r, "path", None)
        }
        for expected in (
            "/",
            "/api/graph",
            "/api/search",
            "/api/work/{work_id}",
            "/api/expansion/{work_id}",
            "/api/path",
            "/api/stats",
            "/api/health",
            "/assets/{path:path}",
        ):
            self.assertIn(expected, paths)

    def test_contribute_and_admin_routes_registered(self) -> None:
        """贡献与管理的路由挂在 include 的 router 下,用 OpenAPI 路径断言。"""
        paths = main.app.openapi()["paths"]
        self.assertIn("/api/contribute/echo", paths)
        self.assertIn("/api/admin/contributions", paths)
        self.assertIn("/api/admin/data", paths)
        self.assertIn("/api/admin/backups", paths)
        self.assertIn("/api/admin/audit", paths)

    def test_version_matches_pyproject(self) -> None:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject.open("rb") as fh:
            expected = tomllib.load(fh)["project"]["version"]
        self.assertEqual(main.app.version, expected)

    def test_stats_and_health(self) -> None:
        stats = main.store.stats()
        self.assertEqual(stats["store"], "sqlite")
        self.assertIn("authors", stats)
        self.assertIn("works", stats)
        health = main.health()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["store"], "sqlite")

    def test_graph_is_empty_on_fresh_db(self) -> None:
        g = main.store.graph()
        self.assertEqual(g["nodes"], [])
        self.assertEqual(g["edges"], [])

    def test_static_serving_rejects_path_traversal(self) -> None:
        cases = [
            (main.frontend_assets, "../../../pyproject.toml"),
            (main.frontend_assets, "..%2f..%2f.env"),
            (main.frontend_assets, ""),
        ]
        for fn, path in cases:
            with self.subTest(fn=fn.__name__, path=path):
                with self.assertRaises(HTTPException):
                    fn(path)

    def test_missing_static_file_returns_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            main.frontend_assets("not-exists.js")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_graph_status_filter_and_stats(self) -> None:
        g = main.store.graph(status="reviewed")
        self.assertEqual(g["nodes"], [])
        self.assertEqual(g["edges"], [])
        stats = main.store.stats()
        self.assertIn("reviewStatus", stats)
        self.assertIn("authors", stats["reviewStatus"])
        self.assertIn("works", stats["reviewStatus"])
        self.assertIn("edges", stats["reviewStatus"])

    def test_admin_create_sets_timestamps_and_default_status(self) -> None:
        import app.admin as admin

        res = admin.create(
            "authors",
            {"originalName": "  \u200b某作家\u200b  ", "Name_CN": "  某\u200b  "},
        )
        row = res["row"]
        self.assertTrue(row["createdAt"])
        self.assertTrue(row["updatedAt"])
        self.assertEqual(row["reviewStatus"], "draft")
        self.assertEqual(row["originalName"], "某作家")  # 落盘前去除首尾空白与零宽字符
        self.assertEqual(row["Name_CN"], "某")
        # 行级写入已落库
        self.assertEqual(len(sqlite_store.list_all()["authors"]), 1)

    def test_admin_update_bumps_updated_at_keeps_created_at(self) -> None:
        import app.admin as admin

        author = {
            "id": "01a013e6-e885-766b-b9db-315d518adeeb",
            "originalName": "旧名",
            "Name_CN": "旧中文名",
            "createdAt": "2026-01-01T00:00:00+00:00",
        }
        sqlite_store.rewrite_all([author], [], [])
        res = admin.update(
            "authors",
            author["id"],
            {"originalName": "新名", "Name_CN": "新中文名"},
        )
        row = res["row"]
        self.assertEqual(row["createdAt"], "2026-01-01T00:00:00+00:00")
        self.assertTrue(row["updatedAt"])
        saved = sqlite_store.list_all()["authors"][0]
        self.assertEqual(saved["originalName"], "新名")
        self.assertEqual(saved["createdAt"], "2026-01-01T00:00:00+00:00")

    def test_admin_update_optimistic_lock_conflict(self) -> None:
        """更新时 updatedAt 已被他人改动 -> 409 乐观锁冲突。"""
        import app.admin as admin

        author = {
            "id": "01a013e6-e885-766b-b9db-315d518adeeb",
            "originalName": "A", "Name_CN": "甲",
            "updatedAt": "2026-08-20T08:00:00+00:00",
        }
        sqlite_store.rewrite_all([author], [], [])
        with self.assertRaises(HTTPException) as ctx:
            admin.update(
                "authors",
                author["id"],
                {"originalName": "B", "Name_CN": "乙", "updatedAt": "2026-08-20T09:00:00+00:00"},
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_admin_get_data_includes_warnings(self) -> None:
        import app.admin as admin

        authors = [
            {"id": "01a013e6-e885-766b-b9db-315d518adeeb", "originalName": "X", "Name_CN": "甲"},
            {"id": "01a013e6-e885-766b-b9db-315d518adeec", "originalName": "Y", "Name_CN": "甲"},
        ]
        sqlite_store.rewrite_all(authors, [], [])
        d = admin.get_data()
        self.assertIn("warnings", d)
        self.assertEqual(len(d["warnings"]["duplicateAuthorNames"]), 1)

    def test_admin_duplicate_edge_error_uses_titles(self) -> None:
        """新增重复涟漪时,400 报错应显示作品标题而不是 UUID。"""
        import app.admin as admin

        w1 = "01a013e8-907e-77f3-83c6-bce355a36268"
        w2 = "01a013e8-907e-77f3-83c6-bce48f19b60d"
        works = [
            {"id": w1, "language": "fr", "originalTitle": "L'Envers et l'Endroit", "Title_CN": "反与正"},
            {"id": w2, "language": "fr", "originalTitle": "Noces", "Title_CN": "婚礼"},
        ]
        edges = [{
            "id": "01a0155e-33a7-772a-8efc-4ad2766bc830",
            "source_work_id": w1,
            "target_work_id": w2,
            "evidence": "x",
        }]
        sqlite_store.rewrite_all([], works, edges)
        with self.assertRaises(HTTPException) as ctx:
            admin.create("edges", {
                "source_work_id": w1, "target_work_id": w2,
                "evidence": "y", "evidenceSource": "c1",
            })
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("反与正", ctx.exception.detail)
        self.assertIn("婚礼", ctx.exception.detail)

    def test_admin_edge_requires_evidence_source(self) -> None:
        """新增涟漪时出处必填。"""
        import app.admin as admin

        w1, w2 = (str(uuid.uuid4()) for _ in range(2))
        works = [
            {"id": w1, "language": "fr", "originalTitle": "A", "Title_CN": "甲书"},
            {"id": w2, "language": "fr", "originalTitle": "B", "Title_CN": "乙书"},
        ]
        sqlite_store.rewrite_all([], works, [])
        with self.assertRaises(HTTPException) as ctx:
            admin.create("edges", {"source_work_id": w1, "target_work_id": w2, "evidence": "x"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("出处不能为空", ctx.exception.detail)

    def test_admin_delete_work_cascades_edges(self) -> None:
        """删除作品时,与其相关的涟漪边一并软删除。"""
        import app.admin as admin

        w1, w2, e1, e2 = (str(uuid.uuid4()) for _ in range(4))
        works = [
            {"id": w1, "language": "en", "originalTitle": "A", "Title_CN": "甲书"},
            {"id": w2, "language": "en", "originalTitle": "B", "Title_CN": "乙书"},
        ]
        edges = [
            {"id": e1, "source_work_id": w1, "target_work_id": w2, "evidence": "x"},
            {"id": e2, "source_work_id": w2, "target_work_id": w1, "evidence": "y"},
        ]
        sqlite_store.rewrite_all([], works, edges)
        res = admin.delete("works", w1)
        self.assertTrue(res["ok"])
        self.assertEqual(sorted(res["cascade"]["edges"]), sorted([e1, e2]))
        data = sqlite_store.list_all()
        saved_works, saved_edges = data["works"], data["edges"]
        self.assertTrue(next(r for r in saved_works if r["id"] == w1)["deletedAt"])
        self.assertFalse(next(r for r in saved_works if r["id"] == w2).get("deletedAt"))
        self.assertEqual(len([r for r in saved_edges if r.get("deletedAt")]), 2)

    def test_admin_delete_author_cascades_works_and_edges(self) -> None:
        """删除作者时,其名下作品及相关涟漪边一并软删除。"""
        import app.admin as admin

        a1, a2, w1, w2, e1 = (str(uuid.uuid4()) for _ in range(5))
        authors = [
            {"id": a1, "originalName": "A", "Name_CN": "甲"},
            {"id": a2, "originalName": "B", "Name_CN": "乙"},
        ]
        works = [
            {"id": w1, "language": "en", "originalTitle": "A", "Title_CN": "甲书", "author_id": a1},
            {"id": w2, "language": "en", "originalTitle": "B", "Title_CN": "乙书", "author_id": a2},
        ]
        edges = [
            {"id": e1, "source_work_id": w1, "target_work_id": w2, "evidence": "x"},
        ]
        sqlite_store.rewrite_all(authors, works, edges)
        res = admin.delete("authors", a1)
        self.assertTrue(res["ok"])
        self.assertEqual(res["cascade"]["works"], [w1])
        self.assertEqual(res["cascade"]["edges"], [e1])
        data = sqlite_store.list_all()
        saved_works, saved_edges = data["works"], data["edges"]
        self.assertTrue(next(r for r in saved_works if r["id"] == w1)["deletedAt"])
        self.assertFalse(next(r for r in saved_works if r["id"] == w2).get("deletedAt"))
        self.assertTrue(saved_edges[0]["deletedAt"])

    def test_admin_restore_work_restores_cascade_edges(self) -> None:
        """恢复作品时,同一删除动作(相同 deletedAt)的涟漪边一并恢复,单独删除的不受影响。"""
        import app.admin as admin

        w1, w2, e1, e2 = (str(uuid.uuid4()) for _ in range(4))
        ts = "2026-08-20T08:00:00+00:00"
        works = [
            {"id": w1, "language": "en", "originalTitle": "A", "Title_CN": "甲书", "deletedAt": ts},
            {"id": w2, "language": "en", "originalTitle": "B", "Title_CN": "乙书"},
        ]
        edges = [
            {"id": e1, "source_work_id": w1, "target_work_id": w2, "evidence": "x", "deletedAt": ts},
            {"id": e2, "source_work_id": w2, "target_work_id": w1, "evidence": "y", "deletedAt": "2026-08-20T09:00:00+00:00"},
        ]
        sqlite_store.rewrite_all([], works, edges)
        res = admin.restore("works", w1)
        self.assertTrue(res["ok"])
        self.assertEqual(res["cascade"]["edges"], [e1])
        data = sqlite_store.list_all()
        saved_works, saved_edges = data["works"], data["edges"]
        self.assertFalse(next(r for r in saved_works if r["id"] == w1).get("deletedAt"))
        self.assertFalse(next(r for r in saved_edges if r["id"] == e1).get("deletedAt"))
        self.assertEqual(next(r for r in saved_edges if r["id"] == e2)["deletedAt"], "2026-08-20T09:00:00+00:00")

    def test_admin_restore_author_restores_works_and_edges(self) -> None:
        """恢复作者时,同批删除的作品与涟漪边一并恢复。"""
        import app.admin as admin

        a1, a2, w1, w2, e1 = (str(uuid.uuid4()) for _ in range(5))
        ts = "2026-08-20T08:00:00+00:00"
        authors = [
            {"id": a1, "originalName": "A", "Name_CN": "甲", "deletedAt": ts},
            {"id": a2, "originalName": "B", "Name_CN": "乙"},
        ]
        works = [
            {"id": w1, "language": "en", "originalTitle": "A", "Title_CN": "甲书", "author_id": a1, "deletedAt": ts},
            {"id": w2, "language": "en", "originalTitle": "B", "Title_CN": "乙书", "author_id": a2},
        ]
        edges = [
            {"id": e1, "source_work_id": w1, "target_work_id": w2, "evidence": "x", "deletedAt": ts},
        ]
        sqlite_store.rewrite_all(authors, works, edges)
        res = admin.restore("authors", a1)
        self.assertTrue(res["ok"])
        self.assertEqual(res["cascade"]["works"], [w1])
        self.assertEqual(res["cascade"]["edges"], [e1])
        data = sqlite_store.list_all()
        saved_works, saved_edges = data["works"], data["edges"]
        self.assertFalse(next(r for r in saved_works if r["id"] == w1).get("deletedAt"))
        self.assertFalse(next(r for r in saved_edges if r["id"] == e1).get("deletedAt"))

    def test_admin_restore_edge_restores_works(self) -> None:
        """恢复涟漪边时,同批删除的源/目标作品一并恢复,避免活跃边引用已删作品。"""
        import app.admin as admin

        w1, w2, e1 = (str(uuid.uuid4()) for _ in range(3))
        ts = "2026-08-20T08:00:00+00:00"
        works = [
            {"id": w1, "language": "en", "originalTitle": "A", "Title_CN": "甲书", "deletedAt": ts},
            {"id": w2, "language": "en", "originalTitle": "B", "Title_CN": "乙书", "deletedAt": ts},
        ]
        edges = [
            {"id": e1, "source_work_id": w1, "target_work_id": w2, "evidence": "x", "deletedAt": ts},
        ]
        sqlite_store.rewrite_all([], works, edges)
        res = admin.restore("edges", e1)
        self.assertTrue(res["ok"])
        self.assertEqual(sorted(res["cascade"]["works"]), sorted([w1, w2]))
        saved_works = sqlite_store.list_all()["works"]
        self.assertFalse(next(r for r in saved_works if r["id"] == w1).get("deletedAt"))
        self.assertFalse(next(r for r in saved_works if r["id"] == w2).get("deletedAt"))

    def test_admin_create_persists_and_audits(self) -> None:
        import app.admin as admin

        res = admin.create("authors", {"originalName": "某", "Name_CN": "某"})
        self.assertTrue(res["ok"])
        # 行级写入落库 + 审计记录
        data = sqlite_store.list_all()
        self.assertEqual(len(data["authors"]), 1)
        audit = sqlite_store.list_audit()
        self.assertEqual(audit["total"], 1)
        self.assertEqual(audit["items"][0]["action"], "create")
        self.assertEqual(audit["items"][0]["kind"], "authors")

    def test_admin_token_rejects_placeholder(self) -> None:
        import app.admin as admin

        with patch("app.admin.os.getenv", return_value="change-me-to-a-long-random-token"):
            with self.assertRaises(HTTPException) as ctx:
                admin.require_admin_token(None)
        self.assertEqual(ctx.exception.status_code, 503)

    def test_admin_token_rejects_wrong_credentials(self) -> None:
        import app.admin as admin

        with patch("app.admin.os.getenv", return_value="a-very-long-and-strong-token-value"):
            creds = admin.HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")
            with self.assertRaises(HTTPException) as ctx:
                admin.require_admin_token(creds)
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()

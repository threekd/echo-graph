"""后端应用冒烟:SQLite 读取模式下路由注册、版本与基础接口。"""

from __future__ import annotations

import tempfile
import tomllib
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main  # noqa: E402
from app import auth, db_sqlite, sqlite_store  # noqa: E402
from app.db import SqliteStore
from tests._helpers import rewrite_all  # noqa: E402


class ApiSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        # 管理写入走 SQLite:全部隔离到临时库,且不落盘 CSV/版本目录
        self.tmp = tempfile.TemporaryDirectory()
        patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "echo-graph.db").start()
        # 固定引导管理员,保证 admin 路径与角色不依赖机器 .env
        self.admin_email = "admin@test.local"
        patch.object(auth, "BOOTSTRAP_EMAIL", self.admin_email).start()
        auth.register(self.admin_email, "admin-password-123", username="admin")
        self.admin_id = auth.admin_user_id()
        self.assertIsNotNone(self.admin_id)
        # 所有 setUp 补丁必须在测试结束时复原,避免泄漏影响后续模块(顺序无关)
        self.addCleanup(patch.stopall)
        self.addCleanup(self.tmp.cleanup)

    def seed(self, authors=(), works=(), edges=(), owner_id: str | None = None) -> None:
        """按 admin 空间造数:所有行显式归属,避免依赖未认领过渡态。"""
        owner = owner_id if owner_id is not None else self.admin_id
        rewrite_all(
            [{**r, "owner_id": owner} for r in authors],
            [{**r, "owner_id": owner} for r in works],
            [{**r, "owner_id": owner} for r in edges],
        )

    def test_expected_routes_registered(self) -> None:
        paths = {
            getattr(r, "path", None)
            for r in main.app.routes
            if getattr(r, "path", None)
        }
        for expected in (
            "/",
            "/api/health",
            "/assets/{path:path}",
        ):
            self.assertIn(expected, paths)
        # 公共星云/官方图谱概念已移除:不再注册面向"默认视图"的 /api 只读端点
        for gone in (
            "/api/graph",
            "/api/search",
            "/api/work/{work_id}",
            "/api/expansion/{work_id}",
            "/api/path",
            "/api/stats",
        ):
            self.assertNotIn(gone, paths)

    def test_admin_and_auth_routes_registered(self) -> None:
        """管理/账号路由挂在 include 的 router 下,用 OpenAPI 路径断言。"""
        paths = main.app.openapi()["paths"]
        self.assertIn("/api/admin/data", paths)
        self.assertIn("/api/admin/backups", paths)
        self.assertIn("/api/admin/audit", paths)
        self.assertIn("/api/auth/register", paths)
        self.assertIn("/api/auth/login", paths)
        self.assertIn("/api/auth/logout", paths)
        self.assertIn("/api/auth/me", paths)
        self.assertIn("/api/auth/config", paths)
        self.assertIn("/api/me/graph", paths)
        self.assertIn("/api/me/stats", paths)
        self.assertIn("/api/me/search", paths)
        self.assertIn("/api/me/data", paths)
        self.assertIn("/api/me/work/{work_id}", paths)
        self.assertIn("/api/me/expansion/{work_id}", paths)
        self.assertIn("/api/me/path", paths)
        self.assertIn("/api/me/{kind}", paths)
        self.assertIn("/api/space/random/graph", paths)
        self.assertIn("/api/space/{user_id}/graph", paths)
        self.assertIn("/api/space/{user_id}/search", paths)
        self.assertIn("/api/space/{user_id}/work/{work_id}", paths)
        self.assertIn("/api/space/{user_id}/expansion/{work_id}", paths)
        self.assertIn("/api/space/{user_id}/path", paths)
        self.assertIn("/api/space/{user_id}/stats", paths)

    def test_version_matches_pyproject(self) -> None:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject.open("rb") as fh:
            expected = tomllib.load(fh)["project"]["version"]
        self.assertEqual(main.app.version, expected)

    def test_stats_and_health(self) -> None:
        stats = SqliteStore(owner_id=self.admin_id).stats()
        self.assertEqual(stats["store"], "sqlite")
        self.assertIn("authors", stats)
        self.assertIn("works", stats)
        health = main.health()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["store"], "sqlite")

    def test_graph_is_empty_on_fresh_db(self) -> None:
        g = SqliteStore(owner_id=self.admin_id).graph()
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
        g = SqliteStore(owner_id=self.admin_id).graph(status="reviewed")
        self.assertEqual(g["nodes"], [])
        self.assertEqual(g["edges"], [])
        stats = SqliteStore(owner_id=self.admin_id).stats()
        self.assertIn("reviewStatus", stats)
        self.assertIn("authors", stats["reviewStatus"])
        self.assertIn("works", stats["reviewStatus"])
        self.assertIn("edges", stats["reviewStatus"])

    def test_search_blank_returns_empty(self) -> None:
        """路由层(/api/me/search)对纯空白 q 返回空结果,而不是全量命中。"""
        client = TestClient(main.app)
        client.cookies.set(auth.SESSION_COOKIE, auth.create_session(self.admin_id))
        for q in ("   ", "\t\n ", "a b"):
            resp = client.get("/api/me/search", params={"q": q})
            self.assertEqual(resp.status_code, 200, q)
            if q.strip() == "":
                self.assertEqual(resp.json(), {"hits": []}, q)
            else:
                self.assertIsInstance(resp.json()["hits"], list, q)

    def test_admin_create_sets_timestamps_and_reviewed_status(self) -> None:
        import app.admin as admin

        res = admin.create(
            "authors",
            {"originalName": "  \u200b某作家\u200b  ", "Name_CN": "  某\u200b  "},
        )
        row = res["row"]
        self.assertTrue(row["createdAt"])
        self.assertTrue(row["updatedAt"])
        self.assertEqual(row["reviewStatus"], "reviewed")  # admin 手动新增默认已审核
        self.assertEqual(row["originalName"], "某作家")  # 落盘前去除首尾空白与零宽字符
        self.assertEqual(row["Name_CN"], "某")
        # 行级写入已落库
        self.assertEqual(len(sqlite_store.list_all()["authors"]), 1)

    def test_admin_create_work_defaults_reading_status_unread(self) -> None:
        """新增作品默认阅读状态为「未读」。"""
        import app.admin as admin

        author = {"id": str(uuid.uuid4()), "originalName": "A", "Name_CN": "甲"}
        self.seed([author])
        row = admin.create("works", {
            "language": "zh",
            "originalTitle": "T",
            "Title_CN": "某书",
            "author_id": author["id"],
        })["row"]
        self.assertEqual(row["readingStatus"], "unread")

    def test_admin_partial_update_work_reading_status(self) -> None:
        """行内编辑:只传 readingStatus 也能更新,其他字段与作者关联保留。"""
        import app.admin as admin

        a = {"id": str(uuid.uuid4()), "originalName": "A", "Name_CN": "甲"}
        w = {
            "id": str(uuid.uuid4()),
            "language": "zh",
            "originalTitle": "T",
            "Title_CN": "某书",
            "author_id": a["id"],
            "updatedAt": "2026-08-20T08:00:00+00:00",
        }
        self.seed([a], [w], [])
        res = admin.update(
            "works", w["id"], {"readingStatus": "read", "updatedAt": w["updatedAt"]}
        )
        row = res["row"]
        self.assertEqual(row["readingStatus"], "read")
        self.assertEqual(row["Title_CN"], "某书")
        self.assertEqual(row["language"], "zh")
        saved = next(x for x in sqlite_store.list_all()["works"] if x["id"] == w["id"])
        self.assertEqual(saved["author_id"], a["id"])  # 作者关联保留

    def test_admin_update_bumps_updated_at_keeps_created_at(self) -> None:
        import app.admin as admin

        author = {
            "id": "01a013e6-e885-766b-b9db-315d518adeeb",
            "originalName": "旧名",
            "Name_CN": "旧中文名",
            "createdAt": "2026-01-01T00:00:00+00:00",
            "updatedAt": "2026-01-01T00:00:00+00:00",
        }
        self.seed([author])
        res = admin.update(
            "authors",
            author["id"],
            {
                "originalName": "新名",
                "Name_CN": "新中文名",
                "updatedAt": author["updatedAt"],
            },
        )
        row = res["row"]
        self.assertEqual(row["createdAt"], "2026-01-01T00:00:00+00:00")
        self.assertTrue(row["updatedAt"])
        saved = sqlite_store.list_all()["authors"][0]
        self.assertEqual(saved["originalName"], "新名")
        self.assertEqual(saved["createdAt"], "2026-01-01T00:00:00+00:00")
        audit = sqlite_store.list_audit()
        self.assertEqual(audit["items"][0]["action"], "update")
        self.assertIn("Name_CN: 旧中文名 → 新中文名", audit["items"][0]["detail"])

    def test_admin_update_requires_updated_at(self) -> None:
        """乐观并发守卫:编辑必须携带 updatedAt,缺失 400。"""
        import app.admin as admin

        author = {
            "id": "01a013e6-e885-766b-b9db-315d518adeeb",
            "originalName": "A",
            "Name_CN": "甲",
            "updatedAt": "2026-08-20T08:00:00+00:00",
        }
        self.seed([author])
        with self.assertRaises(HTTPException) as ctx:
            admin.update("authors", author["id"], {"originalName": "B", "Name_CN": "乙"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("updatedAt", ctx.exception.detail)

    def test_admin_update_optimistic_lock_conflict(self) -> None:
        """更新时 updatedAt 已被他人改动 -> 409 乐观锁冲突。"""
        import app.admin as admin

        author = {
            "id": "01a013e6-e885-766b-b9db-315d518adeeb",
            "originalName": "A", "Name_CN": "甲",
            "updatedAt": "2026-08-20T08:00:00+00:00",
        }
        self.seed([author])
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
        self.seed(authors)
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
        self.seed([], works, edges)
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
        self.seed([], works, [])
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
        self.seed([], works, edges)
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
        self.seed(authors, works, edges)
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
        self.seed([], works, edges)
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
        self.seed(authors, works, edges)
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
        self.seed([], works, edges)
        res = admin.restore("edges", e1)
        self.assertTrue(res["ok"])
        self.assertEqual(sorted(res["cascade"]["works"]), sorted([w1, w2]))
        saved_works = sqlite_store.list_all()["works"]
        self.assertFalse(next(r for r in saved_works if r["id"] == w1).get("deletedAt"))
        self.assertFalse(next(r for r in saved_works if r["id"] == w2).get("deletedAt"))

    def test_admin_permanent_delete_requires_soft_deleted(self) -> None:
        """未软删除的行不允许永久删除(400)。"""
        import app.admin as admin

        author = {"id": str(uuid.uuid4()), "originalName": "A", "Name_CN": "甲"}
        self.seed([author])
        with self.assertRaises(HTTPException) as ctx:
            admin.permanent_delete("authors", author["id"])
        self.assertEqual(ctx.exception.status_code, 400)

    def test_admin_permanent_delete_work_and_edges(self) -> None:
        """软删作品后永久删除:作品与相关涟漪均物理消失,无关作品保留。"""
        import app.admin as admin

        w1, w2, e1 = (str(uuid.uuid4()) for _ in range(3))
        works = [
            {"id": w1, "language": "en", "originalTitle": "A", "Title_CN": "甲书"},
            {"id": w2, "language": "en", "originalTitle": "B", "Title_CN": "乙书"},
        ]
        edges = [{"id": e1, "source_work_id": w1, "target_work_id": w2, "evidence": "x"}]
        self.seed([], works, edges)
        admin.delete("works", w1)
        res = admin.permanent_delete("works", w1)
        self.assertTrue(res["ok"])
        data = sqlite_store.list_all()
        work_ids = [r["id"] for r in data["works"]]
        edge_ids = [r["id"] for r in data["edges"]]
        self.assertNotIn(w1, work_ids)
        self.assertNotIn(e1, edge_ids)
        self.assertIn(w2, work_ids)

    def test_admin_permanent_delete_author_cascades(self) -> None:
        """软删作者后永久删除:作者/名下作品/相关涟漪全部物理消失。"""
        import app.admin as admin

        a1, w1, w2, e1 = (str(uuid.uuid4()) for _ in range(4))
        authors = [{"id": a1, "originalName": "A", "Name_CN": "甲"}]
        works = [
            {"id": w1, "language": "en", "originalTitle": "A", "Title_CN": "甲书", "author_id": a1},
            {"id": w2, "language": "en", "originalTitle": "B", "Title_CN": "乙书"},
        ]
        edges = [{"id": e1, "source_work_id": w1, "target_work_id": w2, "evidence": "x"}]
        self.seed(authors, works, edges)
        admin.delete("authors", a1)
        res = admin.permanent_delete("authors", a1)
        self.assertTrue(res["ok"])
        data = sqlite_store.list_all()
        author_ids = {r["id"] for r in data["authors"]}
        work_ids = {r["id"] for r in data["works"]}
        edge_ids = {r["id"] for r in data["edges"]}
        self.assertNotIn(a1, author_ids)
        self.assertNotIn(w1, work_ids)
        self.assertNotIn(e1, edge_ids)
        self.assertIn(w2, work_ids)  # 无关作品保留

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
        self.assertIn("新增", audit["items"][0]["detail"])
        self.assertIsNotNone(audit["items"][0]["after"])

if __name__ == "__main__":
    unittest.main()

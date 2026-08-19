"""后端应用冒烟:JSON 兜底模式下路由注册、版本与基础接口。"""

from __future__ import annotations

import os
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

os.environ["ECHO_STORE"] = "json"  # 必须在导入 app.main 前设置,避免触网

import app.db as db  # noqa: E402
import app.main as main  # noqa: E402


class ApiSmokeTest(unittest.TestCase):
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
            "/vendor/{path:path}",
        ):
            self.assertIn(expected, paths)

    def test_version_matches_pyproject(self) -> None:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject.open("rb") as fh:
            expected = tomllib.load(fh)["project"]["version"]
        self.assertEqual(main.app.version, expected)

    def test_stats_and_health(self) -> None:
        stats = main.store.stats()
        self.assertEqual(stats["store"], "json")
        self.assertIn("authors", stats)
        self.assertIn("works", stats)
        health = main.health()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["store"], "json")
        self.assertEqual(health["fallbacks"], 0)

    def test_json_store_is_empty_by_default(self) -> None:
        g = main.store.graph()
        self.assertEqual(g["nodes"], [])
        self.assertEqual(g["edges"], [])

    def test_resilient_store_exposes_name(self) -> None:
        class FakePrimary:
            name = "neo4j"

            def stats(self) -> dict:
                return {"store": "neo4j"}

        r = db.ResilientStore(FakePrimary(), db.JsonStore())
        self.assertEqual(r.name, "neo4j")
        self.assertEqual(r.stats()["store"], "neo4j")
        self.assertEqual(r.stats()["fallbacks"], 0)

    def test_static_serving_rejects_path_traversal(self) -> None:
        cases = [
            (main.frontend_assets, "../../../pyproject.toml"),
            (main.frontend_assets, "..%2f..%2f.env"),
            (main.frontend_vendor, "..\\..\\..\\pyproject.toml"),
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

        with (
            patch("app.admin.load_rows", return_value=([], [], [])),
            patch("app.admin.save_rows"),
            patch("app.admin.snapshot", return_value=None),
        ):
            res = admin.create("authors", {"originalName": "  某作家  ", "Name_CN": "  某  "})
        row = res["row"]
        self.assertTrue(row["createdAt"])
        self.assertTrue(row["updatedAt"])
        self.assertEqual(row["reviewStatus"], "draft")
        self.assertEqual(row["originalName"], "某作家")  # 落盘前去除首尾空白
        self.assertEqual(row["Name_CN"], "某")

    def test_admin_update_bumps_updated_at_keeps_created_at(self) -> None:
        import app.admin as admin

        author = {
            "id": "01a013e6-e885-766b-b9db-315d518adeeb",
            "originalName": "旧名",
            "Name_CN": "旧中文名",
            "createdAt": "2026-01-01T00:00:00+00:00",
        }
        with (
            patch("app.admin.load_rows", return_value=([author], [], [])),
            patch("app.admin.save_rows"),
            patch("app.admin.snapshot", return_value=None),
        ):
            res = admin.update(
                "authors",
                author["id"],
                {"originalName": "新名", "Name_CN": "新中文名"},
            )
        row = res["row"]
        self.assertEqual(row["createdAt"], "2026-01-01T00:00:00+00:00")
        self.assertTrue(row["updatedAt"])

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

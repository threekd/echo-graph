"""后端应用冒烟:JSON 兜底模式下路由注册、版本与基础接口。"""

from __future__ import annotations

import os
import tomllib
import unittest
from pathlib import Path

os.environ["ECHO_STORE"] = "json"  # 必须在导入 app.main 前设置,避免触网

import app.main as main  # noqa: E402
import app.db as db  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()

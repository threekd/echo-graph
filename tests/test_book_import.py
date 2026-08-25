"""书籍导入 API 测试:提交任务 → mock LLM 提取 → 轮询 → system_llm 草稿入库。

验证 app/book_import 的「上传书籍 → AI 提取 → 去重 → AI 草稿」链路:
mock extract_source_book.run_extract 避免真实 DeepSeek 调用;去重走 basic_only
且关闭 LLM 兜底确认,不触网。草稿入库用 llm_drafts() 断言。
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from fastapi.testclient import TestClient

import app.main as main  # noqa: E402
from app import auth, book_import, data_store, db_sqlite
from app.llm_review import llm_drafts

_ADMIN_EMAIL = "admin@echo.local"


def _synthetic_extract() -> dict:
    """小型合成提取结果:1 源书作者、1 源书作品、1 提及作品与涟漪。"""
    return {
        "source_book": {"title": "测试之书", "authors": ["测试作者"], "language": "zh"},
        "authors": [
            {
                "originalName": "テスト作者",
                "Name_CN": "测试作者",
                "Name_EN": "Test Author",
                "birthYear": 1900,
            }
        ],
        "work": {
            "language": "zh",
            "originalTitle": "测试之书",
            "Title_CN": "测试之书",
            "Title_EN": "Test Book",
            "publicationYear": 1950,
            "genre": "Fiction",
        },
        "ripples": [
            {
                "work": {
                    "language": "en",
                    "originalTitle": "Moby Dick",
                    "Title_CN": "白鲸",
                    "Title_EN": "Moby Dick",
                    "publicationYear": 1851,
                    "genre": "Fiction",
                    "author": "赫尔曼·梅尔维尔",
                },
                "evidence": {
                    "evidence": "书中提到了《白鲸》这部作品。",
                    "evidenceSource": "第一章",
                    "mention_type": "READ_BY_CHARACTER",
                },
            }
        ],
    }


class BookImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "import.db"

        self.patch_db = patch.object(db_sqlite, "DB_PATH", self.db_path)
        self.patch_db.start()
        self.addCleanup(self.patch_db.stop)

        # 涟漪作者补全(LLM)由 entity_extract / llm_pipeline 单测覆盖,此处隔离避免测试触网
        self.patch_enrich = patch.object(
            book_import.entity_extract, "enrich_ripple_authors", return_value=0
        )
        self.patch_enrich.start()
        self.addCleanup(self.patch_enrich.stop)

        self.patch_email = patch.object(auth, "BOOTSTRAP_EMAIL", _ADMIN_EMAIL)
        self.patch_email.start()
        self.addCleanup(self.patch_email.stop)

        # 写入公共星云会触发 CSV 导出,重定向到临时目录避免污染仓库 data/export
        self.patch_export = patch.object(data_store, "EXPORT_DIR", Path(self.tmp.name) / "export")
        self.patch_export.start()
        self.addCleanup(self.patch_export.stop)

        # 批次登记簿写入临时目录,避免污染 app/ai_assistant/output/batches
        self.patch_batch_dir = patch.object(book_import.llm_space, "BATCH_DIR", Path(self.tmp.name) / "batches")
        self.patch_batch_dir.start()
        self.addCleanup(self.patch_batch_dir.stop)

        self.admin = auth.register(_ADMIN_EMAIL, "password123", username="admin01")
        self.assertEqual(self.admin["role"], "admin")

    def _wait_done(self, task_id: str, timeout: float = 20) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = book_import.get_import_task(task_id)
            if task and task["status"] in ("done", "error"):
                return task
            time.sleep(0.05)
        raise AssertionError(f"导入任务未在 {timeout}s 内结束")

    def test_route_registered(self) -> None:
        """导入端点挂在 /api/admin/import-book(POST + GET)。"""
        paths = main.app.openapi()["paths"]
        self.assertIn("/api/admin/import-book", paths)
        self.assertIn("post", paths["/api/admin/import-book"])
        self.assertIn("/api/admin/import-book/{task_id}", paths)
        self.assertIn("get", paths["/api/admin/import-book/{task_id}"])

    def test_http_upload_endpoint(self) -> None:
        """HTTP 协议冒烟:登录 cookie + 原始 body + X-Filename → 轮询任务 → done。"""
        client = TestClient(main.app, raise_server_exceptions=False)
        admin_id = auth.admin_user_id()
        self.assertIsNotNone(admin_id)
        client.cookies.set(auth.SESSION_COOKIE, auth.create_session(admin_id))

        with patch(
            "app.ai_assistant.tools.extract_source_book.run_extract",
            return_value=_synthetic_extract(),
        ):
            r = client.post(
                "/api/admin/import-book?title=测试之书&authors=测试作者&basic_only=true",
                content=b"fake epub bytes",
                headers={"X-Filename": quote("测试之书.epub")},
            )
        self.assertEqual(r.status_code, 200, r.text)
        task_id = r.json()["task_id"]
        self.assertTrue(task_id)

        task = self._wait_done(task_id)
        self.assertEqual(task["status"], "done", task.get("error"))
        self.assertEqual(task["result"]["counts"]["staged"], 5)

        # 状态端点可查询
        r2 = client.get("/api/admin/import-book/" + task_id)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["status"], "done")

    def test_http_upload_rejects_bad_suffix(self) -> None:
        client = TestClient(main.app, raise_server_exceptions=False)
        admin_id = auth.admin_user_id()
        self.assertIsNotNone(admin_id)
        client.cookies.set(auth.SESSION_COOKIE, auth.create_session(admin_id))
        r = client.post(
            "/api/admin/import-book",
            content=b"x",
            headers={"X-Filename": "book.pdf"},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("不支持的文件类型", r.json()["detail"])

    def test_http_upload_allows_vip(self) -> None:
        """VIP 用户可调用导入接口(200,任务正常完成)。"""
        client = TestClient(main.app, raise_server_exceptions=False)
        vip_user = auth.register("vip@test.local", "password123", username="viptest")
        with db_sqlite._db() as conn:
            conn.execute("UPDATE users SET vip = 1 WHERE id = ?", (vip_user["id"],))
        client.cookies.set(auth.SESSION_COOKIE, auth.create_session(vip_user["id"]))

        with patch(
            "app.ai_assistant.tools.extract_source_book.run_extract",
            return_value=_synthetic_extract(),
        ):
            r = client.post(
                "/api/admin/import-book?title=测试之书&basic_only=true",
                content=b"fake epub bytes",
                headers={"X-Filename": quote("测试之书.epub")},
            )
        self.assertEqual(r.status_code, 200, r.text)
        task = self._wait_done(r.json()["task_id"])
        self.assertEqual(task["status"], "done", task.get("error"))
        self.assertEqual(task["result"]["counts"]["staged"], 5)

    def test_http_upload_denies_normal_user(self) -> None:
        """普通(非 VIP)用户调用导入接口被拒 403。"""
        client = TestClient(main.app, raise_server_exceptions=False)
        plain = auth.register("plain@test.local", "password123", username="plaintest")
        client.cookies.set(auth.SESSION_COOKIE, auth.create_session(plain["id"]))
        r = client.post(
            "/api/admin/import-book",
            content=b"x",
            headers={"X-Filename": "book.epub"},
        )
        self.assertEqual(r.status_code, 403)

    def test_http_upload_requires_admin(self) -> None:
        client = TestClient(main.app, raise_server_exceptions=False)
        r = client.post(
            "/api/admin/import-book",
            content=b"x",
            headers={"X-Filename": "book.epub"},
        )
        self.assertEqual(r.status_code, 401)

        """提交任务 → 提取(mock) → 去重 → 草稿入库,结果落 system_llm 空间。"""
        book = Path(self.tmp.name) / "测试之书.epub"
        book.write_bytes(b"fake epub bytes")  # run_extract 被 mock,不真读文件

        with patch(
            "app.ai_assistant.tools.extract_source_book.run_extract",
            return_value=_synthetic_extract(),
        ):
            resp = book_import.submit_import(book, title="测试之书", authors=["测试作者"], basic_only=True)
        task_id = resp["task_id"]
        self.assertTrue(task_id)

        task = self._wait_done(task_id)
        self.assertEqual(task["status"], "done", task.get("error"))
        self.assertIsNone(task["error"])
        self.assertEqual(task["result"]["extracted"], {"authors": 1, "works": 1, "edges": 1})
        self.assertEqual(task["result"]["counts"]["staged"], 5)  # 2 作者(源书+涟漪) + 2 作品(源书+提及) + 1 涟漪
        self.assertEqual(task["result"]["counts"]["failed"], 0)

        # 草稿已写入 system_llm 空间
        drafts = llm_drafts()
        self.assertEqual(drafts["staging"]["counts"]["authors"], 2)
        self.assertEqual(drafts["staging"]["counts"]["works"], 2)
        self.assertEqual(drafts["staging"]["counts"]["edges"], 1)

        # 批次登记簿已保存到临时 BATCH_DIR
        self.assertTrue(book_import.llm_space.batch_path(task["result"]["batch_id"]).exists())

    def test_unsupported_suffix_rejected(self) -> None:
        book = Path(self.tmp.name) / "book.pdf"
        book.write_bytes(b"x")
        with self.assertRaises(ValueError):
            book_import.submit_import(book)

    def test_reasoning_progress_hook_lands_in_task_log(self) -> None:
        """解析中 LLM 推理进度(on_log)写入任务日志,前端即可展示「思考中...已接收」。"""
        book = Path(self.tmp.name) / "进度.epub"
        book.write_bytes(b"fake epub bytes")

        def fake_extract(book_path, **kwargs):
            on_log = kwargs.get("on_log")
            if on_log:
                on_log("  思考中... 已接收 1000 字符")
                on_log("  思考中... 已接收 2000 字符")
            return _synthetic_extract()

        with patch(
            "app.ai_assistant.tools.extract_source_book.run_extract",
            side_effect=fake_extract,
        ):
            task_id = book_import.submit_import(
                book, title="测试之书", authors=["测试作者"], basic_only=True
            )["task_id"]
        task = self._wait_done(task_id)
        self.assertEqual(task["status"], "done", task.get("error"))
        self.assertIn("  思考中... 已接收 1000 字符", task["log"])
        self.assertIn("  思考中... 已接收 2000 字符", task["log"])

    def test_missing_file_rejected(self) -> None:
        with self.assertRaises(ValueError):
            book_import.submit_import(Path(self.tmp.name) / "nope.epub")

    def test_extract_error_recorded(self) -> None:
        """run_extract 抛异常 → 任务 error,错误信息可读。"""
        book = Path(self.tmp.name) / "坏书.epub"
        book.write_bytes(b"x")

        def boom(*_args, **_kwargs):
            raise RuntimeError("LLM 服务不可用")

        with patch("app.ai_assistant.tools.extract_source_book.run_extract", side_effect=boom):
            task_id = book_import.submit_import(book)["task_id"]

        task = self._wait_done(task_id)
        self.assertEqual(task["status"], "error")
        self.assertIn("LLM 服务不可用", task["error"])

    def test_unknown_task_returns_none(self) -> None:
        self.assertIsNone(book_import.get_import_task("no-such-task"))


if __name__ == "__main__":
    unittest.main()

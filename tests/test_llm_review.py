"""AI 草稿审核 API 测试:导入者 = 审核者 = 发布到自己星云。

覆盖:
- admin / VIP 只能看到并审核自己上传的草稿,互不审核;
- VIP 批准自己上传的作者/作品/涟漪后,发布目标 = 自己的星云;
- 涟漪去重提示通过草稿作品的 published_to_id 解析到自己的星云(回归:
  此前误用边 id 查 works 表导致映射恒为空);
- 清空草稿只清当前上传者自己的草稿;
- HTTP 层:VIP 可访问 /api/admin/llm/*,普通用户 403,未登录 401;
- 普通用户空间行(created_by != 'llm')不能经草稿审核接口操作。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main
from app import auth, db_sqlite, sqlite_store
from app.llm_review import (
    approve_draft,
    approve_ripple,
    approve_source,
    clear_drafts,
    llm_drafts,
)

_ADMIN_EMAIL = "admin@echo.local"


def _insert_draft_row(kind: str, row: dict, owner_id: str) -> str:
    """直接落一条 AI 草稿行(created_by='llm'、reviewStatus='draft')。"""
    row = dict(row)
    row.setdefault("id", db_sqlite.new_uuid())
    row["reviewStatus"] = "draft"
    now = db_sqlite.now_iso()
    row.setdefault("createdAt", now)
    row["updatedAt"] = now
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        sqlite_store.insert_row(conn, kind, row, owner_id=owner_id, extra={"created_by": "llm"})
        return row["id"]


def _stage_chain(owner_id: str, tag: str = "") -> dict:
    """在一个上传者空间直接落一条 AI 草稿链:作者 + 源作品 + 目标作品 + 涟漪。"""
    author_id = _insert_draft_row(
        "authors",
        {"originalName": f"オリジナル{tag}", "Name_CN": f"作者{tag}"},
        owner_id,
    )
    w1 = _insert_draft_row(
        "works",
        {"language": "zh", "originalTitle": f"源书{tag}", "Title_CN": f"源书{tag}"},
        owner_id,
    )
    w2 = _insert_draft_row(
        "works",
        {"language": "en", "originalTitle": f"Target {tag}", "Title_CN": f"目标书{tag}"},
        owner_id,
    )
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        sqlite_store.set_work_authors(conn, w1, [author_id])
        sqlite_store.set_work_authors(conn, w2, [author_id])
    edge_id = _insert_draft_row(
        "edges",
        {
            "source_work_id": w1,
            "target_work_id": w2,
            "evidence": f"正文提及了《目标书{tag}》。",
            "evidenceSource": "第一章",
        },
        owner_id,
    )
    return {"author_id": author_id, "work1": w1, "work2": w2, "edge_id": edge_id}


class LlmReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.patch_db = patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "llm.db")
        self.patch_db.start()
        self.addCleanup(self.patch_db.stop)

        self.patch_email = patch.object(auth, "BOOTSTRAP_EMAIL", _ADMIN_EMAIL)
        self.patch_email.start()
        self.addCleanup(self.patch_email.stop)

        # 批准会触发 CSV 导出(仅引导管理员),测试中置空,避免污染仓库 data/export
        self.patch_export = patch("app.space_crud.export_csv_files", lambda: None)
        self.patch_export.start()
        self.addCleanup(self.patch_export.stop)

        self.admin = auth.register(_ADMIN_EMAIL, "password123", username="admin01")
        self.assertEqual(self.admin["role"], "admin")
        self.vip = auth.register("vip@echo.local", "password123", username="viper01")
        with db_sqlite._db() as conn:
            conn.execute("UPDATE users SET vip = 1 WHERE id = ?", (self.vip["id"],))
        self.vip["vip"] = True

    def test_uploader_sees_only_own_drafts(self) -> None:
        """admin / VIP 各自只能看到自己上传的草稿,互不审核。"""
        _stage_chain(self.vip["id"], "A")
        _stage_chain(self.admin["id"], "B")

        drafts_vip = llm_drafts(self.vip)
        self.assertEqual(drafts_vip["counts"]["batches"], 1)
        self.assertEqual(drafts_vip["batches"][0]["source"]["work"]["Title_CN"], "源书A")
        drafts_admin = llm_drafts(self.admin)
        self.assertEqual(drafts_admin["counts"]["batches"], 1)
        self.assertEqual(drafts_admin["batches"][0]["source"]["work"]["Title_CN"], "源书B")
        # 双方都能看到自己星云的数据量(space_counts)
        self.assertIn("space_counts", drafts_vip)
        self.assertIn("space_counts", drafts_admin)

    def test_cross_uploader_review_rejected(self) -> None:
        """VIP 不能审核 admin 的草稿,admin 也不能审核 VIP 的草稿(404)。"""
        chain_vip = _stage_chain(self.vip["id"], "A")
        chain_admin = _stage_chain(self.admin["id"], "B")
        with self.assertRaises(HTTPException) as ctx:
            approve_draft("authors", chain_vip["author_id"], None, self.admin)
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(HTTPException) as ctx:
            approve_draft("authors", chain_admin["author_id"], None, self.vip)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_vip_approves_own_author_draft_publishes_to_own_space(self) -> None:
        """VIP 批准自己上传的作者草稿:发布到自己的星云(owner_id=VIP)。"""
        chain = _stage_chain(self.vip["id"], "A")
        result = approve_draft("authors", chain["author_id"], None, self.vip)
        self.assertEqual(result["mode"], "copy")
        pub_id = result["public_id"]

        with db_sqlite._db() as conn:
            pub = conn.execute("SELECT * FROM authors WHERE id = ?", (pub_id,)).fetchone()
            self.assertEqual(pub["owner_id"], self.vip["id"])
            self.assertEqual(pub["created_by"], "llm")
            self.assertEqual(pub["reviewStatus"], "reviewed")
            draft = conn.execute(
                "SELECT published_to_id FROM authors WHERE id = ?", (chain["author_id"],)
            ).fetchone()
            self.assertEqual(draft["published_to_id"], pub_id)

    def test_vip_approves_own_ripple(self) -> None:
        """VIP 批准自己上传的涟漪:作者/作品/涟漪全部落到自己的星云。"""
        chain = _stage_chain(self.vip["id"], "A")
        result = approve_ripple(chain["edge_id"], None, self.vip)
        ids = result["public_ids"]
        with db_sqlite._db() as conn:
            for kind, row_id in (
                ("authors", ids["source_authors"][0]),
                ("works", ids["source_work"]),
                ("edges", ids["edge"]),
            ):
                row = conn.execute(
                    f"SELECT owner_id FROM {kind} WHERE id = ?", (row_id,)
                ).fetchone()
                self.assertEqual(row["owner_id"], self.vip["id"])
            draft_edge = conn.execute(
                "SELECT published_to_id FROM edges WHERE id = ?", (chain["edge_id"],)
            ).fetchone()
            self.assertEqual(draft_edge["published_to_id"], ids["edge"])

    def test_edge_hint_resolves_published_work_via_published_to_id(self) -> None:
        """回归:边去重提示用草稿作品的 published_to_id 解析到自己星云的 id。

        发布到自己的星云后若对发布行策展改名(标题不再精确匹配),仍能靠
        published_to_id 映射解析;此前误用边 id 查 works 表导致映射恒为空。
        """
        chain = _stage_chain(self.vip["id"], "A")
        approve_source(chain["work1"], None, self.vip)
        approve_source(chain["work2"], None, self.vip)
        with db_sqlite._db() as conn:
            pub_work1 = conn.execute(
                "SELECT published_to_id FROM works WHERE id = ?", (chain["work1"],)
            ).fetchone()["published_to_id"]
            pub_work2 = conn.execute(
                "SELECT published_to_id FROM works WHERE id = ?", (chain["work2"],)
            ).fetchone()["published_to_id"]
            # 模拟策展改名:发布行标题与草稿不再精确匹配
            conn.execute(
                "UPDATE works SET Title_CN = ?, originalTitle = ? WHERE id = ?",
                ("星云修订名", "Revised", pub_work1),
            )
            now = db_sqlite.now_iso()
            conn.execute(
                "INSERT INTO edges (id, source_work_id, target_work_id, evidence,"
                " evidenceSource, reviewStatus, created_by, owner_id, createdAt, updatedAt)"
                " VALUES (?, ?, ?, ?, ?, 'reviewed', 'curated', ?, ?, ?)",
                (db_sqlite.new_uuid(), pub_work1, pub_work2, "星云证据", "星云出处",
                 self.vip["id"], now, now),
            )

        drafts = llm_drafts(self.vip)
        self.assertEqual(len(drafts["batches"]), 1)
        ripple = drafts["batches"][0]["ripples"][0]
        self.assertIsNotNone(ripple["edge_hint"])
        self.assertEqual(ripple["edge_hint"]["level"], "edge_duplicate")

    def test_clear_drafts_only_own(self) -> None:
        """清空草稿只清当前上传者自己的,不影响其他上传者。"""
        _stage_chain(self.vip["id"], "A")
        _stage_chain(self.admin["id"], "B")

        result = clear_drafts(self.vip)
        self.assertEqual(result["counts"], {"authors": 1, "works": 2, "edges": 1})
        self.assertEqual(llm_drafts(self.vip)["counts"]["batches"], 0)
        self.assertEqual(llm_drafts(self.admin)["counts"]["batches"], 1)

    def test_non_llm_row_not_reviewable_via_draft_endpoints(self) -> None:
        """普通用户空间行(created_by != 'llm')不能经草稿审核接口操作。"""
        now = db_sqlite.now_iso()
        with db_sqlite._write_lock, db_sqlite._db() as conn:
            row = {
                "id": db_sqlite.new_uuid(),
                "originalName": "X",
                "Name_CN": "普通行",
                "reviewStatus": "reviewed",
                "createdAt": now,
                "updatedAt": now,
            }
            sqlite_store.insert_row(
                conn, "authors", row, owner_id=self.vip["id"], extra={"created_by": "user"}
            )
            author_id = row["id"]

        with self.assertRaises(HTTPException) as ctx:
            approve_draft("authors", author_id, None, self.vip)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_http_access_gates(self) -> None:
        """HTTP 层:/api/admin/llm/drafts 对 VIP 开放,普通用户 403,未登录 401。"""
        client = TestClient(main.app, raise_server_exceptions=False)
        client.cookies.set(auth.SESSION_COOKIE, auth.create_session(self.vip["id"]))
        self.assertEqual(client.get("/api/admin/llm/drafts").status_code, 200)

        plain = auth.register("plain@echo.local", "password123", username="plainuser")
        client2 = TestClient(main.app, raise_server_exceptions=False)
        client2.cookies.set(auth.SESSION_COOKIE, auth.create_session(plain["id"]))
        self.assertEqual(client2.get("/api/admin/llm/drafts").status_code, 403)

        client3 = TestClient(main.app, raise_server_exceptions=False)
        self.assertEqual(client3.get("/api/admin/llm/drafts").status_code, 401)


if __name__ == "__main__":
    unittest.main()

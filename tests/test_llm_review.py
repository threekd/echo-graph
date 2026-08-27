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
    ApproveBody,
    ReuseAuthorBody,
    ReuseWorkBody,
    approve_draft,
    approve_ripple,
    approve_source,
    clear_drafts,
    edit_draft,
    llm_drafts,
    reject_draft,
    reopen_draft,
    reuse_draft_author,
    reuse_draft_work,
)
from app.me import my_create

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

        result = clear_drafts(user=self.vip)
        self.assertEqual(result["counts"], {"authors": 1, "works": 2, "edges": 1})
        self.assertEqual(llm_drafts(self.vip)["counts"]["batches"], 0)
        self.assertEqual(llm_drafts(self.admin)["counts"]["batches"], 1)

    def test_clear_draft_batch_only(self) -> None:
        """按批次清空:只软删除该批次相关草稿,其他批次不受影响。"""
        batch_a = _stage_chain(self.vip["id"], "A")
        _stage_chain(self.vip["id"], "B")

        result = clear_drafts({"work_id": batch_a["work1"]}, self.vip)
        self.assertEqual(result["counts"], {"authors": 1, "works": 2, "edges": 1})
        drafts = llm_drafts(self.vip)
        self.assertEqual(drafts["counts"]["batches"], 1)
        titles = [b["source"]["work"]["Title_CN"] for b in drafts["batches"]]
        self.assertEqual(titles, ["源书B"])
        with db_sqlite._db() as conn:
            deleted_a = conn.execute(
                "SELECT count(*) c FROM works WHERE id = ? AND deletedAt IS NOT NULL",
                (batch_a["work1"],),
            ).fetchone()["c"]
            self.assertEqual(deleted_a, 1)
            alive_b = conn.execute(
                "SELECT count(*) c FROM works WHERE id = ? AND deletedAt IS NULL",
                (batch_a["work1"],),
            ).fetchone()["c"]
            self.assertEqual(alive_b, 0)

    def test_clear_draft_batch_keeps_shared_rows(self) -> None:
        """按批次清空:被其他批次引用的共享作者保留,避免破坏其他批次。"""
        batch_a = _stage_chain(self.vip["id"], "A")
        batch_b = _stage_chain(self.vip["id"], "B")
        # 让批次 B 的源书作品也关联批次 A 的作者(跨批次共享)
        with db_sqlite._write_lock, db_sqlite._db() as conn:
            conn.execute(
                "INSERT INTO work_authors (work_id, author_id) VALUES (?, ?)",
                (batch_b["work1"], batch_a["author_id"]),
            )

        result = clear_drafts({"work_id": batch_a["work1"]}, self.vip)
        self.assertEqual(result["counts"], {"authors": 0, "works": 2, "edges": 1})
        with db_sqlite._db() as conn:
            alive = conn.execute(
                "SELECT count(*) c FROM authors WHERE id = ? AND deletedAt IS NULL",
                (batch_a["author_id"],),
            ).fetchone()["c"]
            self.assertEqual(alive, 1)
        # 批次 B 的源书作者仍包含共享作者 A
        drafts = llm_drafts(self.vip)
        authors_b = next(
            b for b in drafts["batches"] if b["source"]["work"]["Title_CN"] == "源书B"
        )["source"]["authors"]
        self.assertIn(batch_a["author_id"], [a["id"] for a in authors_b])

    def test_clear_batch_with_personal_source_work(self) -> None:
        """编辑涟漪改源为个人库作品后,清空该批次:个人库源书保留,草稿边/目标删除。"""
        batch = _stage_chain(self.vip["id"], "A")
        now = db_sqlite.now_iso()
        with db_sqlite._write_lock, db_sqlite._db() as conn:
            manual_w = db_sqlite.new_uuid()
            conn.execute(
                "INSERT INTO works (id, language, originalTitle, Title_CN, reviewStatus,"
                " createdAt, updatedAt, created_by, owner_id)"
                " VALUES (?, 'zh', '个人库源书', '个人库源书', 'reviewed', ?, ?, 'user', ?)",
                (manual_w, now, now, self.vip["id"]),
            )
            # 让草稿作者只关联目标作品(排除孤儿源书 w1A 的关联),便于断言作者一并删除
            conn.execute(
                "DELETE FROM work_authors WHERE work_id = ?", (batch["work1"],)
            )
        edit_draft(
            "edges",
            batch["edge_id"],
            {
                "source_work_id": manual_w,
                "target_work_id": batch["work2"],
                "evidence": "正文提及了《目标书A》。",
                "evidenceSource": "第一章",
            },
            self.vip,
        )
        result = clear_drafts({"work_id": manual_w}, self.vip)
        self.assertEqual(result["counts"], {"authors": 1, "works": 1, "edges": 1})
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT deletedAt FROM works WHERE id = ?", (manual_w,)
            ).fetchone()
            self.assertIsNone(row["deletedAt"])  # 个人库源书保留
            row = conn.execute(
                "SELECT deletedAt FROM works WHERE id = ?", (batch["work2"],)
            ).fetchone()
            self.assertIsNotNone(row["deletedAt"])  # 草稿目标作品删除
            row = conn.execute(
                "SELECT deletedAt FROM edges WHERE id = ?", (batch["edge_id"],)
            ).fetchone()
            self.assertIsNotNone(row["deletedAt"])

    def test_clear_batch_after_source_reuse(self) -> None:
        """复用源书后清空批次:源书草稿(保留映射)被软删,已发布映射不受影响。"""
        batch = _stage_chain(self.vip["id"], "A")
        now = db_sqlite.now_iso()
        with db_sqlite._write_lock, db_sqlite._db() as conn:
            manual_w = db_sqlite.new_uuid()
            conn.execute(
                "INSERT INTO works (id, language, originalTitle, Title_CN, reviewStatus,"
                " createdAt, updatedAt, created_by, owner_id)"
                " VALUES (?, 'zh', '已有源书', '已有源书', 'reviewed', ?, ?, 'user', ?)",
                (manual_w, now, now, self.vip["id"]),
            )
        reuse_draft_work(batch["work1"], ReuseWorkBody(reuse_id=manual_w), self.vip)
        result = clear_drafts({"work_id": batch["work1"]}, self.vip)
        self.assertEqual(result["counts"], {"authors": 1, "works": 2, "edges": 1})
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT deletedAt, published_to_id FROM works WHERE id = ?",
                (batch["work1"],),
            ).fetchone()
            self.assertIsNotNone(row["deletedAt"])
            self.assertEqual(row["published_to_id"], manual_w)  # 映射保留,已发布数据不受影响

    def test_drafts_space_includes_personal_library(self) -> None:
        """编辑弹窗下拉数据(space):含个人库手动新增的作者/作品,排除 AI 草稿。"""
        batch = _stage_chain(self.vip["id"], "A")
        now = db_sqlite.now_iso()
        with db_sqlite._write_lock, db_sqlite._db() as conn:
            manual_w = db_sqlite.new_uuid()
            conn.execute(
                "INSERT INTO works (id, language, originalTitle, Title_CN, reviewStatus,"
                " createdAt, updatedAt, created_by, owner_id)"
                " VALUES (?, 'zh', '手动作品', '手动作品', 'reviewed', ?, ?, 'user', ?)",
                (manual_w, now, now, self.vip["id"]),
            )
        drafts = llm_drafts(self.vip)
        space_works = [w["id"] for w in drafts["space"]["works"]]
        self.assertIn(manual_w, space_works)
        self.assertNotIn(batch["work1"], space_works)  # AI 草稿作品不进个人库下拉
        self.assertNotIn(batch["work2"], space_works)

    def test_edit_edge_source_to_personal_work_stays_visible(self) -> None:
        """编辑涟漪把源作品改为个人库作品后,涟漪仍可见(归入该作品的批次)。"""
        batch = _stage_chain(self.vip["id"], "A")
        now = db_sqlite.now_iso()
        with db_sqlite._write_lock, db_sqlite._db() as conn:
            manual_w = db_sqlite.new_uuid()
            conn.execute(
                "INSERT INTO works (id, language, originalTitle, Title_CN, reviewStatus,"
                " createdAt, updatedAt, created_by, owner_id)"
                " VALUES (?, 'zh', '手动作品', '手动作品', 'reviewed', ?, ?, 'user', ?)",
                (manual_w, now, now, self.vip["id"]),
            )
        edit_draft(
            "edges",
            batch["edge_id"],
            {
                "source_work_id": manual_w,
                "target_work_id": batch["work2"],
                "evidence": "正文提及了《目标书A》。",
                "evidenceSource": "第一章",
            },
            self.vip,
        )
        drafts = llm_drafts(self.vip)
        by_title = {b["source"]["work"]["Title_CN"]: b for b in drafts["batches"]}
        # 涟漪出现在「手动作品」批次下,原源书批次失去涟漪后成为 0 涟漪孤儿批次
        self.assertIn("手动作品", by_title)
        self.assertEqual(
            [r["edge"]["id"] for r in by_title["手动作品"]["ripples"]],
            [batch["edge_id"]],
        )
        self.assertIn("源书A", by_title)
        self.assertEqual(by_title["源书A"]["ripples"], [])

    def test_approve_edge_with_personal_work_endpoint(self) -> None:
        """批准指向个人库作品的涟漪:个人库作品直接复用,不被复制或修改。"""
        batch = _stage_chain(self.vip["id"], "A")
        now = db_sqlite.now_iso()
        with db_sqlite._write_lock, db_sqlite._db() as conn:
            manual_a = db_sqlite.new_uuid()
            manual_w = db_sqlite.new_uuid()
            conn.execute(
                "INSERT INTO authors (id, originalName, Name_CN, reviewStatus, createdAt,"
                " updatedAt, created_by, owner_id)"
                " VALUES (?, '手动作者', '手动作者', 'reviewed', ?, ?, 'user', ?)",
                (manual_a, now, now, self.vip["id"]),
            )
            conn.execute(
                "INSERT INTO works (id, language, originalTitle, Title_CN, reviewStatus,"
                " createdAt, updatedAt, created_by, owner_id)"
                " VALUES (?, 'zh', '手动作品', '手动作品', 'reviewed', ?, ?, 'user', ?)",
                (manual_w, now, now, self.vip["id"]),
            )
            conn.execute(
                "INSERT INTO work_authors (work_id, author_id) VALUES (?, ?)",
                (manual_w, manual_a),
            )
        edit_draft(
            "edges",
            batch["edge_id"],
            {
                "source_work_id": manual_w,
                "target_work_id": batch["work2"],
                "evidence": "正文提及了《目标书A》。",
                "evidenceSource": "第一章",
            },
            self.vip,
        )
        result = approve_ripple(batch["edge_id"], None, self.vip)
        self.assertEqual(result["public_ids"]["source_work"], manual_w)
        self.assertNotEqual(result["public_ids"]["target_work"], batch["work2"])
        # 个人库作品行未被修改或复制
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT created_by, reviewStatus, published_to_id, deletedAt"
                " FROM works WHERE id = ?",
                (manual_w,),
            ).fetchone()
            self.assertEqual(row["created_by"], "user")
            self.assertEqual(row["reviewStatus"], "reviewed")
            self.assertIsNone(row["published_to_id"])
            self.assertIsNone(row["deletedAt"])

    def test_reuse_source_work_redirects_ripples(self) -> None:
        """复用源书草稿:该批次涟漪批准后自动指向库中已有源书,目标行不被修改。"""
        batch = _stage_chain(self.vip["id"], "A")
        now = db_sqlite.now_iso()
        with db_sqlite._write_lock, db_sqlite._db() as conn:
            manual_w = db_sqlite.new_uuid()
            conn.execute(
                "INSERT INTO works (id, language, originalTitle, Title_CN, reviewStatus,"
                " createdAt, updatedAt, created_by, owner_id)"
                " VALUES (?, 'zh', '已有源书', '已有源书', 'reviewed', ?, ?, 'user', ?)",
                (manual_w, now, now, self.vip["id"]),
            )
        result = reuse_draft_work(batch["work1"], ReuseWorkBody(reuse_id=manual_w), self.vip)
        self.assertEqual(result["reuse_id"], manual_w)
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT published_to_id, reviewStatus FROM works WHERE id = ?",
                (batch["work1"],),
            ).fetchone()
            self.assertEqual(row["published_to_id"], manual_w)
            self.assertEqual(row["reviewStatus"], "reviewed")
        # 批准涟漪:source_work 解析为复用目标
        approved = approve_ripple(batch["edge_id"], None, self.vip)
        self.assertEqual(approved["public_ids"]["source_work"], manual_w)
        # 个人库目标行未被修改
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT created_by, reviewStatus, published_to_id, deletedAt"
                " FROM works WHERE id = ?",
                (manual_w,),
            ).fetchone()
            self.assertEqual(row["created_by"], "user")
            self.assertIsNone(row["published_to_id"])
            self.assertIsNone(row["deletedAt"])

    def test_reuse_source_work_rejects_ai_draft_target(self) -> None:
        """复用目标不能是另一个 AI 草稿。"""
        batch_a = _stage_chain(self.vip["id"], "A")
        batch_b = _stage_chain(self.vip["id"], "B")
        with self.assertRaises(HTTPException) as ctx:
            reuse_draft_work(batch_a["work1"], ReuseWorkBody(reuse_id=batch_b["work1"]), self.vip)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_reuse_source_work_requires_own_space(self) -> None:
        """复用目标必须在自己的星云中(跨空间 404)。"""
        batch = _stage_chain(self.vip["id"], "A")
        other = _stage_chain(self.admin["id"], "B")
        with self.assertRaises(HTTPException) as ctx:
            reuse_draft_work(batch["work1"], ReuseWorkBody(reuse_id=other["work1"]), self.vip)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_reuse_source_author_redirects_ripples(self) -> None:
        """复用源书作者:该批次涟漪批准后自动指向库中已有作者,目标行不被修改。"""
        batch = _stage_chain(self.vip["id"], "A")
        now = db_sqlite.now_iso()
        with db_sqlite._write_lock, db_sqlite._db() as conn:
            manual_a = db_sqlite.new_uuid()
            conn.execute(
                "INSERT INTO authors (id, originalName, Name_CN, reviewStatus, createdAt,"
                " updatedAt, created_by, owner_id)"
                " VALUES (?, '已有作者', '已有作者', 'reviewed', ?, ?, 'user', ?)",
                (manual_a, now, now, self.vip["id"]),
            )
        result = reuse_draft_author(
            batch["author_id"], ReuseAuthorBody(reuse_id=manual_a), self.vip
        )
        self.assertEqual(result["reuse_id"], manual_a)
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT published_to_id, reviewStatus FROM authors WHERE id = ?",
                (batch["author_id"],),
            ).fetchone()
            self.assertEqual(row["published_to_id"], manual_a)
            self.assertEqual(row["reviewStatus"], "reviewed")
        # 批准涟漪:源书作者解析为复用目标
        approved = approve_ripple(batch["edge_id"], None, self.vip)
        self.assertIn(manual_a, approved["public_ids"]["source_authors"])
        # 个人库目标行未被修改
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT created_by, published_to_id, deletedAt FROM authors WHERE id = ?",
                (manual_a,),
            ).fetchone()
            self.assertEqual(row["created_by"], "user")
            self.assertIsNone(row["published_to_id"])
            self.assertIsNone(row["deletedAt"])

    def test_reuse_draft_author_rejects_ai_draft_target(self) -> None:
        """作者复用目标不能是另一个 AI 草稿。"""
        batch_a = _stage_chain(self.vip["id"], "A")
        batch_b = _stage_chain(self.vip["id"], "B")
        with self.assertRaises(HTTPException) as ctx:
            reuse_draft_author(
                batch_a["author_id"], ReuseAuthorBody(reuse_id=batch_b["author_id"]), self.vip
            )
        self.assertEqual(ctx.exception.status_code, 400)

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

    def test_reject_reopen_edit_own_draft(self) -> None:
        """驳回 → 重开 → 编辑:审核状态保留,内容可修正。"""
        chain = _stage_chain(self.vip["id"], "A")

        rejected = reject_draft("authors", chain["author_id"], self.vip)
        self.assertEqual(rejected["reviewStatus"], "rejected")
        reopened = reopen_draft("authors", chain["author_id"], self.vip)
        self.assertEqual(reopened["reviewStatus"], "draft")
        edited = edit_draft(
            "authors", chain["author_id"], {"Name_CN": "改后作者"}, self.vip
        )
        self.assertEqual(edited["row"]["Name_CN"], "改后作者")
        self.assertEqual(edited["row"]["reviewStatus"], "draft")  # 编辑不改变审核状态

    def test_published_draft_not_editable(self) -> None:
        """已批准发布的草稿不可再编辑(409)。"""
        chain = _stage_chain(self.vip["id"], "A")
        approve_draft("authors", chain["author_id"], None, self.vip)
        with self.assertRaises(HTTPException) as ctx:
            edit_draft("authors", chain["author_id"], {"Name_CN": "x"}, self.vip)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_approve_with_reuse_own_space_row(self) -> None:
        """批准时可复用自己星云中的现有行(llm_reuse,回写 published_to_id)。"""
        chain = _stage_chain(self.vip["id"], "A")
        existing = my_create(
            "authors", {"originalName": "已有作者", "Name_CN": "已有作者"}, user=self.vip
        )["row"]["id"]

        result = approve_draft(
            "authors", chain["author_id"], ApproveBody(reuse_id=existing), self.vip
        )
        self.assertEqual(result["mode"], "reuse")
        self.assertEqual(result["public_id"], existing)
        with db_sqlite._db() as conn:
            draft = conn.execute(
                "SELECT published_to_id FROM authors WHERE id = ?", (chain["author_id"],)
            ).fetchone()
            self.assertEqual(draft["published_to_id"], existing)

    def test_reuse_other_uploader_row_rejected(self) -> None:
        """不能复用其他上传者(admin)星云中的行作为发布目标(404)。"""
        chain = _stage_chain(self.vip["id"], "A")
        admin_author = my_create(
            "authors", {"originalName": "管理员作者", "Name_CN": "管理员作者"}, user=self.admin
        )["row"]["id"]
        with self.assertRaises(HTTPException) as ctx:
            approve_draft(
                "authors", chain["author_id"], ApproveBody(reuse_id=admin_author), self.vip
            )
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()

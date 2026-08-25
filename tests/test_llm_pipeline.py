"""AI 录入管线端到端测试:提取JSON → 去重 → make-batch → ingest → 审核 → 发布。

原 app/ai_assistant/tmp/e2e_llm_review.py 一次性脚本的自动化版本:用合成提取数据 +
临时 SQLite 库,验证 system_llm 草稿区、依赖守卫与发布链路,不触碰真实
data/echo-graph.db 与 data/export/*(CSV 导出目录已指向临时目录)。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import auth, data_store, db_sqlite
from app.ai_assistant.tools import dedupe_check, llm_space, review_publish
from app.llm_review import (
    approve_draft,
    clear_drafts,
    llm_drafts,
    reject_draft,
    reopen_draft,
)

_ADMIN_EMAIL = "admin@echo.local"


def _synthetic_extract() -> dict:
    """小型合成提取结果:2 作者、2 作品(源书 + 提及)、1 涟漪。"""
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
                    "mention_type": "正文",
                },
            }
        ],
    }


class LlmPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "llm.db"

        self.patch_db = patch.object(db_sqlite, "DB_PATH", self.db_path)
        self.patch_db.start()
        self.addCleanup(self.patch_db.stop)

        self.patch_email = patch.object(auth, "BOOTSTRAP_EMAIL", _ADMIN_EMAIL)
        self.patch_email.start()
        self.addCleanup(self.patch_email.stop)

        # 批准会触发公共星云 CSV 导出,重定向到临时目录,避免污染仓库 data/export
        self.patch_export = patch.object(data_store, "EXPORT_DIR", Path(self.tmp.name) / "export")
        self.patch_export.start()
        self.addCleanup(self.patch_export.stop)

        # 批次登记簿写入临时目录,避免污染 app/ai_assistant/output/batches
        self.patch_batch_dir = patch.object(
            llm_space, "BATCH_DIR", Path(self.tmp.name) / "batches"
        )
        self.patch_batch_dir.start()
        self.addCleanup(self.patch_batch_dir.stop)

        self.admin = auth.register(_ADMIN_EMAIL, "password123", username="admin01")
        self.assertEqual(self.admin["role"], "admin")
        # 草稿 owner_id = 上传者(admin);不再使用共享 system_llm 账号
        self.owner = self.admin["id"]

    def _batch(self) -> dict:
        extract = _synthetic_extract()
        work_cands, author_cands = dedupe_check.collect_candidates_from_extract(extract)
        report = dedupe_check.run_dedupe(
            work_cands, author_cands, db_path=str(self.db_path), basic_only=True
        )
        # 去重候选:源书作者 1 位(涟漪作者在 build_batch 阶段补),源书 + 涟漪作品 2 部
        self.assertEqual(len(report["authors"]), 1)
        self.assertEqual(len(report["works"]), 2)
        batch = review_publish.build_batch(
            extract, report, db_path=str(self.db_path), owner_id=self.owner
        )
        self.assertEqual(len(batch["items"]), 5)  # 2 作者 + 2 作品 + 1 涟漪
        return batch

    def test_stage_approve_publish_roundtrip(self) -> None:
        batch = self._batch()
        counts = review_publish.stage_batch(batch, self.owner)
        self.assertEqual(counts["staged"], 5)
        self.assertEqual(counts["failed"], 0)

        drafts = llm_drafts(self.admin)
        self.assertEqual(drafts["staging"]["counts"]["authors"], 2)
        self.assertEqual(drafts["staging"]["counts"]["works"], 2)
        self.assertEqual(drafts["staging"]["counts"]["edges"], 1)

        admin_user = {"id": self.admin["id"], "email": _ADMIN_EMAIL, "role": "admin"}
        staging = drafts["staging"]

        # 依赖守卫:作者未批准时,作品批准应 409
        first_work = staging["works"][0]
        with self.assertRaises(HTTPException) as ctx:
            approve_draft("works", first_work["id"], None, admin_user)
        self.assertEqual(ctx.exception.status_code, 409)

        # 驳回 / 重开(批准前;驳回保留草稿行)
        a0 = staging["authors"][0]
        reject_draft("authors", a0["id"], admin_user)
        drafts2 = llm_drafts(self.admin)
        row = next(x for x in drafts2["staging"]["authors"] if x["id"] == a0["id"])
        self.assertEqual(row["reviewStatus"], "rejected")
        reopen_draft("authors", a0["id"], admin_user)
        self.assertEqual(
            llm_drafts(self.admin)["staging"]["counts"]["authors"], 2
        )

        # 按 作者 → 作品 → 涟漪 顺序批准(空库无复用目标,全部 copy)
        for a in staging["authors"]:
            r = approve_draft("authors", a["id"], None, admin_user)
            self.assertEqual(r["mode"], "copy")
        for w in staging["works"]:
            r = approve_draft("works", w["id"], None, admin_user)
            self.assertEqual(r["mode"], "copy")
        for e in staging["edges"]:
            r = approve_draft("edges", e["id"], None, admin_user)
            self.assertEqual(r["mode"], "copy")

        # 已发布草稿不可重复发布
        w1 = staging["works"][0]
        with self.assertRaises(HTTPException) as ctx:
            approve_draft("works", w1["id"], None, admin_user)
        self.assertEqual(ctx.exception.status_code, 409)

        # 公共星云落库校验:2 作者 / 2 作品 / 1 涟漪,草稿行回写 published_to_id
        with db_sqlite._db() as conn:
            pub_a = conn.execute(
                "SELECT count(*) c FROM authors WHERE owner_id = ? AND deletedAt IS NULL"
                f" AND {db_sqlite.ai_draft_clause(negate=True)}",
                (self.admin["id"],),
            ).fetchone()["c"]
            pub_w = conn.execute(
                "SELECT count(*) c FROM works WHERE owner_id = ? AND deletedAt IS NULL"
                f" AND {db_sqlite.ai_draft_clause(negate=True)}",
                (self.admin["id"],),
            ).fetchone()["c"]
            pub_e = conn.execute(
                "SELECT count(*) c FROM edges WHERE owner_id = ? AND deletedAt IS NULL"
                f" AND {db_sqlite.ai_draft_clause(negate=True)}",
                (self.admin["id"],),
            ).fetchone()["c"]
            published = conn.execute(
                "SELECT count(*) c FROM works WHERE owner_id = ?"
                " AND published_to_id IS NOT NULL",
                (self.owner,),
            ).fetchone()["c"]
            llm_audit = conn.execute(
                "SELECT count(*) c FROM audit_log"
                " WHERE action IN ('llm_ingest', 'llm_publish', 'llm_reuse')"
            ).fetchone()["c"]
        self.assertEqual((pub_a, pub_w, pub_e), (2, 2, 1))
        self.assertEqual(published, 2)
        self.assertGreater(llm_audit, 0)

    def test_build_batch_uses_enriched_ripple_author(self) -> None:
        """涟漪作者补全后:build_batch 使用完整记录(国籍/生卒年),入库草稿带全字段。"""
        extract = _synthetic_extract()
        ripple_author = {
            "originalName": "Herman Melville",
            "Name_CN": "赫尔曼·梅尔维尔",
            "Name_EN": "Herman Melville",
            "nationality": "US",
            "birthYear": 1819,
            "deathYear": 1891,
            "note": "美国小说家。",
        }
        # 模拟 enrich_ripple_authors 的效果:author_info 写回涟漪 + 涟漪作者存入
        # extract["ripple_authors"](不再混入源书作者 extract["authors"])
        extract["ripples"][0]["work"]["author_info"] = ripple_author
        extract.setdefault("ripple_authors", []).append(ripple_author)

        # 涟漪作者进入去重候选(基础匹配)
        work_cands, author_cands = dedupe_check.collect_candidates_from_extract(extract)
        self.assertEqual(len(author_cands), 2)
        report = dedupe_check.run_dedupe(
            work_cands,
            author_cands,
            db_path=str(self.db_path),
            basic_only=True,
            llm_confirm=False,
        )

        batch = review_publish.build_batch(
            extract, report, db_path=str(self.db_path), owner_id=self.owner
        )
        author_items = [it for it in batch["items"] if it["kind"] == "author"]
        mel = next(it for it in author_items if it["payload"].get("Name_CN") == "赫尔曼·梅尔维尔")
        self.assertEqual(mel["payload"]["nationality"], "US")
        self.assertEqual(mel["payload"]["birthYear"], 1819)
        self.assertEqual(mel["payload"]["deathYear"], 1891)
        # 回归:源书作品只挂源书作者,不挂涟漪作者
        src_item = next(
            it for it in batch["items"] if it["kind"] == "work" and it["label"] == "测试之书"
        )
        src_author_labels = [
            next(i["label"] for i in batch["items"] if i["item_id"] == ref)
            for ref in src_item["author_refs"]
        ]
        self.assertEqual(src_author_labels, ["测试作者"])

        # 入库草稿:作者行带国籍/生卒年,涟漪作品仍正确关联该作者
        counts = review_publish.stage_batch(batch, self.owner)
        self.assertEqual(counts["failed"], 0)
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT nationality, birthYear, deathYear FROM authors"
                " WHERE owner_id = ? AND Name_CN = ?",
                (self.owner, "赫尔曼·梅尔维尔"),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(
                (row["nationality"], row["birthYear"], row["deathYear"]),
                ("US", 1819, 1891),
            )
            wa = conn.execute(
                "SELECT count(*) c FROM work_authors wa"
                " JOIN works w ON w.id = wa.work_id"
                " WHERE w.owner_id = ? AND w.Title_CN = ?",
                (self.owner, "白鲸"),
            ).fetchone()
            self.assertGreater(wa["c"], 0)
            wa_src = conn.execute(
                "SELECT count(*) c FROM work_authors wa"
                " JOIN works w ON w.id = wa.work_id"
                " WHERE w.owner_id = ? AND w.Title_CN = ?",
                (self.owner, "测试之书"),
            ).fetchone()
            self.assertEqual(wa_src["c"], 1)  # 源书作品只关联源书作者

    def test_stage_marks_failed_item(self) -> None:
        """坏数据条目单条失败不中断整批(stage_batch 的容错)。"""
        batch = self._batch()
        batch["items"][0]["payload"] = {"Name_CN": ""}  # 源书作者缺必填 originalName
        counts = review_publish.stage_batch(batch, self.owner)
        # 级联失败:坏作者 1 条 + 依赖它的源书作品 1 条 + 该作品涟漪 1 条
        self.assertEqual(counts["staged"], 2)
        self.assertEqual(counts["failed"], 3)

    def test_legacy_polluted_authors_not_linked_to_source_work(self) -> None:
        """旧版提取结果(涟漪作者曾混入 extract["authors"])容错:源书作品不挂涟漪作者。"""
        extract = _synthetic_extract()
        ripple_author = {
            "originalName": "Herman Melville",
            "Name_CN": "赫尔曼·梅尔维尔",
            "Name_EN": "Herman Melville",
            "nationality": "US",
            "birthYear": 1819,
            "deathYear": 1891,
        }
        # 旧版污染:涟漪作者既写回 author_info,又被追加进 extract["authors"]
        extract["ripples"][0]["work"]["author_info"] = ripple_author
        extract["authors"].append(ripple_author)

        work_cands, author_cands = dedupe_check.collect_candidates_from_extract(extract)
        self.assertEqual(len(author_cands), 2)  # 源书作者 + 涟漪作者都进去重候选
        report = dedupe_check.run_dedupe(
            work_cands, author_cands, db_path=str(self.db_path), basic_only=True, llm_confirm=False
        )
        batch = review_publish.build_batch(
            extract, report, db_path=str(self.db_path), owner_id=self.owner
        )

        src_item = next(
            it for it in batch["items"] if it["kind"] == "work" and it["label"] == "测试之书"
        )
        src_author_labels = [
            next(i["label"] for i in batch["items"] if i["item_id"] == ref)
            for ref in src_item["author_refs"]
        ]
        self.assertEqual(src_author_labels, ["测试作者"])

    def test_clear_drafts_soft_deletes_all(self) -> None:
        """清空 AI 草稿:软删除 system_llm 空间全部草稿,公共数据不受影响,审计留痕。"""
        batch = self._batch()
        review_publish.stage_batch(batch, self.owner)
        before = llm_drafts(self.admin)["staging"]["counts"]
        self.assertEqual((before["authors"], before["works"], before["edges"]), (2, 2, 1))

        admin = {"id": self.admin["id"], "email": _ADMIN_EMAIL, "role": "admin"}
        result = clear_drafts(admin)
        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"], {"authors": 2, "works": 2, "edges": 1})

        after = llm_drafts(self.admin)["staging"]["counts"]
        self.assertEqual((after["authors"], after["works"], after["edges"]), (0, 0, 0))
        with db_sqlite._db() as conn:
            deleted = conn.execute(
                "SELECT count(*) c FROM works WHERE owner_id = ? AND deletedAt IS NOT NULL",
                (self.owner,),
            ).fetchone()["c"]
            audit = conn.execute(
                "SELECT count(*) c FROM audit_log"
                " WHERE action = 'delete' AND detail LIKE '清空 AI 草稿%'",
            ).fetchone()["c"]
        self.assertEqual(deleted, 2)
        self.assertGreater(audit, 0)

    def test_admin_sees_only_own_uploaded_drafts(self) -> None:
        """草稿按 owner_id=上传者 隔离:admin 只能看到自己上传的草稿。"""
        batch_a = self._batch()
        review_publish.stage_batch(batch_a, self.admin["id"])

        owner_b = auth.register("uploader2@test.local", "password123", username="uploader2")
        extract_b = _synthetic_extract()
        extract_b["source_book"]["authors"] = ["作者B"]
        extract_b["authors"] = [{"originalName": "作者B", "Name_CN": "作者B"}]
        extract_b["work"]["Title_CN"] = "书籍B"
        work_cands, author_cands = dedupe_check.collect_candidates_from_extract(extract_b)
        report_b = dedupe_check.run_dedupe(
            work_cands, author_cands, db_path=str(self.db_path), basic_only=True, llm_confirm=False
        )
        batch_b = review_publish.build_batch(
            extract_b, report_b, db_path=str(self.db_path), owner_id=owner_b["id"]
        )
        review_publish.stage_batch(batch_b, owner_b["id"])

        drafts_a = llm_drafts(self.admin)
        drafts_b = llm_drafts(owner_b)
        labels_a = {r["Name_CN"] for r in drafts_a["staging"]["authors"]}
        labels_b = {r["Name_CN"] for r in drafts_b["staging"]["authors"]}
        self.assertIn("测试作者", labels_a)
        self.assertNotIn("作者B", labels_a)
        self.assertIn("作者B", labels_b)
        self.assertNotIn("测试作者", labels_b)

    def test_legacy_shared_drafts_migrated_to_bootstrap_admin(self) -> None:
        """旧 system_llm 共享草稿一次性迁移到引导管理员,并删除空账号。"""
        from app.llm_account import migrate_legacy_llm_drafts

        with db_sqlite._db() as conn:
            legacy = db_sqlite.new_uuid()
            conn.execute(
                "INSERT INTO users (id, email, username, password_hash, role, status,"
                " space_visibility) VALUES (?, 'system_llm@echo.local', 'system_llm',"
                " 'x', 'user', 'active', 'private')",
                (legacy,),
            )
            conn.execute(
                "INSERT INTO works (id, language, originalTitle, Title_CN, reviewStatus,"
                " created_by, owner_id) VALUES ('w-legacy', 'zh', '旧草稿', '旧草稿',"
                " 'draft', 'llm', ?)",
                (legacy,),
            )
        moved = migrate_legacy_llm_drafts()
        self.assertEqual(moved, 1)
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT owner_id FROM works WHERE id = 'w-legacy'"
            ).fetchone()
            self.assertEqual(row["owner_id"], self.admin["id"])
            acc = conn.execute(
                "SELECT count(*) c FROM users WHERE id = ?", (legacy,)
            ).fetchone()["c"]
            self.assertEqual(acc, 0)


if __name__ == "__main__":
    unittest.main()

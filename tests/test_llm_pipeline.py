"""AI 录入管线端到端测试:提取JSON → 去重 → make-batch → ingest → 审核 → 发布。

原 agent_temp/tmp/e2e_llm_review.py 一次性脚本的自动化版本:用合成提取数据 +
临时 SQLite 库,验证 system_llm 草稿区、依赖守卫与发布链路,不触碰真实
data/echo-graph.db 与 data/export/*(CSV 导出目录已指向临时目录)。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from agent_temp.tools import dedupe_check, llm_space, review_publish
from app import auth, data_store, db_sqlite
from app.llm_review import (
    approve_draft,
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
                    "mention_type": "READ_BY_CHARACTER",
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

        # 批次登记簿写入临时目录,避免污染 agent_temp/output/batches
        self.patch_batch_dir = patch.object(
            llm_space, "BATCH_DIR", Path(self.tmp.name) / "batches"
        )
        self.patch_batch_dir.start()
        self.addCleanup(self.patch_batch_dir.stop)

        self.admin = auth.register(_ADMIN_EMAIL, "password123", username="admin01")
        self.assertEqual(self.admin["role"], "admin")
        self.owner = llm_space.ensure_system_llm()

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

        drafts = llm_drafts()
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
        drafts2 = llm_drafts()
        row = next(x for x in drafts2["staging"]["authors"] if x["id"] == a0["id"])
        self.assertEqual(row["reviewStatus"], "rejected")
        reopen_draft("authors", a0["id"], admin_user)
        self.assertEqual(
            llm_drafts()["staging"]["counts"]["authors"], 2
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
                "SELECT count(*) c FROM authors WHERE owner_id = ? AND deletedAt IS NULL",
                (self.admin["id"],),
            ).fetchone()["c"]
            pub_w = conn.execute(
                "SELECT count(*) c FROM works WHERE owner_id = ? AND deletedAt IS NULL",
                (self.admin["id"],),
            ).fetchone()["c"]
            pub_e = conn.execute(
                "SELECT count(*) c FROM edges WHERE owner_id = ? AND deletedAt IS NULL",
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

    def test_stage_marks_failed_item(self) -> None:
        """坏数据条目单条失败不中断整批(stage_batch 的容错)。"""
        batch = self._batch()
        batch["items"][0]["payload"] = {"Name_CN": ""}  # 源书作者缺必填 originalName
        counts = review_publish.stage_batch(batch, self.owner)
        # 级联失败:坏作者 1 条 + 依赖它的源书作品 1 条 + 该作品涟漪 1 条
        self.assertEqual(counts["staged"], 2)
        self.assertEqual(counts["failed"], 3)


if __name__ == "__main__":
    unittest.main()

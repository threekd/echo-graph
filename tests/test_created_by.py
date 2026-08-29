"""溯源列 created_by 测试:curated/user 的推导、显式取值与不可修改(llm 仅内部管线)。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import auth, db_sqlite, space_crud
from app.me import my_create, my_update


class CreatedByTest(unittest.TestCase):
    ADMIN = "boss@test.local"
    ALICE = "alice@test.local"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "created_by.db").start()
        patch.object(auth, "BOOTSTRAP_EMAIL", self.ADMIN).start()
        self.addCleanup(patch.stopall)
        self.admin = auth.register(self.ADMIN, "admin-password-123", username="admin")
        self.alice = auth.register(self.ALICE, "alice-password-123", username="alice")
        self.addCleanup(self.tmp.cleanup)

    def test_admin_space_defaults_curated(self) -> None:
        row = space_crud.create_row(
            "authors", {"originalName": "A", "Name_CN": "公共作者"},
            self.admin["id"], self.admin["email"],
        )["row"]
        self.assertEqual(row["created_by"], "curated")

    def test_user_space_defaults_user(self) -> None:
        row = my_create("authors", {"originalName": "B", "Name_CN": "私人作者"}, user=self.alice)["row"]
        self.assertEqual(row["created_by"], "user")
        self.assertEqual(row["reviewStatus"], "reviewed")  # created_by=user 默认已审核

    def test_explicit_llm_rejected(self) -> None:
        """API 手工写入不允许显式传 created_by=llm(仅供 AI 管线内部使用)。"""
        for user in (self.alice, self.admin):
            with self.subTest(user=user["username"]):
                with self.assertRaises(HTTPException) as ctx:
                    my_create(
                        "authors",
                        {"originalName": "C", "Name_CN": "AI作者", "created_by": "llm"},
                        user=user,
                    )
                self.assertEqual(ctx.exception.status_code, 400)
                self.assertIn("llm", ctx.exception.detail)

    def test_user_cannot_override_review_status_to_unreviewed(self) -> None:
        """输入即确认:手工新增一律强制 reviewed(所有用户一致),显式 draft/rejected 被回正。"""
        for status in ("draft", "rejected"):
            with self.subTest(status=status):
                row = my_create(
                    "authors",
                    {"originalName": "D", "Name_CN": "强制已审核", "reviewStatus": status},
                    user=self.alice,
                )["row"]
                self.assertEqual(row["created_by"], "user")
                self.assertEqual(row["reviewStatus"], "reviewed")

    def test_admin_explicit_draft_forced_reviewed(self) -> None:
        """手工新增一律 reviewed,admin 不做特殊化:显式传 draft 也被回正。"""
        row = space_crud.create_row(
            "authors", {"originalName": "E", "Name_CN": "官方草稿", "reviewStatus": "draft"},
            self.admin["id"], self.admin["email"],
        )["row"]
        self.assertEqual(row["reviewStatus"], "reviewed")

    def test_invalid_created_by_rejected(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            my_create(
                "authors", {"originalName": "D", "Name_CN": "非法", "created_by": "bot"},
                user=self.alice,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("created_by", ctx.exception.detail)

    def test_update_preserves_created_by(self) -> None:
        row = my_create("authors", {"originalName": "E", "Name_CN": "原名"}, user=self.alice)["row"]
        updated = my_update(
            "authors", row["id"],
            {
                "originalName": "E",
                "Name_CN": "改名",
                "created_by": "curated",
                "updatedAt": row["updatedAt"],
            },
            user=self.alice,
        )["row"]
        self.assertEqual(updated["created_by"], "user")  # 响应携带库内真实值
        with db_sqlite._db() as conn:
            stored = conn.execute(
                "SELECT created_by FROM authors WHERE id = ?", (row["id"],)
            ).fetchone()["created_by"]
        self.assertEqual(stored, "user")  # 不可被更新覆盖

    def test_update_rejects_explicit_llm(self) -> None:
        """编辑时显式传 created_by=llm 一律 400(即使库内行不是 AI 草稿)。"""
        row = my_create("authors", {"originalName": "E", "Name_CN": "原名"}, user=self.alice)["row"]
        with self.assertRaises(HTTPException) as ctx:
            my_update(
                "authors", row["id"],
                {"originalName": "E", "Name_CN": "改名", "created_by": "llm",
                 "updatedAt": row["updatedAt"]},
                user=self.alice,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("llm", ctx.exception.detail)

    def test_update_requires_updated_at(self) -> None:
        """乐观并发守卫:编辑必须携带 updatedAt,缺失 400。"""
        row = my_create("authors", {"originalName": "E", "Name_CN": "原名"}, user=self.alice)["row"]
        with self.assertRaises(HTTPException) as ctx:
            my_update(
                "authors", row["id"], {"originalName": "E", "Name_CN": "改名"},
                user=self.alice,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("updatedAt", ctx.exception.detail)

    def test_edge_created_by_in_both_spaces(self) -> None:
        w1 = space_crud.create_row(
            "works", {"language": "zh", "originalTitle": "甲", "Title_CN": "甲"},
            self.admin["id"], self.admin["email"],
        )["row"]
        w2 = space_crud.create_row(
            "works", {"language": "zh", "originalTitle": "乙", "Title_CN": "乙"},
            self.admin["id"], self.admin["email"],
        )["row"]
        edge = space_crud.create_row(
            "edges", {
                "source_work_id": w1["id"],
                "target_work_id": w2["id"],
                "evidence": "公共提及",
                "evidenceSource": "第一章",
            },
            self.admin["id"], self.admin["email"],
        )["row"]
        self.assertEqual(edge["created_by"], "curated")

        wa = my_create("works", {"language": "zh", "originalTitle": "丙", "Title_CN": "丙"}, user=self.alice)["row"]
        wb = my_create("works", {"language": "zh", "originalTitle": "丁", "Title_CN": "丁"}, user=self.alice)["row"]
        edge_u = my_create("edges", {
            "source_work_id": wa["id"],
            "target_work_id": wb["id"],
            "evidence": "私人提及",
            "evidenceSource": "第三章",
        }, user=self.alice)["row"]
        self.assertEqual(edge_u["created_by"], "user")

    def test_all_three_tables_have_column(self) -> None:
        with db_sqlite._db() as conn:
            for table in ("authors", "works", "edges"):
                cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                self.assertIn("created_by", cols)
                default = next(
                    r["dflt_value"] for r in conn.execute(f"PRAGMA table_info({table})")
                    if r["name"] == "created_by"
                )
                self.assertEqual(default, "'curated'")


if __name__ == "__main__":
    unittest.main()

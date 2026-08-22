"""空间隔离测试:公共星云(admin)与个人空间互不可见、不可修改。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import app.admin as admin
import app.space as space
from app import auth, db_sqlite
from app.db import SqliteStore
from app.me import (
    my_create,
    my_data,
    my_delete,
    my_graph,
    my_update,
)


class _FakeReq:
    def __init__(self, cookies: dict | None = None) -> None:
        self.cookies = cookies or {}


class SpaceIsolationTest(unittest.TestCase):
    ADMIN = "boss@test.local"
    ALICE = "alice@test.local"
    BOB = "bob@test.local"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "iso.db").start()
        patch.object(auth, "BOOTSTRAP_EMAIL", self.ADMIN).start()
        # 隔离测试不依赖机器 .env 的审核过滤开关,新建草稿即可见
        patch.dict(os.environ, {"PUBLIC_REVIEWED_ONLY": "0"}, clear=False).start()
        patch("app.space_crud.export_csv_files", lambda: None).start()
        self.admin = auth.register(self.ADMIN, "admin-password-123")
        self.alice = auth.register(self.ALICE, "alice-password-123")
        self.bob = auth.register(self.BOB, "bob-password-123")
        self.addCleanup(self.tmp.cleanup)

    def test_user_space_isolated_from_public_and_others(self) -> None:
        created = my_create(
            "authors", {"originalName": "A", "Name_CN": "爱丽丝的作者"}, user=self.alice
        )
        aid = created["row"]["id"]
        # 公共星云与第三方空间均不可见
        self.assertEqual(SqliteStore().graph()["nodes"], [])
        self.assertEqual(my_graph(user=self.bob)["nodes"], [])
        self.assertEqual(admin.get_data()["authors"], [])
        # 第三方不可改(视为不存在,404)
        with self.assertRaises(HTTPException) as ctx:
            my_update("authors", aid, {"originalName": "B", "Name_CN": "篡改"}, user=self.bob)
        self.assertEqual(ctx.exception.status_code, 404)
        # 本人可见可改可删
        self.assertEqual(len(my_graph(user=self.alice)["nodes"]), 1)
        my_update(
            "authors", aid, {"originalName": "A2", "Name_CN": "改了"}, user=self.alice
        )
        my_delete("authors", aid, user=self.alice)
        self.assertEqual(my_graph(user=self.alice)["nodes"], [])

    def test_cross_space_reference_rejected(self) -> None:
        bob_author = my_create(
            "authors", {"originalName": "B", "Name_CN": "鲍勃的作者"}, user=self.bob
        )["row"]
        with self.assertRaises(HTTPException) as ctx:
            my_create(
                "works",
                {
                    "language": "zh",
                    "originalTitle": "X",
                    "Title_CN": "爱丽丝的书",
                    "author_id": bob_author["id"],
                },
                user=self.alice,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("未在作者表中找到", ctx.exception.detail)

    def test_admin_public_data_visible_but_not_in_user_spaces(self) -> None:
        res = admin.create(
            "authors", {"originalName": "策展人", "Name_CN": "公共作者"}
        )
        aid = res["row"]["id"]
        self.assertEqual(res["row"]["reviewStatus"], "draft")  # admin 保持策展语义
        self.assertEqual(res["row"]["visibility"], "public")  # 公共星云恒为公开
        nodes = SqliteStore().graph()["nodes"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["id"], aid)
        # 用户空间看不到公共数据,也不能改
        self.assertEqual(my_graph(user=self.alice)["nodes"], [])
        with self.assertRaises(HTTPException) as ctx:
            my_update("authors", aid, {"Name_CN": "篡改"}, user=self.alice)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_user_space_reviewed_default_and_visibility(self) -> None:
        created = my_create("authors", {"originalName": "A", "Name_CN": "甲"}, user=self.alice)
        row = created["row"]
        self.assertEqual(row["reviewStatus"], "reviewed")  # 用户输入即确认
        self.assertEqual(row["visibility"], "public")
        # 用户不能把数据改回草稿
        updated = my_update(
            "authors", row["id"],
            {"originalName": "A", "Name_CN": "甲2", "reviewStatus": "draft"},
            user=self.alice,
        )
        self.assertEqual(updated["row"]["reviewStatus"], "reviewed")
        # 隐藏后:本人仍可见,访客不可见
        my_update(
            "authors", row["id"],
            {"originalName": "A", "Name_CN": "甲2", "visibility": "private"},
            user=self.alice,
        )
        self.assertEqual(len(my_graph(user=self.alice)["nodes"]), 1)
        with db_sqlite._db() as conn:
            conn.execute(
                "UPDATE users SET space_visibility = 'private' WHERE id IN (?, ?)",
                (self.admin["id"], self.bob["id"]),
            )
        g = space.space_graph(self.alice["id"], _FakeReq())
        self.assertEqual(len(g["nodes"]), 0)
        # 非法可见性取值
        with self.assertRaises(HTTPException) as ctx:
            my_update(
                "authors", row["id"],
                {"originalName": "A", "Name_CN": "甲2", "visibility": "secret"},
                user=self.alice,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_work_visibility_hides_edges_from_visitors(self) -> None:
        a1 = my_create("authors", {"originalName": "A", "Name_CN": "甲"}, user=self.alice)["row"]
        w1 = my_create(
            "works", {
                "language": "zh", "originalTitle": "A书", "Title_CN": "甲书",
                "author_id": a1["id"],
            },
            user=self.alice,
        )["row"]
        w2 = my_create(
            "works", {
                "language": "zh", "originalTitle": "B书", "Title_CN": "乙书",
                "author_id": a1["id"],
            },
            user=self.alice,
        )["row"]
        my_create(
            "edges", {
                "source_work_id": w1["id"], "target_work_id": w2["id"],
                "evidence": "x", "evidenceSource": "c1",
            },
            user=self.alice,
        )
        with db_sqlite._db() as conn:
            conn.execute(
                "UPDATE users SET space_visibility = 'private' WHERE id IN (?, ?)",
                (self.admin["id"], self.bob["id"]),
            )
        visible_before = space.space_graph(self.alice["id"], _FakeReq())
        echo_before = [e for e in visible_before["edges"] if e["type"] == "echo"]
        self.assertEqual(len(echo_before), 1)
        # 隐藏 w1 后:访客看不到它,相关的涟漪边也一并隐藏
        my_update(
            "works", w1["id"],
            {
                "language": "zh", "originalTitle": "A书", "Title_CN": "甲书",
                "author_id": a1["id"], "visibility": "private",
            },
            user=self.alice,
        )
        visible_after = space.space_graph(self.alice["id"], _FakeReq())
        work_ids = {n["id"] for n in visible_after["nodes"]}
        self.assertNotIn(w1["id"], work_ids)
        self.assertEqual([e for e in visible_after["edges"] if e["type"] == "echo"], [])

    def test_work_recommendation_and_review(self) -> None:
        a1 = my_create("authors", {"originalName": "A", "Name_CN": "甲"}, user=self.alice)["row"]
        w = my_create(
            "works", {
                "language": "zh", "originalTitle": "A书", "Title_CN": "甲书",
                "author_id": a1["id"],
                "recommendation": "recommend", "review": "值得一读",
            },
            user=self.alice,
        )["row"]
        self.assertEqual(w["recommendation"], "recommend")
        self.assertEqual(w["review"], "值得一读")
        # 非法评分取值
        with self.assertRaises(HTTPException) as ctx:
            my_create(
                "works", {
                    "language": "zh", "originalTitle": "B", "Title_CN": "乙书",
                    "author_id": a1["id"], "recommendation": "maybe",
                },
                user=self.alice,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        # 超长评价
        with self.assertRaises(HTTPException) as ctx:
            my_create(
                "works", {
                    "language": "zh", "originalTitle": "C", "Title_CN": "丙书",
                    "author_id": a1["id"], "review": "x" * 2001,
                },
                user=self.alice,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        # 表单空值 = 清除
        upd = my_update(
            "works", w["id"], {
                "language": "zh", "originalTitle": "A书", "Title_CN": "甲书",
                "author_id": a1["id"], "recommendation": "", "review": "",
            },
            user=self.alice,
        )
        self.assertIsNone(upd["row"]["recommendation"])
        self.assertIsNone(upd["row"]["review"])

    def test_owner_written_on_create(self) -> None:
        res = my_create(
            "authors", {"originalName": "A", "Name_CN": "甲"}, user=self.alice
        )
        with db_sqlite._db() as conn:
            row = conn.execute("SELECT owner_id FROM authors WHERE id = ?", (res["row"]["id"],)).fetchone()
        self.assertEqual(row["owner_id"], self.alice["id"])

    def test_my_data_contains_only_own_rows(self) -> None:
        my_create("authors", {"originalName": "A", "Name_CN": "甲"}, user=self.alice)
        d = my_data(user=self.alice)
        self.assertEqual(len(d["authors"]), 1)
        self.assertIn("warnings", d)
        self.assertIn("counts", d)
        self.assertEqual(admin.get_data()["authors"], [])

    def test_space_visibility_default_public_and_jump(self) -> None:
        self.assertEqual(self.alice["space_visibility"], "public")
        my_create("authors", {"originalName": "A", "Name_CN": "甲"}, user=self.alice)
        with db_sqlite._db() as conn:
            conn.execute(
                "UPDATE users SET space_visibility = 'private' WHERE id IN (?, ?)",
                (self.admin["id"], self.bob["id"]),
            )
        # 游客可读公开星云
        g = space.space_graph(self.alice["id"], _FakeReq())
        self.assertEqual(len(g["nodes"]), 1)
        # 随机跃迁命中唯一公开星云
        r = space.random_space_graph(_FakeReq())
        self.assertEqual(r["spaceId"], self.alice["id"])
        self.assertEqual(r["displayName"], self.alice["email"])
        self.assertEqual(len(r["nodes"]), 1)
        # 设为 private:游客 404,owner 与 admin 可读
        with db_sqlite._db() as conn:
            conn.execute("UPDATE users SET space_visibility = 'private' WHERE id = ?", (self.alice["id"],))
        with self.assertRaises(HTTPException) as ctx:
            space.space_graph(self.alice["id"], _FakeReq())
        self.assertEqual(ctx.exception.status_code, 404)
        alice_token = auth.create_session(self.alice["id"])
        g2 = space.space_graph(self.alice["id"], _FakeReq({auth.SESSION_COOKIE: alice_token}))
        self.assertEqual(len(g2["nodes"]), 1)
        admin_token = auth.create_session(self.admin["id"])
        g3 = space.space_graph(self.alice["id"], _FakeReq({auth.SESSION_COOKIE: admin_token}))
        self.assertEqual(len(g3["nodes"]), 1)
        # 全部 private 后随机跃迁 404
        with self.assertRaises(HTTPException) as ctx:
            space.random_space_graph(_FakeReq())
        self.assertEqual(ctx.exception.status_code, 404)

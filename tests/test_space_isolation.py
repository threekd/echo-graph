"""空间隔离测试:admin 星云与普通用户个人空间互不可见、不可修改。"""

from __future__ import annotations

import tempfile
import types
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
    my_permanent_delete,
    my_update,
)


class _FakeReq:
    def __init__(self, cookies: dict | None = None) -> None:
        self.cookies = cookies or {}
        self.state = types.SimpleNamespace()


def _space_graph(request, user_id: str) -> dict:
    """与只读路由工厂同一解析路径:可见性校验 + 目标星云 store.graph()。"""
    row, _ = space._space_context(request, user_id)
    return space._space_store(row).graph()


def _space_search(request, user_id: str, q: str, limit: int) -> dict:
    row, _ = space._space_context(request, user_id)
    return {"hits": space._space_store(row).search(q.strip(), limit)}


def _space_work_detail(request, user_id: str, work_id: str) -> dict:
    row, _ = space._space_context(request, user_id)
    detail = space._space_store(row).work_detail(work_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"work not found: {work_id}")
    return detail


def _space_expansion(request, user_id: str, work_id: str, hops: int) -> dict:
    row, _ = space._space_context(request, user_id)
    data = space._space_store(row).expansion(work_id, hops)
    if data is None:
        raise HTTPException(status_code=404, detail=f"work not found: {work_id}")
    return data


def _space_path(request, user_id: str, frm: str, to: str, max_hops: int) -> dict:
    row, _ = space._space_context(request, user_id)
    result = space._space_store(row).path(frm.strip(), to.strip(), max_hops)
    if result is None:
        raise HTTPException(status_code=404, detail="no mention path found")
    return result


class SpaceIsolationTest(unittest.TestCase):
    ADMIN = "boss@test.local"
    ALICE = "alice@test.local"
    BOB = "bob@test.local"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "iso.db").start()
        patch.object(auth, "BOOTSTRAP_EMAIL", self.ADMIN).start()
        self.addCleanup(patch.stopall)
        self.admin = auth.register(self.ADMIN, "admin-password-123", username="admin")
        self.alice = auth.register(self.ALICE, "alice-password-123", username="alice")
        self.bob = auth.register(self.BOB, "bob-password-123", username="bobby")
        self.addCleanup(self.tmp.cleanup)

    def test_user_space_isolated_from_public_and_others(self) -> None:
        created = my_create(
            "authors", {"originalName": "A", "Name_CN": "爱丽丝的作者"}, user=self.alice
        )
        aid = created["row"]["id"]
        # admin 空间与第三方空间均不可见(alice 的数据只属于 alice)
        self.assertEqual(SqliteStore(owner_id=self.admin["id"]).graph()["nodes"], [])
        self.assertEqual(SqliteStore(owner_id=self.bob["id"]).graph()["nodes"], [])
        self.assertEqual(admin.get_data()["authors"], [])
        # 第三方不可改(视为不存在,404)
        with self.assertRaises(HTTPException) as ctx:
            my_update("authors", aid, {"originalName": "B", "Name_CN": "篡改"}, user=self.bob)
        self.assertEqual(ctx.exception.status_code, 404)
        # 本人可见可改可删
        self.assertEqual(len(SqliteStore(owner_id=self.alice["id"]).graph()["nodes"]), 1)
        my_update(
            "authors", aid,
            {"originalName": "A2", "Name_CN": "改了", "updatedAt": created["row"]["updatedAt"]},
            user=self.alice,
        )
        my_delete("authors", aid, user=self.alice)
        self.assertEqual(SqliteStore(owner_id=self.alice["id"]).graph()["nodes"], [])

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
        self.assertEqual(res["row"]["reviewStatus"], "reviewed")  # admin 手动新增默认已审核(输入即确认)
        nodes = SqliteStore(owner_id=self.admin["id"]).graph()["nodes"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["id"], aid)
        # 用户空间看不到公共数据,也不能改
        self.assertEqual(SqliteStore(owner_id=self.alice["id"]).graph()["nodes"], [])
        with self.assertRaises(HTTPException) as ctx:
            my_update("authors", aid, {"Name_CN": "篡改"}, user=self.alice)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_user_space_reviewed_default(self) -> None:
        created = my_create("authors", {"originalName": "A", "Name_CN": "甲"}, user=self.alice)
        row = created["row"]
        self.assertEqual(row["reviewStatus"], "reviewed")  # 用户输入即确认
        # 用户不能把数据改回草稿
        updated = my_update(
            "authors", row["id"],
            {
                "originalName": "A",
                "Name_CN": "甲2",
                "reviewStatus": "draft",
                "updatedAt": row["updatedAt"],
            },
            user=self.alice,
        )
        self.assertEqual(updated["row"]["reviewStatus"], "reviewed")

    def test_permanent_delete_other_space_keeps_404(self) -> None:
        """他人空间的软删除行永久删除仍 404(隔离语义保留,不被幂等分支吞掉)。"""
        row = my_create("authors", {"originalName": "B", "Name_CN": "鲍勃的作者"}, user=self.bob)["row"]
        my_delete("authors", row["id"], user=self.bob)  # bob 先软删除
        with self.assertRaises(HTTPException) as ctx:
            my_permanent_delete("authors", row["id"], user=self.alice)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_work_recommendation_and_review(self) -> None:
        a1 = my_create("authors", {"originalName": "A", "Name_CN": "甲"}, user=self.alice)["row"]
        w = my_create(
            "works", {
                "language": "zh", "originalTitle": "A书", "Title_CN": "甲书",
                "author_id": a1["id"],
                "readingStatus": "reading",
                "recommendation": "recommend", "review": "值得一读",
            },
            user=self.alice,
        )["row"]
        self.assertEqual(w["readingStatus"], "reading")
        self.assertEqual(w["recommendation"], "recommend")
        self.assertEqual(w["review"], "值得一读")
        # 非法阅读状态取值
        with self.assertRaises(HTTPException) as ctx:
            my_create(
                "works", {
                    "language": "zh", "originalTitle": "D", "Title_CN": "丁书",
                    "author_id": a1["id"], "readingStatus": "finished",
                },
                user=self.alice,
            )
        self.assertEqual(ctx.exception.status_code, 400)
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
                "author_id": a1["id"],
                "readingStatus": "", "recommendation": "", "review": "",
                "updatedAt": w["updatedAt"],
            },
            user=self.alice,
        )
        self.assertIsNone(upd["row"]["readingStatus"])
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
        g = _space_graph(_FakeReq(), self.alice["id"])
        self.assertEqual(len(g["nodes"]), 1)
        # 随机跃迁命中唯一公开星云
        r = space.random_space_graph(_FakeReq())
        self.assertEqual(r["spaceId"], self.alice["id"])
        self.assertEqual(r["displayName"], self.alice["username"])
        self.assertEqual(len(r["nodes"]), 1)
        # 设为 private:游客 404,owner 与 admin 可读
        with db_sqlite._db() as conn:
            conn.execute("UPDATE users SET space_visibility = 'private' WHERE id = ?", (self.alice["id"],))
        with self.assertRaises(HTTPException) as ctx:
            _space_graph(_FakeReq(), self.alice["id"])
        self.assertEqual(ctx.exception.status_code, 404)
        alice_token = auth.create_session(self.alice["id"])
        g2 = _space_graph(_FakeReq({auth.SESSION_COOKIE: alice_token}), self.alice["id"])
        self.assertEqual(len(g2["nodes"]), 1)
        admin_token = auth.create_session(self.admin["id"])
        g3 = _space_graph(_FakeReq({auth.SESSION_COOKIE: admin_token}), self.alice["id"])
        self.assertEqual(len(g3["nodes"]), 1)
        # 全部 private 后随机跃迁 404
        with self.assertRaises(HTTPException) as ctx:
            space.random_space_graph(_FakeReq())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_space_graph_by_username(self) -> None:
        """游客落地星云:按用户名(大小写不敏感)取公开星云;未公开/不存在 404。"""
        g = space.space_graph_by_username("ALICE", _FakeReq())
        self.assertEqual(g["spaceId"], self.alice["id"])
        self.assertEqual(g["displayName"], "alice")
        self.assertIn("nodes", g)
        self.assertIn("edges", g)
        # 未公开 -> 游客 404(不暴露存在性)
        with db_sqlite._db() as conn:
            conn.execute(
                "UPDATE users SET space_visibility = 'private' WHERE id = ?",
                (self.alice["id"],),
            )
        with self.assertRaises(HTTPException) as ctx:
            space.space_graph_by_username("alice", _FakeReq())
        self.assertEqual(ctx.exception.status_code, 404)
        # 本人(owner)可经 by-username 访问自己的 private 星云
        alice_token = auth.create_session(self.alice["id"])
        g2 = space.space_graph_by_username(
            "alice", _FakeReq({auth.SESSION_COOKIE: alice_token})
        )
        self.assertEqual(g2["spaceId"], self.alice["id"])
        # 不存在的用户名 -> 404
        with self.assertRaises(HTTPException) as ctx:
            space.space_graph_by_username("nobody", _FakeReq())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_random_jump_excludes_own_space(self) -> None:
        """随机跃迁不会落到浏览者自己的星云(自己无法关注自己,卡片角标为「我」)。"""
        with db_sqlite._db() as conn:
            conn.execute(
                "UPDATE users SET space_visibility = 'private' WHERE id IN (?, ?)",
                (self.admin["id"], self.bob["id"]),
            )
        # 唯一公开星云是 alice 自己:作为 alice 访问时随机跃迁应 404(排除自己)
        alice_token = auth.create_session(self.alice["id"])
        with self.assertRaises(HTTPException) as ctx:
            space.random_space_graph(_FakeReq({auth.SESSION_COOKIE: alice_token}))
        self.assertEqual(ctx.exception.status_code, 404)
        # 游客视角不受影响:仍可跃迁到 alice 的公开星云
        r = space.random_space_graph(_FakeReq())
        self.assertEqual(r["spaceId"], self.alice["id"])

    def test_disabled_user_space_not_accessible(self) -> None:
        """禁用用户(status='disabled')的星云对游客/本人/admin 一律 404,随机跃迁排除。"""
        my_create("authors", {"originalName": "A", "Name_CN": "甲"}, user=self.alice)
        with db_sqlite._db() as conn:
            conn.execute(
                "UPDATE users SET space_visibility = 'private' WHERE id IN (?, ?)",
                (self.admin["id"], self.bob["id"]),
            )
            conn.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (self.alice["id"],))
        # 游客访问已禁用用户的公开星云:404(与关注语义一致,不暴露存在性)
        with self.assertRaises(HTTPException) as ctx:
            _space_graph(_FakeReq(), self.alice["id"])
        self.assertEqual(ctx.exception.status_code, 404)
        # 本人(会话已失效)与 admin 同样 404,空间访问统一按 active 用户判定
        alice_token = auth.create_session(self.alice["id"])
        with self.assertRaises(HTTPException) as ctx:
            _space_graph(_FakeReq({auth.SESSION_COOKIE: alice_token}), self.alice["id"])
        self.assertEqual(ctx.exception.status_code, 404)
        admin_token = auth.create_session(self.admin["id"])
        with self.assertRaises(HTTPException) as ctx:
            _space_graph(_FakeReq({auth.SESSION_COOKIE: admin_token}), self.alice["id"])
        self.assertEqual(ctx.exception.status_code, 404)
        # 随机跃迁排除禁用用户:无可用星云时 404
        with self.assertRaises(HTTPException) as ctx:
            space.random_space_graph(_FakeReq())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_space_read_endpoints_for_visitors(self) -> None:
        """星际跃迁后的完整交互:搜索/详情/扩散/路径全部路由到目标星云。"""
        a1 = my_create("authors", {"originalName": "甲", "Name_CN": "甲"}, user=self.alice)["row"]
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
        req = _FakeReq()
        hits = _space_search(req, self.alice["id"], "甲书", 20)
        self.assertEqual([h["id"] for h in hits["hits"]], [w1["id"]])
        detail = _space_work_detail(req, self.alice["id"], w1["id"])
        self.assertEqual(detail["work"]["id"], w1["id"])
        self.assertEqual(detail["mentions"][0]["target"], w2["id"])
        ex = _space_expansion(req, self.alice["id"], w1["id"], 2)
        self.assertEqual(ex["centerId"], w1["id"])
        self.assertIn(w2["id"], [n["id"] for n in ex["nodes"]])
        p = _space_path(req, self.alice["id"], w1["id"], w2["id"], 15)
        self.assertEqual(p["nodes"], [w1["id"], w2["id"]])
        # 不存在的作品 404
        with self.assertRaises(HTTPException) as ctx:
            _space_work_detail(req, self.alice["id"], "no-such-id")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_edge_evidence_too_long_returns_400(self) -> None:
        """涟漪 evidence 超过 2000 字符返回 400(与 DB CHECK 对齐,不落 500)。"""
        a1 = my_create(
            "authors", {"originalName": "A", "Name_CN": "甲"}, user=self.alice
        )["row"]
        w1 = my_create(
            "works", {
                "language": "zh", "originalTitle": "A书", "Title_CN": "甲书",
                "author_id": a1["id"],
            },
            user=self.alice,
        )["row"]
        w2 = my_create(
            "works", {
                "language": "en", "originalTitle": "B书", "Title_CN": "乙书",
                "author_id": a1["id"],
            },
            user=self.alice,
        )["row"]
        with self.assertRaises(HTTPException) as ctx:
            my_create(
                "edges", {
                    "source_work_id": w1["id"], "target_work_id": w2["id"],
                    "evidence": "x" * 2001, "evidenceSource": "c1",
                },
                user=self.alice,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        # 恰好 2000 字符可通过
        ok = my_create(
            "edges", {
                "source_work_id": w1["id"], "target_work_id": w2["id"],
                "evidence": "x" * 2000, "evidenceSource": "c1",
            },
            user=self.alice,
        )["row"]
        self.assertEqual(len(ok["evidence"]), 2000)

"""关注模型好友测试:关注/取关幂等、自关注拒绝、目标校验、列表与关系查询、限流。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import app.follows as follows
from app import auth, db_sqlite, ratelimit


class FollowsTest(unittest.TestCase):
    ADMIN = "boss@test.local"
    ALICE = "alice@test.local"
    BOB = "bob@test.local"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "follows.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        ratelimit.clear_rate_limits()
        self.admin = auth.register(self.ADMIN, "admin-password-123", username="admin01")
        self.alice = auth.register(self.ALICE, "alice-password-123", username="alice")
        self.bob = auth.register(self.BOB, "bob-password-123", username="bobby")

    def test_follow_and_lists(self) -> None:
        follows.follow(self.bob["id"], user=self.alice)      # alice 关注 bob
        follows.follow(self.admin["id"], user=self.alice)    # alice 关注 admin
        # alice 的关注 = [admin, bob](按时间倒序,先关注 bob 再关注 admin)
        mine = follows.following_list(self.alice["id"])
        self.assertEqual([u["id"] for u in mine], [self.admin["id"], self.bob["id"]])
        self.assertEqual(mine[0]["displayName"], self.admin["username"])
        # bob / admin 的粉丝都包含 alice
        self.assertEqual([u["id"] for u in follows.followers_list(self.bob["id"])], [self.alice["id"]])
        self.assertEqual([u["id"] for u in follows.followers_list(self.admin["id"])], [self.alice["id"]])

    def test_follow_idempotent(self) -> None:
        follows.follow(self.bob["id"], user=self.alice)
        follows.follow(self.bob["id"], user=self.alice)
        self.assertEqual(len(follows.following_list(self.alice["id"])), 1)

    def test_self_follow_rejected(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            follows.follow(self.alice["id"], user=self.alice)
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx:
            follows.unfollow(self.alice["id"], user=self.alice)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_follow_missing_user_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            follows.follow("01a00000-0000-7000-8000-000000000099", user=self.alice)
        self.assertEqual(ctx.exception.status_code, 404)
        # 不存在的目标不会产生关注行
        self.assertEqual(follows.following_list(self.alice["id"]), [])

    def test_unfollow_idempotent(self) -> None:
        follows.follow(self.bob["id"], user=self.alice)
        result = follows.unfollow(self.bob["id"], user=self.alice)
        self.assertFalse(result["following"])
        self.assertEqual(follows.following_list(self.alice["id"]), [])
        # 重复取关也成功
        follows.unfollow(self.bob["id"], user=self.alice)

    def test_relation_both_directions(self) -> None:
        follows.follow(self.alice["id"], user=self.bob)  # bob 关注 alice
        rel = follows.follow_relation(self.alice["id"], user=self.bob)
        self.assertTrue(rel["following"])   # bob 关注了 alice
        self.assertFalse(rel["follower"])   # alice 没有关注 bob
        rel2 = follows.follow_relation(self.bob["id"], user=self.alice)
        self.assertFalse(rel2["following"])
        self.assertTrue(rel2["follower"])   # alice 是 bob 的粉丝
        self.assertEqual(follows.follow_relation(self.alice["id"], user=self.alice),
                         {"following": False, "follower": False})

    def test_follow_rate_limited(self) -> None:
        with patch.object(follows, "FOLLOW_LIMIT", 2):
            follows.follow(self.bob["id"], user=self.alice)
            follows.follow(self.admin["id"], user=self.alice)
            with self.assertRaises(HTTPException) as ctx:
                follows.follow(self.admin["id"], user=self.alice)
            self.assertEqual(ctx.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()

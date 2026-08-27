"""admin 用户管理接口测试:列表 / 禁用启用 / 角色 / 星云可见性 / VIP / 保护规则。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import app.admin as admin
from app import auth, db_sqlite


class AdminUsersTest(unittest.TestCase):
    ADMIN = "boss@test.local"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patch.object(db_sqlite, "DB_PATH", Path(self.tmp.name) / "users.db").start()
        patch.object(auth, "BOOTSTRAP_EMAIL", self.ADMIN).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.tmp.cleanup)
        self.admin = auth.register(self.ADMIN, "admin-password-123", username="admin")
        self.alice = auth.register("alice@test.local", "password123", username="alice")
        self.bob = auth.register("bob@test.local", "password123", username="bobby")

    def _list(self) -> list[dict]:
        return admin.admin_users(user=self.admin)["items"]

    def _patch(self, user_id: str, actor: dict | None = None, **fields) -> dict:
        return admin.admin_update_user(
            user_id, admin.UserPatchBody(**fields), user=actor or self.admin
        )

    def test_list_users_returns_all_with_fields(self) -> None:
        items = self._list()
        ids = {r["id"] for r in items}
        self.assertEqual(ids, {self.admin["id"], self.alice["id"], self.bob["id"]})
        alice = next(r for r in items if r["id"] == self.alice["id"])
        self.assertEqual(alice["username"], "alice")
        self.assertEqual(alice["role"], "user")
        self.assertEqual(alice["status"], "active")
        self.assertEqual(alice["space_visibility"], "public")
        self.assertFalse(alice["vip"])
        self.assertEqual(alice["counts"], {"authors": 0, "works": 0, "edges": 0})
        self.assertNotIn("password_hash", alice)

    def test_disable_user_revokes_login_and_space(self) -> None:
        self._patch(self.alice["id"], status="disabled")
        self.assertIsNone(auth.login("alice@test.local", "password123"))
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT status FROM users WHERE id = ?", (self.alice["id"],)
            ).fetchone()
        self.assertEqual(row["status"], "disabled")
        # 重新启用后恢复登录
        self._patch(self.alice["id"], status="active")
        self.assertIsNotNone(auth.login("alice@test.local", "password123"))

    def test_role_promote_and_demote(self) -> None:
        self._patch(self.bob["id"], role="admin")
        self.assertEqual(auth.login("bob@test.local", "password123")["role"], "admin")
        self._patch(self.bob["id"], role="user")
        self.assertEqual(auth.login("bob@test.local", "password123")["role"], "user")

    def test_self_modification_rejected(self) -> None:
        """不能修改自己的角色/状态(防止管理员把自己锁出系统)。"""
        with self.assertRaises(HTTPException) as ctx:
            self._patch(self.admin["id"], status="disabled")
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx2:
            self._patch(self.admin["id"], role="user")
        self.assertEqual(ctx2.exception.status_code, 400)

    def test_bootstrap_admin_protected(self) -> None:
        """引导管理员不可被禁用/降级(即使由其他管理员操作)。"""
        self._patch(self.bob["id"], role="admin")
        with self.assertRaises(HTTPException) as ctx:
            self._patch(self.admin["id"], actor=self.bob, status="disabled")
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx2:
            self._patch(self.admin["id"], actor=self.bob, role="user")
        self.assertEqual(ctx2.exception.status_code, 400)

    def test_visibility_and_vip_patch(self) -> None:
        self._patch(self.alice["id"], space_visibility="private", vip=True)
        with db_sqlite._db() as conn:
            row = conn.execute(
                "SELECT space_visibility, vip FROM users WHERE id = ?",
                (self.alice["id"],),
            ).fetchone()
        self.assertEqual(row["space_visibility"], "private")
        self.assertEqual(row["vip"], 1)
        self.assertTrue(auth.login("alice@test.local", "password123")["vip"])

    def test_vip_endpoint_still_works(self) -> None:
        """旧 VIP 接口(POST /users/{id}/vip)保持兼容并走同一写路径。"""
        result = admin.admin_set_vip(self.alice["id"], {"vip": True}, self.admin)
        self.assertTrue(result["ok"])
        self.assertTrue(auth.login("alice@test.local", "password123")["vip"])

    def test_update_writes_audit_without_password_hash(self) -> None:
        self._patch(self.alice["id"], role="admin", space_visibility="private")
        with db_sqlite._db() as conn:
            rows = conn.execute(
                "SELECT before, after, detail FROM audit_log"
                " WHERE kind = 'users' ORDER BY id DESC LIMIT 1"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        before = json.loads(rows[0]["before"] or "{}")
        after = json.loads(rows[0]["after"] or "{}")
        self.assertNotIn("password_hash", before)
        self.assertNotIn("password_hash", after)
        self.assertIn("role: user → admin", rows[0]["detail"])

    def test_missing_user_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            self._patch("01a00000-0000-7000-8000-000000000099", vip=True)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()

"""关注模型好友:单向关注(user 关注 friend),不改变星云可见性。

- POST /api/follow/{user_id}:关注(幂等);DELETE /api/follow/{user_id}:取关(幂等)
- GET /api/follow/following|followers:我的关注 / 粉丝列表(displayName 优先昵称、其次用户名)
- GET /api/follow/relation/{user_id}:我与该用户的关注关系
- 仅登录用户可用;不可关注自己;目标用户不存在 / 已禁用返回 404(不暴露存在性)
- 限流:每用户每小时最多 FOLLOW_LIMIT 次关注操作(复用进程内滑动窗口)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app import db_sqlite
from app.auth import require_user
from app.ratelimit import sliding_limited

router = APIRouter(prefix="/api/follow", tags=["follow"])

# 每用户每小时关注操作上限(取关不计入,降低误伤)
FOLLOW_LIMIT = 50
WINDOW_SECONDS = 3600.0

_now = db_sqlite.now_iso
_new_uuid = db_sqlite.new_uuid


def _display_name(row: dict) -> str:
    """星云显示名:昵称 > 用户名 > 兜底(不暴露邮箱)。"""
    return (
        (row.get("nickname") or "").strip()
        or (row.get("username") or "").strip()
        or "匿名星云"
    )


def _user_row(user_id: str) -> dict | None:
    """活跃用户(关注目标必须存在且 active)。"""
    with db_sqlite._db() as conn:
        row = conn.execute(
            "SELECT id, username, nickname, bio FROM users WHERE id = ? AND status = 'active'",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def _user_payload(row: dict) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "nickname": row["nickname"],
        "bio": row["bio"],
        "displayName": _display_name(row),
    }


def _follow(user_id: str, friend_id: str) -> None:
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM friendships WHERE user_id = ? AND friend_id = ?",
            (user_id, friend_id),
        ).fetchone()
        if exists:
            return  # 幂等:已关注则直接成功
        conn.execute(
            "INSERT INTO friendships (id, user_id, friend_id, created_at) VALUES (?, ?, ?, ?)",
            (_new_uuid(), user_id, friend_id, _now()),
        )


def _unfollow(user_id: str, friend_id: str) -> None:
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        conn.execute(
            "DELETE FROM friendships WHERE user_id = ? AND friend_id = ?",
            (user_id, friend_id),
        )


def following_list(user_id: str) -> list[dict]:
    """我关注的用户(按关注时间倒序)。"""
    with db_sqlite._db() as conn:
        rows = conn.execute(
            "SELECT u.id, u.username, u.nickname, u.bio FROM users u"
            " JOIN friendships f ON f.friend_id = u.id"
            " WHERE f.user_id = ? AND u.status = 'active'"
            " ORDER BY f.created_at DESC, f.id DESC",
            (user_id,),
        ).fetchall()
    return [_user_payload(dict(r)) for r in rows]


def followers_list(user_id: str) -> list[dict]:
    """关注我的用户(粉丝,按关注时间倒序)。"""
    with db_sqlite._db() as conn:
        rows = conn.execute(
            "SELECT u.id, u.username, u.nickname, u.bio FROM users u"
            " JOIN friendships f ON f.user_id = u.id"
            " WHERE f.friend_id = ? AND u.status = 'active'"
            " ORDER BY f.created_at DESC, f.id DESC",
            (user_id,),
        ).fetchall()
    return [_user_payload(dict(r)) for r in rows]


def relation(user_id: str, me_id: str) -> dict:
    """我与目标用户的关注关系:following=我关注了 TA;follower=TA 关注了我。"""
    with db_sqlite._db() as conn:
        following = conn.execute(
            "SELECT 1 FROM friendships WHERE user_id = ? AND friend_id = ?",
            (me_id, user_id),
        ).fetchone() is not None
        follower = conn.execute(
            "SELECT 1 FROM friendships WHERE user_id = ? AND friend_id = ?",
            (user_id, me_id),
        ).fetchone() is not None
    return {"following": following, "follower": follower}


@router.get("/following")
def my_following(user: dict = Depends(require_user)) -> dict:  # noqa: B008
    return {"items": following_list(user["id"])}


@router.get("/followers")
def my_followers(user: dict = Depends(require_user)) -> dict:  # noqa: B008
    return {"items": followers_list(user["id"])}


@router.get("/relation/{user_id}")
def follow_relation(user_id: str, user: dict = Depends(require_user)) -> dict:  # noqa: B008
    if user_id == user["id"]:
        return {"following": False, "follower": False}
    return relation(user_id, user["id"])


@router.post("/{user_id}")
def follow(user_id: str, user: dict = Depends(require_user)) -> dict:  # noqa: B008
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能关注自己")
    if sliding_limited(f"follow:{user['id']}", FOLLOW_LIMIT, WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="关注操作过于频繁,请稍后再试")
    if _user_row(user_id) is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    _follow(user["id"], user_id)
    return {"ok": True, "following": True}


@router.delete("/{user_id}")
def unfollow(user_id: str, user: dict = Depends(require_user)) -> dict:  # noqa: B008
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能对自己取关")
    _unfollow(user["id"], user_id)
    return {"ok": True, "following": False}

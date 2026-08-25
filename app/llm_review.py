"""AI 草稿审核 API(admin 角色):按上传者隔离的 AI 草稿 → 公共星云。

流程:
    1) 导入(Web/CLI)把 AI 提取的作者/作品/涟漪写入上传者的空间,
       owner_id=上传者、reviewStatus='draft'、created_by='llm'
       (见 app/ai_assistant/tools/review_publish.py ingest)。
    2) admin 在本页浏览草稿(附与公共星云的去重提示),可编辑/驳回/重开。
    3) 批准:默认复制进公共星云(created_by='llm'、reviewStatus='reviewed');
       或按去重提示选择「复用」现有公共记录。
       草稿行回写 published_to_id(公共行 id),同一草稿不可重复发布。

隔离规则:
    - 草稿区 = 上传者的空间(owner_id=上传者 + created_by='llm'),admin 只能
      看到自己上传的草稿;公共星云/策展/导出读取统一排除 AI 草稿
      (见 db_sqlite.ai_draft_clause);
    - 公共星云 = 引导管理员(admin)空间;
    - 批准复制依赖先决条件:作品依赖的作者、涟漪依赖的两端作品必须已批准,
      依赖通过草稿行的 published_to_id 解析到公共行 id,保证引用不跨空间。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import db_sqlite, sqlite_store
from app.auth import admin_user_id, require_admin
from app.data_store import clean_row
from app.dedupe_util import char_bigrams, jaccard, load_rows, normalize_title
from app.llm_account import migrate_legacy_llm_drafts
from app.space_crud import Kind, after_write, validate_row

router = APIRouter(
    prefix="/api/admin/llm",
    tags=["llm"],
    dependencies=[Depends(require_admin)],
)

KIND_TABLE = sqlite_store.KIND_TABLE


def _author_id_list(value) -> list[str]:
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def _label(kind: Kind, row: dict) -> str:
    if kind == "authors":
        return str(row.get("Name_CN") or row.get("originalName") or row.get("id") or "")
    if kind == "works":
        return str(row.get("Title_CN") or row.get("originalTitle") or row.get("id") or "")
    return f"{row.get('source_work_id')} → {row.get('target_work_id')}"


# ======================================================================
# 公共空间数据 + 去重提示(基础匹配原语与行读取共用 app/dedupe_util)
# ======================================================================


def _best_hit(
    cand_variants: list[str],
    rows: list[dict],
    row_variants,
    row_label,
    cand_author: str = "",
    row_author=lambda r: r.get("author_names") or "",
) -> dict[str, Any] | None:
    """对公共行做基础匹配,返回最高命中 {level, existing_id, existing_label, score}。"""
    best: dict[str, Any] | None = None
    for row in rows:
        for cv in cand_variants:
            if not cv:
                continue
            for rv in row_variants(row):
                if not rv:
                    continue
                if cv == rv:
                    level, score = "exact", 1.0
                    if cand_author and row_author(row) and normalize_title(cand_author) != normalize_title(row_author(row)):
                        level, score = "exact_diff_author", 0.5
                elif len(cv) >= 2 and len(rv) >= 2 and (cv in rv or rv in cv):
                    level, score = "contained", 0.7
                else:
                    sim = jaccard(char_bigrams(cv), char_bigrams(rv))
                    if sim < 0.45:
                        continue
                    level, score = "token", round(sim, 3)
                if best is None or score > best["score"]:
                    best = {
                        "level": level,
                        "score": score,
                        "existing_id": row["id"],
                        "existing_label": row_label(row),
                    }
    return best


def _hint_author(row: dict, public_authors: list[dict]) -> dict[str, Any] | None:
    cand = [normalize_title(row.get("Name_CN")), normalize_title(row.get("Name_EN")), normalize_title(row.get("originalName"))]
    hit = _best_hit(
        cand,
        public_authors,
        lambda r: [normalize_title(r.get("Name_CN")), normalize_title(r.get("Name_EN")), normalize_title(r.get("originalName"))],
        lambda r: r.get("Name_CN") or r.get("Name_EN") or r.get("originalName") or r["id"],
    )
    return hit


def _hint_work(row: dict, public_works: list[dict], author_names: list[str]) -> dict[str, Any] | None:
    cand = [normalize_title(row.get("Title_CN")), normalize_title(row.get("originalTitle")),
            normalize_title(row.get("Title_EN")), normalize_title(row.get("Title_Other"))]
    return _best_hit(
        cand,
        public_works,
        lambda r: [normalize_title(r.get("Title_CN")), normalize_title(r.get("originalTitle")),
                   normalize_title(r.get("Title_EN")), normalize_title(r.get("Title_Other"))],
        lambda r: r.get("Title_CN") or r.get("originalTitle") or r["id"],
        cand_author=normalize_title(" ".join(n for n in author_names if n)),
    )


# ======================================================================
# 草稿读取
# ======================================================================
def _draft_rows(owner_id: str) -> dict:
    """读取某 admin 的 AI 草稿行(owner_id=上传者 + created_by='llm')。

    返回 {"authors", "works", "edges"} 三张列表(活跃行,不含软删除);
    草稿判定与公共读取的排除条件一致(见 db_sqlite.ai_draft_clause)。
    """
    draft = db_sqlite.ai_draft_clause()
    with db_sqlite._db() as conn:
        authors = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM authors WHERE owner_id = ? AND deletedAt IS NULL"
                f" AND {draft} ORDER BY id",
                (owner_id,),
            )
        ]
        works = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM works WHERE owner_id = ? AND deletedAt IS NULL"
                f" AND {draft} ORDER BY id",
                (owner_id,),
            )
        ]
        edges = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM edges WHERE owner_id = ? AND deletedAt IS NULL"
                f" AND {draft} ORDER BY id",
                (owner_id,),
            )
        ]
    return {"authors": authors, "works": works, "edges": edges}


@router.get("/drafts")
def llm_drafts(user: dict = Depends(require_admin)) -> dict:  # noqa: B008
    """当前 admin 上传的 AI 草稿(owner_id=user + created_by='llm')+ 公共星云去重提示。"""
    migrate_legacy_llm_drafts()  # 旧 system_llm 共享草稿一次性改挂到引导管理员
    owner = user["id"]
    data = _draft_rows(owner)
    counts = {
        "authors": len(data["authors"]),
        "works": len(data["works"]),
        "edges": len(data["edges"]),
        "deleted": {"authors": 0, "works": 0, "edges": 0},
    }
    data["warnings"] = {
        "duplicateAuthorNames": [],
        "duplicateWorkTitles": [],
        "duplicateEdgePairs": [],
    }
    data["counts"] = counts
    admin = admin_user_id()
    public = load_rows(public_only=True)
    public_authors, public_works = public["authors"], public["works"]
    staging_author_names = {
        a["id"]: (a.get("Name_CN") or a.get("Name_EN") or "")
        for a in data["authors"]
    }
    hints_a = {r["id"]: _hint_author(r, public_authors) for r in data["authors"]}
    hints_w = {
        r["id"]: _hint_work(
            r,
            public_works,
            [staging_author_names.get(aid, "") for aid in _author_id_list(r.get("author_id"))],
        )
        for r in data["works"]
    }
    hints_e: dict[str, Any] = {}
    with db_sqlite._db() as conn:
        # 批量取回草稿作品的发布映射,避免对每条涟漪重复查库(N+1)
        edge_ids = [r["id"] for r in data["edges"]]
        published_by_id: dict[str, Any] = {}
        if edge_ids:
            placeholders = ",".join("?" for _ in edge_ids)
            pub_rows = conn.execute(
                f"SELECT id, published_to_id FROM works WHERE id IN ({placeholders})"
                " AND owner_id = ?",
                (*edge_ids, owner),
            ).fetchall()
            published_by_id = {r["id"]: r["published_to_id"] for r in pub_rows}
        for r in data["edges"]:
            src_id = published_by_id.get(r.get("source_work_id"))
            tgt_id = published_by_id.get(r.get("target_work_id"))
            if not (src_id and tgt_id):
                continue
            dup = conn.execute(
                "SELECT id, source_work_id, target_work_id FROM edges"
                " WHERE source_work_id = ? AND target_work_id = ? AND deletedAt IS NULL"
                " AND (owner_id = ? OR owner_id IS NULL)",
                (src_id, tgt_id, admin),
            ).fetchone()
            if dup:
                hints_e[r["id"]] = {
                    "level": "edge_duplicate",
                    "score": 1.0,
                    "existing_id": dup["id"],
                    "existing_label": f"{dup['source_work_id']} → {dup['target_work_id']}",
                }
    return {
        "staging": data,
        "hints": {"authors": hints_a, "works": hints_w, "edges": hints_e},
        "public_counts": {"authors": len(public_authors), "works": len(public_works)},
    }


# ======================================================================
# 草稿操作
# ======================================================================
@router.post("/drafts/clear")
def clear_drafts(user: dict = Depends(require_admin)) -> dict:  # noqa: B008
    """清空当前 admin 上传的 AI 草稿(owner_id=user + created_by='llm')。

    不影响其他 admin 的草稿与公共星云已发布数据;软删除保留行
    (带 deletedAt)可恢复,审计留痕。
    """
    owner = user["id"]
    now = db_sqlite.now_iso()
    counts: dict[str, int] = {"authors": 0, "works": 0, "edges": 0}
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        for kind in ("authors", "works", "edges"):
            rows = conn.execute(
                f"SELECT id FROM {KIND_TABLE[kind]}"
                f" WHERE owner_id = ? AND deletedAt IS NULL"
                f" AND {db_sqlite.ai_draft_clause()}",
                (owner,),
            ).fetchall()
            ids = [r["id"] for r in rows]
            if not ids:
                continue
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE {KIND_TABLE[kind]} SET deletedAt = ?, updatedAt = ?"
                f" WHERE id IN ({placeholders}) AND owner_id = ?",
                (now, now, *ids, owner),
            )
            counts[kind] = len(ids)
            db_sqlite.audit(
                conn,
                "delete",
                kind,
                None,
                f"清空 AI 草稿:软删除 {len(ids)} 条",
                actor=user["email"],
            )
    return {"ok": True, "counts": counts}


def _staging_row(conn, kind: Kind, item_id: str, owner: str) -> dict:
    row = sqlite_store.get_row(conn, kind, item_id, owner)
    if row is None:
        raise HTTPException(status_code=404, detail=f"草稿不存在:{item_id}")
    if row.get("deletedAt"):
        raise HTTPException(status_code=409, detail="草稿已删除")
    if row.get("published_to_id"):
        raise HTTPException(status_code=409, detail="该草稿已批准发布,不可重复操作")
    return row


def _resolve_published(conn, kind: Kind, staging_id: str, owner: str) -> str:
    """草稿依赖解析:作者/作品草稿必须已批准(published_to_id 非空)。"""
    row = conn.execute(
        f"SELECT published_to_id FROM {KIND_TABLE[kind]} WHERE id = ? AND owner_id = ?",
        (staging_id, owner),
    ).fetchone()
    if row is None or not row["published_to_id"]:
        raise HTTPException(
            status_code=409,
            detail=f"依赖草稿 {staging_id} 尚未批准发布,请先处理其作者/作品",
        )
    return row["published_to_id"]


def _public_payload(conn, kind: Kind, staging: dict, staging_owner: str, admin_id: str) -> dict:
    """由草稿构造公共行载荷(依赖解析到公共 id)。"""
    now = db_sqlite.now_iso()
    if kind == "authors":
        row = {
            k: staging.get(k)
            for k in ("originalName", "Name_CN", "Name_EN", "nationality",
                      "birthYear", "deathYear", "note")
        }
    elif kind == "works":
        # 作者关联存在 work_authors 表(get_row 不返回 author_id),
        # 直接查草稿行关联,保证依赖校验对「作者未批准」的草稿生效
        draft_author_ids = [
            r["author_id"]
            for r in conn.execute(
                "SELECT author_id FROM work_authors WHERE work_id = ?", (staging["id"],)
            )
        ]
        public_authors = [
            _resolve_published(conn, "authors", aid, staging_owner)
            for aid in draft_author_ids
        ]
        row = {
            k: staging.get(k)
            for k in ("language", "originalTitle", "Title_CN", "Title_EN", "Title_Other",
                      "publicationYear", "genre", "note", "recommendation", "review",
                      "readingStatus")
        }
        row["author_id"] = ",".join(public_authors)
    else:
        row = {
            k: staging.get(k)
            for k in ("evidence", "evidenceSource", "note")
        }
        row["source_work_id"] = _resolve_published(conn, "works", staging["source_work_id"], staging_owner)
        row["target_work_id"] = _resolve_published(conn, "works", staging["target_work_id"], staging_owner)
    row = clean_row(row)
    row["id"] = db_sqlite.new_uuid()
    row["reviewStatus"] = "reviewed"
    row["createdAt"] = now
    row["updatedAt"] = now
    return row


class ApproveBody(BaseModel):
    reuse_id: str | None = None


@router.post("/drafts/{kind}/{item_id}/approve")
def approve_draft(
    kind: Kind,
    item_id: str,
    body: ApproveBody | None = None,
    user: dict = Depends(require_admin),  # noqa: B008
) -> dict:
    """批准草稿:复制进公共星云(默认),或复用现有公共记录(reuse_id)。"""
    admin_id = user["id"]
    staging_owner = user["id"]
    reuse_id = ((body.reuse_id if body else None) or "").strip() or None
    now = db_sqlite.now_iso()
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        staging = _staging_row(conn, kind, item_id, staging_owner)
        if reuse_id:
            target = sqlite_store.get_row(conn, kind, reuse_id)
            if target is None or target.get("deletedAt") or target.get("owner_id") not in (admin_id, None):
                raise HTTPException(status_code=404, detail="复用目标在公共星云不存在或已删除")
            sqlite_store.update_row(
                conn, kind, item_id, staging, owner_id=staging_owner,
                extra={"published_to_id": reuse_id, "reviewStatus": "reviewed", "updatedAt": now},
            )
            db_sqlite.audit(
                conn, "llm_reuse", kind, item_id,
                f"复用公共记录发布「{_label(kind, staging)}」→ #{reuse_id}",
                before=staging,
                after={**staging, "published_to_id": reuse_id, "reviewStatus": "reviewed"},
                actor=user["email"],
            )
            return {"ok": True, "mode": "reuse", "public_id": reuse_id}

        public_row = _public_payload(conn, kind, staging, staging_owner, admin_id)
        errors = validate_row(conn, kind, public_row, owner_id=admin_id)
        if errors:
            raise HTTPException(status_code=409, detail="校验失败:\n- " + "\n".join(errors))
        sqlite_store.insert_row(
            conn, kind, public_row, owner_id=admin_id, extra={"created_by": "llm"},
        )
        if kind == "works":
            sqlite_store.set_work_authors(conn, public_row["id"], _author_id_list(public_row.get("author_id")))
        db_sqlite.audit(
            conn, "create", kind, public_row["id"],
            f"AI 草稿发布「{_label(kind, public_row)}」",
            after=public_row,
            actor=user["email"],
        )
        sqlite_store.update_row(
            conn, kind, item_id, staging, owner_id=staging_owner,
            extra={"published_to_id": public_row["id"], "reviewStatus": "reviewed", "updatedAt": now},
        )
        db_sqlite.audit(
            conn, "llm_publish", kind, item_id,
            f"草稿「{_label(kind, staging)}」发布到公共星云 → #{public_row['id']}",
            before=staging,
            after={**staging, "published_to_id": public_row["id"], "reviewStatus": "reviewed"},
            actor=user["email"],
        )
    after_write(admin_id)
    return {"ok": True, "mode": "copy", "public_id": public_row["id"]}


@router.post("/drafts/{kind}/{item_id}/reject")
def reject_draft(
    kind: Kind,
    item_id: str,
    user: dict = Depends(require_admin),  # noqa: B008
) -> dict:
    """驳回草稿(reviewStatus='rejected',草稿保留可重开)。"""
    staging_owner = user["id"]
    now = db_sqlite.now_iso()
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        staging = _staging_row(conn, kind, item_id, staging_owner)
        if staging.get("reviewStatus") == "rejected":
            return {"ok": True, "reviewStatus": "rejected"}
        sqlite_store.update_row(
            conn, kind, item_id, staging, owner_id=staging_owner,
            extra={"reviewStatus": "rejected", "updatedAt": now},
        )
        db_sqlite.audit(
            conn, "llm_reject", kind, item_id,
            f"驳回草稿「{_label(kind, staging)}」",
            before=staging,
            after={**staging, "reviewStatus": "rejected"},
            actor=user["email"],
        )
    return {"ok": True, "reviewStatus": "rejected"}


@router.post("/drafts/{kind}/{item_id}/reopen")
def reopen_draft(
    kind: Kind,
    item_id: str,
    user: dict = Depends(require_admin),  # noqa: B008
) -> dict:
    """重开草稿:rejected → draft,重新进入审核队列。"""
    staging_owner = user["id"]
    now = db_sqlite.now_iso()
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        staging = _staging_row(conn, kind, item_id, staging_owner)
        if staging.get("reviewStatus") != "rejected":
            return {"ok": True, "reviewStatus": staging.get("reviewStatus", "draft")}
        sqlite_store.update_row(
            conn, kind, item_id, staging, owner_id=staging_owner,
            extra={"reviewStatus": "draft", "updatedAt": now},
        )
        db_sqlite.audit(
            conn, "llm_reopen", kind, item_id,
            f"重开草稿「{_label(kind, staging)}」",
            before=staging,
            after={**staging, "reviewStatus": "draft"},
            actor=user["email"],
        )
    return {"ok": True, "reviewStatus": "draft"}


@router.put("/drafts/{kind}/{item_id}")
def edit_draft(
    kind: Kind,
    item_id: str,
    row: dict,
    user: dict = Depends(require_admin),  # noqa: B008
) -> dict:
    """编辑草稿内容(修正 AI 提取),审核状态保持不变;已发布的草稿不可再编辑。"""
    staging_owner = user["id"]
    now = db_sqlite.now_iso()
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        staging = _staging_row(conn, kind, item_id, staging_owner)
        merged = clean_row({**staging, **row})
        merged["id"] = item_id
        merged["createdAt"] = staging.get("createdAt") or now
        merged["updatedAt"] = now
        merged["reviewStatus"] = staging.get("reviewStatus", "draft")  # 保留审核状态
        errors = validate_row(conn, kind, merged, exclude_id=item_id, owner_id=staging_owner)
        if errors:
            raise HTTPException(status_code=409, detail="校验失败:\n- " + "\n".join(errors))
        status = sqlite_store.update_row(
            conn, kind, item_id, merged, expected_updated_at=staging.get("updatedAt"),
            owner_id=staging_owner, extra={"updatedAt": now},
        )
        if status == -1:
            raise HTTPException(status_code=409, detail="草稿已被其他人修改,请刷新后重试")
        if status == 0:
            raise HTTPException(status_code=404, detail=f"未找到草稿:{item_id}")
        if kind == "works":
            sqlite_store.set_work_authors(conn, item_id, _author_id_list(merged.get("author_id")))
        db_sqlite.audit(
            conn, "update", kind, item_id,
            f"编辑草稿「{_label(kind, merged)}」",
            before=staging,
            after=merged,
            actor=user["email"],
        )
        return {"ok": True, "row": merged}


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
from app.ai_assistant.tools import dedupe_check
from app.auth import admin_user_id, require_admin
from app.data_store import clean_row
from app.dedupe_util import load_user_rows
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
# 去重提示(统一走 dedupe_check 基础匹配,判重目标 = 当前用户个人空间)
# ======================================================================


def _hint_author(row: dict, user_rows: dict) -> dict[str, Any] | None:
    """作者基础匹配提示(与去重管线同一实现)。"""
    hit = dedupe_check.basic_match_author(row, user_rows["authors"])
    if hit.get("level") == "none":
        return None
    existing = hit.get("existing") or {}
    return {
        "level": hit["level"],
        "score": hit["score"],
        "existing_id": existing.get("id"),
        "existing_label": (
            existing.get("Name_CN") or existing.get("Name_EN")
            or existing.get("originalName") or existing.get("id") or ""
        ),
    }


def _hint_work(row: dict, user_rows: dict, author_names: list[str]) -> dict[str, Any] | None:
    """作品基础匹配提示(作者名用于同名异书消歧,与去重管线同一实现)。"""
    cand = dict(row)
    names = " ".join(n for n in author_names if n)
    if names:
        cand["author"] = names
    hit = dedupe_check.basic_match_work(cand, user_rows["works"])
    if hit.get("level") == "none":
        return None
    existing = hit.get("existing") or {}
    return {
        "level": hit["level"],
        "score": hit["score"],
        "existing_id": existing.get("id"),
        "existing_label": (
            existing.get("Title_CN") or existing.get("originalTitle")
            or existing.get("id") or ""
        ),
    }


# ======================================================================
# 草稿读取
# ======================================================================
def _draft_rows(owner_id: str) -> dict:
    """读取某 admin 的 AI 草稿行(owner_id=上传者 + created_by='llm')。

    返回 {"authors", "works", "edges", "work_authors"} 四张列表(活跃行,
    不含软删除);草稿判定与公共读取的排除条件一致(见 db_sqlite.ai_draft_clause)。
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
        wa_rows = conn.execute(
            "SELECT wa.work_id, wa.author_id FROM work_authors wa"
            " JOIN works w ON w.id = wa.work_id"
            f" WHERE w.owner_id = ? AND w.deletedAt IS NULL AND {db_sqlite.ai_draft_clause('w')}"
            " ORDER BY wa.work_id, wa.author_id",
            (owner_id,),
        ).fetchall()
    return {
        "authors": authors,
        "works": works,
        "edges": edges,
        "work_authors": [dict(r) for r in wa_rows],
    }


def _draft_batches(owner_id: str) -> tuple[list[dict], list[dict]]:
    """按源书作品分组 AI 草稿为「批次」,并列出已发布条目。

    批次 = 一部导入的书:source(作品+作者) + ripples(每条涟漪含目标作品/作者与
    证据,字段对齐「点亮星空」表单)。无涟漪的孤立作品视为 0 涟漪批次
    (--no-ripples 导入)。返回 (batches, published)。
    """
    rows = _draft_rows(owner_id)
    authors_by_id = {a["id"]: a for a in rows["authors"]}
    works_by_id = {w["id"]: w for w in rows["works"]}
    wa_by_work: dict[str, list[dict]] = {}
    for r in rows["work_authors"]:
        author = authors_by_id.get(r["author_id"])
        if author is not None:
            wa_by_work.setdefault(r["work_id"], []).append(author)

    src_ids = {e["source_work_id"] for e in rows["edges"] if e["source_work_id"] in works_by_id}
    tgt_ids = {e["target_work_id"] for e in rows["edges"] if e["target_work_id"] in works_by_id}
    # 孤立作品(非任何涟漪端点)按 0 涟漪批次处理(--no-ripples 的源书)
    orphan_ids = [w["id"] for w in rows["works"] if w["id"] not in src_ids and w["id"] not in tgt_ids]

    batches: list[dict] = []
    for wid in sorted(src_ids) + sorted(orphan_ids):
        work = works_by_id[wid]
        batch_edges = sorted(
            (e for e in rows["edges"] if e["source_work_id"] == wid),
            key=lambda e: e["id"],
        )
        ripples: list[dict] = []
        for e in batch_edges:
            target_work = works_by_id.get(e["target_work_id"])
            ripples.append({
                "edge": e,
                "target": {
                    "work": target_work,
                    "authors": wa_by_work.get(e["target_work_id"]) or [],
                } if target_work else None,
            })
        batches.append({
            "source": {
                "work": work,
                "authors": wa_by_work.get(wid) or [],
            },
            "ripples": ripples,
            "created_at": work.get("createdAt") or "",
        })

    published: list[dict] = []
    for kind, table_rows in (("authors", rows["authors"]), ("works", rows["works"]), ("edges", rows["edges"])):
        for r in table_rows:
            public_id = r.get("published_to_id")
            if not public_id:
                continue
            if kind == "authors":
                label = r.get("Name_CN") or r.get("originalName") or r["id"]
            elif kind == "works":
                label = r.get("Title_CN") or r.get("originalTitle") or r["id"]
            else:
                src = works_by_id.get(r.get("source_work_id")) or {}
                tgt = works_by_id.get(r.get("target_work_id")) or {}
                label = (
                    f"{src.get('Title_CN') or r.get('source_work_id')}"
                    f" → {tgt.get('Title_CN') or r.get('target_work_id')}"
                )
            published.append({
                "kind": kind,
                "id": r["id"],
                "label": label,
                "public_id": public_id,
            })
    published.sort(key=lambda x: x["label"])
    return batches, published


@router.get("/drafts")
def llm_drafts(user: dict = Depends(require_admin)) -> dict:  # noqa: B008
    """当前 admin 上传的 AI 草稿,按导入批次(源书)分组 + 公共星云去重提示。"""
    migrate_legacy_llm_drafts()  # 旧 system_llm 共享草稿一次性改挂到引导管理员
    owner = user["id"]
    batches, published = _draft_batches(owner)

    admin = admin_user_id()
    user_rows = load_user_rows(admin)
    public_authors, public_works = user_rows["authors"], user_rows["works"]

    # 收集批次内全部作者/作品,批量算去重提示(源书与目标作品都会用)
    batch_works: dict[str, dict] = {}
    batch_authors: dict[str, dict] = {}
    for b in batches:
        src = b["source"]
        batch_works[src["work"]["id"]] = src["work"]
        for a in src["authors"]:
            batch_authors[a["id"]] = a
        for r in b["ripples"]:
            if not r["target"]:
                continue
            batch_works[r["target"]["work"]["id"]] = r["target"]["work"]
            for a in r["target"]["authors"]:
                batch_authors[a["id"]] = a
    # 作品作者名按 work_authors 解析(works 表没有 author_id 列),
    # 供同名异书(exact_diff_author)降级判断使用
    work_author_names: dict[str, list[str]] = {}
    for b in batches:
        src_names = [
            a.get("Name_CN") or a.get("Name_EN") or a.get("originalName") or ""
            for a in b["source"]["authors"]
        ]
        work_author_names[b["source"]["work"]["id"]] = src_names
        for r in b["ripples"]:
            if not r["target"]:
                continue
            tgt_names = [
                a.get("Name_CN") or a.get("Name_EN") or a.get("originalName") or ""
                for a in r["target"]["authors"]
            ]
            work_author_names[r["target"]["work"]["id"]] = tgt_names
    hints_a = {aid: _hint_author(a, user_rows) for aid, a in batch_authors.items()}
    hints_w = {
        wid: _hint_work(w, user_rows, work_author_names.get(wid) or [])
        for wid, w in batch_works.items()
    }

    for b in batches:
        b["source"]["hint"] = hints_w.get(b["source"]["work"]["id"])
        b["source"]["author_hint"] = (
            hints_a.get(b["source"]["authors"][0]["id"]) if b["source"]["authors"] else None
        )
        for r in b["ripples"]:
            if not r["target"]:
                r["hint"] = None
                r["author_hint"] = None
                continue
            r["hint"] = hints_w.get(r["target"]["work"]["id"])
            r["author_hint"] = (
                hints_a.get(r["target"]["authors"][0]["id"]) if r["target"]["authors"] else None
            )

    hints_e: dict[str, Any] = {}
    with db_sqlite._db() as conn:
        # 批量取回草稿作品的发布映射,避免对每条涟漪重复查库(N+1)
        edge_ids = [r["edge"]["id"] for b in batches for r in b["ripples"]]
        published_by_id: dict[str, Any] = {}
        if edge_ids:
            placeholders = ",".join("?" for _ in edge_ids)
            pub_rows = conn.execute(
                f"SELECT id, published_to_id FROM works WHERE id IN ({placeholders})"
                " AND owner_id = ?",
                (*edge_ids, owner),
            ).fetchall()
            published_by_id = {r["id"]: r["published_to_id"] for r in pub_rows}

        def resolve_public_work(wid: str | None) -> str | None:
            """把草稿端点作品解析到公共作品 id:
            已发布用 published_to_id,否则用精确去重命中的公共 id。"""
            if not wid:
                return None
            pub = published_by_id.get(wid)
            if pub:
                return pub
            hint = hints_w.get(wid)
            if hint and hint.get("level") == "exact":
                return hint.get("existing_id")
            return None

        for b in batches:
            for r in b["ripples"]:
                e = r["edge"]
                src_id = resolve_public_work(e.get("source_work_id"))
                tgt_id = resolve_public_work(e.get("target_work_id"))
                if not (src_id and tgt_id):
                    continue
                dup = conn.execute(
                    "SELECT e.id, e.source_work_id, e.target_work_id,"
                    " ws.Title_CN AS src_title, wt.Title_CN AS tgt_title"
                    " FROM edges e"
                    " LEFT JOIN works ws ON ws.id = e.source_work_id"
                    " LEFT JOIN works wt ON wt.id = e.target_work_id"
                    " WHERE e.source_work_id = ? AND e.target_work_id = ?"
                    " AND e.deletedAt IS NULL AND (e.owner_id = ? OR e.owner_id IS NULL)",
                    (src_id, tgt_id, admin),
                ).fetchone()
                if dup:
                    hints_e[e["id"]] = {
                        "level": "edge_duplicate",
                        "score": 1.0,
                        "existing_id": dup["id"],
                        "existing_label": (
                            f"{dup['src_title'] or dup['source_work_id']}"
                            f" → {dup['tgt_title'] or dup['target_work_id']}"
                        ),
                    }
        for b in batches:
            for r in b["ripples"]:
                r["edge_hint"] = hints_e.get(r["edge"]["id"])

    counts = {
        "batches": len(batches),
        "ripples": sum(len(b["ripples"]) for b in batches),
        "published": len(published),
    }
    return {
        "batches": batches,
        "published": published,
        "counts": counts,
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


class ApproveRippleBody(BaseModel):
    reuse_source_work_id: str | None = None
    reuse_source_author_id: str | None = None
    reuse_target_work_id: str | None = None
    reuse_target_author_id: str | None = None
    reuse_edge_id: str | None = None


class ApproveSourceBody(BaseModel):
    reuse_work_id: str | None = None
    reuse_author_id: str | None = None


def _draft_work_authors(conn, work_id: str, owner: str) -> list[dict]:
    """草稿作品的作者行(按 work_authors 关联,活跃作者)。"""
    rows = conn.execute(
        "SELECT a.* FROM work_authors wa JOIN authors a ON a.id = wa.author_id"
        " WHERE wa.work_id = ? AND a.owner_id = ? AND a.deletedAt IS NULL",
        (work_id, owner),
    ).fetchall()
    return [dict(r) for r in rows]


def _publish_draft_entity(
    conn,
    kind: Kind,
    draft: dict,
    owner: str,
    admin_id: str,
    reuse_id: str | None,
    actor: str,
) -> str:
    """把单条草稿发布/复用到公共星云;已发布直接返回现有公共 id。

    返回公共行 id;审计 create / llm_publish / llm_reuse 留痕。
    """
    existing = draft.get("published_to_id")
    if existing:
        return existing
    now = db_sqlite.now_iso()
    reuse_id = (reuse_id or "").strip() or None
    if reuse_id:
        target = sqlite_store.get_row(conn, kind, reuse_id)
        if target is None or target.get("deletedAt") or target.get("owner_id") not in (admin_id, None):
            raise HTTPException(status_code=404, detail="复用目标在公共星云不存在或已删除")
        sqlite_store.update_row(
            conn, kind, draft["id"], draft, owner_id=owner,
            extra={"published_to_id": reuse_id, "reviewStatus": "reviewed", "updatedAt": now},
        )
        db_sqlite.audit(
            conn, "llm_reuse", kind, draft["id"],
            f"复用公共记录发布「{_label(kind, draft)}」→ #{reuse_id}",
            before=draft,
            after={**draft, "published_to_id": reuse_id, "reviewStatus": "reviewed"},
            actor=actor,
        )
        return reuse_id

    public_row = _public_payload(conn, kind, draft, owner, admin_id)
    errors = validate_row(conn, kind, public_row, owner_id=admin_id)
    if errors:
        raise HTTPException(status_code=409, detail="校验失败:\n- " + "\n".join(errors))
    sqlite_store.insert_row(conn, kind, public_row, owner_id=admin_id, extra={"created_by": "llm"})
    if kind == "works":
        sqlite_store.set_work_authors(
            conn, public_row["id"], _author_id_list(public_row.get("author_id"))
        )
    db_sqlite.audit(
        conn, "create", kind, public_row["id"],
        f"AI 草稿发布「{_label(kind, public_row)}」",
        after=public_row,
        actor=actor,
    )
    sqlite_store.update_row(
        conn, kind, draft["id"], draft, owner_id=owner,
        extra={"published_to_id": public_row["id"], "reviewStatus": "reviewed", "updatedAt": now},
    )
    db_sqlite.audit(
        conn, "llm_publish", kind, draft["id"],
        f"草稿「{_label(kind, draft)}」发布到公共星云 → #{public_row['id']}",
        before=draft,
        after={**draft, "published_to_id": public_row["id"], "reviewStatus": "reviewed"},
        actor=actor,
    )
    return public_row["id"]


def _exact_reuse_id(
    kind: Kind,
    draft_row: dict,
    user_rows: dict,
    author_names: list[str] | None = None,
) -> str | None:
    """精确命中判重目标库(exact)时返回可复用的行 id,否则 None。

    批准时自动复用:只有 level == 'exact' 才复用(同名异书 exact_diff_author
    以及 contained/token 仍走新建,避免误复用)。
    """
    hint = (
        _hint_author(draft_row, user_rows)
        if kind == "authors"
        else _hint_work(draft_row, user_rows, author_names or [])
    )
    if hint and hint.get("level") == "exact":
        return hint["existing_id"]
    return None


@router.post("/drafts/{kind}/{item_id}/approve")
def approve_draft(
    kind: Kind,
    item_id: str,
    body: ApproveBody | None = None,
    user: dict = Depends(require_admin),  # noqa: B008
) -> dict:
    """批准草稿:复制进公共星云(默认),或复用现有公共记录(reuse_id)。"""
    admin_id = user["id"]
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        staging = _staging_row(conn, kind, item_id, user["id"])
        reuse_id = ((body.reuse_id if body else None) or "").strip() or None
        public_id = _publish_draft_entity(
            conn, kind, staging, user["id"], admin_id, reuse_id, user["email"]
        )
    after_write(admin_id)
    return {"ok": True, "mode": "reuse" if reuse_id else "copy", "public_id": public_id}


@router.post("/ripples/{edge_id}/approve")
def approve_ripple(
    edge_id: str,
    body: ApproveRippleBody | None = None,
    user: dict = Depends(require_admin),  # noqa: B008
) -> dict:
    """批准一条涟漪:按 源作者→源作品→目标作者→目标作品→涟漪 依赖顺序建库。

    已批准的依赖自动复用;body 可传各端复用目标(reuse_*_id,默认新建)。
    """
    admin_id = user["id"]
    owner = user["id"]
    body = body or ApproveRippleBody()
    user_rows = load_user_rows(admin_id)
    public_edges = user_rows["edges"]
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        edge = _staging_row(conn, "edges", edge_id, owner)
        src_work = sqlite_store.get_row(conn, "works", edge["source_work_id"], owner)
        tgt_work = sqlite_store.get_row(conn, "works", edge["target_work_id"], owner)
        if src_work is None or tgt_work is None:
            raise HTTPException(status_code=404, detail="涟漪端点作品草稿不存在")
        src_authors = _draft_work_authors(conn, src_work["id"], owner)
        tgt_authors = _draft_work_authors(conn, tgt_work["id"], owner)
        if not src_authors:
            raise HTTPException(status_code=409, detail="源书作品缺少作者草稿,无法发布")

        src_author_names = [
            a.get("Name_CN") or a.get("Name_EN") or a.get("originalName") or ""
            for a in src_authors
        ]
        tgt_author_names = [
            a.get("Name_CN") or a.get("Name_EN") or a.get("originalName") or ""
            for a in tgt_authors
        ]

        public_ids: dict[str, Any] = {}
        public_ids["source_authors"] = [
            _publish_draft_entity(
                conn, "authors", a, owner, admin_id,
                body.reuse_source_author_id
                if (len(src_authors) == 1 and body.reuse_source_author_id)
                else _exact_reuse_id("authors", a, user_rows),
                user["email"],
            )
            for a in src_authors
        ]
        public_ids["source_work"] = _publish_draft_entity(
            conn, "works", src_work, owner, admin_id,
            body.reuse_source_work_id
            or _exact_reuse_id("works", src_work, user_rows, src_author_names),
            user["email"],
        )
        public_ids["target_authors"] = [
            _publish_draft_entity(
                conn, "authors", a, owner, admin_id,
                body.reuse_target_author_id
                if (len(tgt_authors) == 1 and body.reuse_target_author_id)
                else _exact_reuse_id("authors", a, user_rows),
                user["email"],
            )
            for a in tgt_authors
        ]
        public_ids["target_work"] = _publish_draft_entity(
            conn, "works", tgt_work, owner, admin_id,
            body.reuse_target_work_id
            or _exact_reuse_id("works", tgt_work, user_rows, tgt_author_names),
            user["email"],
        )
        # 涟漪本身:两端作品(可能已复用)在公共星云已有同对边时,直接复用该边
        edge_reuse = None
        if public_ids["source_work"] and public_ids["target_work"]:
            dup = next(
                (
                    e for e in public_edges
                    if e["source_work_id"] == public_ids["source_work"]
                    and e["target_work_id"] == public_ids["target_work"]
                ),
                None,
            )
            edge_reuse = dup["id"] if dup else None
        public_ids["edge"] = _publish_draft_entity(
            conn, "edges", edge, owner, admin_id, body.reuse_edge_id or edge_reuse, user["email"]
        )
    after_write(admin_id)
    return {"ok": True, "public_ids": public_ids}


@router.post("/source/{work_id}/approve")
def approve_source(
    work_id: str,
    body: ApproveSourceBody | None = None,
    user: dict = Depends(require_admin),  # noqa: B008
) -> dict:
    """批准无涟漪批次的源书(作者+作品),--no-ripples 导入使用。"""
    admin_id = user["id"]
    owner = user["id"]
    body = body or ApproveSourceBody()
    user_rows = load_user_rows(admin_id)
    with db_sqlite._write_lock, db_sqlite._db() as conn:
        work = _staging_row(conn, "works", work_id, owner)
        authors = _draft_work_authors(conn, work["id"], owner)
        if not authors:
            raise HTTPException(status_code=409, detail="源书作品缺少作者草稿,无法发布")
        author_names = [
            a.get("Name_CN") or a.get("Name_EN") or a.get("originalName") or ""
            for a in authors
        ]
        author_ids = [
            _publish_draft_entity(
                conn, "authors", a, owner, admin_id,
                body.reuse_author_id
                if (len(authors) == 1 and body.reuse_author_id)
                else _exact_reuse_id("authors", a, user_rows),
                user["email"],
            )
            for a in authors
        ]
        work_public = _publish_draft_entity(
            conn, "works", work, owner, admin_id,
            body.reuse_work_id
            or _exact_reuse_id("works", work, user_rows, author_names),
            user["email"],
        )
    after_write(admin_id)
    return {
        "ok": True,
        "public_ids": {"source_authors": author_ids, "source_work": work_public},
    }


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


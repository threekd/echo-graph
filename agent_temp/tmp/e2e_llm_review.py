import shutil, sys, pathlib
from pathlib import Path
ROOT = pathlib.Path(".").resolve()
sys.path.insert(0, str(ROOT / "agent_temp" / "tools"))
sys.path.insert(0, str(ROOT))

# 1) 复制真实库到工作区临时副本,全程只动副本
tmp_db = ROOT / "agent_temp" / "tmp" / "e2e.db"
tmp_db.parent.mkdir(parents=True, exist_ok=True)
if tmp_db.exists(): tmp_db.unlink()
shutil.copy(ROOT / "data" / "echo-graph.db", tmp_db)

from app import db_sqlite
db_sqlite.DB_PATH = tmp_db.resolve()

from agent_temp.tools import llm_space
from review_publish import build_batch, stage_batch, _read_json
from app.llm_review import llm_drafts, approve_draft, reject_draft, reopen_draft, ApproveBody
import app.llm_review as _lr

# 测试只动临时库副本:禁用批准后的 CSV 导出,避免污染真实 data/export/*
_lr._after_write = lambda admin_id: None
from app.auth import admin_user_id
from fastapi import HTTPException

owner = llm_space.ensure_system_llm()
admin = admin_user_id()
assert admin, "副本库缺少 admin"
print("system_llm:", owner[:8], " admin:", admin[:8])

# 2) 构建批次并入库草稿
extract = _read_json(ROOT / "agent_temp" / "output" / "source_book_result.json")
report = _read_json(ROOT / "agent_temp" / "output" / "dedupe_report.json")
batch = build_batch(extract, report, db_path=str(tmp_db), owner_id=owner)
counts = stage_batch(batch, owner)
print("stage counts:", counts)
assert counts["failed"] == 0, "存在入库失败条目"

# 3) 草稿接口形状
d = llm_drafts()
print("drafts:", d["staging"]["counts"])
assert d["staging"]["counts"]["authors"] == 16, "作者草稿数量不符"

# 4) 依赖守卫:作品未批准作者前应 409
first_work = d["staging"]["works"][0]
try:
    approve_draft("works", first_work["id"], None, {"id": admin, "email": "admin@test"})
    print("FAIL: 依赖守卫未生效")
except HTTPException as e:
    print("依赖守卫 OK:", e.status_code, str(e.detail)[:30])

staging = d["staging"]

# 5) 驳回/重开(批准前测试;已发布草稿不可再驳回)
a0 = staging["authors"][0]
reject_draft("authors", a0["id"], {"id": admin, "email": "admin@test"})
d2 = llm_drafts()
row = next(x for x in d2["staging"]["authors"] if x["id"] == a0["id"])
print("rejected retained:", row["reviewStatus"])
assert row["reviewStatus"] == "rejected"
reopen_draft("authors", a0["id"], {"id": admin, "email": "admin@test"})
print("reopened ok")

# 6) 按 作者→作品→涟漪 顺序批准;圣经复用现有记录
hints_w = d["hints"]["works"]
for a in staging["authors"]:
    r = approve_draft("authors", a["id"], None, {"id": admin, "email": "admin@test"})
    assert r["mode"] == "copy"
print("authors approved:", len(staging["authors"]))
reused = 0
for w in staging["works"]:
    h = hints_w.get(w["id"])
    if h and h.get("level") == "exact" and h.get("existing_id"):
        r = approve_draft("works", w["id"], ApproveBody(reuse_id=h["existing_id"]), {"id": admin, "email": "admin@test"})
        assert r["mode"] == "reuse"
        reused += 1
    else:
        r = approve_draft("works", w["id"], None, {"id": admin, "email": "admin@test"})
        assert r["mode"] == "copy"
print("works approved, reused:", reused)
for e in staging["edges"]:
    r = approve_draft("edges", e["id"], None, {"id": admin, "email": "admin@test"})
    assert r["mode"] == "copy"
print("edges approved:", len(staging["edges"]))

# 7) 已发布草稿不可重复发布
w1 = staging["works"][0]
try:
    approve_draft("works", w1["id"], None, {"id": admin, "email": "admin@test"})
    print("FAIL: 重复发布未被拦截")
except HTTPException as e:
    print("重复发布守卫 OK:", e.status_code)

# 8) 校验:草稿行 published_to_id、公共星云计数、审计
import sqlite3
conn = sqlite3.connect(tmp_db)
conn.row_factory = sqlite3.Row
published = [dict(r) for r in conn.execute("SELECT id, published_to_id FROM works WHERE owner_id = ? AND published_to_id IS NOT NULL", (owner,))]
print("staging works published_to_id:", len(published))
pub_a = conn.execute("SELECT count(*) c FROM authors WHERE owner_id = ? AND deletedAt IS NULL", (admin,)).fetchone()["c"]
pub_w = conn.execute("SELECT count(*) c FROM works WHERE owner_id = ? AND deletedAt IS NULL", (admin,)).fetchone()["c"]
pub_e = conn.execute("SELECT count(*) c FROM edges WHERE owner_id = ? AND deletedAt IS NULL", (admin,)).fetchone()["c"]
print("public counts:", pub_a, pub_w, pub_e)
audit = conn.execute("SELECT action, count(*) c FROM audit_log WHERE actor = ? OR actor = ? GROUP BY action", ("admin@test", "system_llm")).fetchall()
print("audit:", [(r["action"], r["c"]) for r in audit])
conn.close()
print("E2E OK")

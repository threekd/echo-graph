"""数据导入核心:加载 CSV → 校验 → 写入 Neo4j → 快照。

数据管理 API 与 scripts/import_data.py 共用本模块。
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase
from pydantic import BaseModel

from app.data_models import AuthorRow, EchoRow, WorkRow, parse_rows
from app.sqlite_store import load_rows

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "snapshots"
CHUNK = 500
KEEP_SNAPSHOTS = 20


def _chunks(rows: list, size: int = CHUNK):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _node_props(row: BaseModel, now: str) -> dict:
    # author_id 仅用于 CSV 层关联,图谱中由 AUTHORED_BY 关系表达,不写为节点属性;
    # deletedAt 同理只在 CSV 层表达:软删除的行由 run_import 过滤并在导入时从图中
    # 物理移除(DETACH DELETE),从不作为属性写入 Neo4j(避免查询引用不存在的属性键)
    d = row.model_dump(exclude={"id", "slug", "deletedAt", "author_id"})
    d["createdAt"] = d.get("createdAt") or now
    if not d.get("updatedAt"):
        # 仅在数据自带更新时间时同步,避免每次导入把全库 updatedAt 刷成导入时间
        d.pop("updatedAt", None)
    return d


def _echo_props(row: EchoRow, now: str) -> dict:
    # 与 _node_props 一致:软删除标记不写入 Neo4j,图中只存活跃的 ECHO 关系
    d = row.model_dump(exclude={"source_work_id", "target_work_id", "deletedAt"})
    d["reviewStatus"] = d.get("reviewStatus") or "draft"
    d["createdAt"] = d.get("createdAt") or now
    if not d.get("updatedAt"):
        d.pop("updatedAt", None)
    return d


def import_data(
    driver: GraphDatabase,
    database: str | None,
    authors: list[AuthorRow],
    works: list[WorkRow],
    echoes: list[EchoRow],
    work_authors: dict[str, list[str]],
    *,
    wipe: bool,
    version: str,
    deleted_authors: list[dict] | None = None,
    deleted_works: list[dict] | None = None,
    deleted_echoes: list[dict] | None = None,
) -> None:
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    with driver.session(database=database) as session:
        session.run("CREATE CONSTRAINT author_id IF NOT EXISTS FOR (a:Author) REQUIRE a.id IS UNIQUE").consume()
        session.run("CREATE CONSTRAINT work_id IF NOT EXISTS FOR (w:Work) REQUIRE w.id IS UNIQUE").consume()
        session.run("DROP CONSTRAINT author_slug IF EXISTS").consume()  # slug 已弃用,URL 直接用 UUID
        session.run("DROP CONSTRAINT work_slug IF EXISTS").consume()
        session.run(
            "CREATE FULLTEXT INDEX work_search IF NOT EXISTS "
            "FOR (n:Work) ON EACH [n.Title_CN, n.Title_EN, n.originalTitle, n.Title_Other]"
        ).consume()

        with session.begin_transaction() as tx:
            if wipe:
                tx.run("MATCH (a:Author) DETACH DELETE a")
                tx.run("MATCH (w:Work) DETACH DELETE w")

            for chunk in _chunks(
                [{"id": a.id, "props": _node_props(a, now)} for a in authors]
            ):
                tx.run(
                    "UNWIND $rows AS row "
                    "MERGE (a:Author {id: row.id}) "
                    "ON CREATE SET a.updatedAt = $now "
                    "SET a += row.props "
                    "REMOVE a.slug",
                    {"rows": chunk, "now": now},
                )

            for chunk in _chunks(
                [{"id": w.id, "props": _node_props(w, now)} for w in works]
            ):
                tx.run(
                    "UNWIND $rows AS row "
                    "MERGE (w:Work {id: row.id}) "
                    "ON CREATE SET w.updatedAt = $now "
                    "SET w += row.props "
                    "REMOVE w.slug, w.Author",
                    {"rows": chunk, "now": now},
                )

            authored = [
                {"wid": wid, "aid": aid} for wid, aids in work_authors.items() for aid in aids
            ]
            for chunk in _chunks(authored):
                tx.run(
                    "UNWIND $rows AS row "
                    "MATCH (w:Work {id: row.wid}), (a:Author {id: row.aid}) "
                    "MERGE (w)-[:AUTHORED_BY]->(a)",
                    {"rows": chunk},
                )

            for chunk in _chunks(
                [
                    {
                        "source": e.source_work_id,
                        "target": e.target_work_id,
                        "props": _echo_props(e, now),
                    }
                    for e in echoes
                ]
            ):
                tx.run(
                    "UNWIND $rows AS row "
                    "MATCH (s:Work {id: row.source}), (t:Work {id: row.target}) "
                    "MERGE (s)-[r:ECHO]->(t) "
                    "ON CREATE SET r.updatedAt = $now "
                    "SET r += row.props",
                    {"rows": chunk, "now": now},
                )

            # 清理历史遗留的 evidenceLang 属性(schema 1.1 起不再使用)
            tx.run("MATCH ()-[r:ECHO]->() REMOVE r.evidenceLang")

            # 软删除同步:CSV 中 deletedAt 非空的行从图谱中物理移除(数据仍保留在
            # CSV 存档)。设计上 deletedAt 只在 CSV 层表达,图中只存活跃数据,
            # 因此不写入该属性,查询层也不按 deletedAt 过滤(见 app/db.py 说明)
            if deleted_echoes:
                deleted_rel_rows = [
                    {"source": r.get("source_work_id"), "target": r.get("target_work_id")}
                    for r in deleted_echoes
                    if r.get("source_work_id") and r.get("target_work_id")
                ]
                for chunk in _chunks(deleted_rel_rows):
                    tx.run(
                        "UNWIND $rows AS row "
                        "MATCH (s:Work {id: row.source})-[r:ECHO]->(t:Work {id: row.target}) "
                        "DELETE r",
                        {"rows": chunk},
                    )
            if deleted_works:
                for chunk in _chunks([{"id": r.get("id")} for r in deleted_works if r.get("id")]):
                    tx.run(
                        "UNWIND $rows AS row "
                        "MATCH (w:Work {id: row.id}) "
                        "DETACH DELETE w",
                        {"rows": chunk},
                    )
            if deleted_authors:
                for chunk in _chunks([{"id": r.get("id")} for r in deleted_authors if r.get("id")]):
                    tx.run(
                        "UNWIND $rows AS row "
                        "MATCH (a:Author {id: row.id}) "
                        "DETACH DELETE a",
                        {"rows": chunk},
                    )

            tx.run(
                "MERGE (m:Dataset {id: 'echo-graph'}) "
                "SET m.version = $version, m.importedAt = $now",
                {"version": version, "now": now},
            )


def write_snapshot(driver: GraphDatabase, database: str | None, version: str) -> None:
    def q(cypher: str) -> list[dict]:
        with driver.session(database=database) as session:
            return [dict(r) for r in session.run(cypher)]

    authors = q("MATCH (a:Author) RETURN properties(a) AS p ORDER BY a.id")
    works = q("MATCH (w:Work) RETURN properties(w) AS p ORDER BY w.id")
    edges = q(
        "MATCH (s:Work)-[r:ECHO]->(t:Work) "
        "RETURN s.id AS source, t.id AS target, properties(r) AS p ORDER BY s.id"
    )
    payload = {
        "meta": {
            "name": "echo-graph snapshot",
            "datasetVersion": version,
            "exportedAt": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        },
        "authors": [r["p"] for r in authors],
        "works": [r["p"] for r in works],
        "edges": [{"source": r["source"], "target": r["target"], **r["p"]} for r in edges],
    }
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    (SNAPSHOT_DIR / f"echo-graph-{ts}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SNAPSHOT_DIR / "echo-graph-latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _prune_snapshots()


def _prune_snapshots() -> None:
    """只保留最近 KEEP_SNAPSHOTS 份带时间戳的快照,latest 不受影响。"""
    files = sorted(SNAPSHOT_DIR.glob("echo-graph-[0-9]*.json"))
    for old in files[:-KEEP_SNAPSHOTS]:
        old.unlink(missing_ok=True)


def run_import(
    wipe: bool = False,
    version: str = "1.1",
    no_snapshot: bool = False,
) -> dict:
    """从 SQLite 读取策展数据 → 校验 → 写入 Neo4j → 快照。返回统计。"""
    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE") or None
    if not (uri and username and password):
        raise RuntimeError("NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD missing in .env")

    authors_all, works_all, echoes_all = load_rows()

    # 软删除的行保留在 CSV 存档,但不进入图谱
    authors = [a for a in authors_all if not a.get("deletedAt")]
    works = [w for w in works_all if not w.get("deletedAt")]
    echoes = [e for e in echoes_all if not e.get("deletedAt")]
    deleted_authors = [a for a in authors_all if a.get("deletedAt")]
    deleted_works = [w for w in works_all if w.get("deletedAt")]
    deleted_echoes = [e for e in echoes_all if e.get("deletedAt")]

    author_models, work_models, echo_models, work_authors = parse_rows(authors, works, echoes)
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        import_data(
            driver, database, author_models, work_models, echo_models, work_authors,
            wipe=wipe, version=version,
            deleted_authors=deleted_authors,
            deleted_works=deleted_works,
            deleted_echoes=deleted_echoes,
        )
        if not no_snapshot:
            write_snapshot(driver, database, version)
    finally:
        driver.close()

    return {
        "authors": len(author_models),
        "works": len(work_models),
        "echoes": len(echo_models),
        "authored_links": sum(len(v) for v in work_authors.values()),
        "version": version,
        "wipe": wipe,
    }

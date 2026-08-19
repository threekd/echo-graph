"""数据导入核心:加载 CSV → 校验 → 写入 Neo4j → 快照。

数据管理 API 与 scripts/import_data.py 共用本模块。
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase
from pydantic import BaseModel

from app.data_models import EchoRow, WorkRow, AuthorRow, parse_rows
from app.data_store import load_rows, REAL_DIR

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "snapshots"
CHUNK = 500


def _chunks(rows: list, size: int = CHUNK):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _node_props(row: BaseModel, now: str) -> dict:
    d = row.model_dump(exclude={"id", "slug", "deletedAt"})
    d["createdAt"] = d.get("createdAt") or now
    d["updatedAt"] = now
    return d


def _echo_props(row: EchoRow, now: str) -> dict:
    d = row.model_dump(exclude={"source_work_id", "target_work_id", "deletedAt"})
    d["reviewStatus"] = d.get("reviewStatus") or "draft"
    d["createdAt"] = d.get("createdAt") or now
    d["updatedAt"] = now
    return d


def import_data(
    driver: GraphDatabase,
    database: Optional[str],
    authors: list[AuthorRow],
    works: list[WorkRow],
    echoes: list[EchoRow],
    work_authors: dict[str, list[str]],
    *,
    wipe: bool,
    version: str,
    deleted_authors: Optional[list[dict]] = None,
    deleted_works: Optional[list[dict]] = None,
    deleted_echoes: Optional[list[dict]] = None,
) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
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
                    "SET a += row.props, a.slug = null",
                    {"rows": chunk},
                )

            for chunk in _chunks(
                [{"id": w.id, "props": _node_props(w, now)} for w in works]
            ):
                tx.run(
                    "UNWIND $rows AS row "
                    "MERGE (w:Work {id: row.id}) "
                    "SET w += row.props, w.slug = null",
                    {"rows": chunk},
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
                    "SET r += row.props",
                    {"rows": chunk},
                )

            # 清理历史遗留的 evidenceLang 属性(schema 1.1 起不再使用)
            tx.run("MATCH ()-[r:ECHO]->() REMOVE r.evidenceLang")

            # 软删除同步:CSV 中 deletedAt 非空的行从图谱中移除(数据仍保留在 CSV 存档)
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


def write_snapshot(driver: GraphDatabase, database: Optional[str], version: str) -> None:
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
            "exportedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
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


def run_import(
    source: str,
    *,
    wipe: bool = False,
    version: str = "1.0",
    no_snapshot: bool = False,
) -> dict:
    """加载 CSV → 校验 → 写入 Neo4j → 快照。返回统计。"""
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

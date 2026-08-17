"""Import data/seed.json into the Neo4j database configured in .env."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = ROOT / "data" / "seed.json"


def main() -> None:
    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE") or None
    if not (uri and username and password):
        raise SystemExit("NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD missing in .env")

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        print("connected to Neo4j")
        with driver.session(database=database) as session:
            # 约束属于 schema 操作,必须在显式事务外执行
            session.run("CREATE CONSTRAINT author_id IF NOT EXISTS FOR (a:Author) REQUIRE a.id IS UNIQUE").consume()
            session.run("CREATE CONSTRAINT work_id IF NOT EXISTS FOR (w:Work) REQUIRE w.id IS UNIQUE").consume()

            # 数据写入放入单个显式事务,保证整体提交
            with session.begin_transaction() as tx:
                # 全新导入演示数据:清空本项目 Author/Work(不含用户既有 Entity 节点)
                tx.run("MATCH (a:Author) DETACH DELETE a")
                tx.run("MATCH (w:Work) DETACH DELETE w")
                # 兼容性清理旧版演示关系(此时节点已删,顺带兜底)
                tx.run("MATCH (:Work)-[r:INFLUENCES]->(:Work) DELETE r")
                tx.run("MATCH (:Work)-[r:MENTIONS]->(:Work) DELETE r")
                tx.run("MATCH ()-[r:WROTE]->() DELETE r")
                for a in seed["authors"]:
                    tx.run(
                        """
                        MERGE (a:Author {id: $id})
                        SET a += $props
                        """,
                        {"id": a["id"], "props": {k: v for k, v in a.items() if k != "id"}},
                    )
                for w in seed["works"]:
                    tx.run(
                        """
                        MERGE (w:Work {id: $id})
                        SET w += $props
                        """,
                        {"id": w["id"], "props": {k: v for k, v in w.items() if k not in ("id", "author_id")}},
                    )
                # 结构关系:(Work)-[:AUTHORED_BY]->(Author)
                for w in seed["works"]:
                    tx.run(
                        """
                        MATCH (w:Work {id: $wid}), (a:Author {id: $aid})
                        MERGE (w)-[:AUTHORED_BY]->(a)
                        """,
                        {"wid": w["id"], "aid": w["author_id"]},
                    )
                # 回声关系:(Work)-[:ECHO]->(Work),A 提及 B
                for e in seed["edges"]:
                    tx.run(
                        """
                        MATCH (s:Work {id: $source}), (t:Work {id: $target})
                        MERGE (s)-[r:ECHO]->(t)
                        SET r.evidence = $evidence, r.note = $note
                        """,
                        e,
                    )

            def count_one(cypher: str) -> int:
                result = session.run(cypher)
                row = result.single()
                result.consume()
                return int(row["c"]) if row else -1

            authors = count_one("MATCH (a:Author) RETURN count(a) AS c")
            works = count_one("MATCH (w:Work) RETURN count(w) AS c")
            echoes = count_one("MATCH (:Work)-[r:ECHO]->(:Work) RETURN count(r) AS c")
            authored = count_one("MATCH (:Work)-[:AUTHORED_BY]->(:Author) RETURN count(*) AS c")
            print(
                "import complete: "
                f"authors={authors}, works={works}, echo_edges={echoes}, authored_by={authored}"
            )
    finally:
        driver.close()


if __name__ == "__main__":
    main()

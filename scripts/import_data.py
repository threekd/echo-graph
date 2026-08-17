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
            session.run("CREATE CONSTRAINT author_id IF NOT EXISTS FOR (a:Author) REQUIRE a.id IS UNIQUE")
            session.run("CREATE CONSTRAINT work_id IF NOT EXISTS FOR (w:Work) REQUIRE w.id IS UNIQUE")
            for a in seed["authors"]:
                session.run(
                    """
                    MERGE (a:Author {id: $id})
                    SET a.name = $name, a.name_en = $name_en, a.birth = $birth,
                        a.death = $death, a.nationality = $nationality,
                        a.language = $language, a.era = $era
                    """,
                    a,
                )
            for w in seed["works"]:
                session.run(
                    """
                    MERGE (w:Work {id: $id})
                    SET w.title = $title, w.title_en = $title_en, w.year = $year,
                        w.language = $language, w.genre = $genre, w.author_id = $author_id
                    WITH w
                    MATCH (a:Author {id: $author_id})
                    MERGE (a)-[:WROTE]->(w)
                    """,
                    w,
                )
            for e in seed["edges"]:
                session.run(
                    """
                    MATCH (s:Work {id: $source}), (t:Work {id: $target})
                    MERGE (s)-[r:INFLUENCES]->(t)
                    SET r.kind = $kind, r.confidence = $confidence, r.quote = $quote
                    """,
                    e,
                )
            counts = session.run(
                """
                MATCH (a:Author) WITH count(a) AS authors
                MATCH (w:Work) WITH authors, count(w) AS works
                MATCH ()-[r:INFLUENCES]->() WITH authors, works, count(r) AS edges
                RETURN authors, works, edges
                """
            ).single()
            print(
                "import complete: "
                f"authors={counts['authors']}, works={counts['works']}, influence_edges={counts['edges']}"
            )
    finally:
        driver.close()


if __name__ == "__main__":
    main()

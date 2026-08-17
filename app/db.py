"""Data access layer for Echo Graph.

Primary store is Neo4j (per README architecture). If Neo4j is unreachable,
the app transparently falls back to the bundled demo JSON dataset so the demo
always works. Set ECHO_STORE=json to force the JSON store.
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("echo_graph.db")

ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = ROOT / "data" / "seed.json"


def _load_seed() -> dict:
    if not SEED_PATH.exists():
        raise FileNotFoundError(
            f"seed data not found at {SEED_PATH}; run scripts/generate_seed_data.py first"
        )
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


class JsonStore:
    """In-memory fallback store backed by data/seed.json."""

    name = "json"

    def __init__(self) -> None:
        self.seed = _load_seed()
        self.authors: dict[str, dict] = {a["id"]: a for a in self.seed["authors"]}
        self.works: dict[str, dict] = {w["id"]: w for w in self.seed["works"]}
        self.edges: list[dict] = self.seed["edges"]
        self.out: dict[str, list[dict]] = {}
        self.inc: dict[str, list[dict]] = {}
        for e in self.edges:
            self.out.setdefault(e["source"], []).append(e)
            self.inc.setdefault(e["target"], []).append(e)

    def graph(self) -> dict:
        nodes = []
        for a in self.authors.values():
            nodes.append(
                {
                    "id": a["id"],
                    "slug": a["slug"],
                    "type": "author",
                    "label": a["Name_CN"],
                    "label_en": a["Name_EN"],
                    "originalName": a["originalName"],
                    "nationality": a["nationality"],
                    "primaryLanguage": a["primaryLanguage"],
                    "birthYear": a["birthYear"],
                    "deathYear": a["deathYear"],
                    "bio": a["bio"],
                }
            )
        for w in self.works.values():
            author = self.authors[w["author_id"]]
            nodes.append(
                {
                    "id": w["id"],
                    "slug": w["slug"],
                    "type": "work",
                    "label": w["Title_CN"],
                    "label_en": w["Title_EN"],
                    "originalTitle": w["originalTitle"],
                    "year": w["publicationYear"] or w["creationYear"],
                    "publicationYear": w["publicationYear"],
                    "creationYear": w["creationYear"],
                    "language": w["language"],
                    "genre": w["genre"],
                    "summary": w["summary"],
                    "author_id": w["author_id"],
                    "author": author["Name_CN"],
                }
            )
        edges = []
        for e in self.edges:
            edges.append(
                {
                    "source": e["source"],
                    "target": e["target"],
                    "type": "echo",
                    "evidence": e["evidence"],
                    "evidenceSource": e["evidenceSource"],
                    "evidenceLang": e["evidenceLang"],
                    "note": e["note"],
                    "confidence": e["confidence"],
                    "reviewStatus": e["reviewStatus"],
                    "dataSource": e["dataSource"],
                }
            )
        for w in self.works.values():
            edges.append({"source": w["id"], "target": w["author_id"], "type": "authored"})
        return {"nodes": nodes, "edges": edges}

    def search(self, q: str, limit: int = 20) -> list[dict]:
        ql = q.lower()
        hits = []
        for a in self.authors.values():
            if ql in a["Name_CN"].lower() or ql in a["Name_EN"].lower() or ql in a["originalName"].lower():
                hits.append(
                    {
                        "id": a["id"],
                        "type": "author",
                        "label": a["Name_CN"],
                        "sub": f"{a['originalName']} · {a['nationality']}",
                    }
                )
        for w in self.works.values():
            if ql in w["Title_CN"].lower() or ql in w["Title_EN"].lower() or ql in w["originalTitle"].lower():
                year = w["publicationYear"] or w["creationYear"]
                hits.append(
                    {
                        "id": w["id"],
                        "type": "work",
                        "label": w["Title_CN"],
                        "sub": f"{self.authors[w['author_id']]['Name_CN']} · {year}",
                    }
                )
        return hits[:limit]

    def path(self, from_id: str, to_id: str, max_hops: int) -> Optional[dict]:
        if from_id not in self.works or to_id not in self.works:
            return None
        if from_id == to_id:
            return {"nodes": [self.works[from_id]["id"]], "edges": []}
        # BFS over directed influence edges
        prev: dict[str, dict] = {from_id: {"node": from_id, "edge": None}}
        queue = deque([from_id])
        found = False
        while queue and not found:
            cur = queue.popleft()
            if prev[cur]["node"] and len(self._backtrack(prev, cur)) > max_hops:
                continue
            for e in self.out.get(cur, []):
                nxt = e["target"]
                if nxt not in prev:
                    prev[nxt] = {"node": nxt, "edge": e, "prev": cur}
                    if nxt == to_id:
                        found = True
                        break
                    queue.append(nxt)
        if not found:
            return None
        return self._backtrack(prev, to_id)

    def _backtrack(self, prev: dict, node: str) -> dict:
        nodes = []
        edges = []
        cur = node
        while prev[cur].get("edge") is not None:
            e = prev[cur]["edge"]
            edges.append(
                {
                    "source": e["source"],
                    "target": e["target"],
                    "evidence": e["evidence"],
                    "evidenceSource": e["evidenceSource"],
                    "evidenceLang": e["evidenceLang"],
                    "note": e["note"],
                    "confidence": e["confidence"],
                    "reviewStatus": e["reviewStatus"],
                    "dataSource": e["dataSource"],
                }
            )
            nodes.append(cur)
            cur = prev[cur]["prev"]
        nodes.append(cur)
        nodes.reverse()
        edges.reverse()
        return {"nodes": nodes, "edges": edges}

    def work_detail(self, work_id: str) -> Optional[dict]:
        w = self.works.get(work_id)
        if not w:
            return None
        author = self.authors[w["author_id"]]
        return {
            "work": {
                "id": w["id"],
                "slug": w["slug"],
                "title": w["Title_CN"],
                "title_en": w["Title_EN"],
                "originalTitle": w["originalTitle"],
                "year": w["publicationYear"] or w["creationYear"],
                "publicationYear": w["publicationYear"],
                "creationYear": w["creationYear"],
                "language": w["language"],
                "genre": w["genre"],
                "summary": w["summary"],
            },
            "author": {
                "id": author["id"],
                "slug": author["slug"],
                "name": author["Name_CN"],
                "name_en": author["Name_EN"],
                "originalName": author["originalName"],
                "birthYear": author["birthYear"],
                "deathYear": author["deathYear"],
                "nationality": author["nationality"],
                "primaryLanguage": author["primaryLanguage"],
                "bio": author["bio"],
            },
            "mentioned_by": [
                {
                    "source": e["source"],
                    "source_title": self.works[e["source"]]["Title_CN"],
                    "source_author": self.authors[self.works[e["source"]]["author_id"]]["Name_CN"],
                    "evidence": e["evidence"],
                    "evidenceSource": e["evidenceSource"],
                    "evidenceLang": e["evidenceLang"],
                    "note": e["note"],
                    "confidence": e["confidence"],
                    "reviewStatus": e["reviewStatus"],
                    "dataSource": e["dataSource"],
                }
                for e in self.inc.get(work_id, [])
            ],
            "mentions": [
                {
                    "target": e["target"],
                    "target_title": self.works[e["target"]]["Title_CN"],
                    "target_author": self.authors[self.works[e["target"]]["author_id"]]["Name_CN"],
                    "evidence": e["evidence"],
                    "evidenceSource": e["evidenceSource"],
                    "evidenceLang": e["evidenceLang"],
                    "note": e["note"],
                    "confidence": e["confidence"],
                    "reviewStatus": e["reviewStatus"],
                    "dataSource": e["dataSource"],
                }
                for e in self.out.get(work_id, [])
            ],
        }

    def expansion(self, work_id: str, hops: int) -> Optional[dict]:
        """以 work_id 为中心,沿 ECHO 关系(无向)向外扩散 hops 级,返回子图。"""
        if work_id not in self.works:
            return None
        visited = {work_id}
        frontier = [work_id]
        for _ in range(max(1, int(hops))):
            nxt = []
            for wid in frontier:
                for e in self.out.get(wid, []) + self.inc.get(wid, []):
                    other = e["target"] if e["source"] == wid else e["source"]
                    if other not in visited:
                        visited.add(other)
                        nxt.append(other)
            frontier = nxt
            if not frontier:
                break
        nodes = []
        for wid in visited:
            w = self.works[wid]
            author = self.authors[w["author_id"]]
            nodes.append(
                {
                    "id": w["id"],
                    "slug": w["slug"],
                    "type": "work",
                    "label": w["Title_CN"],
                    "label_en": w["Title_EN"],
                    "originalTitle": w["originalTitle"],
                    "year": w["publicationYear"] or w["creationYear"],
                    "publicationYear": w["publicationYear"],
                    "creationYear": w["creationYear"],
                    "language": w["language"],
                    "genre": w["genre"],
                    "summary": w["summary"],
                    "author_id": w["author_id"],
                    "author": author["Name_CN"],
                }
            )
        edges = [
            {
                "source": e["source"],
                "target": e["target"],
                "type": "echo",
                "evidence": e["evidence"],
                "evidenceSource": e["evidenceSource"],
                "evidenceLang": e["evidenceLang"],
                "note": e["note"],
                "confidence": e["confidence"],
                "reviewStatus": e["reviewStatus"],
                "dataSource": e["dataSource"],
            }
            for e in self.edges
            if e["source"] in visited and e["target"] in visited
        ]
        return {"nodes": nodes, "edges": edges, "centerId": work_id}

    def stats(self) -> dict:
        return {
            "authors": len(self.authors),
            "works": len(self.works),
            "echo_edges": len(self.edges),
            "store": self.name,
            "demo": bool(self.seed.get("meta", {}).get("demo", False)),
        }


class Neo4jStore:
    """Neo4j-backed store using the Aura connection from .env."""

    name = "neo4j"

    def __init__(self, uri: str, username: str, password: str, database: Optional[str] = None) -> None:
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(uri, auth=(username, password))
        self._database = database
        try:
            self._driver.verify_connectivity()
        except Exception:
            self._driver.close()
            raise

    def close(self) -> None:
        self._driver.close()

    def _query(self, cypher: str, params: Optional[dict] = None) -> list[dict]:
        with self._driver.session(database=self._database) as session:
            result = session.run(cypher, params or {})
            return [dict(r) for r in result]

    def _node(self, props: dict, label: str) -> dict:
        return {
            "id": props.get("id"),
            "slug": props.get("slug"),
            "type": "work",
            "label": props.get("Title_CN"),
            "label_en": props.get("Title_EN"),
            "originalTitle": props.get("originalTitle"),
            "year": props.get("publicationYear") or props.get("creationYear"),
            "publicationYear": props.get("publicationYear"),
            "creationYear": props.get("creationYear"),
            "language": props.get("language"),
            "genre": props.get("genre"),
            "summary": props.get("summary"),
            "author_id": props.get("author_id"),
            "author": props.get("author_name", ""),
        }

    def graph(self) -> dict:
        author_rows = self._query(
            """
            MATCH (a:Author)
            RETURN properties(a) AS props
            """
        )
        nodes = []
        for row in author_rows:
            p = row["props"]
            nodes.append(
                {
                    "id": p.get("id"),
                    "slug": p.get("slug"),
                    "type": "author",
                    "label": p.get("Name_CN"),
                    "label_en": p.get("Name_EN"),
                    "originalName": p.get("originalName"),
                    "nationality": p.get("nationality"),
                    "primaryLanguage": p.get("primaryLanguage"),
                    "birthYear": p.get("birthYear"),
                    "deathYear": p.get("deathYear"),
                    "bio": p.get("bio"),
                }
            )

        node_rows = self._query(
            """
            MATCH (w:Work)
            OPTIONAL MATCH (w)-[:AUTHORED_BY]->(a:Author)
            RETURN properties(w) AS props, a.Name_CN AS author_name, a.id AS author_id
            """
        )
        for row in node_rows:
            row["props"] = dict(row["props"])
            row["props"]["author_name"] = row["author_name"] or ""
            row["props"]["author_id"] = row["author_id"]
        nodes.extend(self._node(row["props"], "work") for row in node_rows)

        echo_rows = self._query(
            """
            MATCH (w1:Work)-[r:ECHO]->(w2:Work)
            RETURN w1.id AS source, w2.id AS target,
                   r.evidence AS evidence, r.evidenceSource AS evidenceSource,
                   r.evidenceLang AS evidenceLang, r.note AS note,
                   r.confidence AS confidence, r.reviewStatus AS reviewStatus,
                   r.dataSource AS dataSource
            """
        )
        edges = [
            {"source": r["source"], "target": r["target"], "type": "echo",
             "evidence": r["evidence"], "evidenceSource": r["evidenceSource"],
             "evidenceLang": r["evidenceLang"], "note": r["note"],
             "confidence": r["confidence"], "reviewStatus": r["reviewStatus"],
             "dataSource": r["dataSource"]}
            for r in echo_rows
        ]
        authored_rows = self._query(
            """
            MATCH (w:Work)-[:AUTHORED_BY]->(a:Author)
            RETURN w.id AS source, a.id AS target
            """
        )
        edges += [
            {"source": r["source"], "target": r["target"], "type": "authored"}
            for r in authored_rows
        ]
        return {"nodes": nodes, "edges": edges}

    def search(self, q: str, limit: int = 20) -> list[dict]:
        rows = self._query(
            """
            MATCH (n)
            WHERE (n:Work AND (n.Title_CN CONTAINS $q OR toLower(n.Title_EN) CONTAINS toLower($q) OR toLower(n.originalTitle) CONTAINS toLower($q)))
               OR (n:Author AND (n.Name_CN CONTAINS $q OR toLower(n.Name_EN) CONTAINS toLower($q) OR toLower(n.originalName) CONTAINS toLower($q)))
            RETURN n.id AS id, labels(n)[0] AS label, n LIMIT $limit
            """,
            {"q": q, "limit": limit},
        )
        hits = []
        for r in rows:
            props = dict(r["n"])
            if r["label"] == "Author":
                hits.append(
                    {
                        "id": props["id"],
                        "type": "author",
                        "label": props["Name_CN"],
                        "sub": f"{props['originalName']} · {props['nationality']}",
                    }
                )
            else:
                year = props.get("publicationYear") or props.get("creationYear")
                hits.append(
                    {
                        "id": props["id"],
                        "type": "work",
                        "label": props["Title_CN"],
                        "sub": f"{props['Title_EN']} · {year}",
                    }
                )
        return hits[:limit]

    def path(self, from_id: str, to_id: str, max_hops: int) -> Optional[dict]:
        hop = max(1, int(max_hops))
        cypher = (
            "MATCH p = shortestPath((a:Work {id:$from})-[r:ECHO*1.."
            f"{hop}"
            "]->(b:Work {id:$to})) "
            "RETURN [x IN nodes(p) | x.id] AS node_ids, "
            "[rel IN relationships(p) | {source: startNode(rel).id, target: endNode(rel).id, "
            "evidence: rel.evidence, evidenceSource: rel.evidenceSource, "
            "evidenceLang: rel.evidenceLang, note: rel.note, confidence: rel.confidence, "
            "reviewStatus: rel.reviewStatus, dataSource: rel.dataSource}] AS rels LIMIT 1"
        )
        rows = self._query(cypher, {"from": from_id, "to": to_id})
        if not rows:
            return None
        row = rows[0]
        return {"nodes": row["node_ids"], "edges": row["rels"]}

    def work_detail(self, work_id: str) -> Optional[dict]:
        rows = self._query(
            """
            MATCH (w:Work {id:$id})-[:AUTHORED_BY]->(a:Author)
            RETURN properties(w) AS w, properties(a) AS a LIMIT 1
            """,
            {"id": work_id},
        )
        if not rows:
            return None
        wp, ap = rows[0]["w"], rows[0]["a"]
        inc = self._query(
            """
            MATCH (i:Work)-[r:ECHO]->(w:Work {id:$id})
            MATCH (i)-[:AUTHORED_BY]->(ia:Author)
            RETURN i.id AS source, i.Title_CN AS source_title, ia.Name_CN AS source_author,
                   r.evidence AS evidence, r.evidenceSource AS evidenceSource,
                   r.evidenceLang AS evidenceLang, r.note AS note,
                   r.confidence AS confidence, r.reviewStatus AS reviewStatus,
                   r.dataSource AS dataSource
            """,
            {"id": work_id},
        )
        out = self._query(
            """
            MATCH (w:Work {id:$id})-[r:ECHO]->(o:Work)
            MATCH (o)-[:AUTHORED_BY]->(oa:Author)
            RETURN o.id AS target, o.Title_CN AS target_title, oa.Name_CN AS target_author,
                   r.evidence AS evidence, r.evidenceSource AS evidenceSource,
                   r.evidenceLang AS evidenceLang, r.note AS note,
                   r.confidence AS confidence, r.reviewStatus AS reviewStatus,
                   r.dataSource AS dataSource
            """,
            {"id": work_id},
        )
        return {
            "work": {
                "id": wp.get("id"),
                "slug": wp.get("slug"),
                "title": wp.get("Title_CN"),
                "title_en": wp.get("Title_EN"),
                "originalTitle": wp.get("originalTitle"),
                "year": wp.get("publicationYear") or wp.get("creationYear"),
                "publicationYear": wp.get("publicationYear"),
                "creationYear": wp.get("creationYear"),
                "language": wp.get("language"),
                "genre": wp.get("genre"),
                "summary": wp.get("summary"),
            },
            "author": {
                "id": ap.get("id"),
                "slug": ap.get("slug"),
                "name": ap.get("Name_CN"),
                "name_en": ap.get("Name_EN"),
                "originalName": ap.get("originalName"),
                "birthYear": ap.get("birthYear"),
                "deathYear": ap.get("deathYear"),
                "nationality": ap.get("nationality"),
                "primaryLanguage": ap.get("primaryLanguage"),
                "bio": ap.get("bio"),
            },
            "mentioned_by": [dict(r) for r in inc],
            "mentions": [dict(r) for r in out],
        }

    def expansion(self, work_id: str, hops: int) -> Optional[dict]:
        hop = max(1, min(int(hops), 8))
        node_rows = self._query(
            "MATCH (c:Work {id:$id}) "
            f"MATCH (n:Work) WHERE n.id = c.id OR (c)-[:ECHO*1..{hop}]-(n) "
            "OPTIONAL MATCH (n)-[:AUTHORED_BY]->(a:Author) "
            "RETURN properties(n) AS props, a.Name_CN AS author_name, a.id AS author_id",
            {"id": work_id},
        )
        if not node_rows:
            return None
        nodes = []
        ids = []
        for row in node_rows:
            props = dict(row["props"])
            props["author_name"] = row["author_name"] or ""
            props["author_id"] = row["author_id"]
            nodes.append(self._node(props, "work"))
            ids.append(props["id"])
        edge_rows = self._query(
            f"MATCH (c:Work {{id:$id}}) "
            f"MATCH (n:Work) WHERE n.id = c.id OR (c)-[:ECHO*1..{hop}]-(n) "
            "WITH collect(n.id) AS ids "
            "MATCH (a:Work)-[r:ECHO]->(b:Work) "
            "WHERE a.id IN ids AND b.id IN ids "
            "RETURN a.id AS source, b.id AS target, r.evidence AS evidence, "
            "r.evidenceSource AS evidenceSource, r.evidenceLang AS evidenceLang, "
            "r.note AS note, r.confidence AS confidence, r.reviewStatus AS reviewStatus, "
            "r.dataSource AS dataSource",
            {"id": work_id},
        )
        edges = [
            {
                "source": r["source"],
                "target": r["target"],
                "type": "echo",
                "evidence": r["evidence"],
                "evidenceSource": r["evidenceSource"],
                "evidenceLang": r["evidenceLang"],
                "note": r["note"],
                "confidence": r["confidence"],
                "reviewStatus": r["reviewStatus"],
                "dataSource": r["dataSource"],
            }
            for r in edge_rows
        ]
        return {"nodes": nodes, "edges": edges, "centerId": work_id}

    def stats(self) -> dict:
        author_count = self._query("MATCH (a:Author) RETURN count(a) AS c")[0]["c"]
        work_count = self._query("MATCH (w:Work) RETURN count(w) AS c")[0]["c"]
        edge_count = self._query("MATCH (:Work)-[r:ECHO]->(:Work) RETURN count(r) AS c")[0]["c"]
        return {
            "authors": author_count,
            "works": work_count,
            "echo_edges": edge_count,
            "store": self.name,
            "demo": False,
        }


class ResilientStore:
    """Try Neo4j first; if a query fails (e.g. idle connection dropped by Aura),
    fall back to the JSON demo store for that request so the demo never breaks."""

    def __init__(self, primary: Any, fallback: JsonStore) -> None:
        self.primary = primary
        self.fallback = fallback
        self._warned = False

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return getattr(self.primary, name)(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - demo resilience
            if not self._warned:
                logger.warning("Neo4j query '%s' failed (%s); falling back to JSON for this request", name, exc)
                self._warned = True
            return getattr(self.fallback, name)(*args, **kwargs)

    def graph(self) -> dict:
        return self._call("graph")

    def search(self, q: str, limit: int = 20) -> list[dict]:
        return self._call("search", q, limit)

    def path(self, from_id: str, to_id: str, max_hops: int) -> Optional[dict]:
        return self._call("path", from_id, to_id, max_hops)

    def work_detail(self, work_id: str) -> Optional[dict]:
        return self._call("work_detail", work_id)

    def expansion(self, work_id: str, hops: int) -> Optional[dict]:
        return self._call("expansion", work_id, hops)

    def stats(self) -> dict:
        return self._call("stats")


_store: Any = None


def get_store() -> Any:
    global _store
    if _store is not None:
        return _store
    if os.getenv("ECHO_STORE", "").lower() == "json":
        _store = JsonStore()
        logger.warning("ECHO_STORE=json: using bundled demo data instead of Neo4j")
        return _store
    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE") or None
    if uri and username and password:
        try:
            _store = ResilientStore(
                Neo4jStore(uri, username, password, database),
                JsonStore(),
            )
            logger.info("connected to Neo4j at %s", uri)
            return _store
        except Exception as exc:  # noqa: BLE001 - fall back for demo
            logger.warning("Neo4j unavailable (%s); falling back to JSON demo store", exc)
    _store = JsonStore()
    return _store

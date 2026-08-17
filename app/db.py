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
                    "type": "author",
                    "label": a["name"],
                    "label_en": a["name_en"],
                    "era": a["era"],
                    "nationality": a["nationality"],
                    "language": a["language"],
                    "birth": a["birth"],
                    "death": a["death"],
                }
            )
        for w in self.works.values():
            author = self.authors[w["author_id"]]
            nodes.append(
                {
                    "id": w["id"],
                    "type": "work",
                    "label": w["title"],
                    "label_en": w["title_en"],
                    "year": w["year"],
                    "language": w["language"],
                    "genre": w["genre"],
                    "author_id": w["author_id"],
                    "author": author["name"],
                }
            )
        edges = []
        for e in self.edges:
            edges.append(
                {
                    "source": e["source"],
                    "target": e["target"],
                    "type": "influence",
                    "kind": e["kind"],
                    "confidence": e["confidence"],
                    "quote": e["quote"],
                }
            )
        for w in self.works.values():
            edges.append({"source": w["author_id"], "target": w["id"], "type": "wrote"})
        return {"nodes": nodes, "edges": edges}

    def search(self, q: str, limit: int = 20) -> list[dict]:
        ql = q.lower()
        hits = []
        for a in self.authors.values():
            if ql in a["name"].lower() or ql in a["name_en"].lower():
                hits.append(
                    {
                        "id": a["id"],
                        "type": "author",
                        "label": a["name"],
                        "sub": f"{a['name_en']} · {a['era']}",
                    }
                )
        for w in self.works.values():
            if ql in w["title"].lower() or ql in w["title_en"].lower():
                hits.append(
                    {
                        "id": w["id"],
                        "type": "work",
                        "label": w["title"],
                        "sub": f"{self.authors[w['author_id']]['name']} · {w['year']}",
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
                    "kind": e["kind"],
                    "confidence": e["confidence"],
                    "quote": e["quote"],
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
                "title": w["title"],
                "title_en": w["title_en"],
                "year": w["year"],
                "language": w["language"],
                "genre": w["genre"],
            },
            "author": {
                "id": author["id"],
                "name": author["name"],
                "name_en": author["name_en"],
                "birth": author["birth"],
                "death": author["death"],
                "nationality": author["nationality"],
                "era": author["era"],
            },
            "influenced_by": [
                {
                    "source": e["source"],
                    "source_title": self.works[e["source"]]["title"],
                    "source_author": self.authors[self.works[e["source"]]["author_id"]]["name"],
                    "kind": e["kind"],
                    "confidence": e["confidence"],
                    "quote": e["quote"],
                }
                for e in self.inc.get(work_id, [])
            ],
            "influences": [
                {
                    "target": e["target"],
                    "target_title": self.works[e["target"]]["title"],
                    "target_author": self.authors[self.works[e["target"]]["author_id"]]["name"],
                    "kind": e["kind"],
                    "confidence": e["confidence"],
                    "quote": e["quote"],
                }
                for e in self.out.get(work_id, [])
            ],
        }

    def stats(self) -> dict:
        return {
            "authors": len(self.authors),
            "works": len(self.works),
            "influence_edges": len(self.edges),
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
        if label == "author":
            return {
                "id": props.get("id"),
                "type": "author",
                "label": props.get("name"),
                "label_en": props.get("name_en"),
                "era": props.get("era"),
                "nationality": props.get("nationality"),
                "language": props.get("language"),
                "birth": props.get("birth"),
                "death": props.get("death"),
            }
        return {
            "id": props.get("id"),
            "type": "work",
            "label": props.get("title"),
            "label_en": props.get("title_en"),
            "year": props.get("year"),
            "language": props.get("language"),
            "genre": props.get("genre"),
            "author_id": props.get("author_id"),
            "author": props.get("author_name", ""),
        }

    def graph(self) -> dict:
        node_rows = self._query(
            """
            MATCH (n)
            WHERE n:Author OR n:Work
            RETURN n.id AS id, labels(n)[0] AS label, properties(n) AS props
            """
        )
        nodes = []
        for row in node_rows:
            nodes.append(self._node(row["props"], row["label"].lower()))
        # enrich work nodes with author name
        author_map = {a["id"]: a["label"] for a in nodes if a["type"] == "author"}
        for n in nodes:
            if n["type"] == "work":
                n["author"] = author_map.get(n["author_id"], "")

        wrote_rows = self._query(
            "MATCH (a:Author)-[r:WROTE]->(w:Work) RETURN a.id AS source, w.id AS target"
        )
        influence_rows = self._query(
            """
            MATCH (w1:Work)-[r:INFLUENCES]->(w2:Work)
            RETURN w1.id AS source, w2.id AS target,
                   r.kind AS kind, r.confidence AS confidence, r.quote AS quote
            """
        )
        edges = [
            {"source": r["source"], "target": r["target"], "type": "influence",
             "kind": r["kind"], "confidence": r["confidence"], "quote": r["quote"]}
            for r in influence_rows
        ]
        edges += [
            {"source": r["source"], "target": r["target"], "type": "wrote"}
            for r in wrote_rows
        ]
        return {"nodes": nodes, "edges": edges}

    def search(self, q: str, limit: int = 20) -> list[dict]:
        rows = self._query(
            """
            MATCH (n)
            WHERE (n:Work AND (n.title CONTAINS $q OR toLower(n.title_en) CONTAINS toLower($q)))
               OR (n:Author AND (n.name CONTAINS $q OR toLower(n.name_en) CONTAINS toLower($q)))
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
                        "label": props["name"],
                        "sub": f"{props['name_en']} · {props['era']}",
                    }
                )
            else:
                hits.append(
                    {
                        "id": props["id"],
                        "type": "work",
                        "label": props["title"],
                        "sub": f"{props['title_en']} · {props['year']}",
                    }
                )
        return hits[:limit]

    def path(self, from_id: str, to_id: str, max_hops: int) -> Optional[dict]:
        hop = max(1, int(max_hops))
        cypher = (
            "MATCH p = shortestPath((a:Work {id:$from})-[r:INFLUENCES*1.."
            f"{hop}"
            "]->(b:Work {id:$to})) "
            "RETURN [x IN nodes(p) | x.id] AS node_ids, "
            "[rel IN relationships(p) | {source: startNode(rel).id, target: endNode(rel).id, "
            "kind: rel.kind, confidence: rel.confidence, quote: rel.quote}] AS rels LIMIT 1"
        )
        rows = self._query(cypher, {"from": from_id, "to": to_id})
        if not rows:
            return None
        row = rows[0]
        return {"nodes": row["node_ids"], "edges": row["rels"]}

    def work_detail(self, work_id: str) -> Optional[dict]:
        rows = self._query(
            """
            MATCH (a:Author)-[:WROTE]->(w:Work {id:$id})
            RETURN properties(w) AS w, properties(a) AS a LIMIT 1
            """,
            {"id": work_id},
        )
        if not rows:
            return None
        wp, ap = rows[0]["w"], rows[0]["a"]
        inc = self._query(
            """
            MATCH (i:Work)-[r:INFLUENCES]->(w:Work {id:$id})
            MATCH (ia:Author)-[:WROTE]->(i)
            RETURN i.id AS source, i.title AS source_title, ia.name AS source_author,
                   r.kind AS kind, r.confidence AS confidence, r.quote AS quote
            ORDER BY r.confidence DESC
            """,
            {"id": work_id},
        )
        out = self._query(
            """
            MATCH (w:Work {id:$id})-[r:INFLUENCES]->(o:Work)
            MATCH (oa:Author)-[:WROTE]->(o)
            RETURN o.id AS target, o.title AS target_title, oa.name AS target_author,
                   r.kind AS kind, r.confidence AS confidence, r.quote AS quote
            ORDER BY r.confidence DESC
            """,
            {"id": work_id},
        )
        return {
            "work": {
                "id": wp.get("id"),
                "title": wp.get("title"),
                "title_en": wp.get("title_en"),
                "year": wp.get("year"),
                "language": wp.get("language"),
                "genre": wp.get("genre"),
            },
            "author": {
                "id": ap.get("id"),
                "name": ap.get("name"),
                "name_en": ap.get("name_en"),
                "birth": ap.get("birth"),
                "death": ap.get("death"),
                "nationality": ap.get("nationality"),
                "era": ap.get("era"),
            },
            "influenced_by": [dict(r) for r in inc],
            "influences": [dict(r) for r in out],
        }

    def stats(self) -> dict:
        author_count = self._query("MATCH (a:Author) RETURN count(a) AS c")[0]["c"]
        work_count = self._query("MATCH (w:Work) RETURN count(w) AS c")[0]["c"]
        edge_count = self._query("MATCH (:Work)-[r:INFLUENCES]->(:Work) RETURN count(r) AS c")[0]["c"]
        return {
            "authors": author_count,
            "works": work_count,
            "influence_edges": edge_count,
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

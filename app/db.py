"""Data access layer for Echo Graph.

Primary store is Neo4j (per README architecture). If Neo4j is unreachable,
the app transparently falls back to the bundled demo JSON dataset so the demo
always works. Set ECHO_STORE=json to force the JSON store.
"""

from __future__ import annotations

import json
import logging
import os
import time
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
        return {"meta": {"demo": False, "note": "no bundled dataset"}, "authors": [], "works": [], "edges": []}
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _env_int(name: str, default: int) -> int:
    """读取 .env 中的整数配置,非法值回退默认。"""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s 不是合法整数(%r),使用默认值 %s", name, raw, default)
        return default


class JsonStore:
    """In-memory fallback store (bundled snapshot if present, otherwise empty)."""

    name = "json"

    def __init__(self) -> None:
        self.seed = _load_seed()
        self.authors: dict[str, dict] = {a["id"]: a for a in self.seed["authors"] if not a.get("deletedAt")}
        self.works: dict[str, dict] = {w["id"]: w for w in self.seed["works"] if not w.get("deletedAt")}
        self.edges: list[dict] = [e for e in self.seed["edges"] if not e.get("deletedAt")]
        self.out: dict[str, list[dict]] = {}
        self.inc: dict[str, list[dict]] = {}
        for e in self.edges:
            self.out.setdefault(e["source"], []).append(e)
            self.inc.setdefault(e["target"], []).append(e)

    def _work_title(self, work_id: str) -> str:
        w = self.works.get(work_id)
        return w["Title_CN"] if w else work_id

    def _author_name(self, author_id: Optional[str]) -> str:
        a = self.authors.get(author_id or "")
        return a["Name_CN"] if a else ""

    def graph(self) -> dict:
        nodes = []
        for a in self.authors.values():
            nodes.append(
                {
                    "id": a["id"],
                    "type": "author",
                    "label": a["Name_CN"],
                    "label_en": a["Name_EN"],
                    "originalName": a["originalName"],
                    "nationality": a["nationality"],
                    "birthYear": a["birthYear"],
                    "deathYear": a["deathYear"],
                }
            )
        for w in self.works.values():
            nodes.append(
                {
                    "id": w["id"],
                    "type": "work",
                    "label": w["Title_CN"],
                    "label_en": w["Title_EN"],
                    "originalTitle": w["originalTitle"],
                    "year": w["publicationYear"] or w["creationYear"],
                    "publicationYear": w["publicationYear"],
                    "creationYear": w["creationYear"],
                    "language": w["language"],
                    "genre": w["genre"],
                    "author_id": w.get("author_id"),
                    "author": self._author_name(w.get("author_id")),
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
                    "reviewStatus": e["reviewStatus"],
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
                        "sub": f"{self._author_name(w.get('author_id'))} · {year}",
                    }
                )
        return hits[:limit]

    def path(self, from_id: str, to_id: str, max_hops: int) -> Optional[dict]:
        if from_id not in self.works or to_id not in self.works:
            return None
        if from_id == to_id:
            return {"nodes": [self.works[from_id]["id"]], "edges": []}
        # BFS over directed influence edges
        prev: dict[str, dict] = {from_id: {"node": from_id, "edge": None, "depth": 0}}
        queue = deque([from_id])
        found = False
        while queue and not found:
            cur = queue.popleft()
            if prev[cur]["depth"] >= max_hops:
                continue
            for e in self.out.get(cur, []):
                nxt = e["target"]
                if nxt not in prev:
                    prev[nxt] = {"node": nxt, "edge": e, "prev": cur, "depth": prev[cur]["depth"] + 1}
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
                    "reviewStatus": e["reviewStatus"],
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
        author = self.authors.get(w.get("author_id")) or {}
        return {
            "work": {
                "id": w["id"],
                "title": w["Title_CN"],
                "title_en": w["Title_EN"],
                "originalTitle": w["originalTitle"],
                "year": w["publicationYear"] or w["creationYear"],
                "publicationYear": w["publicationYear"],
                "creationYear": w["creationYear"],
                "language": w["language"],
                "genre": w["genre"],
            },
            "author": {
                "id": author.get("id"),
                "name": author.get("Name_CN", ""),
                "name_en": author.get("Name_EN"),
                "originalName": author.get("originalName"),
                "birthYear": author.get("birthYear"),
                "deathYear": author.get("deathYear"),
                "nationality": author.get("nationality"),
            },
            "mentioned_by": [
                {
                    "source": e["source"],
                    "source_title": self._work_title(e["source"]),
                    "source_author": self._author_name(self.works.get(e["source"], {}).get("author_id")),
                    "evidence": e["evidence"],
                    "evidenceSource": e["evidenceSource"],
                    "evidenceLang": e["evidenceLang"],
                    "note": e["note"],
                    "reviewStatus": e["reviewStatus"],
                }
                for e in self.inc.get(work_id, [])
            ],
            "mentions": [
                {
                    "target": e["target"],
                    "target_title": self._work_title(e["target"]),
                    "target_author": self._author_name(self.works.get(e["target"], {}).get("author_id")),
                    "evidence": e["evidence"],
                    "evidenceSource": e["evidenceSource"],
                    "evidenceLang": e["evidenceLang"],
                    "note": e["note"],
                    "reviewStatus": e["reviewStatus"],
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
            nodes.append(
                {
                    "id": w["id"],
                    "type": "work",
                    "label": w["Title_CN"],
                    "label_en": w["Title_EN"],
                    "originalTitle": w["originalTitle"],
                    "year": w["publicationYear"] or w["creationYear"],
                    "publicationYear": w["publicationYear"],
                    "creationYear": w["creationYear"],
                    "language": w["language"],
                    "genre": w["genre"],
                    "author_id": w.get("author_id"),
                    "author": self._author_name(w.get("author_id")),
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
                "reviewStatus": e["reviewStatus"],
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

        self._driver = GraphDatabase.driver(
            uri,
            auth=(username, password),
            max_connection_lifetime=_env_int("NEO4J_MAX_CONNECTION_LIFETIME", 3600),
            max_connection_pool_size=_env_int("NEO4J_MAX_CONNECTION_POOL_SIZE", 100),
            connection_timeout=_env_int("NEO4J_CONNECTION_TIMEOUT", 30),
        )
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
            "type": "work",
            "label": props.get("Title_CN"),
            "label_en": props.get("Title_EN"),
            "originalTitle": props.get("originalTitle"),
            "year": props.get("publicationYear") or props.get("creationYear"),
            "publicationYear": props.get("publicationYear"),
            "creationYear": props.get("creationYear"),
            "language": props.get("language"),
            "genre": props.get("genre"),
            "author_id": props.get("author_id"),
            "author": props.get("author_name", ""),
        }

    def graph(self) -> dict:
        author_rows = self._query(
            """
            MATCH (a:Author)
            WHERE a.deletedAt IS NULL
            RETURN properties(a) AS props
            """
        )
        nodes = []
        for row in author_rows:
            p = row["props"]
            nodes.append(
                {
                    "id": p.get("id"),
                    "type": "author",
                    "label": p.get("Name_CN"),
                    "label_en": p.get("Name_EN"),
                    "originalName": p.get("originalName"),
                    "nationality": p.get("nationality"),
                    "birthYear": p.get("birthYear"),
                    "deathYear": p.get("deathYear"),
                }
            )

        node_rows = self._query(
            """
            MATCH (w:Work)
            WHERE w.deletedAt IS NULL
            OPTIONAL MATCH (w)-[:AUTHORED_BY]->(a:Author)
            WHERE a.deletedAt IS NULL
            RETURN properties(w) AS props,
                   collect(DISTINCT a.Name_CN) AS author_names,
                   collect(DISTINCT a.id) AS author_ids
            """
        )
        for row in node_rows:
            row["props"] = dict(row["props"])
            names = [n for n in (row["author_names"] or []) if n]
            ids = [i for i in (row["author_ids"] or []) if i]
            row["props"]["author_name"] = "、".join(names)
            row["props"]["author_id"] = ids[0] if ids else None
        nodes.extend(self._node(row["props"], "work") for row in node_rows)

        echo_rows = self._query(
            """
            MATCH (w1:Work)-[r:ECHO]->(w2:Work)
            WHERE w1.deletedAt IS NULL AND w2.deletedAt IS NULL AND r.deletedAt IS NULL
            RETURN w1.id AS source, w2.id AS target,
                   r.evidence AS evidence, r.evidenceSource AS evidenceSource,
                   r.evidenceLang AS evidenceLang, r.note AS note,
                   r.reviewStatus AS reviewStatus
            """
        )
        edges = [
            {"source": r["source"], "target": r["target"], "type": "echo",
             "evidence": r["evidence"], "evidenceSource": r["evidenceSource"],
             "evidenceLang": r["evidenceLang"], "note": r["note"],
             "reviewStatus": r["reviewStatus"]}
            for r in echo_rows
        ]
        authored_rows = self._query(
            """
            MATCH (w:Work)-[:AUTHORED_BY]->(a:Author)
            WHERE w.deletedAt IS NULL AND a.deletedAt IS NULL
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
            WHERE ((n:Work AND (n.Title_CN CONTAINS $q OR toLower(n.Title_EN) CONTAINS toLower($q) OR toLower(n.originalTitle) CONTAINS toLower($q)))
               OR (n:Author AND (n.Name_CN CONTAINS $q OR toLower(n.Name_EN) CONTAINS toLower($q) OR toLower(n.originalName) CONTAINS toLower($q))))
              AND n.deletedAt IS NULL
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
            "WHERE all(x IN nodes(p) WHERE x.deletedAt IS NULL) "
            "AND all(rel IN relationships(p) WHERE rel.deletedAt IS NULL) "
            "RETURN [x IN nodes(p) | x.id] AS node_ids, "
            "[rel IN relationships(p) | {source: startNode(rel).id, target: endNode(rel).id, "
            "evidence: rel.evidence, evidenceSource: rel.evidenceSource, "
            "evidenceLang: rel.evidenceLang, note: rel.note, "
            "reviewStatus: rel.reviewStatus}] AS rels LIMIT 1"
        )
        rows = self._query(cypher, {"from": from_id, "to": to_id})
        if not rows:
            return None
        row = rows[0]
        return {"nodes": row["node_ids"], "edges": row["rels"]}

    def work_detail(self, work_id: str) -> Optional[dict]:
        rows = self._query(
            """
            MATCH (w:Work {id:$id})
            WHERE w.deletedAt IS NULL
            OPTIONAL MATCH (w)-[:AUTHORED_BY]->(a:Author)
            WHERE a.deletedAt IS NULL
            RETURN properties(w) AS w, collect(DISTINCT a) AS author_nodes LIMIT 1
            """,
            {"id": work_id},
        )
        if not rows:
            return None
        wp = rows[0]["w"]
        author_rows = [dict(a) for a in (rows[0]["author_nodes"] or []) if a]
        ap = author_rows[0] if author_rows else {}

        def author_payload(a: dict) -> dict:
            return {
                "id": a.get("id"),
                "name": a.get("Name_CN", ""),
                "name_en": a.get("Name_EN"),
                "originalName": a.get("originalName"),
                "birthYear": a.get("birthYear"),
                "deathYear": a.get("deathYear"),
                "nationality": a.get("nationality"),
            }

        authors = [author_payload(a) for a in author_rows]
        inc = self._query(
            """
            MATCH (i:Work)-[r:ECHO]->(w:Work {id:$id})
            MATCH (i)-[:AUTHORED_BY]->(ia:Author)
            WHERE i.deletedAt IS NULL AND r.deletedAt IS NULL AND ia.deletedAt IS NULL
            RETURN i.id AS source, i.Title_CN AS source_title, ia.Name_CN AS source_author,
                   r.evidence AS evidence, r.evidenceSource AS evidenceSource,
                   r.evidenceLang AS evidenceLang, r.note AS note,
                   r.reviewStatus AS reviewStatus
            """,
            {"id": work_id},
        )
        out = self._query(
            """
            MATCH (w:Work {id:$id})-[r:ECHO]->(o:Work)
            MATCH (o)-[:AUTHORED_BY]->(oa:Author)
            WHERE r.deletedAt IS NULL AND o.deletedAt IS NULL AND oa.deletedAt IS NULL
            RETURN o.id AS target, o.Title_CN AS target_title, oa.Name_CN AS target_author,
                   r.evidence AS evidence, r.evidenceSource AS evidenceSource,
                   r.evidenceLang AS evidenceLang, r.note AS note,
                   r.reviewStatus AS reviewStatus
            """,
            {"id": work_id},
        )
        return {
            "work": {
                "id": wp.get("id"),
                "title": wp.get("Title_CN"),
                "title_en": wp.get("Title_EN"),
                "originalTitle": wp.get("originalTitle"),
                "year": wp.get("publicationYear") or wp.get("creationYear"),
                "publicationYear": wp.get("publicationYear"),
                "creationYear": wp.get("creationYear"),
                "language": wp.get("language"),
                "genre": wp.get("genre"),
            },
            "author": authors[0] if authors else None,
            "authors": authors,
            "mentioned_by": [dict(r) for r in inc],
            "mentions": [dict(r) for r in out],
        }

    def expansion(self, work_id: str, hops: int) -> Optional[dict]:
        hop = max(1, min(int(hops), 8))
        node_rows = self._query(
            "MATCH (c:Work {id:$id}) "
            f"MATCH (n:Work) WHERE (n.id = c.id OR (c)-[:ECHO*1..{hop}]-(n)) AND n.deletedAt IS NULL "
            "OPTIONAL MATCH (n)-[:AUTHORED_BY]->(a:Author) WHERE a.deletedAt IS NULL "
            "RETURN properties(n) AS props, "
            "collect(DISTINCT a.Name_CN) AS author_names, "
            "collect(DISTINCT a.id) AS author_ids",
            {"id": work_id},
        )
        if not node_rows:
            return None
        nodes = []
        ids = []
        for row in node_rows:
            props = dict(row["props"])
            names = [n for n in (row["author_names"] or []) if n]
            auth_ids = [i for i in (row["author_ids"] or []) if i]
            props["author_name"] = "、".join(names)
            props["author_id"] = auth_ids[0] if auth_ids else None
            nodes.append(self._node(props, "work"))
            ids.append(props["id"])
        edge_rows = self._query(
            f"MATCH (c:Work {{id:$id}}) "
            f"MATCH (n:Work) WHERE n.id = c.id OR (c)-[:ECHO*1..{hop}]-(n) "
            "WITH collect(n.id) AS ids "
            "MATCH (a:Work)-[r:ECHO]->(b:Work) "
            "WHERE a.id IN ids AND b.id IN ids "
            "AND a.deletedAt IS NULL AND b.deletedAt IS NULL AND r.deletedAt IS NULL "
            "RETURN a.id AS source, b.id AS target, r.evidence AS evidence, "
            "r.evidenceSource AS evidenceSource, r.evidenceLang AS evidenceLang, "
            "r.note AS note, r.reviewStatus AS reviewStatus",
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
                "reviewStatus": r["reviewStatus"],
            }
            for r in edge_rows
        ]
        return {"nodes": nodes, "edges": edges, "centerId": work_id}

    def stats(self) -> dict:
        author_count = self._query("MATCH (a:Author) WHERE a.deletedAt IS NULL RETURN count(a) AS c")[0]["c"]
        work_count = self._query("MATCH (w:Work) WHERE w.deletedAt IS NULL RETURN count(w) AS c")[0]["c"]
        edge_count = self._query(
            "MATCH (a:Work)-[r:ECHO]->(b:Work) "
            "WHERE a.deletedAt IS NULL AND b.deletedAt IS NULL AND r.deletedAt IS NULL "
            "RETURN count(r) AS c"
        )[0]["c"]
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
        self._last_warn_at = 0.0
        self._fallbacks = 0

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return getattr(self.primary, name)(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - demo resilience
            self._fallbacks += 1
            now = time.monotonic()
            if now - self._last_warn_at >= 60:
                logger.warning("Neo4j query '%s' failed (%s); falling back to JSON for this request", name, exc)
                self._last_warn_at = now
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
        stats = self._call("stats")
        if isinstance(stats, dict):
            stats = dict(stats)
            stats["fallbacks"] = self._fallbacks
        return stats

    def fallback_count(self) -> int:
        return self._fallbacks

    def close(self) -> None:
        """关闭底层 Neo4j driver(由 FastAPI 生命周期在退出时调用)。"""
        close = getattr(self.primary, "close", None)
        if callable(close):
            close()


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

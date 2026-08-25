"""公开读取数据层:SQLite 为唯一权威,全部查询直接读 SQLite。

Neo4j 查询层与 JSON 兜底(seed.json)已退役(见 docs/sqlite-migration.md);
软删除(deletedAt 非空)的行不进入任何读取结果。输出形状与旧 JsonStore 保持一致,
前端无需感知存储层变化。
"""

from __future__ import annotations

import os
import time
from collections import deque

from app import db_sqlite
from app.auth import admin_user_id

# 进程内读缓存:同一 DB 路径缓存活跃行(默认 3 秒,兜底外部进程写入);
# admin 写入 / 整库重建 / 快照恢复会显式调用 invalidate_cache() 立即失效。
_CACHE_TTL_SECONDS = 3.0
_read_cache: dict[tuple[str, ...], tuple[float, tuple]] = {}


def _cache_key() -> tuple[str, ...]:
    return (str(db_sqlite.DB_PATH),)


def invalidate_cache() -> None:
    """清除公开读取缓存(admin 写入 / 整库重建 / 快照恢复后调用)。"""
    _read_cache.clear()


def _author_node(p: dict) -> dict:
    """作者图谱节点。"""
    return {
        "id": p.get("id"),
        "type": "author",
        "label": p.get("Name_CN"),
        "label_en": p.get("Name_EN"),
        "originalName": p.get("originalName"),
        "nationality": p.get("nationality"),
        "birthYear": p.get("birthYear"),
        "deathYear": p.get("deathYear"),
        "reviewStatus": p.get("reviewStatus"),
    }


def _work_node(p: dict) -> dict:
    """作品图谱节点。调用方需在 p 中注入 author_ids / author_name。"""
    author_ids = p.get("author_ids") or []
    return {
        "id": p.get("id"),
        "type": "work",
        "label": p.get("Title_CN"),
        "label_en": p.get("Title_EN"),
        "originalTitle": p.get("originalTitle"),
        "year": p.get("publicationYear"),
        "publicationYear": p.get("publicationYear"),
        "language": p.get("language"),
        "genre": p.get("genre"),
        "reviewStatus": p.get("reviewStatus"),
        "author_id": author_ids[0] if author_ids else None,
        "author_ids": author_ids,
        "author": p.get("author_name", ""),
    }


def _echo_edge(r: dict) -> dict:
    """ECHO 提及关系(图谱 / 路径 / 涟漪详情共用)。"""
    return {
        "source": r.get("source"),
        "target": r.get("target"),
        "type": "echo",
        "evidence": r.get("evidence"),
        "evidenceSource": r.get("evidenceSource"),
        "note": r.get("note"),
        "reviewStatus": r.get("reviewStatus"),
    }


def _authored_edge(source: str, target: str) -> dict:
    """作品归属边 (Work)-[:AUTHORED_BY]->(Author)。"""
    return {"source": source, "target": target, "type": "authored"}


def _work_payload(p: dict) -> dict:
    """作品详情载荷。"""
    return {
        "id": p.get("id"),
        "title": p.get("Title_CN"),
        "title_en": p.get("Title_EN"),
        "originalTitle": p.get("originalTitle"),
        "year": p.get("publicationYear"),
        "publicationYear": p.get("publicationYear"),
        "language": p.get("language"),
        "genre": p.get("genre"),
        "readingStatus": p.get("readingStatus"),  # 个人阅读状态(仅用户空间语义)
        "recommendation": p.get("recommendation"),  # 个人评分(仅用户空间语义)
        "review": p.get("review"),  # 个人评价(仅用户空间语义)
    }


def _author_payload(a: dict) -> dict:
    """作者详情载荷(work_detail 的 author / authors)。"""
    return {
        "id": a.get("id"),
        "name": a.get("Name_CN", ""),
        "name_en": a.get("Name_EN"),
        "originalName": a.get("originalName"),
        "birthYear": a.get("birthYear"),
        "deathYear": a.get("deathYear"),
        "nationality": a.get("nationality"),
    }


def _mention_row(prefix: str, e: dict, title: str, author: str) -> dict:
    """涟漪详情中的单条提及记录(prefix 为 source 或 target)。"""
    return {
        prefix: e.get(prefix),
        f"{prefix}_title": title,
        f"{prefix}_author": author,
        "evidence": e.get("evidence"),
        "evidenceSource": e.get("evidenceSource"),
        "note": e.get("note"),
        "reviewStatus": e.get("reviewStatus"),
    }


class SqliteStore:
    """SQLite-backed read store(输出形状与旧 JsonStore 一致)。

    每次查询读取活跃(未软删除)数据;当前规模下开销可忽略,
    数据量增长后可在此层加进程内缓存(写入时失效)。

    reviewed_only(公开视图):为 True 时所有公开接口只返回 reviewStatus=reviewed
    的内容(草稿/驳回不可见)。默认读取环境变量 PUBLIC_REVIEWED_ONLY
    (取值 1 / true / yes / on 开启),部署时在 .env 中配置。

    作者/作品的节点可见性(visibility)已于 schema v21 移除:公开星云内的数据
    对所有访客一致可见,访客/owner 视图不再区分。
    """

    name = "sqlite"

    def __init__(
        self,
        reviewed_only: bool | None = None,
        owner_id: str | None = None,
    ) -> None:
        if reviewed_only is None:
            reviewed_only = os.getenv("PUBLIC_REVIEWED_ONLY", "").strip().lower() in (
                "1", "true", "yes", "on",
            )
        # 审核过滤只约束公共视图:个人空间里用户必须能看到自己的草稿/驳回数据
        self.reviewed_only = reviewed_only and owner_id is None
        # 空间过滤:None = 公共视图(admin 认领的数据 + 尚未认领的历史行);
        # 具体用户 id = 该用户私有空间(仅本人可见)。
        self.owner_id = owner_id

    def _effective_status(self, status: str | None) -> str | None:
        """公开视图强制 reviewed;内部/管理场景沿用显式 status。"""
        return "reviewed" if self.reviewed_only else status

    def _owner_clause(self, prefix: str = "") -> tuple[str, tuple]:
        """返回 owner 过滤 SQL 片段与参数;公共视图包含未认领行(认领前的过渡态)。"""
        col = f"{prefix}owner_id"
        if self.owner_id is not None:
            return f"{col} = ?", (self.owner_id,)
        admin = admin_user_id()
        if admin is None:
            return f"{col} IS NULL", ()
        return f"({col} IS NULL OR {col} = ?)", (admin,)

    def close(self) -> None:
        """无连接池,无需清理。"""

    def _tables(self) -> tuple[list[dict], list[dict], list[dict], dict[str, list[str]]]:
        """一次取回活跃数据:authors / works / edges(附 source/target 别名)+ work_authors。

        结果按 DB 路径进程内缓存(TTL 3 秒);调用方不得修改返回的行 dict,
        写路径通过 invalidate_cache() 保证"编辑保存后即时可读"。
        """
        now = time.monotonic()
        # 缓存键含空间与审核过滤:不同 owner/公共视图互不串缓存,
        # 同一 DB 路径下不同 reviewed_only 的 store 也不串缓存
        key = _cache_key() + (
            self.owner_id or "public",
            self.reviewed_only,
        )
        hit = _read_cache.get(key)
        if hit is not None and now - hit[0] < _CACHE_TTL_SECONDS:
            return hit[1]
        owner_sql, owner_params = self._owner_clause()
        wa_sql, wa_params = self._owner_clause("w.")
        not_ai_draft = db_sqlite.ai_draft_clause(negate=True)
        not_ai_draft_w = db_sqlite.ai_draft_clause("w", negate=True)
        with db_sqlite._db() as conn:
            authors = [
                dict(r) for r in conn.execute(
                    f"SELECT * FROM authors WHERE deletedAt IS NULL AND {owner_sql}"
                    f" AND {not_ai_draft}"
                    " ORDER BY id",
                    owner_params,
                )
            ]
            works = [
                dict(r) for r in conn.execute(
                    f"SELECT * FROM works WHERE deletedAt IS NULL AND {owner_sql}"
                    f" AND {not_ai_draft}"
                    " ORDER BY id",
                    owner_params,
                )
            ]
            edges = [
                dict(r) for r in conn.execute(
                    f"SELECT * FROM edges WHERE deletedAt IS NULL AND {owner_sql}"
                    f" AND {not_ai_draft} ORDER BY id",
                    owner_params,
                )
            ]
            wa_rows = conn.execute(
                "SELECT wa.work_id, wa.author_id FROM work_authors wa"
                " JOIN works w ON w.id = wa.work_id"
                f" WHERE w.deletedAt IS NULL AND {wa_sql} AND {not_ai_draft_w}"
                " ORDER BY wa.work_id, wa.author_id",
                wa_params,
            ).fetchall()
        work_authors: dict[str, list[str]] = {}
        for r in wa_rows:
            work_authors.setdefault(r["work_id"], []).append(r["author_id"])
        for e in edges:
            e["source"] = e["source_work_id"]
            e["target"] = e["target_work_id"]
        payload = (authors, works, edges, work_authors)
        _read_cache[key] = (now, payload)
        return payload

    @staticmethod
    def _join_names(author_ids: list[str], authors_by_id: dict[str, dict]) -> str:
        return "、".join(
            n for n in (authors_by_id.get(aid, {}).get("Name_CN") for aid in author_ids) if n
        )

    def graph(self, status: str | None = None) -> dict:
        authors, works, edges, work_authors = self._tables()
        status = self._effective_status(status)
        if status:
            authors = [a for a in authors if (a.get("reviewStatus") or "draft") == status]
            works = [w for w in works if (w.get("reviewStatus") or "draft") == status]
            edges = [e for e in edges if (e.get("reviewStatus") or "draft") == status]
        # 只返回端点均可见(未软删除且通过状态过滤)的边,避免幽灵边指向被过滤的作品
        visible_work_ids = {w["id"] for w in works}
        edges = [e for e in edges if e["source"] in visible_work_ids and e["target"] in visible_work_ids]
        authors_by_id = {a["id"]: a for a in authors}
        nodes = [_author_node(a) for a in authors]
        for w in works:
            props = dict(w)
            props["author_ids"] = work_authors.get(w["id"], [])
            props["author_name"] = self._join_names(props["author_ids"], authors_by_id)
            nodes.append(_work_node(props))
        echo_edges = [_echo_edge(e) for e in edges]
        authored_edges = [
            _authored_edge(w["id"], aid)
            for w in works
            for aid in work_authors.get(w["id"], [])
            if aid in authors_by_id
        ]
        return {"nodes": nodes, "edges": echo_edges + authored_edges}

    def search(self, q: str, limit: int = 20) -> list[dict]:
        authors, works, _, work_authors = self._tables()
        if self.reviewed_only:
            authors = [a for a in authors if (a.get("reviewStatus") or "draft") == "reviewed"]
            works = [w for w in works if (w.get("reviewStatus") or "draft") == "reviewed"]
        ql = q.lower()
        authors_by_id = {a["id"]: a for a in authors}
        hits: list[dict] = []
        for a in authors:
            hay = " ".join(
                str(v or "") for v in (a.get("Name_CN"), a.get("Name_EN"), a.get("originalName"))
            ).lower()
            if ql in hay:
                sub_parts = [a.get("originalName") or "", a.get("nationality") or ""]
                hits.append({
                    "id": a["id"],
                    "type": "author",
                    "label": a.get("Name_CN"),
                    "sub": " · ".join(p for p in sub_parts if p),
                })
        for w in works:
            hay = " ".join(
                str(v or "") for v in (w.get("Title_CN"), w.get("Title_EN"), w.get("originalTitle"))
            ).lower()
            if ql in hay:
                year = w.get("publicationYear")
                sub_parts = [
                    self._join_names(work_authors.get(w["id"], []), authors_by_id),
                    str(year) if year else "",
                ]
                hits.append({
                    "id": w["id"],
                    "type": "work",
                    "label": w.get("Title_CN"),
                    "sub": " · ".join(p for p in sub_parts if p),
                })
        return hits[:limit]

    def path(self, from_id: str, to_id: str, max_hops: int) -> dict | None:
        _, works, edges, _ = self._tables()
        status = self._effective_status(None)
        if status:
            works = [w for w in works if (w.get("reviewStatus") or "draft") == status]
            edges = [e for e in edges if (e.get("reviewStatus") or "draft") == status]
        work_ids = {w["id"] for w in works}
        if from_id not in work_ids or to_id not in work_ids:
            return None
        if from_id == to_id:
            return {"nodes": [from_id], "edges": []}
        out: dict[str, list[dict]] = {}
        for e in edges:
            out.setdefault(e["source"], []).append(e)
        prev: dict[str, dict] = {from_id: {"node": from_id, "edge": None, "depth": 0}}
        queue = deque([from_id])
        found = False
        while queue and not found:
            cur = queue.popleft()
            if prev[cur]["depth"] >= max_hops:
                continue
            for e in out.get(cur, []):
                nxt = e["target"]
                # 只经过可见(未软删除且通过状态过滤)的作品,避免路径绕行被过滤的草稿
                if nxt in work_ids and nxt not in prev:
                    prev[nxt] = {"node": nxt, "edge": e, "prev": cur, "depth": prev[cur]["depth"] + 1}
                    if nxt == to_id:
                        found = True
                        break
                    queue.append(nxt)
        if not found:
            return None
        return self._backtrack(prev, to_id)

    @staticmethod
    def _backtrack(prev: dict, node: str) -> dict:
        nodes: list[str] = []
        edges: list[dict] = []
        cur = node
        while prev[cur].get("edge") is not None:
            e = prev[cur]["edge"]
            edges.append(_echo_edge(e))
            nodes.append(cur)
            cur = prev[cur]["prev"]
        nodes.append(cur)
        nodes.reverse()
        edges.reverse()
        return {"nodes": nodes, "edges": edges}

    def work_detail(self, work_id: str) -> dict | None:
        authors, works, edges, work_authors = self._tables()
        w = next((x for x in works if x["id"] == work_id), None)
        if w is None:
            return None
        if self.reviewed_only and (w.get("reviewStatus") or "draft") != "reviewed":
            return None
        if self.reviewed_only:
            edges = [e for e in edges if (e.get("reviewStatus") or "draft") == "reviewed"]
        works_by_id = {x["id"]: x for x in works}
        authors_by_id = {a["id"]: a for a in authors}

        def author_ids_of(wid: str) -> list[str]:
            return work_authors.get(wid, [])

        authors_payload = [
            _author_payload(authors_by_id[aid])
            for aid in author_ids_of(work_id)
            if aid in authors_by_id
        ]
        mentioned_by = [
            _mention_row(
                "source",
                _echo_edge(e),
                works_by_id.get(e["source"], {}).get("Title_CN") or e["source"],
                self._join_names(author_ids_of(e["source"]), authors_by_id),
            )
            for e in edges
            if e["target"] == work_id
        ]
        mentions = [
            _mention_row(
                "target",
                _echo_edge(e),
                works_by_id.get(e["target"], {}).get("Title_CN") or e["target"],
                self._join_names(author_ids_of(e["target"]), authors_by_id),
            )
            for e in edges
            if e["source"] == work_id
        ]
        return {
            "work": _work_payload(w),
            "author": authors_payload[0] if authors_payload else None,
            "authors": authors_payload,
            "mentioned_by": mentioned_by,
            "mentions": mentions,
        }

    def expansion(self, work_id: str, hops: int) -> dict | None:
        """以 work_id 为中心,沿 ECHO 关系(无向)向外扩散 hops 级,返回子图。"""
        authors, works, edges, work_authors = self._tables()
        status = self._effective_status(None)
        if status:
            authors = [a for a in authors if (a.get("reviewStatus") or "draft") == status]
            works = [w for w in works if (w.get("reviewStatus") or "draft") == status]
            edges = [e for e in edges if (e.get("reviewStatus") or "draft") == status]
        works_by_id = {w["id"]: w for w in works}
        if work_id not in works_by_id:
            return None
        out: dict[str, list[dict]] = {}
        inc: dict[str, list[dict]] = {}
        for e in edges:
            out.setdefault(e["source"], []).append(e)
            inc.setdefault(e["target"], []).append(e)
        visited = {work_id}
        frontier = [work_id]
        for _ in range(max(1, int(hops))):
            nxt: list[str] = []
            for wid in frontier:
                for e in out.get(wid, []) + inc.get(wid, []):
                    other = e["target"] if e["source"] == wid else e["source"]
                    # 只扩散到可见(未软删除且通过状态过滤)的作品,跳过被过滤的草稿
                    if other in works_by_id and other not in visited:
                        visited.add(other)
                        nxt.append(other)
            frontier = nxt
            if not frontier:
                break
        authors_by_id = {a["id"]: a for a in authors}
        nodes = []
        for wid in visited:
            w = works_by_id[wid]
            props = dict(w)
            props["author_ids"] = work_authors.get(wid, [])
            props["author_name"] = self._join_names(props["author_ids"], authors_by_id)
            nodes.append(_work_node(props))
        echo_edges = [
            _echo_edge(e) for e in edges if e["source"] in visited and e["target"] in visited
        ]
        return {"nodes": nodes, "edges": echo_edges, "centerId": work_id}

    def stats(self) -> dict:
        authors, works, edges, _ = self._tables()
        status = self._effective_status(None)
        if status:
            authors = [a for a in authors if (a.get("reviewStatus") or "draft") == status]
            works = [w for w in works if (w.get("reviewStatus") or "draft") == status]
            edges = [e for e in edges if (e.get("reviewStatus") or "draft") == status]

        def status_counts(items: list[dict]) -> dict[str, int]:
            counts = {"draft": 0, "reviewed": 0, "rejected": 0}
            for it in items:
                key = it.get("reviewStatus") or "draft"
                counts[key] = counts.get(key, 0) + 1
            return counts

        return {
            "authors": len(authors),
            "works": len(works),
            "echo_edges": len(edges),
            "store": self.name,
            "demo": False,
            "reviewStatus": {
                "authors": status_counts(authors),
                "works": status_counts(works),
                "edges": status_counts(edges),
            },
        }


_store: SqliteStore | None = None


def get_store() -> SqliteStore:
    """返回进程内唯一的 SQLite 读取 Store(DB 路径按 db_sqlite.DB_PATH 惰性解析)。"""
    global _store
    if _store is None:
        _store = SqliteStore()
    return _store

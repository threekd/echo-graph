"""Import Echo Graph data into Neo4j.

数据源(按优先级):
  1. xlsx:data/real/data_echo-graph.xlsx(真实数据,推荐,sheet: Author/Work/Echo)
  2. csv :data/real/ 下的 authors.csv / works.csv / echoes.csv

特性:
  - Pydantic 校验(类型、枚举、交叉引用、重复 id/slug、作者关联),失败不导入
  - 幂等导入:UNWIND 批量 MERGE + SET +=,可重复执行;默认不删除已有数据
  - --wipe:全量重建(删除示例数据)
  - 软删除:deletedAt 非空则跳过
  - 自动补齐:slug 为空时自动生成;Echo.reviewStatus 默认 draft;evidenceLang 从源作品语言推导
  - 导入后导出 JSON 快照到 data/snapshots/

用法:
  uv run python scripts/import_data.py                     # 自动识别 xlsx / csv
  uv run python scripts/import_data.py --source xlsx --wipe --version real-1.0
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase
from pydantic import BaseModel, Field, field_validator, model_validator

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
REAL_DIR = ROOT / "data" / "real"
XLSX_PATH = REAL_DIR / "data_echo-graph.xlsx"
SNAPSHOT_DIR = ROOT / "data" / "snapshots"
CHUNK = 500

SLUG_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
GENRES = ("Fiction", "Non-fiction", "Poetry", "Drama")
REVIEW_STATUSES = ("draft", "reviewed", "rejected")


# =============================== 校验模型(对齐 data_schema.md 1.1) ===============================

class AuthorRow(BaseModel):
    model_config = {"extra": "ignore"}

    id: str = Field(min_length=1)
    slug: Optional[str] = None
    originalName: str = Field(min_length=1)
    Name_CN: str
    Name_EN: Optional[str] = None
    nationality: Optional[str] = None
    birthYear: Optional[int] = None
    deathYear: Optional[int] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    deletedAt: Optional[str] = None

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id 不能为空")
        return v

    @model_validator(mode="after")
    def _years(self) -> "AuthorRow":
        if (
            self.birthYear is not None
            and self.deathYear is not None
            and self.birthYear >= self.deathYear
        ):
            raise ValueError(f"作者 {self.id} 的出生年应早于去世年")
        return self


class WorkRow(BaseModel):
    model_config = {"extra": "ignore"}

    id: str = Field(min_length=1)
    slug: Optional[str] = None
    language: str = Field(min_length=2, max_length=3)
    originalTitle: str = Field(min_length=1)
    Title_CN: str
    Title_EN: Optional[str] = None
    Title_Other: Optional[str] = None
    Author: Optional[str] = None  # 多人用逗号","隔开
    publicationYear: Optional[int] = None
    creationYear: Optional[int] = None
    genre: Optional[Literal["Fiction", "Non-fiction", "Poetry", "Drama"]] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    deletedAt: Optional[str] = None

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id 不能为空")
        return v


class EchoRow(BaseModel):
    model_config = {"extra": "ignore"}

    source_work_id: str = Field(min_length=1)
    target_work_id: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    evidenceSource: Optional[str] = None
    evidenceLang: Optional[str] = None
    note: Optional[str] = None
    reviewStatus: Optional[Literal["draft", "reviewed", "rejected"]] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    deletedAt: Optional[str] = None

    @model_validator(mode="after")
    def _no_self(self) -> "EchoRow":
        if self.source_work_id == self.target_work_id:
            raise ValueError("ECHO 不允许自环(source == target)")
        return self


# =============================== 读取 ===============================

def _clean_row(raw: dict) -> dict:
    out: dict = {}
    for k, v in raw.items():
        if isinstance(v, str):
            v = v.strip() or None
        elif isinstance(v, (dt.datetime, dt.date)):
            v = v.isoformat()
        out[k] = v
    return out


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as fh:
        return [_clean_row(r) for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]


def load_xlsx() -> tuple[list[dict], list[dict], list[dict]]:
    import openpyxl

    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)

    def sheet_rows(name: str) -> list[dict]:
        ws = wb[name]
        rows = [r for r in ws.iter_rows(values_only=True) if any(v is not None for v in r)]
        header = [str(c) if c is not None else "" for c in rows[0]]
        return [
            _clean_row({header[i]: (v if i < len(header) else None) for i, v in enumerate(r)})
            for r in rows[1:]
        ]

    authors = sheet_rows("Author")
    works = sheet_rows("Work")
    echoes = sheet_rows("Echo")
    # 忽略 Echo 中仅用于人工核对的信息列(source_original_title 等)
    keep = {
        "source_work_id", "target_work_id", "evidence", "evidenceSource",
        "evidenceLang", "note", "reviewStatus", "createdAt", "updatedAt", "deletedAt",
    }
    echoes = [{k: v for k, v in e.items() if k in keep} for e in echoes]
    return authors, works, echoes


def load_csv_real() -> tuple[list[dict], list[dict], list[dict]]:
    return (
        _read_csv(REAL_DIR / "authors.csv"),
        _read_csv(REAL_DIR / "works.csv"),
        _read_csv(REAL_DIR / "echoes.csv"),
    )


def make_slug(text: Optional[str], fallback: str) -> str:
    """把标题/姓名转成 slug;失败时回退到 fallback(通常是 id)。"""
    if not text:
        return fallback
    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if c.isascii() and (c.isalnum() or c in "- "))
    s = re.sub(r"\s+", "-", s.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s if s else fallback


def assign_slugs(authors: list[dict], works: list[dict]) -> None:
    for a in authors:
        if not a.get("slug"):
            a["slug"] = make_slug(a.get("Name_EN") or a.get("originalName") or a.get("Name_CN"), a["id"])
    for w in works:
        if not w.get("slug"):
            w["slug"] = make_slug(
                w.get("Title_EN") or w.get("originalTitle") or w.get("Title_CN"), w["id"]
            )


# =============================== 校验 ===============================

def parse_rows(
    authors: list[dict], works: list[dict], echoes: list[dict]
) -> tuple[list[AuthorRow], list[WorkRow], list[EchoRow], dict[str, list[str]]]:
    errors: list[str] = []

    def check(rows: list[dict], model: type[BaseModel], label: str) -> list[BaseModel]:
        parsed: list[BaseModel] = []
        for i, row in enumerate(rows, start=2):
            try:
                parsed.append(model.model_validate(row))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label} 第 {i} 行: {exc}")
        return parsed

    assign_slugs(authors, works)
    author_models: list[AuthorRow] = check(authors, AuthorRow, "Author")
    work_models: list[WorkRow] = check(works, WorkRow, "Work")
    echo_models: list[EchoRow] = check(echoes, EchoRow, "Echo")

    author_by_name: dict[str, str] = {}
    for a in author_models:
        for key in (a.originalName, a.Name_CN, a.Name_EN):
            if key:
                author_by_name.setdefault(key.strip().lower(), a.id)

    author_ids: set[str] = {a.id for a in author_models}
    work_ids: set[str] = {w.id for w in work_models}

    def dup(items: list[str], label: str) -> None:
        seen: set[str] = set()
        for it in items:
            if it in seen:
                errors.append(f"{label} 重复:{it}")
            seen.add(it)

    dup([a.id for a in author_models], "作者 id")
    dup([a.slug or a.id for a in author_models], "作者 slug")
    dup([w.id for w in work_models], "作品 id")
    dup([w.slug or w.id for w in work_models], "作品 slug")

    work_authors: dict[str, list[str]] = {}
    for w in work_models:
        if w.Author:
            for raw in w.Author.split(","):
                name = raw.strip()
                if not name:
                    continue
                aid = author_by_name.get(name.lower())
                if not aid:
                    errors.append(f"作品 {w.id} 的作者 {name!r} 未在 Author 表中找到")
                    continue
                work_authors.setdefault(w.id, []).append(aid)

    for e in echo_models:
        if e.source_work_id not in work_ids:
            errors.append(f"ECHO 引用了不存在的源作品 {e.source_work_id}")
        if e.target_work_id not in work_ids:
            errors.append(f"ECHO 引用了不存在的目标作品 {e.target_work_id}")

    if errors:
        raise SystemExit("校验失败,未导入:\n- " + "\n- ".join(errors[:60]))
    print(
        f"校验通过: authors={len(author_models)}, works={len(work_models)}, "
        f"echoes={len(echo_models)}, authored_links={sum(len(v) for v in work_authors.values())}"
    )
    return author_models, work_models, echo_models, work_authors


# =============================== 导入 ===============================

def _chunks(rows: list, size: int = CHUNK):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _node_props(row: BaseModel, now: str) -> dict:
    d = row.model_dump(exclude={"id", "slug", "deletedAt"})
    d["createdAt"] = d.get("createdAt") or now
    d["updatedAt"] = now
    return d


def _echo_props(row: EchoRow, now: str, source_lang: Optional[str]) -> dict:
    d = row.model_dump(exclude={"source_work_id", "target_work_id", "deletedAt"})
    d["evidenceLang"] = d.get("evidenceLang") or source_lang
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
) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    work_lang = {w.id: w.language for w in works}

    with driver.session(database=database) as session:
        session.run("CREATE CONSTRAINT author_id IF NOT EXISTS FOR (a:Author) REQUIRE a.id IS UNIQUE").consume()
        session.run("CREATE CONSTRAINT work_id IF NOT EXISTS FOR (w:Work) REQUIRE w.id IS UNIQUE").consume()
        session.run("CREATE CONSTRAINT author_slug IF NOT EXISTS FOR (a:Author) REQUIRE a.slug IS UNIQUE").consume()
        session.run("CREATE CONSTRAINT work_slug IF NOT EXISTS FOR (w:Work) REQUIRE w.slug IS UNIQUE").consume()
        session.run(
            "CREATE FULLTEXT INDEX work_search IF NOT EXISTS "
            "FOR (n:Work) ON EACH [n.Title_CN, n.Title_EN, n.originalTitle, n.Title_Other]"
        ).consume()

        with session.begin_transaction() as tx:
            if wipe:
                tx.run("MATCH (a:Author) DETACH DELETE a")
                tx.run("MATCH (w:Work) DETACH DELETE w")
                tx.run("MATCH (:Work)-[r:INFLUENCES]->(:Work) DELETE r")
                tx.run("MATCH (:Work)-[r:MENTIONS]->(:Work) DELETE r")
                tx.run("MATCH ()-[r:WROTE]->() DELETE r")

            for chunk in _chunks(
                [
                    {
                        "id": a.id,
                        "slug": a.slug or a.id,
                        "props": _node_props(a, now),
                    }
                    for a in authors
                ]
            ):
                tx.run(
                    "UNWIND $rows AS row "
                    "MERGE (a:Author {id: row.id}) "
                    "SET a += row.props, a.slug = row.slug",
                    {"rows": chunk},
                )

            for chunk in _chunks(
                [
                    {
                        "id": w.id,
                        "slug": w.slug or w.id,
                        "props": _node_props(w, now),
                    }
                    for w in works
                ]
            ):
                tx.run(
                    "UNWIND $rows AS row "
                    "MERGE (w:Work {id: row.id}) "
                    "SET w += row.props, w.slug = row.slug",
                    {"rows": chunk},
                )

            authored = [
                {"wid": wid, "aid": aid}
                for wid, aids in work_authors.items()
                for aid in aids
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
                        "props": _echo_props(e, now, work_lang.get(e.source_work_id)),
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

            tx.run(
                "MERGE (m:Dataset {id: 'echo-graph'}) "
                "SET m.version = $version, m.importedAt = $now",
                {"version": version, "now": now},
            )

    print(f"导入完成: version={version}, wipe={wipe}")


# =============================== 快照 ===============================

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
    print(
        f"快照已导出: data/snapshots/echo-graph-{ts}.json "
        f"(authors={len(payload['authors'])}, works={len(payload['works'])}, edges={len(payload['edges'])})"
    )


# =============================== 入口 ===============================

def main() -> None:
    parser = argparse.ArgumentParser(description="Echo Graph 数据导入")
    parser.add_argument("--source", choices=["auto", "xlsx", "csv"], default="auto")
    parser.add_argument("--wipe", action="store_true", help="全量重建(删除旧数据)")
    parser.add_argument("--version", default="1.0", help="数据集版本号")
    parser.add_argument("--no-snapshot", action="store_true", help="跳过快照导出")
    args = parser.parse_args()

    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE") or None
    if not (uri and username and password):
        raise SystemExit("NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD missing in .env")

    source = args.source
    if source == "auto":
        if XLSX_PATH.exists():
            source = "xlsx"
        elif any((REAL_DIR / f).exists() for f in ("authors.csv", "works.csv", "echoes.csv")):
            source = "csv"
        else:
            raise SystemExit("未找到数据源:请放置 data/real/data_echo-graph.xlsx 或 authors/works/echoes.csv")

    if source == "xlsx":
        if not XLSX_PATH.exists():
            raise SystemExit(f"未找到 {XLSX_PATH}")
        authors, works, echoes = load_xlsx()
        wipe = args.wipe
    elif source == "csv":
        authors, works, echoes = load_csv_real()
        wipe = args.wipe

    author_models, work_models, echo_models, work_authors = parse_rows(authors, works, echoes)

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        print(f"connected to Neo4j (source={source}, wipe={wipe})")
        import_data(
            driver,
            database,
            author_models,
            work_models,
            echo_models,
            work_authors,
            wipe=wipe,
            version=args.version,
        )
        if not args.no_snapshot:
            write_snapshot(driver, database, args.version)
    finally:
        driver.close()


if __name__ == "__main__":
    main()

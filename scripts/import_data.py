"""Import Echo Graph data into Neo4j.

数据源(按优先级):
  1. real:data/real/ 下的 authors.csv / works.csv / echoes.csv(真实数据,推荐)
  2. seed:data/seed.json(演示数据,回退)

特性:
  - Pydantic 校验(类型、枚举、交叉引用),校验失败不导入
  - 幂等导入:UNWIND 批量 MERGE + SET +=,可重复执行;默认不删除已有数据
  - --wipe:演示/开发用全量重建
  - 软删除:行中 deletedAt 非空则跳过
  - 导入后导出 JSON 快照到 data/snapshots/

用法:
  uv run python scripts/import_data.py
  uv run python scripts/import_data.py --source real --version 1.0
  uv run python scripts/import_data.py --source seed --wipe
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase
from pydantic import BaseModel, Field, field_validator, model_validator

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
REAL_DIR = ROOT / "data" / "real"
SEED_PATH = ROOT / "data" / "seed.json"
SNAPSHOT_DIR = ROOT / "data" / "snapshots"
CHUNK = 500

SLUG_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


# =============================== 校验模型 ===============================

class AuthorRow(BaseModel):
    model_config = {"extra": "ignore"}

    id: str = Field(min_length=1)
    originalName: str = Field(min_length=1)
    Name_CN: str
    Name_EN: str
    nationality: Optional[str] = None
    birthYear: Optional[int] = None
    deathYear: Optional[int] = None
    primaryLanguage: str = Field(min_length=2, max_length=3)
    bio: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    deletedAt: Optional[str] = None

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.fullmatch(v):
            raise ValueError(f"id 需为 slug 格式(字母/数字/下划线/连字符),got {v!r}")
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
    author_id: str = Field(min_length=1)
    language: str = Field(min_length=2, max_length=3)
    originalTitle: str = Field(min_length=1)
    Title_CN: str
    Title_EN: str
    publicationYear: Optional[int] = None
    creationYear: Optional[int] = None
    genre: Optional[str] = None
    summary: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    deletedAt: Optional[str] = None

    @field_validator("id", "author_id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.fullmatch(v):
            raise ValueError(f"id 需为 slug 格式,got {v!r}")
        return v

    @model_validator(mode="after")
    def _years(self) -> "WorkRow":
        if self.publicationYear is None and self.creationYear is None:
            raise ValueError(f"作品 {self.id} 需填写 publicationYear 或 creationYear 至少一个")
        return self


class EchoRow(BaseModel):
    model_config = {"extra": "ignore"}

    source_work_id: str = Field(min_length=1)
    target_work_id: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    evidenceSource: Optional[str] = None
    evidenceLang: Optional[str] = None
    note: Optional[str] = None
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reviewStatus: Literal["draft", "reviewed", "rejected"] = "draft"
    dataSource: Literal["manual", "auto", "nlp"] = "manual"
    reviewer: Optional[str] = None
    reviewedAt: Optional[str] = None
    source_url: Optional[str] = None
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
    return {k: (v.strip() if isinstance(v, str) else v) or None for k, v in raw.items()}


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as fh:
        return [_clean_row(r) for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]


def load_real() -> tuple[list[dict], list[dict], list[dict]]:
    return (
        _read_csv(REAL_DIR / "authors.csv"),
        _read_csv(REAL_DIR / "works.csv"),
        _read_csv(REAL_DIR / "echoes.csv"),
    )


def load_seed() -> tuple[list[dict], list[dict], list[dict]]:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    authors = [dict(a) for a in seed["authors"]]
    works = [dict(w) for w in seed["works"]]
    echoes = [
        {
            "source_work_id": e["source"],
            "target_work_id": e["target"],
            **{k: v for k, v in e.items() if k not in ("source", "target")},
        }
        for e in seed["edges"]
    ]
    return authors, works, echoes


# =============================== 校验 ===============================

def validate_rows(authors: list[dict], works: list[dict], echoes: list[dict]) -> None:
    errors: list[str] = []

    def check(rows: list[dict], model: type[BaseModel], label: str) -> list[BaseModel]:
        parsed: list[BaseModel] = []
        for i, row in enumerate(rows, start=2):  # 第 1 行为表头
            try:
                parsed.append(model.model_validate(row))
            except Exception as exc:  # noqa: BLE001 - 收集全部错误
                errors.append(f"{label} 第 {i} 行: {exc}")
        return parsed

    author_models = check(authors, AuthorRow, "authors.csv")
    work_models = check(works, WorkRow, "works.csv")
    echo_models = check(echoes, EchoRow, "echoes.csv")

    author_ids = {a.id for a in author_models}
    work_ids = {w.id for w in work_models}

    seen_a: set[str] = set()
    for a in author_models:
        if a.id in seen_a:
            errors.append(f"作者 id 重复:{a.id}")
        seen_a.add(a.id)
    seen_w: set[str] = set()
    for w in work_models:
        if w.id in seen_w:
            errors.append(f"作品 id 重复:{w.id}")
        seen_w.add(w.id)
        if w.author_id not in author_ids:
            errors.append(f"作品 {w.id} 引用了不存在的作者 {w.author_id}")

    seen_e: set[tuple[str, str]] = set()
    for e in echo_models:
        if e.source_work_id not in work_ids:
            errors.append(f"ECHO 引用了不存在的源作品 {e.source_work_id}")
        if e.target_work_id not in work_ids:
            errors.append(f"ECHO 引用了不存在的目标作品 {e.target_work_id}")
        key = (e.source_work_id, e.target_work_id)
        if key in seen_e:
            errors.append(f"ECHO 重复:{key[0]} -> {key[1]}")
        seen_e.add(key)

    if errors:
        raise SystemExit("校验失败,未导入:\n- " + "\n- ".join(errors[:60]))
    print(f"校验通过: authors={len(author_models)}, works={len(work_models)}, echoes={len(echo_models)}")


# =============================== 导入 ===============================

def _chunks(rows: list, size: int = CHUNK):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _node_props(row: BaseModel, now: str) -> dict:
    d = row.model_dump(exclude={"id", "deletedAt"})
    d["createdAt"] = d.get("createdAt") or now
    d["updatedAt"] = now
    return d


def _echo_props(row: EchoRow, now: str) -> dict:
    d = row.model_dump(exclude={"source_work_id", "target_work_id", "deletedAt"})
    d["createdAt"] = d.get("createdAt") or now
    d["updatedAt"] = now
    return d


def import_data(
    driver: GraphDatabase,
    database: Optional[str],
    authors: list[dict],
    works: list[dict],
    echoes: list[dict],
    *,
    wipe: bool,
    version: str,
) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    author_rows = [AuthorRow.model_validate(r) for r in authors]
    work_rows = [WorkRow.model_validate(r) for r in works]
    echo_rows = [EchoRow.model_validate(r) for r in echoes]

    with driver.session(database=database) as session:
        session.run("CREATE CONSTRAINT author_id IF NOT EXISTS FOR (a:Author) REQUIRE a.id IS UNIQUE").consume()
        session.run("CREATE CONSTRAINT work_id IF NOT EXISTS FOR (w:Work) REQUIRE w.id IS UNIQUE").consume()
        session.run("CREATE CONSTRAINT author_slug IF NOT EXISTS FOR (a:Author) REQUIRE a.slug IS UNIQUE").consume()
        session.run("CREATE CONSTRAINT work_slug IF NOT EXISTS FOR (w:Work) REQUIRE w.slug IS UNIQUE").consume()
        session.run(
            "CREATE FULLTEXT INDEX work_search IF NOT EXISTS "
            "FOR (n:Work) ON EACH [n.Title_CN, n.Title_EN, n.originalTitle, n.summary]"
        ).consume()

        with session.begin_transaction() as tx:
            if wipe:
                tx.run("MATCH (a:Author) DETACH DELETE a")
                tx.run("MATCH (w:Work) DETACH DELETE w")
                tx.run("MATCH (:Work)-[r:INFLUENCES]->(:Work) DELETE r")
                tx.run("MATCH (:Work)-[r:MENTIONS]->(:Work) DELETE r")
                tx.run("MATCH ()-[r:WROTE]->() DELETE r")

            for chunk in _chunks([{"id": r.id, "props": _node_props(r, now)} for r in author_rows]):
                tx.run(
                    "UNWIND $rows AS row "
                    "MERGE (a:Author {id: row.id}) "
                    "SET a += row.props",
                    {"rows": chunk},
                )

            for chunk in _chunks(
                [{"id": r.id, "author_id": r.author_id, "props": _node_props(r, now)} for r in work_rows]
            ):
                tx.run(
                    "UNWIND $rows AS row "
                    "MERGE (w:Work {id: row.id}) "
                    "SET w += row.props",
                    {"rows": chunk},
                )

            for chunk in _chunks([{"wid": r.id, "aid": r.author_id} for r in work_rows]):
                tx.run(
                    "UNWIND $rows AS row "
                    "MATCH (w:Work {id: row.wid}), (a:Author {id: row.aid}) "
                    "MERGE (w)-[:AUTHORED_BY]->(a)",
                    {"rows": chunk},
                )

            for chunk in _chunks(
                [
                    {
                        "source": r.source_work_id,
                        "target": r.target_work_id,
                        "props": _echo_props(r, now),
                    }
                    for r in echo_rows
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
        "edges": [
            {"source": r["source"], "target": r["target"], **r["p"]}
            for r in edges
        ],
    }
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    (SNAPSHOT_DIR / f"echo-graph-{ts}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SNAPSHOT_DIR / "echo-graph-latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"快照已导出: data/snapshots/echo-graph-{ts}.json "
          f"(authors={len(payload['authors'])}, works={len(payload['works'])}, edges={len(payload['edges'])})")


# =============================== 入口 ===============================

def main() -> None:
    parser = argparse.ArgumentParser(description="Echo Graph 数据导入")
    parser.add_argument("--source", choices=["auto", "real", "seed"], default="auto")
    parser.add_argument("--wipe", action="store_true", help="全量重建(演示/开发用)")
    parser.add_argument("--version", default="1.0", help="数据集版本号")
    parser.add_argument("--no-snapshot", action="store_true", help="跳过快照导出")
    args = parser.parse_args()

    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE") or None
    if not (uri and username and password):
        raise SystemExit("NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD missing in .env")

    real_exists = any((REAL_DIR / f).exists() for f in ("authors.csv", "works.csv", "echoes.csv"))
    source = args.source
    if source == "auto":
        source = "real" if real_exists else "seed"
    if source == "real" and not real_exists:
        raise SystemExit("未找到 data/real/*.csv,请先放置数据(可用 --source seed 导入演示数据)")

    if source == "real":
        authors, works, echoes = load_real()
        wipe = args.wipe
    else:
        authors, works, echoes = load_seed()
        wipe = True  # 演示数据默认全量重建

    validate_rows(authors, works, echoes)

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        print(f"connected to Neo4j (source={source}, wipe={wipe})")
        import_data(driver, database, authors, works, echoes, wipe=wipe, version=args.version)
        if not args.no_snapshot:
            write_snapshot(driver, database, args.version)
    finally:
        driver.close()


if __name__ == "__main__":
    main()

"""导出 JSON 兜底种子:从 data/real/*.csv 生成 data/seed.json。

JsonStore(Neo4j 不可用时的内存兜底)读取该文件;部署脚本在初始化/更新时
执行,保证线上 Neo4j 抖动或短暂不可用时站点不显示空图。

种子文件是派生产物(data/seed.json 已 gitignore),数据事实源为 SQLite(data/echo-graph.db);
导出前复用与导入相同的校验规则(parse_rows),校验失败则拒绝生成。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data_models import parse_rows
from app.sqlite_store import load_rows

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    authors_all, works_all, edges_all = load_rows()
    authors = [a for a in authors_all if not a.get("deletedAt")]
    works = [w for w in works_all if not w.get("deletedAt")]
    edges = [e for e in edges_all if not e.get("deletedAt")]
    parse_rows(authors, works, edges)  # 与导入同一套校验,失败则拒绝导出

    seed_edges = [
        {
            "id": e.get("id"),
            "source": e.get("source_work_id"),
            "target": e.get("target_work_id"),
            "evidence": e.get("evidence"),
            "evidenceSource": e.get("evidenceSource"),
            "note": e.get("note"),
            "reviewStatus": e.get("reviewStatus") or "draft",
        }
        for e in edges
    ]
    payload = {
        "meta": {
            "name": "echo-graph seed (from data/real CSV)",
            "exportedAt": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        },
        "authors": authors,
        "works": works,
        "edges": seed_edges,
    }
    out = ROOT / "data" / "seed.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {out}: authors={len(authors)}, works={len(works)}, edges={len(edges)}")


if __name__ == "__main__":
    main()

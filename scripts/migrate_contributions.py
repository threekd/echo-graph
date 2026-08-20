"""把旧 data/contributions.db 中的贡献行并入主库 data/echo-graph.db(幂等)。

旧库保留不删,作为备份;已存在的 id 不会重复写入。
用法: uv run python scripts/migrate_contributions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.contributions import merge_legacy_db  # noqa: E402

LEGACY_DB = Path(__file__).resolve().parent.parent / "data" / "contributions.db"


def main() -> None:
    if not LEGACY_DB.exists():
        print("未发现旧库 data/contributions.db,无需迁移")
        return
    merged = merge_legacy_db(LEGACY_DB)
    if not merged:
        print("旧库为空,无需迁移")
        return
    print(f"已并入 {merged} 条贡献(旧库保留为备份)")


if __name__ == "__main__":
    main()

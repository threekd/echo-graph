"""CSV -> SQLite 重建:data/export/*.csv -> data/echo-graph.db。

用途:CI 导出新鲜度门禁、全新 VPS 初始化引导。
⚠ 仅限全新环境:本脚本会整库重建策展表,已有用户数据时执行会清空用户星云
(日常部署不再从 CSV 重建,见 deploy/deploy.sh;contributions / audit_log 不受影响)。

用法:
  uv run python scripts/migrate_csv_to_sqlite.py                # 默认 data/echo-graph.db
  uv run python scripts/migrate_csv_to_sqlite.py --db <path>    # 指定库文件
  uv run python scripts/migrate_csv_to_sqlite.py --no-check     # 跳过往返一致性校验
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db_sqlite import DB_PATH  # noqa: E402
from app.sqlite_store import migrate_from_csv  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="把策展 CSV 迁移到 SQLite(整库重建)")
    parser.add_argument("--db", default=str(DB_PATH), help="目标 SQLite 库文件")
    parser.add_argument("--no-check", action="store_true", help="跳过迁移后的往返一致性校验")
    args = parser.parse_args()

    try:
        result = migrate_from_csv(args.db, check=not args.no_check)
    except ValueError as exc:
        raise SystemExit(f"CSV 校验失败,未迁移:\n- {exc}") from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    print(
        f"迁移完成 -> {args.db}\n"
        f"  authors={result['authors']}, works={result['works']}, "
        f"echoes={result['echoes']}, authored_links={result['authored_links']}"
    )


if __name__ == "__main__":
    main()

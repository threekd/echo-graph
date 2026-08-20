"""清理过期的审计日志(管理写操作记录)。

用法:
  uv run python scripts/prune_audit.py --days 90            # 删除 90 天前的审计记录
  uv run python scripts/prune_audit.py --days 90 --dry-run  # 只统计不删除
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.sqlite_store import prune_audit  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="清理过期审计日志")
    parser.add_argument("--days", type=int, default=90, help="保留最近 N 天(默认 90)")
    parser.add_argument("--dry-run", action="store_true", help="只统计将删除的行数,不实际删除")
    args = parser.parse_args()
    if args.days < 1:
        raise SystemExit("--days 必须 >= 1")
    count = prune_audit(days=args.days, dry_run=args.dry_run)
    verb = "将删除" if args.dry_run else "已删除"
    print(f"{verb} {count} 条早于 {args.days} 天的审计记录")


if __name__ == "__main__":
    main()

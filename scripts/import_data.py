"""命令行导入入口:委托 app.importer.run_import。

用法:
  uv run python scripts/import_data.py                      # 默认从 data/real/*.csv 导入(幂等)
  uv run python scripts/import_data.py --wipe --version 1.1  # 全量重建
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.importer import run_import


def main() -> None:
    parser = argparse.ArgumentParser(description="Echo Graph 数据导入")
    parser.add_argument("--source", choices=["csv"], default="csv")
    parser.add_argument("--wipe", action="store_true", help="全量重建(删除旧数据)")
    parser.add_argument("--version", default="1.0", help="数据集版本号")
    parser.add_argument("--no-snapshot", action="store_true", help="跳过快照导出")
    args = parser.parse_args()

    try:
        result = run_import(
            args.source,
            wipe=args.wipe,
            version=args.version,
            no_snapshot=args.no_snapshot,
        )
    except ValueError as exc:
        raise SystemExit(f"校验失败,未导入:\n- {exc}") from exc
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    print(
        f"导入完成: version={result['version']}, wipe={result['wipe']}, "
        f"authors={result['authors']}, works={result['works']}, "
        f"echoes={result['echoes']}, authored_links={result['authored_links']}"
    )


if __name__ == "__main__":
    main()

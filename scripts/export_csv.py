"""从 SQLite 重新生成 data/real/*.csv(确定性导出)。

用法:
  uv run python scripts/export_csv.py          # 覆盖 data/real/*.csv
  uv run python scripts/export_csv.py --check  # 导出到临时目录并逐字节比对(CI 门禁)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data_store import REAL_DIR, export_csv_files  # noqa: E402

FILES = ("authors.csv", "works.csv", "edges.csv")


def main() -> None:
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as td:
            export_csv_files(Path(td))
            mismatched = [
                name for name in FILES
                if (Path(td) / name).read_bytes() != (REAL_DIR / name).read_bytes()
            ]
        if mismatched:
            raise SystemExit("CSV 导出与仓库不一致,请运行 scripts/export_csv.py 后提交: " + ", ".join(mismatched))
        print("CSV 导出与仓库一致")
        return
    export_csv_files()
    print("CSV 已导出到 data/real/")


if __name__ == "__main__":
    main()

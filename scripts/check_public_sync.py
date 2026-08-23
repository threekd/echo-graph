"""本地库公共数据 ↔ 仓库 CSV 一致性检查(弥补 CI 盲区)。

背景:CI 的 export_csv.py --check 先"从 CSV 重建库再比对",只能证明 CSV 自洽,
无法发现某台机器的本地库与仓库 CSV 发生漂移(仓库 CSV 更新后本地库未同步)。
本脚本直接比对"本地库公共载荷(admin 空间 + 未认领行)"与"仓库 data/export/*.csv",
不一致时以非零码退出,适合作为开发机 / VPS 手动同步前的例行检查。

用法:
  uv run python scripts/check_public_sync.py           # 仅比对(不写任何文件)
  uv run python scripts/check_public_sync.py --apply   # 备份当前库后,从 CSV 合并公共数据

--apply 使用 replace_public_rows 只重建公共星云(admin 空间 + 未认领行),
用户私有空间原样保留;执行前自动创建整库快照(backups/echo-graph-<ts>.db)。
引导管理员未注册时拒绝执行(公共数据无法归属)。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import admin_user_id  # noqa: E402
from app.data_store import load_csv_rows  # noqa: E402
from app.sqlite_store import canonical_payload, list_all  # noqa: E402

KINDS = ("authors", "works", "edges")


def db_public_payload() -> dict:
    """本地库公共载荷:admin 认领的行 + 尚未认领的历史行。

    与 export_csv_files 同口径(list_all 已把 work_authors 重组回 works.author_id,
    保证 canonical_payload 与 CSV 侧的 works.author_id 可比)。
    """
    admin = admin_user_id()
    data = list_all()
    public = {
        key: [
            r for r in data[key]
            if not r.get("owner_id") or r["owner_id"] == admin
        ]
        for key in KINDS
    }
    return canonical_payload(public["authors"], public["works"], public["edges"])


def diff_summary(db_payload: dict, csv_payload: dict) -> str:
    lines: list[str] = []
    for table, key in (("作者", "authors"), ("作品", "works"), ("涟漪", "echoes")):
        db_ids = {r["id"] for r in db_payload[key]}
        csv_ids = {r["id"] for r in csv_payload[key]}
        lines.append(
            f"{table}: 库 {len(db_ids)} 条 / CSV {len(csv_ids)} 条"
            f"(仅库有 {len(db_ids - csv_ids)} 条,仅 CSV 有 {len(csv_ids - db_ids)} 条)"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="本地库公共数据 ↔ 仓库 CSV 一致性检查")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="备份当前库后,把仓库 CSV 的公共数据合并进本地库(用户空间保留)",
    )
    args = parser.parse_args()

    csv_a, csv_w, csv_e = load_csv_rows()
    csv_payload = canonical_payload(csv_a, csv_w, csv_e)
    db_payload = db_public_payload()

    if db_payload == csv_payload:
        print("OK:本地库公共数据与仓库 CSV 一致")
        return 0

    print("不一致:本地库公共数据与仓库 CSV 有差异。")
    print(diff_summary(db_payload, csv_payload))
    if not args.apply:
        print('如需以仓库 CSV 为准追平(仅公共星云,用户空间保留):uv run python scripts/check_public_sync.py --apply')
        return 1

    admin = admin_user_id()
    if admin is None:
        print("引导管理员未注册,无法执行合并(公共数据无法归属)。", file=sys.stderr)
        return 2

    from app.backups import create_snapshot
    from app.data_models import parse_rows
    from app.sqlite_store import replace_public_rows

    snapshot = create_snapshot()
    print(f"已备份当前库 -> {snapshot['name']}")
    models = parse_rows(csv_a, csv_w, csv_e)
    replace_public_rows(*models, owner_id=admin)

    again = db_public_payload()
    if again != csv_payload:
        print("合并后仍不一致,请人工检查。", file=sys.stderr)
        return 3
    print("已从 CSV 合并公共数据(用户空间保留),重新比对一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

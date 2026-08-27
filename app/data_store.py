"""数据清洗与用户空间 CSV 导出(zip)。

历史上 `data/export/*.csv` 曾作为自动导出 + git 审计/跨机器传输通道;
2026-08-27 起该备份层移除(多设备/调试导致漂移,改为整库备份,见 docs/to-do.md)。
本模块保留通用数据清洗(clean_row / remove_invisible_chars)与用户主动导出的
space_csv_zip()(数据管理页「导出 CSV」按钮,所有登录用户可用)。
"""

from __future__ import annotations

import csv
import io
import zipfile

from app import sqlite_store

# 导出表头与 sqlite_store 的列定义保持单一来源(works 额外在 Title_Other 后插入
# author_id;个人字段 readingStatus/recommendation/review 附加在末尾,
# 供用户导出自己的星云时保留个人语义)
AUTHOR_HEADER = sqlite_store.AUTHOR_COLS
WORK_HEADER = sqlite_store.WORK_COLS[:6] + ["author_id"] + sqlite_store.WORK_COLS[6:]
WORK_HEADER_EXPORT = WORK_HEADER + ["readingStatus", "recommendation", "review"]
EDGE_HEADER = sqlite_store.EDGE_COLS

# 不可见格式字符:网页复制文本常带入零宽空格(U+200B)等,录入时统一移除
INVISIBLE_CHARS = "\u200b\u200c\u200d\u2060\ufeff"  # 零宽空格/连接符/不换行零宽等


def remove_invisible_chars(value: str) -> str:
    """移除零宽空格等不可见格式字符,不触碰普通空格与换行。"""
    return value.translate(str.maketrans("", "", INVISIBLE_CHARS))


def clean_row(raw: dict) -> dict:
    """基础数据清洗:去首尾空白、移除零宽/不可见字符,空串归一为 None。所有落盘数据先过这里。"""
    out: dict = {}
    for k, v in raw.items():
        if isinstance(v, str):
            v = remove_invisible_chars(v).strip() or None
        out[k] = v
    return out


def _rows_to_csv(rows: list[dict], header: list[str]) -> str:
    """行列表 → CSV 文本(UTF-8 BOM,便于 Excel 直接打开;空值输出空串)。"""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({h: (r.get(h) if r.get(h) is not None else "") for h in header})
    return "\ufeff" + buf.getvalue()


def space_csv_zip(owner_id: str) -> io.BytesIO:
    """把某空间(与数据管理页同口径)的作者/作品/涟漪打包为 zip,返回 BytesIO。

    口径:仅该 owner 的行、排除 AI 草稿、含软删除行(deletedAt 列标注);
    不含 owner_id / created_by / published_to_id 等内部列。
    """
    a, w, e = sqlite_store.load_rows(owner_id=owner_id)

    def _not_ai_draft(r: dict) -> bool:
        return not (
            r.get("created_by") == "llm"
            and (r.get("reviewStatus") != "reviewed" or r.get("published_to_id"))
        )

    a = [r for r in a if _not_ai_draft(r)]
    w = [r for r in w if _not_ai_draft(r)]
    e = [r for r in e if _not_ai_draft(r)]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("authors.csv", _rows_to_csv(a, AUTHOR_HEADER))
        zf.writestr("works.csv", _rows_to_csv(w, WORK_HEADER_EXPORT))
        zf.writestr("edges.csv", _rows_to_csv(e, EDGE_HEADER))
    buf.seek(0)
    return buf

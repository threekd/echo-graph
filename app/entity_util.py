"""实体行公共工具:作者/作品/涟漪的 id 列表解析与展示名(单一来源)。

space_crud 与 llm_review 此前各自实现一份 `_author_id_list` / `_label`,
统一收敛到这里,避免同名逻辑漂移。
"""

from __future__ import annotations

from typing import Any


def author_id_list(value) -> list[str]:
    """把 works.author_id(逗号分隔,可能带空格)拆成去空后的 id 列表。"""
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def entity_label(kind: str, row: dict[str, Any]) -> str:
    """审计/展示用对象名称:作者中文名 / 作品中文名 / 涟漪 A → B(id 兜底)。"""
    if kind == "authors":
        return str(row.get("Name_CN") or row.get("originalName") or row.get("id") or "")
    if kind == "works":
        return str(row.get("Title_CN") or row.get("originalTitle") or row.get("id") or "")
    return f"{row.get('source_work_id')} → {row.get('target_work_id')}"

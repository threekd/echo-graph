"""共享数据模型与校验(对齐 data_schema.md 1.2)。

导入脚本与数据管理 API 共用本模块,保证校验规则单一来源。
"""

from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.data_store import remove_invisible_chars


def _coerce_review_status(v):
    """CSV 空值(None / 空串)统一视为 draft,显式值保持原样。"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return "draft"
    return v


def _coerce_int(v):
    """可选整数字段:空串视为 None(前端清空输入框会发送 '')。"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return v


def _strip_strings(v):
    """自由文本字段基础清洗:去首尾空白、移除零宽/不可见字符(内部空白与换行保留)。"""
    if isinstance(v, dict):
        return {k: (remove_invisible_chars(x).strip() if isinstance(x, str) else x) for k, x in v.items()}
    return v


class AuthorRow(BaseModel):
    model_config = {"extra": "ignore"}

    id: str = Field(min_length=1)
    originalName: str = Field(min_length=1)
    Name_CN: str = Field(min_length=1)
    Name_EN: str | None = None
    nationality: str | None = None
    birthYear: int | None = Field(default=None, ge=-9999, le=9999)
    deathYear: int | None = Field(default=None, ge=-9999, le=9999)
    note: str | None = None
    reviewStatus: Literal["draft", "reviewed", "rejected"] = "draft"
    readingStatus: Literal["read", "reading", "unread"] | None = None
    createdAt: str | None = None
    updatedAt: str | None = None
    deletedAt: str | None = None

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id 不能为空")
        try:
            uuid.UUID(v)
        except ValueError as exc:
            raise ValueError(f"id 需为 UUID 格式,got {v!r}") from exc
        return v

    @field_validator("reviewStatus", mode="before")
    @classmethod
    def _review_status_default(cls, v):
        return _coerce_review_status(v)

    @field_validator("birthYear", "deathYear", mode="before")
    @classmethod
    def _int_or_none(cls, v):
        return _coerce_int(v)

    @model_validator(mode="before")
    @classmethod
    def _trim_strings(cls, data):
        return _strip_strings(data)

    @field_validator("nationality")
    @classmethod
    def _nationality_ok(cls, v: str | None) -> str | None:
        if v is None or not str(v).strip():
            return None
        v = str(v).strip()
        if not re.fullmatch(r"[A-Za-z]{2}", v):
            raise ValueError(f"国籍需为 ISO 3166-1 alpha-2 代码(如 CN),got {v!r}")
        return v.upper()

    @model_validator(mode="after")
    def _years(self) -> AuthorRow:
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
    language: str = Field(min_length=2, max_length=3)
    originalTitle: str = Field(min_length=1, max_length=200)
    Title_CN: str = Field(min_length=1)
    Title_EN: str | None = None
    Title_Other: str | None = None
    author_id: str | None = None  # 作者 id(UUID),多人用逗号","隔开;按 id 关联,改名不再破坏
    publicationYear: int | None = None
    genre: Literal["Fiction", "Non-fiction", "Poetry", "Drama"] | None = None
    note: str | None = None
    reviewStatus: Literal["draft", "reviewed", "rejected"] = "draft"
    createdAt: str | None = None
    updatedAt: str | None = None
    deletedAt: str | None = None

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id 不能为空")
        try:
            uuid.UUID(v)
        except ValueError as exc:
            raise ValueError(f"id 需为 UUID 格式,got {v!r}") from exc
        return v

    @field_validator("language")
    @classmethod
    def _language_ok(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.fullmatch(r"[a-z]{2,3}", v):
            raise ValueError(f"语言需为 ISO 639-1/639-3 代码(如 zh、en、enm),got {v!r}")
        return v

    @field_validator("reviewStatus", mode="before")
    @classmethod
    def _review_status_default(cls, v):
        return _coerce_review_status(v)

    @field_validator("publicationYear", mode="before")
    @classmethod
    def _int_or_none(cls, v):
        return _coerce_int(v)

    @model_validator(mode="before")
    @classmethod
    def _trim_strings(cls, data):
        return _strip_strings(data)


class EchoRow(BaseModel):
    model_config = {"extra": "ignore"}

    id: str = Field(min_length=1)
    source_work_id: str = Field(min_length=1)
    target_work_id: str = Field(min_length=1)
    evidence: str = Field(min_length=1, max_length=2000)  # 与 DB CHECK length(evidence) <= 2000 对齐
    evidenceSource: str | None = None
    note: str | None = None
    reviewStatus: Literal["draft", "reviewed", "rejected"] = "draft"
    createdAt: str | None = None
    updatedAt: str | None = None
    deletedAt: str | None = None

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id 不能为空")
        try:
            uuid.UUID(v)
        except ValueError as exc:
            raise ValueError(f"id 需为 UUID 格式,got {v!r}") from exc
        return v

    @field_validator("reviewStatus", mode="before")
    @classmethod
    def _review_status_default(cls, v):
        return _coerce_review_status(v)

    @model_validator(mode="before")
    @classmethod
    def _trim_strings(cls, data):
        return _strip_strings(data)

    @model_validator(mode="after")
    def _no_self(self) -> EchoRow:
        if self.source_work_id == self.target_work_id:
            raise ValueError("ECHO 不允许自环(source == target)")
        return self

def parse_rows(
    authors: list[dict], works: list[dict], echoes: list[dict]
) -> tuple[list[AuthorRow], list[WorkRow], list[EchoRow], dict[str, list[str]]]:
    """校验并解析三张表,返回模型与 作品->作者id 映射;失败抛 ValueError。"""
    errors: list[str] = []

    def check(rows: list[dict], model: type[BaseModel], label: str) -> list[BaseModel]:
        parsed: list[BaseModel] = []
        for i, row in enumerate(rows, start=1):
            try:
                parsed.append(model.model_validate(row))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label} 第 {i} 条: {exc}")
        return parsed

    author_models: list[AuthorRow] = check(authors, AuthorRow, "作者")
    work_models: list[WorkRow] = check(works, WorkRow, "作品")
    echo_models: list[EchoRow] = check(echoes, EchoRow, "提及")

    author_ids: set[str] = {a.id for a in author_models}
    work_ids: set[str] = {w.id for w in work_models}
    work_title = {w.id: w.Title_CN for w in work_models}

    def dup(items: list, label: str, display=None) -> None:
        seen: set[str] = set()
        for it in items:
            if it in seen:
                errors.append(f"{label} 重复:{display(it) if display else it}")
            seen.add(it)

    dup([a.id for a in author_models], "作者 id")
    dup([w.id for w in work_models], "作品 id")
    dup([e.id for e in echo_models], "涟漪 id")
    dup(
        [(e.source_work_id, e.target_work_id) for e in echo_models],
        "涟漪对",
        lambda pair: f"{work_title.get(pair[0], pair[0])} -> {work_title.get(pair[1], pair[1])}",
    )

    work_authors: dict[str, list[str]] = {}
    for w in work_models:
        if w.author_id:
            for raw in w.author_id.split(","):
                aid = raw.strip()
                if not aid:
                    continue
                if aid not in author_ids:
                    errors.append(f"作品 {w.id} 的作者 id {aid} 未在作者表中找到")
                    continue
                work_authors.setdefault(w.id, []).append(aid)

    for e in echo_models:
        if e.source_work_id not in work_ids:
            errors.append(f"提及引用了不存在的源作品 {e.source_work_id}")
        if e.target_work_id not in work_ids:
            errors.append(f"提及引用了不存在的目标作品 {e.target_work_id}")

    if errors:
        raise ValueError("\n- ".join(errors))
    return author_models, work_models, echo_models, work_authors


def find_duplicates(
    authors: list[dict], works: list[dict], echoes: list[dict]
) -> dict[str, list[str]]:
    """非结构性重复报告(软提示):作者重名、作品标题重复、涟漪对重复。

    软删除行不计入;名称比较前 trim + casefold;同一行内(如原名列与中文名列相同)
    不视为重复。结构性重复(id、涟漪对)仍由 parse_rows / admin 硬拒绝。
    """

    def norm(v: object) -> str:
        return v.strip().casefold() if isinstance(v, str) else ""

    def collect(rows: list[dict], fields: tuple[str, ...]) -> list[str]:
        by_key: dict[str, tuple[str, str]] = {}  # 归一化键 -> (行 id, 原始展示串)
        dup: list[str] = []
        for r in rows:
            if r.get("deletedAt"):
                continue
            rid = str(r.get("id") or "")
            for f in fields:
                raw = r.get(f)
                key = norm(raw)
                if not key:
                    continue
                if key in by_key:
                    prev_rid, display = by_key[key]
                    if prev_rid != rid and display not in dup:
                        dup.append(display)
                else:
                    by_key[key] = (rid, str(raw).strip())
        return dup

    dup_pairs: list[str] = []
    seen_pairs: dict[tuple[str, str], str] = {}
    title_by_id = {str(w.get("id")): w.get("Title_CN") for w in works if w.get("id")}

    def work_label(work_id: str) -> str:
        return title_by_id.get(work_id) or work_id

    for r in echoes:
        if r.get("deletedAt"):
            continue
        s, t = r.get("source_work_id"), r.get("target_work_id")
        if not s or not t:
            continue
        pair = (str(s), str(t))
        display = f"{work_label(str(s))} -> {work_label(str(t))}"
        if pair in seen_pairs:
            if seen_pairs[pair] not in dup_pairs:
                dup_pairs.append(seen_pairs[pair])
        else:
            seen_pairs[pair] = display

    return {
        "duplicateAuthorNames": collect(authors, ("originalName", "Name_CN", "Name_EN")),
        "duplicateWorkTitles": collect(works, ("Title_CN", "originalTitle")),
        "duplicateEdgePairs": dup_pairs,
    }

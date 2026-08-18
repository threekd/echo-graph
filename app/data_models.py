"""共享数据模型与校验(对齐 data_schema.md 1.1)。

导入脚本与数据管理 API 共用本模块,保证校验规则单一来源。
"""

from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class AuthorRow(BaseModel):
    model_config = {"extra": "ignore"}

    id: str = Field(min_length=1)
    originalName: str = Field(min_length=1)
    Name_CN: str
    Name_EN: Optional[str] = None
    nationality: Optional[str] = None
    birthYear: Optional[int] = None
    deathYear: Optional[int] = None
    reviewStatus: Optional[Literal["draft", "reviewed", "rejected"]] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    deletedAt: Optional[str] = None

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

    @model_validator(mode="after")
    def _years(self) -> "AuthorRow":
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
    originalTitle: str = Field(min_length=1)
    Title_CN: str
    Title_EN: Optional[str] = None
    Title_Other: Optional[str] = None
    Author: Optional[str] = None  # 多人用逗号","隔开
    publicationYear: Optional[int] = None
    creationYear: Optional[int] = None
    genre: Optional[Literal["Fiction", "Non-fiction", "Poetry", "Drama"]] = None
    reviewStatus: Optional[Literal["draft", "reviewed", "rejected"]] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    deletedAt: Optional[str] = None

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


class EchoRow(BaseModel):
    model_config = {"extra": "ignore"}

    id: str = Field(min_length=1)
    source_work_id: str = Field(min_length=1)
    target_work_id: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    evidenceSource: Optional[str] = None
    evidenceLang: Optional[str] = None
    note: Optional[str] = None
    reviewStatus: Optional[Literal["draft", "reviewed", "rejected"]] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    deletedAt: Optional[str] = None

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

    @model_validator(mode="after")
    def _no_self(self) -> "EchoRow":
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

    author_by_name: dict[str, str] = {}
    for a in author_models:
        for key in (a.originalName, a.Name_CN, a.Name_EN):
            if key:
                author_by_name.setdefault(key.strip().lower(), a.id)

    author_ids: set[str] = {a.id for a in author_models}
    work_ids: set[str] = {w.id for w in work_models}

    def dup(items: list[str], label: str) -> None:
        seen: set[str] = set()
        for it in items:
            if it in seen:
                errors.append(f"{label} 重复:{it}")
            seen.add(it)

    dup([a.id for a in author_models], "作者 id")
    dup([w.id for w in work_models], "作品 id")
    dup([e.id for e in echo_models], "涟漪 id")

    work_authors: dict[str, list[str]] = {}
    for w in work_models:
        if w.Author:
            for raw in w.Author.split(","):
                name = raw.strip()
                if not name:
                    continue
                aid = author_by_name.get(name.lower())
                if not aid:
                    errors.append(f"作品 {w.id} 的作者 {name!r} 未在作者表中找到")
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

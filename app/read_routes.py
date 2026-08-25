"""只读六件套路由工厂:graph / search / work / expansion / path / stats。

`/api`(公共)、`/api/me`(个人空间)、`/api/space/{user_id}`(星际跃迁)三套端点
此前各自实现一份(参数校验与 404 处理逐行重复),统一收敛到本模块:
调用方只需提供 store 工厂与 owner 资料提供者,URL 前缀/鉴权语义由调用方决定。
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request

from app.db import SqliteStore

# 端点内部名:operationId / 路由名由 name_prefix + 下表派生,保证三套端点唯一
StoreFactory = Callable[[Request, str | None], SqliteStore]
OwnerProvider = Callable[[Request, str | None], dict | None] | None
GraphExtraProvider = Callable[[Request, str | None], dict] | None


def _user_id(request: Request) -> str | None:
    """星际跃迁路由的路径参数;非 user_id_path 路由下恒为 None。"""
    return request.path_params.get("user_id")


def register_read_routes(
    target: FastAPI | APIRouter,
    store_factory: StoreFactory,
    owner_provider: OwnerProvider = None,
    graph_extra: GraphExtraProvider = None,
    *,
    path_prefix: str = "",
    user_id_path: bool = False,
    name_prefix: str = "",
    tag: str | None = None,
) -> None:
    """注册只读六件套。

    target:FastAPI 实例或 APIRouter。
    path_prefix:目标完整前缀(FastAPI 实例用 /api;APIRouter 自带前缀时传空串)。
    user_id_path:为 True 时路径为 {prefix}/{{user_id}}/graph 等(星际跃迁)。
    store_factory(request, user_id) 每次请求调用;owner_provider(request, user_id)
    返回图谱附带的 owner 公开资料(公共星云 = 引导管理员,个人空间 = 本人,
    他人星云 = 目标用户),为 None 时图谱响应不附 owner 字段;graph_extra(request, user_id)
    返回并入图谱响应的顶层字段(星际跃迁需要 spaceId / displayName)。
    """
    def _path(tail: str) -> str:
        return path_prefix + ("/{user_id}" if user_id_path else "") + tail

    def _register(tail: str, name: str):
        op_id = f"{name_prefix}{name}"

        def deco(fn):
            fn.__name__ = op_id
            kwargs: dict = {"operation_id": op_id, "name": op_id}
            if tag:
                kwargs["tags"] = [tag]
            return target.get(_path(tail), **kwargs)(fn)

        return deco

    @_register("/graph", "graph")
    def graph(
        request: Request,
        status: str | None = Query(None, pattern="^(draft|reviewed|rejected)$"),
    ) -> dict:
        uid = _user_id(request)
        data = store_factory(request, uid).graph(status)
        owner = owner_provider(request, uid) if owner_provider else None
        if owner is not None:
            data["owner"] = owner
        extra = graph_extra(request, uid) if graph_extra else None
        if extra:
            data = {**data, **extra}
        return data

    @_register("/search", "search")
    def search(
        request: Request,
        q: str = Query(..., min_length=1),
        limit: int = Query(20, ge=1, le=50),
    ) -> dict:
        return {"hits": store_factory(request, _user_id(request)).search(q.strip(), limit)}

    @_register("/work/{work_id}", "work_detail")
    def work_detail(request: Request, work_id: str) -> dict:
        detail = store_factory(request, _user_id(request)).work_detail(work_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"work not found: {work_id}")
        return detail

    @_register("/expansion/{work_id}", "expansion")
    def expansion(
        request: Request,
        work_id: str,
        hops: int = Query(1, ge=1, description="向外扩散的级数(无上限,BFS 无更多节点时自动终止)"),
    ) -> dict:
        data = store_factory(request, _user_id(request)).expansion(work_id, hops)
        if data is None:
            raise HTTPException(status_code=404, detail=f"work not found: {work_id}")
        return data

    @_register("/stats", "stats")
    def stats(request: Request) -> dict:
        return store_factory(request, _user_id(request)).stats()

    @_register("/path", "path")
    def path(
        request: Request,
        frm: str = Query(..., alias="from", description="起点作品 id"),
        to: str = Query(..., description="终点作品 id"),
        max_hops: int = Query(15, ge=1, le=30),
    ) -> dict:
        result = store_factory(request, _user_id(request)).path(frm.strip(), to.strip(), max_hops)
        if result is None:
            raise HTTPException(status_code=404, detail="no mention path found")
        return result

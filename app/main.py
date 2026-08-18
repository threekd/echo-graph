"""Echo Graph API server."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.admin import router as admin_router
from app.db import get_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("echo_graph")

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Echo Graph API", version="0.2.0", description="世界文学提及图谱 API(演示)")

store = get_store()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/stats")
def stats() -> dict:
    return store.stats()


@app.get("/api/graph")
def graph() -> dict:
    return store.graph()


@app.get("/api/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)) -> dict:
    return {"hits": store.search(q.strip(), limit)}


@app.get("/api/work/{work_id}")
def work_detail(work_id: str) -> dict:
    detail = store.work_detail(work_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"work not found: {work_id}")
    return detail


@app.get("/api/expansion/{work_id}")
def expansion(
    work_id: str,
    hops: int = Query(1, ge=1, le=8, description="向外扩散的级数"),
) -> dict:
    data = store.expansion(work_id, hops)
    if data is None:
        raise HTTPException(status_code=404, detail=f"work not found: {work_id}")
    return data


@app.get("/api/path")
def path(
    frm: str = Query(..., alias="from", description="起点作品 id"),
    to: str = Query(..., description="终点作品 id"),
    max_hops: int = Query(15, ge=1, le=30),
) -> dict:
    result = store.path(frm.strip(), to.strip(), max_hops)
    if result is None:
        raise HTTPException(status_code=404, detail="no mention path found")
    return result


class NoCacheStaticFiles(StaticFiles):
    """静态文件总是重新校验,避免浏览器缓存旧版 JS/CSS 模块。"""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


app.mount("/static", NoCacheStaticFiles(directory=ROOT / "static"), name="static")
app.include_router(admin_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

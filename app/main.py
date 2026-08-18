"""Echo Graph API server."""

from __future__ import annotations

import logging
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from app.admin import router as admin_router
from app.db import get_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("echo_graph")

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"


def _app_version() -> str:
    """版本单一来源:pyproject.toml 的 [project].version。"""
    try:
        with (ROOT / "pyproject.toml").open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except Exception:  # noqa: BLE001 - 版本读取失败时回退
        return "0.0.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close = getattr(store, "close", None)
    if callable(close):
        close()


app = FastAPI(
    title="Echo Graph API",
    version=_app_version(),
    description="世界文学提及图谱 API(演示)",
    lifespan=lifespan,
)

store = get_store()


@app.get("/")
def index() -> FileResponse:
    # 需先构建 React 前端:cd frontend && pnpm build
    index_file = FRONTEND_DIST / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="前端未构建:请先运行 cd frontend && pnpm build")
    return FileResponse(index_file)


@app.get("/assets/{path:path}")
def frontend_assets(path: str) -> FileResponse:
    if (FRONTEND_DIST / "assets" / path).exists():
        return FileResponse(FRONTEND_DIST / "assets" / path)
    raise HTTPException(status_code=404, detail=f"asset not found: {path}")


@app.get("/vendor/{path:path}")
def frontend_vendor(path: str) -> FileResponse:
    if (FRONTEND_DIST / "vendor" / path).exists():
        return FileResponse(FRONTEND_DIST / "vendor" / path)
    raise HTTPException(status_code=404, detail=f"vendor file not found: {path}")


@app.get("/api/stats")
def stats() -> dict:
    return store.stats()


@app.get("/api/health")
def health() -> dict:
    """健康检查:返回当前存储后端与 Neo4j 回退次数。"""
    return {
        "status": "ok",
        "store": store.name,
        "fallbacks": getattr(store, "fallback_count", lambda: 0)(),
    }


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


app.include_router(admin_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

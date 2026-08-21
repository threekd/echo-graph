"""Litnebula API server."""

from __future__ import annotations

import logging
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from app.admin import router as admin_router
from app.auth import router as auth_router
from app.contributions import router as contributions_router
from app.db import get_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("echo_graph")

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"
STATIC_BASES = {
    "assets": FRONTEND_DIST / "assets",
    "root": FRONTEND_DIST,
}


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
    title="Litnebula API",
    version=_app_version(),
    description="回声图谱——世界文学的涟漪地图 API",
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


def _serve_static(kind: str, path: str) -> FileResponse:
    """安全地提供 frontend/dist 下的静态资源,拒绝路径穿越。"""
    base = STATIC_BASES[kind]
    if not path or ".." in Path(path).parts:
        raise HTTPException(status_code=404, detail=f"{kind} file not found: {path}")
    target = (base / path).resolve()
    if not target.is_relative_to(base.resolve()) or not target.is_file():
        raise HTTPException(status_code=404, detail=f"{kind} file not found: {path}")
    return FileResponse(target)


@app.get("/assets/{path:path}")
def frontend_assets(path: str) -> FileResponse:
    return _serve_static("assets", path)


@app.get("/favicon.svg")
def favicon_svg() -> FileResponse:
    return _serve_static("root", "favicon.svg")


@app.get("/favicon-32x32.png")
def favicon_png_32() -> FileResponse:
    return _serve_static("root", "favicon-32x32.png")


@app.get("/apple-touch-icon.png")
def apple_touch_icon() -> FileResponse:
    return _serve_static("root", "apple-touch-icon.png")


@app.get("/api/stats")
def stats() -> dict:
    return store.stats()


@app.get("/api/health")
def health() -> dict:
    """健康检查:返回当前存储后端(SQLite)。"""
    return {"status": "ok", "store": store.name}


@app.get("/api/graph")
def graph(
    status: str | None = Query(None, pattern="^(draft|reviewed|rejected)$"),
) -> dict:
    return store.graph(status)


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
    hops: int = Query(1, ge=1, description="向外扩散的级数(无上限,BFS 无更多节点时自动终止)"),
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
app.include_router(contributions_router)
app.include_router(auth_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

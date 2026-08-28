"""Litnebula API server."""

from __future__ import annotations

import logging
import os
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app import mailer
from app.admin import router as admin_router
from app.auth import bootstrap_admin
from app.auth import router as auth_router
from app.book_import import IMPORT_DIR
from app.book_import import router as book_import_router
from app.follows import router as follows_router
from app.llm_account import migrate_legacy_llm_drafts
from app.llm_review import router as llm_review_router
from app.me import router as me_router
from app.security import is_state_changing, same_origin_allowed
from app.space import router as space_router

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
    # 启动引导:ADMIN_BOOTSTRAP_EMAIL 已注册则补 admin 角色
    bootstrap_admin()
    # 旧 system_llm 共享草稿一次性改挂到引导管理员(GET 端点保持只读,迁移只在启动执行)
    migrate_legacy_llm_drafts()
    try:
        IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error(
            "书籍导入上传目录不可写(IMPORT_DIR=%s):%s,AI 书籍导入将失败",
            IMPORT_DIR,
            exc,
        )
    if os.getenv("COOKIE_SECURE", "").strip().lower() not in ("1", "true", "yes", "on"):
        logger.warning(
            "COOKIE_SECURE 未开启:会话 Cookie 允许经非 HTTPS 连接传输,"
            "生产环境必须设 COOKIE_SECURE=1"
        )
    if mailer.mailer_configured():
        logger.info("邮件服务已配置:MAILER=%s", mailer.mailer_mode())
    else:
        logger.warning(
            "邮件服务未配置(MAILER=log 仅本地开发):邮箱验证/密码重置功能"
            "在生产环境将无法送达;开启 EMAIL_VERIFY_REQUIRED=1 时新注册会被拒绝"
        )
    if (
        os.getenv("EMAIL_VERIFY_REQUIRED", "").strip().lower() in ("1", "true", "yes", "on")
        and not mailer.mailer_configured()
    ):
        logger.error(
            "EMAIL_VERIFY_REQUIRED=1 但邮件服务未配置:新用户注册将全部失败(fail-closed),"
            "请先完成 DirectMail/SMTP 配置"
        )
    yield
    # SQLite 存储无连接池,关闭阶段无需清理(SqliteStore.close 为 no-op)


app = FastAPI(
    title="Litnebula API",
    version=_app_version(),
    description="回声图谱——世界文学的涟漪地图 API",
    lifespan=lifespan,
)


@app.middleware("http")
async def csrf_same_origin_guard(request: Request, call_next):
    """全局 CSRF 同源校验:所有状态变更请求(POST/PUT/PATCH/DELETE)带 Origin 头时
    必须与本站同源,否则 403。覆盖 /api/auth、/api/me、/api/admin 全部写接口。"""
    if is_state_changing(request.method) and not same_origin_allowed(request):
        return JSONResponse(status_code=403, content={"detail": "跨站请求被拒绝"})
    return await call_next(request)


@app.middleware("http")
async def no_store_api_responses(request: Request, call_next):
    """API 响应禁止缓存:登录态接口可能返回用户数据(共享设备场景),避免被浏览器/代理缓存。"""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


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


@app.get("/api/health")
def health() -> dict:
    """健康检查:返回当前存储后端(SQLite)。"""
    return {"status": "ok", "store": "sqlite"}


app.include_router(book_import_router)
app.include_router(admin_router)
app.include_router(llm_review_router)
app.include_router(auth_router)
app.include_router(follows_router)
app.include_router(me_router)
app.include_router(space_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


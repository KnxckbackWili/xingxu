"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import config
from app.access import public, validate_routes
from app.db import get_db, init_db
from app.middleware import HTTPSOnlyMiddleware, StaticAssetCompressionMiddleware, TrustedHostsMiddleware
from app.routers import (auth, excel, files, history, projects, records, system, system_updates, templates, users)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate_public_mode()
    validate_routes(app)
    init_db()
    yield


app = FastAPI(
    title="行序",
    description="AGV 实施项目的记录与查看",
    version=config.APP_VERSION,
    lifespan=lifespan,
)

# The deployed SPA is same-origin. Explicit origins can be enabled for a
# separate development client without opening every browser origin by default.
if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.add_middleware(StaticAssetCompressionMiddleware)
if config.FORCE_HTTPS:
    app.add_middleware(HTTPSOnlyMiddleware)
if config.TRUSTED_HOSTS != ["*"]:
    # HYPE-24: 自研中间件在保留 Starlette 精确/子域语义的同时支持 IP 网段（CIDR），
    # 使 TRUSTED_HOSTS 能表达"整个局域网网段"，避免 DHCP 换 IP/新增网卡/反代域名
    # 导致的合法访问被 400 Invalid host header 拒绝。Host 校验不放开。
    app.add_middleware(TrustedHostsMiddleware, allowed_hosts=config.TRUSTED_HOSTS)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/api/") and "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(self), microphone=(), geolocation=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
        "worker-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    if config.FORCE_HTTPS:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.middleware("http")
async def csrf_protection(request, call_next):
    """CSRF 双提交校验（P2-安全）：cookie 认证的写请求必须携带 X-CSRF-Token。

    Bearer 认证（API 客户端/旧会话）免疫；无 access cookie 的公开端点跳过。
    校验失败返回 403，不进入路由。
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        # 登录/刷新是「建立会话」的端点，豁免 CSRF：
        # - login 天然免疫（攻击者无从得知口令），且登录时可能已有残留 access
        #   cookie，强制 CSRF 会造成「已有会话无法重新登录」的鸡生蛋问题；
        # - refresh 只换发令牌不改变业务状态，且 refresh cookie 已 HttpOnly +
        #   path=/api/auth/refresh + SameSite=Lax，跨站 POST 不会携带该 cookie。
        if request.url.path in ("/api/auth/login", "/api/auth/refresh"):
            return await call_next(request)
        from app.services.cookies import verify_csrf

        try:
            verify_csrf(request)
        except Exception as exc:  # HTTPException(403)
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=403,
                content={
                    "detail": getattr(exc, "detail", "CSRF 校验失败，请刷新页面后重试")
                },
            )
    return await call_next(request)


# API routes. Fixed paths are registered before the generic /projects/{id}/{kind} ones.
for module in (auth, users, projects, files, excel, templates, history, system, system_updates, records):
    app.include_router(module.router, prefix="/api")


@app.middleware("http")
async def update_maintenance(request, call_next):
    # A newly started image must not accept business writes before its health
    # and revision are verified. The host bridge does not use HTTP.
    if request.url.path.startswith("/api/"):
        allowed_read = request.method == "GET" and request.url.path in {
            "/api/auth/me",
            "/api/system/updates",
        }
        if not allowed_read:
            from app.services.system_updates import is_maintenance

            if is_maintenance():
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=503,
                    headers={"Retry-After": "10"},
                    content={
                        "detail": "系统正在更新维护，暂时无法操作；请稍后重试，保留当前输入",
                        "maintenance": True,
                    },
                )
    return await call_next(request)




@app.get("/health")
@public("健康检查：不带凭据，只执行 SELECT 1")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": config.APP_VERSION}


@app.api_route(
    "/api/{missing_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
@public("未知接口一律 404，不做任何事")
def missing_api(missing_path: str):
    from fastapi import HTTPException

    raise HTTPException(404, "接口不存在")


# Serve frontend static files (SPA) with proper fallback.
# StaticFiles' html=True only falls back to index.html for *existing* paths,
# so deep links like /pm/people 404 on refresh. We serve manually:
#   - real files (assets, sw.js, manifest) → the file
#   - everything else (SPA routes)         → index.html
# Layout differs dev vs container:
#   dev:       <project>/backend/app/main.py → <project>/frontend/dist
#   container: /app/app/main.py             → /app/frontend/dist
_BASE = Path(__file__).resolve().parent.parent  # backend dir (dev) or /app (container)
FRONTEND_DIST = _BASE.parent / "frontend" / "dist"
if not FRONTEND_DIST.exists():
    FRONTEND_DIST = _BASE / "frontend" / "dist"


def _safe_frontend_file(full_path: str) -> Optional[Path]:
    """Resolve a requested asset without allowing it to escape dist/."""
    root = FRONTEND_DIST.resolve()
    candidate = (root / full_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


if FRONTEND_DIST.exists():
    from fastapi.responses import FileResponse, JSONResponse

    # index.html must never be cached: a stale cached HTML references old
    # hashed bundles that no longer exist after a redeploy → white screen.
    def _spa_response(path: Path, cache_control: Optional[str] = None):
        return FileResponse(
            path,
            headers={"Cache-Control": cache_control} if cache_control else None,
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # API 404s stay JSON (this only catches routes the API didn't match)
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "接口不存在"}, status_code=404)
        candidate = _safe_frontend_file(full_path)
        if candidate is not None:
            relative = candidate.relative_to(FRONTEND_DIST.resolve())
            if relative.parts and relative.parts[0] == "assets":
                return _spa_response(candidate, "public, max-age=31536000, immutable")
            # Service worker, manifest and fixed-name icons must revalidate.
            return _spa_response(candidate, "no-cache")
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            # Never cache the app shell
            return _spa_response(index, "no-store")
        return JSONResponse({"detail": "Not Found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)  # nosec B104

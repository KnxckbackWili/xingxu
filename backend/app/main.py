"""FastAPI application entry point."""

import os
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission_exempt
from app.db import get_db, init_db
from app import config
from app.routers import system_updates
from app.middleware import TrustedHostsMiddleware, StaticAssetCompressionMiddleware, HTTPSOnlyMiddleware
from app.routers import (
    external_shares,
    project_recycle_bin,
    permissions,
    agent,
    auth,
    users,
    projects,
    project_events,
    project_documents,
    uploads,
    storage,
    logs,
    templates,
    document_requirements,
    tasks,
    work_items,
    schedules,
    worker,
    progress,
    issues,
    io_routes,
    ai_projects,
    ai_internal,
    attachments,
    notifications,
    dashboard,
    reports,
    insights,
    preparations,
    vehicle_lifecycle,
    vehicle_progress,
    inventory,
    system,
    archives,
    report_forms,
    availability,
    notification_channels,
    vehicle_types,
    holiday_calendars,
    feedback,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate_public_mode()
    from app.services.system_permissions import validate_route_permissions

    validate_route_permissions(app)
    init_db()
    # Recover a crash during an explicit cleanup even on installations that
    # run their scheduler in a separate process.
    from app.db import SessionLocal
    from app.services.storage_maintenance import maintain_storage
    with SessionLocal() as maintenance:
        maintain_storage(maintenance)
        maintenance.commit()
    # 定时报告调度器（SCHEDULER_ENABLED=1 时启动；测试/本地默认关）
    scheduler = None
    if config.SCHEDULER_ENABLED:
        from app.services.report_scheduler import start_scheduler

        scheduler = start_scheduler()
    app.state.scheduler = scheduler

    # Mounted ASGI applications do not receive the parent lifespan automatically.
    from app.services.ai_mcp import agent_mcp_lifespan

    try:
        async with agent_mcp_lifespan():
            yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(
    title="行序 · 项目工作台",
    description="面向小型 AGV 实施团队的项目管理工具",
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
    if request.url.path.startswith(("/api/projects", "/api/dashboard", "/api/worker", "/api/people")):
        response.headers["Cache-Control"]="private, no-store"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer" if request.url.path.startswith(("/external", "/api/external")) else "same-origin"
    if request.url.path.startswith(("/api/external/", "/api/agent/", "/api/ai/internal/", "/api/ai/mcp", "/api/ai-projects/")) or "/external-shares" in request.url.path:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
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
        # MFA public steps authenticate with an audience/purpose-bound signed
        # challenge in the JSON body, never with the ambient business Cookie.
        if request.url.path == "/api/external/bootstrap" or request.url.path in ("/api/auth/login", "/api/auth/refresh", "/api/auth/2fa/verify", "/api/auth/2fa/enroll/start", "/api/auth/2fa/enroll/confirm", "/api/auth/2fa/recover/start", "/api/auth/2fa/cancel"):
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


# API routes
app.include_router(auth.router, prefix="/api")
app.include_router(external_shares.router, prefix="/api")
app.include_router(external_shares.external_router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(permissions.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(project_events.router, prefix="/api")
app.include_router(project_documents.router, prefix="/api")
app.include_router(uploads.router,prefix='/api')
app.include_router(storage.router,prefix='/api')
app.include_router(project_recycle_bin.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(document_requirements.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(work_items.router, prefix="/api")
app.include_router(schedules.router, prefix="/api")
from app.routers import field_week, weekly_plans
app.include_router(field_week.router, prefix="/api")
app.include_router(weekly_plans.router, prefix="/api")
app.include_router(worker.router, prefix="/api")
app.include_router(progress.router, prefix="/api")
app.include_router(issues.router, prefix="/api")
app.include_router(io_routes.router, prefix="/api")
app.include_router(ai_projects.router, prefix="/api")
app.include_router(attachments.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(preparations.router, prefix="/api")
app.include_router(vehicle_lifecycle.router, prefix="/api")
app.include_router(vehicle_progress.router, prefix="/api")
app.include_router(inventory.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(system_updates.router, prefix="/api")
app.include_router(ai_internal.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(archives.router, prefix="/api")
app.include_router(report_forms.router, prefix="/api")
app.include_router(availability.router, prefix="/api")
app.include_router(notification_channels.router, prefix="/api")
app.include_router(vehicle_types.router, prefix="/api")
app.include_router(holiday_calendars.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")


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


# Internal AI access: Model Context Protocol endpoint for Claude Desktop/Dify/etc.
from app.services.ai_mcp import mcp_http_app  # noqa: E402

app.mount("/api/ai/mcp", mcp_http_app)


@app.get("/health")
@route_permission_exempt('无凭据健康检查，只执行数据库SELECT 1')
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": config.APP_VERSION}


@app.api_route(
    "/api/{missing_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
@route_permission_exempt('未知接口统一返回404，不执行业务操作')
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

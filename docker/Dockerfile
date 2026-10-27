# Build the frontend from the lockfile so a clean checkout is deployable.
FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --global npm@11.6.0 \
    && npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Single runtime container: FastAPI serves the compiled React application.
# A1/A2：容器内由 supervisord 托管 postgres / web / scheduler，
# USE_POSTGRES=1 时启用容器内 PostgreSQL（单容器架构，不额外起容器）。
FROM python:3.12-slim-trixie
ARG APP_VERSION=3.0.0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    APP_VERSION=${APP_VERSION}
LABEL org.opencontainers.image.title="AGV Project Management" \
      org.opencontainers.image.version="${APP_VERSION}"

WORKDIR /app

# 固定 Debian 发行版与 PostgreSQL 主版本，更新镜像时继续兼容现有 PGDATA。
# A1：容器内 PostgreSQL（USE_POSTGRES=1 时由 supervisord 托管）。
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.lock.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && pip check
# 启动依赖须在构建时可导入，避免镜像构建成功但 supervisord 无法启动。
RUN python -c "import supervisor.options; from apscheduler.schedulers.background import BackgroundScheduler"

COPY backend/app ./app
COPY docker/scripts/backup_runtime.py ./backup_runtime.py
# Alembic 迁移脚本与配置：init_db 启动时 _alembic_sync_schema() 依赖
# /app/alembic.ini 与 /app/migrations（upgrade head），必须随镜像打包。
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY skills ./skills
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist
COPY docker/start.sh /app/start.sh
COPY docker/supervisord.conf /app/supervisord.conf
COPY docker/pg-entry.sh /app/pg-entry.sh
# 安全解包的源码入口为 0700/0600；仅 +x 会留下 0711，postgres 无法读取 shell 脚本。
RUN chmod 0755 /app/start.sh /app/pg-entry.sh

# 构建来源 git 短 SHA：ARG 声明放这里（紧贴 ENV/LABEL 使用处）。
# 若声明放顶部，其值会进入下一个 ENV 层的缓存键，GIT_SHA 每次变化都会
# 重建 apt/pip/前端等昂贵层；放末尾则仅最后一个 ENV/LABEL 层变化。
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
LABEL org.opencontainers.image.revision="${GIT_SHA}"

ENV WEB_CONCURRENCY=2 \
    AGVPM_ENABLE_CACHE=1 \
    # T024：FORWARDED_ALLOW_IPS 默认不信任任意来源（空 → uvicorn 仅回环 127.0.0.1 可信，
    # 见 supervisord.conf）；NPM 反代场景由 compose/.env 显式配置为可信地址/网段。
    FORWARDED_ALLOW_IPS= \
    # 兜底：即使宿主/运行时注入代理环境变量，也不影响容器内自环与对外直连。
    NO_PROXY=* \
    no_proxy=*

EXPOSE 8000

CMD ["/app/start.sh"]

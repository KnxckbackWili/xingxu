# AGV 项目管理系统 — 8002 单容器一键部署（Multica 正式部署）
# 统一入口：docker/scripts/deploy.sh（首次 + 二次部署，健康检查 + 失败自动回滚）。
# 用法：
#   make deploy   首次部署（构建镜像并启动单容器到 8002，PostgreSQL 在容器内）
#   make update   二次部署（更新到当前代码：自动备份 → 重建 → 健康检查 → 失败自动回滚）
#   make stop     停止
#   make logs     跟踪日志
#   make ps       状态
#   make status   健康检查
#   make backup   全量备份（pg_dump / sqlite backup）+ 旧包轮转
#   make restore  恢复备份：make restore BACKUP=backups/agv-pm-xxx.tar.gz
#                 （恢复前 SHA-256 校验；无校验文件的旧备份需 SKIP_SHA_CHECK=1）
#   make rollback 回滚到上一次 update 前的镜像
# 需要配置的变量极少，写入 docker/.env（见 docker/.env.example）即可；二次部署通常无需改动任何变量。
# 定时备份（cron 示例，每天 03:17 备份）：
#   17 3 * * * cd /path/to/agv-pm && make backup >> backups/cron.log 2>&1

COMPOSE_FILE ?= docker/docker-compose.multica.yml
APP_PORT ?= 8002
BACKUP ?=
# 备份轮转（docs/deployment.md:246）：日备保留 / 月备保留 / pre-restore 快照保留，均可配置。
BACKUP_KEEP_DAILY ?= 30
BACKUP_KEEP_MONTHLY ?= 12
BACKUP_KEEP_PRE_RESTORE ?= 20

.PHONY: deploy update stop logs ps status backup restore rollback

deploy:
	bash docker/scripts/deploy.sh install

update:
	bash docker/scripts/deploy.sh update

stop:
	docker compose -f $(COMPOSE_FILE) down

logs:
	docker compose -f $(COMPOSE_FILE) logs -f --tail=200

ps:
	docker compose -f $(COMPOSE_FILE) ps

status:
	bash docker/scripts/deploy.sh status

backup:
	BACKUP_KEEP_DAILY="$(BACKUP_KEEP_DAILY)" BACKUP_KEEP_MONTHLY="$(BACKUP_KEEP_MONTHLY)" BACKUP_KEEP_PRE_RESTORE="$(BACKUP_KEEP_PRE_RESTORE)" \
	bash docker/scripts/deploy.sh backup

restore:
	BACKUP_KEEP_PRE_RESTORE="$(BACKUP_KEEP_PRE_RESTORE)" \
	bash docker/scripts/deploy.sh restore "$(BACKUP)"

rollback:
	bash docker/scripts/deploy.sh rollback

# 7001 独立实例部署

- 容器：`agv-pm-7001`，镜像：`agv-pm:7001`。
- 端口：`0.0.0.0:7001` 转发到容器 `8000`。
- 数据：外部 Docker volume `agv-pm-7001-data`，挂载至容器 `/app/data`，不复用 8002 数据。原 `data/7001` 已退出运行，仅保留历史快照与故障恢复证据。
- 运行方式：SQLite、单 Web worker、独立后台调度器，自动重启与健康检查。
- 实际环境文件：`docker/.env.7001`（含初始密码，不提交 Git）。
- 本机登录资料：`.secrets/deployment-7001.txt`（权限 600，不提交 Git，也不进入镜像构建上下文）。

## Nginx Proxy Manager

| 设置 | 值 |
|---|---|
| Domain Names | `agv.arrowwood.top` |
| Scheme | `http` |
| Forward Hostname / IP | `192.168.1.136` |
| Forward Port | `7001` |
| Websockets Support | 开启 |
| SSL | 为该域名配置证书，启用 HTTPS |

对外入口为 `https://agv.arrowwood.top:8773`。8773 是外部 HTTPS 入口端口，NPM 上游仍填写 7001。

应用已设置 `COOKIE_SECURE=1`；使用域名 HTTPS 登录。内网 HTTP 地址可用于健康检查，但不用于浏览器会话登录。

可信 Host 包含该域名、本机 IP 和回环地址。`FORWARDED_ALLOW_IPS` 暂留空，待确认 NPM 的实际来源 IP 后填写精确地址，避免信任任意客户端伪造的代理头。

## 启动与更新

在仓库根目录执行（Docker Compose 需支持 `!override`）。首次部署须先准备外部卷并导入数据；卷不存在时 Compose 会拒绝启动。已有部署直接更新，不要重建空卷：

```bash
docker compose --env-file docker/.env.7001 \
  -f docker/docker-compose.yml -f docker/docker-compose.7001.yml \
  -p agv-pm-7001 up -d --build
```

```bash
curl http://127.0.0.1:7001/health
docker inspect agv-pm-7001 --format '{{.State.Health.Status}}'
docker exec -i agv-pm-7001 python - < docker/scripts/verify_live_reads.py
```

首次初始化仅创建 `admin`，初始密码存于本机登录资料文件。未迁移 8002 的账号或项目。

读接口验收脚本检查现有管理员 / 项目经理的页面数据，并对非空申请列表并发重复读取；空列表会明确提示未覆盖本次故障。它不替代浏览器操作与隔离副本的写入流程验证。日志不输出凭据或响应正文。

**数据库操作必须在容器内执行。** 禁止用 macOS SQLite 直接打开运行中的数据库。备份使用 `AGV_CONTAINER=agv-pm-7001 BACKUP_DIR=/absolute/backup/path bash docker/scripts/backup.sh`；宿主机只能检查已导出的离线备份。

2026-09-17 已修复申请列表间歇性 500，并完成数据库存储迁移。此前的单次健康检查与宿主机数据库核对未覆盖真实运行状态；原因、恢复方法与验收范围见 [故障记录](retired-features.md)。

## 本次部署修复

- 重新拉取官方 Python 3.12 与 Node 20 基础镜像，纠正本机已有镜像标签与实际版本不一致的问题。
- 为 Supervisor 4.2.5 固定 `setuptools==80.9.0`，并在 Docker 构建阶段验证进程管理器与调度器可导入。新版 setuptools 已移除旧接口，参见 [setuptools 官方记录](https://github.com/pypa/setuptools/issues/5174)。
- SQLite 启动配置停用 PostgreSQL 子进程，兼容容器的最小权限设置。

## 2026-09-16 验证

## 2026-09-16 Agent 与性能版本复核

应用代码提交：`856ce2a7519195cf63ad379087ea52df0c24f6e5`。7001健康，本机 / 内网 / 外网域名的首页与静态资源均通过。主脚本gzip传输约193KB（原始约577KB），前端新配色与版本资源在浏览器中确认加载。数据库备份完成，部署后完整性与数据数量一致；8002启动时间未变化。

外部助手从「系统 → Agent 接口」配置；具体参数与权限见 [接入文档](ai-internal-api.md)。性能对比与验证范围见 [本次改动记录](agent-interface-performance-2026-09-16.md)。

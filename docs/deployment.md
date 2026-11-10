# 部署指南（NAS / 服务器）

> 本文引用的 QA 回执描述历史时点，原件已归档；当前 v3 操作请从[文档入口](index.md)开始。

## 公网部署必改清单（T10）

公网访问必须显式启用 `PUBLIC_MODE=1`。内网 HTTP 可继续使用 `PUBLIC_MODE=0` 和原有配置。公网模式会在容器启动任何服务之前、以及应用初始化数据库之前检查以下四项；不满足时明确报错并停止：

- `COOKIE_SECURE=1`：所有会话 Cookie 带 `Secure`。
- `FORCE_HTTPS=1`：业务 HTTP 请求重定向到 HTTPS，HTTPS 响应包含 HSTS。
- `TRUSTED_HOSTS`：明确列出访问域名/IP；禁止 `*`（即使混在列表内）、空条目和全地址网段。
- `FORWARDED_ALLOW_IPS`：明确列出真正代理到应用的 IP 或有限 CIDR；禁止空值、`*`、`0.0.0.0/0`、`::/0` 和非法地址。推荐固定代理 IP，专用 Docker 网段也可使用；不要把普通访问者所在网段当作可信代理。

SQLite 部署编辑根 `.env`；8002 PostgreSQL 部署编辑 `docker/.env`。示例假定 Nginx 容器在专用网络中的固定地址为 `172.20.0.5`，并可直接访问同网络应用名 `agv-pm:8000`：

```dotenv
PUBLIC_MODE=1
COOKIE_SECURE=1
FORCE_HTTPS=1
TRUSTED_HOSTS=agv.example.com,127.0.0.1,localhost
FORWARDED_ALLOW_IPS=172.20.0.5
BIND_ADDRESS=127.0.0.1
SEED_DEMO_USERS=0
```

代理地址以**应用实际看到的连接对端**为准；宿主机反代经 Docker 端口转发时可能是网桥网关，不能凭域名、外部客户 IP 或 Nginx 页面地址猜测。仅开放 HTTPS 入口，应用 8000/8002 端口绑定回环或由防火墙限制为代理可访问。`TRUSTED_HOSTS` 中的回环地址用于容器健康检查，不会允许其他业务请求绕过 HTTPS。

Nginx HTTPS 示例（替换域名和证书路径；代理与应用须在上述同一网络）：

```nginx
server {
    listen 80;
    server_name agv.example.com;
    return 308 https://agv.example.com$request_uri;
}
server {
    listen 443 ssl;
    server_name agv.example.com;
    ssl_certificate /etc/nginx/certs/agv.example.com/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/agv.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://agv-pm:8000;
        proxy_set_header Host agv.example.com;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Forwarded "";
        proxy_set_header X-Forwarded-Host "";
    }
}
```

代理必须**覆盖**客户端传入的转发头，且只把实际代理对端加入 `FORWARDED_ALLOW_IPS`。应用只根据 Uvicorn 验证后的连接 scheme 判断 HTTPS，不直接采信请求的 `X-Forwarded-Proto`；不可信客户端伪造该头仍被重定向。使用仓库的 supervisord 启动命令，或手动启动时保留 `--proxy-headers` 并使用同一个 `FORWARDED_ALLOW_IPS`；误配代理地址会造成 HTTPS 重定向循环，应修正代理信任配置。

容器内 `GET /health` 仅在**回环连接、回环 Host、无 Cookie/Authorization**时允许 HTTP，仍需通过正常 Host 白名单；此例外不覆盖任何业务 API。外部 HTTP `/health` 与其他页面一样要求 HTTPS。健康检查默认使用 `http://127.0.0.1:8000/health`，不要从 Host 白名单移除 `127.0.0.1`。

上线核对：HTTP 域名跳转到 HTTPS；`curl -sS -D - -o /dev/null https://agv.example.com/health` 返回 HSTS；HTTPS 登录响应的四个会话 Cookie 均带 `Secure`；未配置域名返回 400。修改环境文件后重建/更新容器使启动校验生效。

## 从 3.6 之前的版本升级

3.6 起数据库从新的起点开始，不迁移旧数据。升级后第一次启动时：

- 先照常生成一份迁移前加密备份（`DATA_DIR/backups/agvpm-before-migrate-*.agvenc`）。
- 旧数据库原样挪开：SQLite 文件移到 `DATA_DIR/old-<时间>/`，PostgreSQL 的表移到 `old_<时间>` 架构；上传文件、项目删除备份一起移到 `DATA_DIR/old-<时间>/`。
- 系统从空库开始，用 `INITIAL_ADMIN_PASSWORD` 建管理员账号，内置模板、车型字典自动写入。

旧数据不会被删除；确认不需要后，可以手动删掉 `old-<时间>` 目录和 `old_<时间>` 架构。

## 环境要求

| 项目 | 要求 |
|---|---|
| Docker | 20.10+（群晖 Container Manager / QNAP Container Station / Unraid 均可用） |
| CPU | x86_64 或 arm64（如群晖 ARM 机型） |
| 内存 | ≥ 512MB（限制值 512MB，建议 1GB） |
| 存储 | 数据文件约几 MB ~ 几十 MB |

## 首次部署（群晖 NAS）

通过 SSH 登录 NAS。以下使用 `/volume1/docker/agv-pm`；QNAP 或其他 NAS 请替换为自己的绝对路径。

源码在 GitHub 开源：<https://github.com/KnxckbackWili/xingxu>。`<版本>` 换成[最新发布标签](https://github.com/KnxckbackWili/xingxu/tags)去掉 `v` 的版本号，例如 `3.5.0`。

```bash
mkdir -p /volume1/docker
cd /volume1/docker
git clone --branch v<版本> https://github.com/KnxckbackWili/xingxu.git agv-pm
cd agv-pm
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，首次至少确认下面这些值（不想在 NAS 上构建，可直接用下文 GHCR 镜像）：

```dotenv
DEPLOY_MODE=build
APP_VERSION=<版本>
AGV_IMAGE=agv-pm:<版本>
INITIAL_ADMIN_PASSWORD=请换成至少16位的独立强密码
SEED_DEMO_USERS=0
BIND_ADDRESS=127.0.0.1
APP_PORT=8000
DATA_PATH=/volume1/docker/agv-pm-data
BACKUP_DIR=/volume1/backup/agv-pm
TRUSTED_HOSTS=agv.example.com,192.168.1.137
FORCE_HTTPS=1
MAX_BACKUP_UPLOAD_MB=2048
MAX_BACKUP_EXPANDED_MB=8192
```

`SECRET_KEY` 可留空，系统会在数据目录生成并持久化随机密钥。不要把密码或密钥提交到 Git。

开始部署并检查：

```bash
bash docker/scripts/manage.sh install
bash docker/scripts/manage.sh status
```

成功时 `/health` 会返回当前版本，例如 `{"status":"ok","version":"1.9.0"}`。首次账号是 `admin`，密码是 `.env` 中的 `INITIAL_ADMIN_PASSWORD`。

### 公网访问

在 NAS 反向代理中配置：

```text
外部：https://agv.example.com:443
内部：http://127.0.0.1:8000
```

只向公网开放 HTTPS，禁止直接转发数据库目录、备份目录或 Docker API。域名证书生效后再设置 `FORCE_HTTPS=1`。

### GitHub 自动构建（GHCR）

GitHub 仓库的 `.github/workflows/docker-image.yml` 会自动构建 `linux/amd64` 与 `linux/arm64` 镜像，发布到 `ghcr.io/knxckbackwili/xingxu`：

| 触发 | 发布的标签 | 用途 |
|---|---|---|
| 推送 `master` | `edge`、`sha-<7 位提交号>` | 试用最新代码；`sha-` 标签固定不变，可用于回滚 |
| Actions → 镜像构建 → Run workflow，勾选“发布正式版本” | `<版本>`、`latest`，并创建 `v<版本>` 标签和 Release | 正式版本（推荐）：按代码里的版本号自动建标签，先运行 `release-check.sh` |
| 手工推送 `v<版本>` 标签 | `<版本>`、`latest` | 标签必须建在版本号已改好的提交上，否则构建会拒绝 |

源码仓库是公开的。镜像包在 GitHub 的 Packages → xingxu → Package settings 设为 Public 后可匿名拉取；仍为私有时，NAS 先用 GitHub 账号和一个只勾选 `read:packages` 的个人访问令牌执行 `docker login ghcr.io -u <GitHub 用户名>`。账号和令牌只交给 `docker login`，不要写入 `.env` 或 Compose 文件。切换为 registry 模式：

```bash
sed -i 's|^DEPLOY_MODE=.*|DEPLOY_MODE=registry|' .env
sed -i 's|^AGV_IMAGE=.*|AGV_IMAGE=ghcr.io/knxckbackwili/xingxu:<版本>|' .env
bash docker/scripts/manage.sh install
```

正式环境使用版本号或 `sha-` 标签，不要直接跟随 `edge`。接入网页「软件更新」后，后续版本可在网页检查并安装，见[软件更新](software-updates.md)。

默认只监听 NAS 本机 `127.0.0.1:8000`。在群晖/QNAP 的反向代理中创建一个 HTTPS 域名，将上游指向 `http://127.0.0.1:8000`，不要直接把 8000 端口映射到公网。如确需局域网直连，把 `.env` 的 `BIND_ADDRESS` 改为 `0.0.0.0`。

公网启用时必须按文首清单配置：

```dotenv
PUBLIC_MODE=1
TRUSTED_HOSTS=agv.example.com,127.0.0.1,localhost
FORWARDED_ALLOW_IPS=172.20.0.5
FORCE_HTTPS=1
COOKIE_SECURE=1
```

### Nginx Proxy Manager（NPM）反代 8002（T023，2026-08-25 实测）

以 `docker-compose.multica.yml` 部署到 8002 时，端口按 `BIND_ADDRESS:8002 → 8000` 发布（历史未配置时为 `0.0.0.0`；公网设 `127.0.0.1` 或防火墙限制代理来源），容器内 uvicorn 监听 `0.0.0.0:8000`。`TRUSTED_HOSTS` 默认仅本机回环（`127.0.0.1,localhost`）；被 NPM 反代时必须在 `docker/.env` 显式加入访问域名（如 `agv.example.com`），否则 Host 校验会拒绝请求。

**NPM Proxy Host 配置（三条即可）：**

| 配置项 | 值 |
|---|---|
| 域名（Domain Names） | `agv.example.com`（或你的外网域名） |
| Scheme / Forward Hostname | `http` + 宿主机局域网 IP（如 `192.168.1.136`）；若 NPM 与 8002 同 Docker 网络，可直接填容器名 `agv-pm-8002` + 端口 `8000` |
| Forward Port | `8002`（指向宿主机映射端口；同一网络指向容器时填 `8000`） |
| WebSockets Support | **开启**（`/Advanced` 里勾选 `Websockets Support`，为 WebSocket 链路预留） |

**为什么这样可行（本次修复的落点）：**

1. **代理头默认不信任任意来源（T024 加固）**：`FORWARDED_ALLOW_IPS` 默认**为空**，容器内 uvicorn 因此不信任代理头（原生启动且完全未设置该环境变量时，Uvicorn 默认仅信任 `127.0.0.1`）。直连 8002 的局域网/外部客户端伪造 `X-Forwarded-For/Proto` 会被一律忽略（登录审计 IP 与登录限流均使用真实对端，伪造头无法绕过限流）。需要 NPM 反代拿到真实客户端 IP 与 https scheme 时，将 `FORWARDED_ALLOW_IPS` 显式配置为 NPM 可信地址/网段（见下方「T024 配置」）。
2. **完整链路已验证**：临时反代容器（独立 bridge 网络 → 宿主机 `host.docker.internal:8002`）实测——页面加载、深链刷新、登录、登录后 API、SSE 流式（含 `X-Accel-Buffering: no`）全部 200；宿主机局域网 IP（如 `192.168.1.136:8002`）直连同样 200。
4. **常见误区**：NPM 的 Forward Hostname 不要填 `127.0.0.1`（NPM 容器自己的回环地址，会连接拒绝）；应填宿主机局域网 IP、`host.docker.internal`，或同网络容器名。容器内服务间调用不受影响（`NO_PROXY=*` 已兜底）。

**HTTPS 反代必须同步设 `COOKIE_SECURE=1`（HYPE-99）**：浏览器会话已改为 HttpOnly Cookie 承载（不再把令牌写进 localStorage）。NPM 在容器外终止 HTTPS，容器内 uvicorn 看到的仍是 http——`FORCE_HTTPS=1` 负责 HTTPS 重定向和 HSTS，`COOKIE_SECURE=1` 单独负责 Set-Cookie 的 Secure 属性。若 `docker/.env` 不设 `COOKIE_SECURE=1`，https 页面下浏览器会拒绝非 Secure 的 HttpOnly Cookie，表现为**登录接口 200 成功、但随后每个请求都 401，界面回到登录页**。在 `docker/.env` 加一行再 `make update`：

```dotenv
COOKIE_SECURE=1
```

### T024 配置：`FORWARDED_ALLOW_IPS`（代理头信任，默认安全）

| 场景 | `FORWARDED_ALLOW_IPS` | uvicorn 行为 |
|---|---|---|
| 容器默认 | 空 | 不信任代理头；局域网/外部伪造 `X-Forwarded-*` 一律忽略 |
| 原生 Uvicorn 默认 | 完全不设置环境变量 | Uvicorn 默认仅信任 `127.0.0.1` |
| NPM 反代（推荐） | NPM 容器 IP，如 `172.17.0.5` | 仅该可信代理转发的 `X-Forwarded-For/Proto` 生效，登录审计/限流按真实客户端 |
| NPM 反代（同网段） | 桥接网段，如 `172.16.0.0/12` | 该网段内可信；**注意**：若网段含 Docker 网关（`*.0.1`），经发布端口直连的外部流量源 IP 即网关，也会被信任——生产更推荐收敛到 NPM 容器具体 IP |

```dotenv
# .env 示例：NPM 容器与 8002 同 Docker 网络时，收敛到 NPM 容器 IP
FORWARDED_ALLOW_IPS=172.17.0.5
# 或用 docker network inspect 查看 8002 所在网络里 NPM 容器的 IP
```

安全基线（T024 回归测试 `docs/scripts/t024_proxy_security_test.py` 与 `backend/tests/test_proxy_security.py` 覆盖）：
- 默认模式下，非可信对端伪造 `X-Forwarded-For` 无效——uvicorn 访问日志与登录失败 key 均用真实对端 IP；
- 轮换伪造头无法绕过登录限流（第 9 次仍按真实对端触发 429）；
- 显式配置可信网段后，可信代理转发的头生效（审计 IP = 转发头中的真实客户端）。

### T025 登录失败限流：PostgreSQL 原子共享计数（多 worker / 重启不绕过）

登录失败限流（阈值 8 次、窗口 15 分钟）由进程内 `_login_failures` 改为 **PostgreSQL 共享计数**，复用 T006 导出限流的共享桶设计：

- **表** `login_failure_buckets`：`key`=真实客户端 IP + 用户名（`request.client.host`，T024 可信代理后即真实客户端）、`bucket`=当前固定窗口、`window`=窗口秒数（PG 保留字，SQL 内双引号引用）、`count`=失败数。启动 `create_all` 自动建表，无需迁移操作。
- **原子性**：`INSERT ... ON CONFLICT (key, bucket, "window") DO NOTHING` 幂等建行 + `UPDATE ... SET count = count + 1 WHERE count < :limit RETURNING count` 原子递增——PG 行锁保证并发（含 `WEB_CONCURRENCY=2` 多 worker）下恰好 8 次成功，第 9 次返回空 → 429。
- **语义不变**：仅统计失败；**成功登录清空**该 key 全部失败计数；每桶清理早于上一桶的过期行防膨胀；SQLite/单进程保留原内存路径（测试与本地行为不变）。
- **运行时回归**：`docs/scripts/t025_login_limit_test.py`（真实 8002 单容器）：确认 uvicorn `--workers 2`（master + 2 worker 子进程）、顺序 9 次失败登录前 8 次 401 第 9 次 429（跨 worker 全局累计）、不同账号隔离（PG 两 key 计数 {8,1}）、`docker restart` 后同一账号仍 429（窗口未被绕过）、重启后另一账号仍 401、清理测试行后 `/health` 200。

### HYPE-24：`TRUSTED_HOSTS` 白名单支持 IP 网段（CIDR）

**故障链路（复现定位）**：HYPE-19 暴露面收口把 `docker/.env` 的 `TRUSTED_HOSTS` 配成
**静态精确 IP 白名单**（回环 + 本机 hostname + 两个 LAN IP）。Starlette 自带
`TrustedHostMiddleware` 只做精确匹配/`*.domain` 后缀通配，无法表达"整个局域网网段"，
于是以下任一合法访问都会被 400 `Invalid host header` 拒绝：

- 经 NPM/nginx 反代以**公网域名**访问（Host = 域名，不在白名单）；
- **DHCP 重新分配 LAN IP**（Host = 未逐条列出的新 IP）；
- 新增**网卡/VPN 接口**（Host = 白名单外本机其他接口 IP）。

**修复（不放开校验）**：`backend/app/middleware.py` 新增 `TrustedHostsMiddleware`，
在保留精确/`*.domain` 语义基础上支持 **IP 网段（CIDR）** 条目；未命中任何条目仍返回
400 `Invalid host header`。回归测试 `backend/tests/test_trusted_hosts.py`（8 项）与全量
pytest 通过。

**部署侧配置**：把白名单中的精确 LAN IP 收敛为网段，并补上反代域名。示例：

```dotenv
# docker/.env（8002 单容器部署）
TRUSTED_HOSTS=127.0.0.1,localhost,HUAWEI-Harmony-mini.local,192.168.1.0/24,agv.example.com
```

- `192.168.1.0/24`：该网段任意 IP 可访问，DHCP 换 IP / 新增网卡不失效；
- `agv.example.com`：反代访问的公网域名必须显式列出（或 `*.example.com`），否则
  反代链路仍 400；
- 不要用 `TRUSTED_HOSTS=*` 掩盖问题——任意 Host 校验仍保留。

### 手动构建运行

```bash
cd AGV-项目管理
docker build -f docker/Dockerfile -t agv-pm .
docker run -d \
  --name agv-pm \
  -p 8000:8000 \
  -e SECRET_KEY="请替换为随机长字符串" \
  -e INITIAL_ADMIN_PASSWORD="请替换为至少8位的首次密码" \
  -e SEED_DEMO_USERS=0 \
  -v /path/to/data:/app/data \
  --restart unless-stopped \
  agv-pm
```

## 首次使用

生产模式首次只创建管理员账号：

| 账号 | 密码 | 角色 |
|---|---|---|
| admin | `.env` 中的 `INITIAL_ADMIN_PASSWORD` | 管理员（用户管理） |

本地演示如需预置 `pm`、`worker1`、`worker2`，可在 `.env` 设置 `SEED_DEMO_USERS=1`。该选项仅在空数据库首次启动时生效，不建议用于生产。

修改密码：登录后 → 右上角头像 → 修改密码（或由管理员在「用户管理」中修改）。

存量 admin 的运维轮换（忘记当前密码 / 计划性轮换）：在 `.env` 设置 `ADMIN_PASSWORD_ROTATE=1` 并同时提供 `INITIAL_ADMIN_PASSWORD`（≥8 位）后重启，启动时会显式改密并使所有已登录会话失效；密码未变时幂等跳过。轮换完成后建议移除 `ADMIN_PASSWORD_ROTATE=1`，避免每次重启重复轮换。明文只从环境变量读取，不会写入日志或落盘。

## 数据与备份

所有数据保存在挂载卷的 `data/` 目录下：

```
data/
├── agvpm.db          # SQLite 数据库（全部业务数据）
├── agvpm.db-wal      # WAL 日志（运行时产生）
├── secret.key        # 登录令牌密钥
├── uploads/          # 项目与交付附件
└── backups/          # 系统界面生成的完整备份
```

推荐使用项目自带脚本执行在线一致性备份：

```bash
bash docker/scripts/backup.sh
```

脚本会把数据库一致性快照、附件和持久化密钥打包到 `backups/agv-pm-日期时间.tar.gz`。可通过 `BACKUP_DIR=/备份目录` 修改输出位置。直接复制 `data/` 仅建议在容器停止后进行。

恢复使用 `bash docker/scripts/manage.sh restore /备份路径/agv-pm-时间.tar.gz`。系统会在容器启动前校验并恢复，且自动保存恢复前快照。不要在运行中的容器上手工覆盖数据库。

### 定时自动备份（推荐）

在 NAS 任务计划中每天执行：

```bash
cd /volume1/docker/agv-pm && bash docker/scripts/manage.sh backup
```

备份包含数据库一致性快照、上传附件和登录密钥，并生成 SHA-256 校验文件。再用 Hyper Backup、rsync 或对象存储把 `/volume1/backup/agv-pm` 同步到另一台设备；同一块 NAS 里的备份不能防硬盘或整机故障。保留建议：每日 30 份、每月 12 份，每季度做一次恢复演练。`backup.sh` 已按此建议实现自动轮转：默认日备保留 30 份、月备保留 12 份（每个日历月最新一份），可通过 `BACKUP_KEEP_DAILY` / `BACKUP_KEEP_MONTHLY` 覆盖；pre-restore 快照（`agvpm-pre-restore-*`）纳入轮转并单独设保留数 `BACKUP_KEEP_PRE_RESTORE`（默认 20）。迁移前快照（`agvpm-before-migrate-*`，应用启动时生成）保留最近 20 份的逻辑不变。

## 后续更新

已接入网页「软件更新」时直接在网页检查和安装（[软件更新](software-updates.md)）。手动更新时先安排短暂维护窗口，`<版本>` 换成新发布的版本号：

```bash
cd /volume1/docker/agv-pm
git fetch --tags origin
git checkout v<版本>
bash docker/scripts/manage.sh update
bash docker/scripts/manage.sh status
```

源码构建模式会自动把 `.env` 的 `APP_VERSION` 和本地镜像标签同步到新版本。Registry 模式需先把 `AGV_IMAGE` 改为已发布的新版本镜像。不要使用 `latest`。

更新脚本会：

1. 在线生成数据库、附件和密钥的完整一致性备份及校验值。
2. 将正在运行的旧镜像保存为带时间戳的回滚镜像。
3. 在旧容器继续在线时先构建或拉取固定版本，完成后才进入切换窗口。
4. 重新创建唯一的 `agv-pm` 容器，等待 Docker 健康检查并请求 `/health`。
5. 新版失败时自动恢复旧镜像和升级前数据，并保存失败日志。

更新成功后登录核对项目数、用户数、附件和一条核心业务流程。升级前备份与回滚镜像至少保留 7 天。

## 回滚与恢复

新版健康但业务验证发现问题时：

```bash
cd /volume1/docker/agv-pm
bash docker/scripts/manage.sh rollback
```

该命令只切回旧镜像，不会删除更新后新增的数据。若确认数据库迁移与旧版不兼容，再按照命令输出的备份路径执行 `restore`。恢复备份会丢弃备份时间点之后的数据，应先征得业务负责人确认。

常用运维命令：

```bash
bash docker/scripts/manage.sh status
bash docker/scripts/manage.sh backup
docker logs --tail 200 agv-pm
```

## 一键验证（可选）

在任意有 Docker 的机器上运行：

```bash
bash docker/scripts/verify.sh
```

脚本会自动：构建镜像 → 启动容器 → 登录 → 建项目/车型 → 生成任务 → 排程 → 检查 SPA/PWA → 清理。全部通过即说明构建链路正常。

## 正式部署（单容器 PostgreSQL，8002）

从 v2.1 起支持**容器内 PostgreSQL**：仍是单容器，但数据库由 supervisord 托管的 PostgreSQL 17 承担（A1/A2），适合 500 项目级并发写入。这是**正式部署**使用的唯一入口（`make deploy` / `make update`），统一由 `docker/scripts/deploy.sh` 驱动。

### 需要配置的变量（极少）

只需准备一个 `docker/.env`（从 `docker/.env.example` 复制），通常只填前几项：

```bash
cp docker/.env.example docker/.env
chmod 600 docker/.env
# 编辑 docker/.env，首次部署至少设置 INITIAL_ADMIN_PASSWORD（≥8 位）
```

| 变量 | 说明 | 默认 |
|---|---|---|
| `INITIAL_ADMIN_PASSWORD` | 首次部署必填（≥8 位）；`SEED_DEMO_USERS=0` 时未设置会启动失败 | 空 |
| `SEED_DEMO_USERS` | `0`=仅 admin（正式）；`1`=额外建演示账号（评审/演示用） | `0` |
| `TRUSTED_HOSTS` | Host 白名单：域名/IP/`*.domain`/IP 网段（CIDR） | `127.0.0.1,localhost` |
| `PUBLIC_MODE` | `1` 启用公网配置强制检查；内网 HTTP 用 `0` | `0` |
| `FORWARDED_ALLOW_IPS` | 反代可信 IP/有限网段；公网模式必须显式配置 | 空 |
| `WEB_CONCURRENCY` | uvicorn worker 数 | `2` |
| `COOKIE_SECURE` | `1`=HTTPS 反代前置时给会话 Cookie 打 Secure。容器内 uvicorn 看到的是 http，`FORCE_HTTPS=1` 负责重定向和 HSTS，不替代 `COOKIE_SECURE=1`——https 页面下浏览器会拒绝非 Secure 的 HttpOnly Cookie，表现为登录成功但随即回到登录页/接口 401 | `0` |
| `COOKIE_SAMESITE` | 会话 Cookie SameSite 策略：`lax`（默认）/ `strict` / `none`（`none` 必须同时 `COOKIE_SECURE=1`） | `lax` |
| `ADMIN_PASSWORD_ROTATE` | `1` 且提供 `INITIAL_ADMIN_PASSWORD` 时启动显式改密并使旧会话失效（幂等） | `0` |
| `AGV_IMAGE` / `APP_VERSION` | 镜像标签与版本（自动从源码同步，一般无需改动） | 自动 |

> 演示账号（`SEED_DEMO_USERS=1`）若仍持默认口令（pm123/worker123），seed 会在启动时幂等禁用并失效其旧会话；需保留演示角色请先用 `DEMO_ADMIN_PASSWORD` / `DEMO_PM_PASSWORD` / `DEMO_WORKER_PASSWORD` 轮换为强口令。

其余变量（备份上限等）不配置即用内置默认值。**二次部署通常无需改动任何变量。**

### 首次部署

```bash
make deploy
```

流程：构建镜像 → 启动单容器（容器内 PostgreSQL）→ 等待健康检查。成功输出 `/health` 版本号与访问地址 `http://127.0.0.1:8002`。首次登录账号 `admin`，密码为 `docker/.env` 中的 `INITIAL_ADMIN_PASSWORD`。

### 二次部署（更新到当前代码）

```bash
# 拉取新代码后，一条命令完成二次部署：
git pull
make update
```

`make update` 自动完成四步，**失败自动回滚，无需手工干预**：

1. 构建新镜像（当前容器保持在线，不中断服务）；
2. 全量备份（`pg_dump -Fc` → `backups/`）并**立即校验备份 SHA-256**，校验不过则中止更新（不留不可回滚的现场）；保留旧镜像为回滚镜像；
3. 切换到新镜像；
4. 等待健康检查；未通过则自动回滚——**先切回旧镜像，再恢复已校验备份，最后做最终健康检查**（成功才输出“已自动回滚…已恢复”），输出失败日志路径。

安全保证：备份恢复（`restore.sh`）前**强制校验 SHA-256**，校验失败拒绝执行破坏性恢复（不 dropdb/createdb）；自动回滚区分两条失败路径——容器切换命令失败时只切回旧镜像并检查健康（数据未动，不盲目恢复）；新版本健康检查失败时**不以恢复前的旧镜像健康为门槛**（迁移可能令旧版本与新 schema 不兼容，恢复前健康检查会提前退出），而是切回旧镜像 → 恢复已校验备份 → 再做最终健康检查，且只有“切回旧镜像 + 恢复数据 + 最终健康检查”全部成功才输出“已自动回滚…已恢复”的成功措辞，任一步失败都会明确报错并保留失败日志（`backups/failed-update-*.log`、`backups/failed-restore-*.log`），不会误报恢复成功。

更新成功后核对 `/health` 版本与核心业务数据即可。回滚镜像与更新前备份保留在 `backups/`。

### PostgreSQL 恢复失败时

`restore.sh` 会先记录原应用服务状态，再停止 `web`、`scheduler`、`healthwatch`，并确认三者均为 `STOPPED`，保留 PostgreSQL 服务供恢复使用。无法确认停止状态时，脚本不会进入恢复，也不会自动启动服务。确认停写后，若恢复前快照或归档校验失败，数据库和文件尚未改动，脚本只恢复本次操作前确实为 `RUNNING` 的服务，并返回非零退出码；原本已停止或原状态未知的服务保持停止，避免失败后的维护重试再次启动半恢复状态。

一旦开始替换文件或恢复数据库，后续失败会返回非零退出码，并明确显示“服务保持停止”。此时保持维护停写，不要直接重启容器或手动启动应用服务；保留失败输出、原完整备份以及输出中列出的 `agvpm-pre-restore-*.dump`。该 dump 只包含恢复前数据库，不包含附件和密钥，不能代替完整备份。

先排除磁盘空间、文件权限或数据库恢复报错，再对来源可靠、校验通过的完整备份重新执行 `restore.sh`。只有文件与数据库恢复均成功后，脚本才启动应用服务；随后检查 `/health`、项目和附件。若启动应用服务本身失败，脚本也会返回非零退出码，不会输出“恢复完成”。恢复会覆盖当前数据，选择恢复时间点前应与业务负责人确认。

SQLite 恢复请求同样先核实停写；备份先复制到临时文件，复制完整后才发布为 `restore-pending.tar.gz`。提交或启动服务失败均返回非零退出码。成功输出“恢复请求已提交”，表示交给应用启动引导处理，仍需在重启后核对 `/health`、项目与附件，不表示已经完成数据验收。

### 其他运维命令

```bash
make status        # 容器状态 + /health
make logs          # 跟踪日志
make backup        # 全量备份（pg_dump -Fc → backups/）+ 旧包轮转
make restore BACKUP=backups/agv-pm-xxx.tar.gz   # 恢复（PG/SQLite 自动识别；恢复前强制 SHA-256 校验）
make rollback      # 回滚到上一次 update 前的镜像（依据状态文件 PREVIOUS_REF，不覆盖数据）
```

> `make rollback` 以更新时记录的 `PREVIOUS_REF`（上一次 update 前容器实际使用的镜像引用）为回滚目标，自定义 `AGV_IMAGE` 或版本升级后同样能精确回到更新前镜像，不依赖写死的 `2.1.0`。

要点：

#### O2：unhealthy 自动重启（容器内看门狗）

`restart: unless-stopped` 只在容器进程退出时生效，`/health` 失败（如 uvicorn 多 worker 全部挂起、PG 故障）不会触发重启，容器可能带病运行。本版本在 **不改变单容器部署形态** 的前提下，由 supervisord 新增 `healthwatch` 进程实现 health-based 自愈：

- 每 `HEALTH_CHECK_INTERVAL`（默认 15s）GET `HEALTH_CHECK_URL`（默认 `http://127.0.0.1:8000/health`）；
- **连续失败 `HEALTH_FAIL_THRESHOLD` 次**（默认 3，约 45s）→ `supervisorctl restart web`，快速恢复 web 挂起而无需重启整个容器；
- **同一窗口内 web 重启达 `HEALTH_WEB_RESTART_LIMIT` 次**（默认 2）仍未恢复 → `supervisorctl shutdown`，容器主进程退出 → Docker 按 `restart: unless-stopped` 重建容器（覆盖 PG/整体性故障）；
- **启动窗口**：应用首次成功前 `HEALTH_START_GRACE` 秒（默认 180）内只观察不动作，避免 PG 初始化/迁移阶段误判；应用成功过一次后立即进入正常判断。

权衡：autoheal sidecar 需额外常驻容器 + Docker socket（破坏单容器形态、提升攻击面）；宿主 watchdog 需 NAS 上额外 systemd/cron（逻辑不在仓库内）。看门狗为仓库内代码（`backend/app/services/healthwatch.py`），零外部依赖，两个 compose（SQLite 基线与 8002/PG）默认都启用。参数均可用环境变量覆盖（见 `.env.example`）。

#### 周报时间

```dotenv
REPORT_WEEKLY_TIME=20:00  # 每个项目当地周日晚
```

修改后重启容器（`make deploy` 或 `docker compose -f docker/docker-compose.multica.yml up -d`）生效。

### 部署参数（8002 单容器）

**几乎零配置即可启动**：不准备 `.env` 时 `make deploy` 直接使用 compose 默认值——演示账号
`admin/admin123`、数据库为容器内 PostgreSQL、宿主端口 `8002`。

需要覆盖参数时写 `.env` 并注意其位置：`make deploy` 等价于
`docker compose -f docker/docker-compose.multica.yml up -d --build`，compose 从
**compose 文件所在目录（`docker/`）** 读取 `.env`（`docker/.env`）；而 `manage.sh`
基线显式 `--env-file` 指向仓库根 `.env`，两者不是同一个文件。

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `INITIAL_ADMIN_PASSWORD` | 视模式 | 空 | 非空值一律用作 admin 密码且必须 ≥8 字符（`seed_data.py` 校验，演示模式下同样生效——短密码即使 `SEED_DEMO_USERS=1` 也会启动失败）；`SEED_DEMO_USERS=0` 时必填；留空且演示模式时 admin 用 `admin123` |
| `SEED_DEMO_USERS` | 否 | `1`（本 compose；`.env.example` 的 `0` 是 SQLite 基线默认） | `1` 预置演示账号 `admin/admin123`、`pm/pm123`、`worker1/worker2/worker123`；`0` 仅建 admin |
| `SECRET_KEY` | 否 | 空 | 留空自动生成并持久化到 `/app/data/secret.key`（重启不失效）；生产建议显式设置 |
| `APP_PORT` | 否 | `8002` | 宿主映射端口 → 容器内 `8000`。若 `docker/.env` 直接复制了 `.env.example` 的 `APP_PORT=8000`，会覆盖为 8000，不再是 8002 |
| `AGV_IMAGE` | 否 | `agv-pm-multica:2.1.2` | 固定版本标签；生产不要用 `latest` |
| `TRUSTED_HOSTS` | 否 | `*` | 逗号分隔 Host 白名单：精确域名/IP、`*.domain`、CIDR 网段（`192.168.1.0/24`）；生产收敛为局域网网段 + 反代域名，否则反代访问 400 |
| `PUBLIC_MODE` | 公网必须 | `0` | `1` 强制校验 HTTPS、Secure Cookie、Host 和代理信任配置 |
| `FORWARDED_ALLOW_IPS` | 公网必须 | 空 | NPM/nginx 反代时填可信代理地址/网段（如 NPM 容器 IP），uvicorn 才信任 `X-Forwarded-*`；容器默认空值不信任代理头 |
| `FORCE_HTTPS` | 否 | `0` | HTTPS 反代正确配置后设 `1`（重定向业务 HTTP 并下发 HSTS） |
| `COOKIE_SECURE` | 否 | `0` | 会话 Cookie 打 Secure。NPM/nginx 终止 HTTPS 后容器内 uvicorn 看到的是 http（`FORCE_HTTPS=1` 不会传导给 Cookie），https 页面下浏览器拒绝非 Secure 的 HttpOnly Cookie → 登录成功但无会话/接口 401；**HTTPS 反代部署必须设 `1`**，本地/内网 http 直连保持 `0` |
| `COOKIE_SAMESITE` | 否 | `lax` | 会话 Cookie SameSite：`lax`/`strict`/`none`（`none` 必须同时 `COOKIE_SECURE=1`） |
| `WEB_CONCURRENCY` | 否 | `2` | uvicorn worker 数；多 worker 下登录/导出限流由 PostgreSQL 共享计数保证 |
| `MAX_BACKUP_UPLOAD_MB` / `MAX_BACKUP_EXPANDED_MB` | 否 | `2048` / `8192` | 备份上传 / 恢复解压大小上限 |

> 说明：`config.py` 还支持 `CORS_ORIGINS`、`TIMEZONE` 等键（旧 `SOFT_DELETE_RETENTION_DAYS` 已由 #85 停用，回收站不自动到期），但
> **8002 compose（`docker-compose.multica.yml`）未对这三个变量做 `environment` 透传**，写进
> `docker/.env` 只参与 interpolation、不会注入容器进程，因此不会生效。它们仅在直接运行
> uvicorn（本地开发）或自建 compose 显式透传时可用，故不列入上表。

**验证**：`curl http://127.0.0.1:8002/health` 返回 `{"status":"ok","version":"2.1.2"}`；
`make status` / `docker compose -f docker/docker-compose.multica.yml ps` 见容器
`agv-pm-8002` healthy；浏览器访问 `http://127.0.0.1:8002` 用 `admin/admin123` 登录。

## 常见问题

| 问题 | 解决 |
|---|---|
| macOS OrbStack 报 `Permission denied while opening data image` | 数据目录权限被迁移助理改坏。打开 OrbStack 应用 → 设置 → 重置；或在系统设置 → 隐私与安全 中授予终端对 OrbStack 容器的访问权限 |
| Registry 登录跳转到错误端口或返回 EOF | 检查 Gitea `[server] ROOT_URL` 是否包含外网 HTTPS 端口，并让反向代理保留原始 `Host` 端口 |
| 端口 8000 被占用 | 修改 docker-compose.yml 的 `ports: "8080:8000"` |
| 手机访问不了 | 确认 NAS 防火墙放行该端口；群晖需在「控制面板→安全性→防火墙」放行 |
| 忘记密码 | 首选：登录后右上角头像 →「修改密码」；管理员可在「用户管理」中代改。兜底（部署主机受限终端）：`python3 docker/scripts/reset_password.py <用户名>` —— 用户名作命令行参数，新密码经 TTY 隐藏输入（getpass，不回显、两次一致、≥6 位），绝不进入命令行参数、环境变量、shell 历史或日志；成功后原子同步 `.secrets/` 对应凭据条目（临时文件 + os.replace，保持 0600），token_version 递增使旧会话全部失效。生产账号改密须在隔离演练容器验证过该脚本后再执行 |
| 数据库损坏 | 使用最近的备份文件替换 `data/agvpm.db` 后重启容器 |

## 性能说明

- 当前按约 **100 个账号 / 100 个项目**规划；单 worker + SQLite WAL 适合项目管理这种中低并发工作负载。若持续并发写入显著增加，再迁移 PostgreSQL。
- 如需更高并发，可将 `DATABASE_URL` 切换到 PostgreSQL（代码使用 SQLAlchemy，切换成本低）

## 离线使用（现场人员）

1. 现场人员用手机浏览器打开系统地址 → 登录
2. 浏览器菜单选择「添加到主屏幕」（iOS Safari：分享 → 添加到主屏幕；Android Chrome：菜单 → 安装应用）
3. 打开后即为全屏 App，界面和资源已离线缓存
4. **断网时**：仍可查看今日任务（缓存）并填写数量 → 记录进入本地队列
5. **联网后**：点击「同步」按钮（或自动同步），本地记录上传服务器

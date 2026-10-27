# 隔离的本地网页验收环境

> 本文引用的 QA 回执描述历史时点，原件已[归档](evidence-archive.md)；当前 v3 操作请从[文档入口](index.md)开始。

本环境供管理员、项目经理和现场人员执行真实网页流程。它只监听本机地址，使用独立 SQLite 数据目录，不连接 NAS 或生产 PostgreSQL。业务数据、附件、会话密钥与依赖目录均在 Git 忽略范围内。

## 安装依赖

在仓库根目录执行，沿用仓库现有版本及锁文件：

```bash
uv venv --python 3.12 backend/.venv
uv pip install --python backend/.venv/bin/python -r backend/requirements-dev.txt
cd frontend
npm ci --no-audit --no-fund
```

## 启动后端

在一个终端执行：

```bash
cd backend
audit_data_dir="$(cd .. && pwd)/data/browser-audit-20261005"
env -u AI_API_KEY -u AI_API_KEY_FILE \
  -u DEEPSEEK_API_KEY -u DEEPSEEK_API_KEY_FILE \
  -u MIMO_API_KEY -u MIMO_API_KEY_FILE \
  -u MINIMAX_API_KEY -u MINIMAX_API_KEY_FILE \
  -u AI_PROVIDER -u AI_PROVIDER_NAME -u APP_VERSION \
  DATA_DIR="$audit_data_dir" \
  DATABASE_URL="sqlite:///$audit_data_dir/agvpm.db" \
  SEED_DEMO_USERS=1 \
  TRUSTED_HOSTS=localhost,127.0.0.1 \
  SCHEDULER_ENABLED=0 \
  COOKIE_SECURE=0 \
  FORCE_HTTPS=0 \
  TIMEZONE=Asia/Shanghai \
  AI_ALLOW_NO_KEY=0 AI_BASE_URL= AI_MODEL= \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18000 --reload --reload-dir app --no-access-log
```

首次启动会生成演示账号和默认模板。后续启动复用该验收库，保留网页操作形成的项目和附件。要开展新的独立验收，将目录末尾更改为另一个明确的验收批次名称。

默认验收启动清除进程继承的 AI 密钥/密钥文件设置，关闭无密钥兼容服务，避免误用外部服务。2026-10-05 曾用纯 QA 文本做一次已授权整理，外部 DeepSeek 返回 HTTP 402 余额不足；随后按上述空配置参数重启。该外部调用结果不当作产品整理成功，也未复制任何密钥到文档或仓库。后端仅监视业务源码，补充测试不会触发验收服务重载。

需要补测收集箱的异步正向流程时，可显式运行 [固定 QA 依赖](evidence-archive.md "原路径：docs/scripts/qa_ai_provider.py；SHA256：bbe1d6f361f2d0fd46b7512c21c0f997d97955ec631201d8e523165b14f1554a")：它只监听 `127.0.0.1:18081`，仅响应指定 QA 文件与连接探测，不调用模型、不外发、不记录请求内容或认证头。先执行 `backend/.venv/bin/python docs/scripts/qa_ai_provider.py --self-test` 做协议自检；启动命令是 `backend/.venv/bin/python docs/scripts/qa_ai_provider.py`。只有获得串行验收窗口后才临时把隔离后端的自建服务指向它，模型为 `qa-fixed-response`，名称必须明确标为“本地受控QA固定响应”；脚本中的 token 是公开的假测试值。此结果只证明产品在固定合法响应下的解析、进度与人工归档流程，不证明外部 AI 推断能力或可用性。测试后停止该依赖，并恢复上方全部 AI 空配置启动参数。

本轮正向网页验证使用 `--delay 8`：连接测试成功，实际观察到 2% 队列状态，随后历史记录、分类、摘要和建议项目均按响应呈现；归档先取消后确认，独立 QA 项目下载的 83 字节原文件与上传内容完全一致。测试结束后已停止 `18081` 服务、清空临时 AI 配置，并在原数据目录和会话密钥下重启后端，健康检查为 `ok / 2.1.2`。

## 最终备份恢复配合

最新完整备份须在本轮网页业务写入结束后，从管理员备份页面实际创建并下载。只增加明确的个人 QA 恢复探针，再通过网页上传同一个最新备份进入待恢复状态；确认所有网页写操作、上传和请求均已停止后，关闭后端并用上方空 AI 配置启动。保持同一 `DATA_DIR`、`DATABASE_URL`，不替换为早期备份，也不另设版本或会话密钥。启动会先校验并应用 `restore-pending.tar.gz`，保留恢复前备份，然后再加载数据库和认证配置。

健康检查成功只表示服务启动；恢复验收仍须在网页重新登录，回读正式数量、最终归档状态与完整复盘，并下载 QA 附件逐字节对比。恢复探针应消失。待恢复包消失及恢复前备份存在属于辅助证据，不能代替上述网页回归。

本轮最终恢复已完成：网页创建的 `agvpm-manual-20261005-073720-acfe504448af48349c73b4516b14ca4e.tar.gz` 为 582556 字节；重启前核对待恢复包与该最新包完全相同、会话密钥相同。应用后健康检查为 `ok / 2.1.2`，待恢复包消失并自动生成恢复前备份。管理员实际退出后重新登录成功，114 字节个人恢复探针消失，83 字节已归档参考记录保留；最终项目仍已归档且复盘全文、作者与当地 05:58 时间保留，主项目仍为 1 台、1 项、2 米及 10%。实际下载的 610 字节原 PDF、83 字节参考文件均与原文件逐字节一致，9 个启用用户资料也保留。网页证据见 [探针消失](evidence-archive.md "原路径：docs/qa-admin-backup-probe-absent.txt；SHA256：2b202d87f6bb8fda7ae691e44e9e80ccc42e8ed02649c9e69616d93c153d0798")、[归档与复盘](evidence-archive.md "原路径：docs/qa-admin-backup-restored-archive.txt；SHA256：bd7b09115e3d0ff4398513dec846b532ed1cf8bd58ba17beef5f27cdfea065ee")、[主项目](evidence-archive.md "原路径：docs/qa-admin-backup-restored-main.txt；SHA256：239b3fda55885d0ce048079053af9bd2741fe54cdf0ec7712c54c99cd3263da0")、[用户资料](evidence-archive.md "原路径：docs/qa-admin-backup-restored-user.txt；SHA256：a7f8154d72644f16700e8fa17b10a74d1b46a926eeedcdf268e6dd813bfd3c93")。完成后继续以同数据目录、空 AI 配置运行。

## 查看生产构建网页

在 `frontend` 执行 `npm run build` 后，当前后端会直接提供 `frontend/dist`，可以通过 [管理端](http://localhost:18000/pm/dashboard) 与 [现场端](http://127.0.0.1:18000/worker/today) 查看本轮实际验收的生产构建。当前版本2.1.2；浏览器采用正常刷新获取更新后的脚本和PWA。

两个主机名分别保存角色Cookie；同一主机名的不同端口会共享Cookie，因此不要把不同端口当作隔离账号的办法。该网页服务仅监听本机，并没有部署到NAS正式环境。

## 启动前端

在第二个终端执行：

```bash
cd frontend
env VITE_API_PROXY_TARGET=http://127.0.0.1:18000 \
  npm run dev -- --host 127.0.0.1 --port 15173 --strictPort
```

| 用途 | URL |
| --- | --- |
| 管理员或项目经理 | http://localhost:15173 |
| 项目经理独立会话 | http://pm.localhost:15173 |
| 现场人员独立会话 | http://127.0.0.1:15173 |
| 后端健康检查 | http://127.0.0.1:18000/health |

`localhost`、`pm.localhost` 与 `127.0.0.1` 的浏览器 Cookie、离线草稿和本地偏好互相隔离，但业务数据来自同一后端。不同角色分别使用不同地址，避免同源登录覆盖会话。此次浏览器工具的页面焦点存在并发干扰，实际网页验收采用串行操作窗口；服务和单元测试可独立运行。

演示账号为 `admin / admin123`、`pm / pm123`、`worker1 / worker123`、`worker2 / worker123`。这些账号仅用于本机隔离环境。

## 停止与验证

在两个启动终端分别按 `Ctrl+C`。不需要删除验收数据。健康检查可执行：

```bash
curl --noproxy '*' -sS http://127.0.0.1:18000/health
curl --noproxy '*' -sS http://localhost:15173/health
```

2026-10-05 首次启动验证：Python 3.12.8、Node.js 24.9.0；后端依赖安装成功，前端按当时原锁文件执行 `npm ci` 成功，启动阶段未改依赖。后续依赖修补以主验收清单和最终锁文件为准。首次后端启动正常完成 Alembic 初始化及默认种子创建；两个健康接口和前端首页均返回 HTTP 200。

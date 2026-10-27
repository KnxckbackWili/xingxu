# AGV 项目管理系统 v1.9.0 交接说明

更新时间：2026-08-14。本文用于把项目迁移到另一台开发机、NAS 或交给新的 AI/开发者继续维护。

## 1. 当前基线

- 仓库：`https://gitea.arrowwood.top:8773/claude/agv-pm.git`
- 主分支：`main`
- 发布标签：`v1.9.0`
- 目标规模：约 100 个账号、100 个在管项目，中低并发写入
- 部署形态：FastAPI + React 构建产物 + SQLite，单 Docker 容器
- 持久化目录：容器内 `/app/data`，必须挂载 NAS 目录
- 默认端口：容器 `8000`；生产建议仅监听 NAS 本机并由 HTTPS 反向代理访问

源码仓库不包含 `.env`、数据库、附件、备份和任何 AI 密钥。这些内容由 `.gitignore` 明确排除。

## 2. 已实现业务范围

### 项目与执行

- 项目列表支持搜索、状态筛选、分页和大批量项目浏览。
- 项目准备独立为工作台提醒，不进入任务计划和甘特图。
- 阶段、模块、任务、检查项四层结构；任务支持交付物、参考附件和验收证据。
- 项目日程支持自动排程、预览、锁定、拖拽、确认下达、日历和甘特视图。
- 项目经理、技术负责人、项目协管和实施成员按项目关系控制可见与可写范围。
- 项目移交与删除走治理申请，系统管理员为最高权限。

### 人员与组织

- 系统角色：系统管理员、总监、项目经理、技术经理、技术工程师、实施工程师、实习工程师。
- 组织架构为两级：大组 -> 小组；用户账号绑定小组，负责人仍必须是系统用户。
- 人员管理按约 100 人设计，提供搜索、岗位/小组/状态筛选、负载与可用性信息。
- 一个小项目可由实施工程师作为有期限的项目协管，与项目经理共同维护执行过程。

### 车辆、问题与现场交接

- 车辆配置记录项目车型和数量；现场车辆台账记录每一台实车。
- 车辆问题以生命周期事件记录故障部位、原因、处理、更换配件、验证和是否解决。
- 项目问题与车辆问题在“问题关注”统一查看，但单车故障不重复建立项目问题。
- 现场交接保存甲方部门/小组/联系人、主联系人、负责事项、签字范围和入场方式。

### 现场物品 v1.9.0

- 项目内“现场物品”维护物品编号、名称、分类、规格、序列号、数量、单位、位置、保管人和状态。
- 归属明确区分我方、甲方、第三方；支持按数量管理或按序列号逐件管理。
- 每件物品保留收货、领用、转移、消耗、归还、调整、盘点流水和操作人。
- 支持最低库存、损坏/丢失关注；全局“物品总览”按用户可见项目检索和 SQL 聚合统计。
- 项目 JSON 导入导出包含物品及历史流水；Excel 导出增加“现场物品”，共 13 个 Sheet。

### 分域 AI 助手 v1.9.0

- 兼容 OpenAI Chat Completions 格式，内置 DeepSeek、小米 MiMo、MiniMax 和自建服务配置。
- 5 个独立 Skill：项目建档、计划排程、现场物品、问题研判、现场交接。
- 项目列表、项目日程、现场物品、问题关注、现场交接分别调用对应 Skill。
- 后台任务显示读取资料、调用模型、解析结果、业务校验和百分比；任务状态仅在内存保留 1 小时。
- AI 密钥只在后端环境变量读取；上传原文件不持久化，但提取文字会发给选定 AI 服务。
- AI 结果不会静默写库：项目、问题、物品和交接信息均需用户审核后应用；排程 AI 当前只给建议和 JSON 下载，不直接覆盖日程。

## 3. 关键目录

```text
backend/app/
  main.py                         FastAPI 入口、路由和 SPA 托管
  models/__init__.py              SQLAlchemy 数据模型
  routers/inventory.py            物品台账与流水 API
  routers/ai_projects.py          AI 状态、文件提取、异步任务
  services/ai_project_assistant.py AI 提供商兼容层、Skill 路由和校验
  services/import_export.py       Excel/JSON 导入导出
frontend/src/
  components/AiProjectAssistant.tsx
  components/AiInventoryAssistant.tsx
  components/AiDomainAssistant.tsx
  pages/pm/InventoryOverviewPage.tsx
  pages/pm/project/InventoryPage.tsx
skills/
  agv-project-organizer/
  agv-project-planner/
  agv-site-inventory/
  agv-issue-triage/
  agv-site-handover/
docker/
  Dockerfile
  docker-compose.yml
  scripts/manage.sh                安装、更新、备份、恢复、回滚
docs/                              架构、部署、用户手册和本交接文档
```

## 4. 迁移源码到另一台开发机

```bash
git clone --branch v1.9.0 https://gitea.arrowwood.top:8773/claude/agv-pm.git
cd agv-pm

python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.lock.txt

cd frontend
npm ci
npm run build
cd ..

pytest -q backend/tests
```

本地前后端联调可分别运行：

```bash
# 终端 1
. .venv/bin/activate
DATA_DIR="$PWD/data" SEED_DEMO_USERS=1 uvicorn app.main:app --app-dir backend --reload --port 8000

# 终端 2
cd frontend
npm run dev -- --host 127.0.0.1
```

## 5. 迁移生产数据到另一台机器

不要复制运行中的 SQLite 文件。先在旧机器生成一致性备份：

```bash
cd /旧机器/agv-pm
bash docker/scripts/manage.sh backup
```

把生成的 `agv-pm-时间.tar.gz` 和同名 `.sha256` 传到新机器。再准备新机器的 `.env`，其中 AI 密钥、管理员初始密码、域名和路径需自行填写，不从公开 Git 获取。

```bash
git clone --branch v1.9.0 https://gitea.arrowwood.top:8773/claude/agv-pm.git
cd agv-pm
cp .env.example .env
# 编辑 DATA_PATH、BACKUP_DIR、TRUSTED_HOSTS、FORCE_HTTPS 与密钥
bash docker/scripts/manage.sh install
bash docker/scripts/manage.sh restore /新机器/备份/agv-pm-时间.tar.gz
bash docker/scripts/manage.sh status
```

备份包含 `agvpm.db`、上传附件和 `secret.key`。保留 `secret.key` 可以避免恢复后所有现有登录令牌立刻失效。

## 6. NAS 更新与回滚

```bash
cd /NAS上的/agv-pm
git fetch --tags origin
git checkout v1.9.0
bash docker/scripts/manage.sh update
bash docker/scripts/manage.sh status
```

`update` 会先备份，再构建/拉取新镜像，健康检查失败时自动恢复。业务验证后仍需手动回滚时运行：

```bash
bash docker/scripts/manage.sh rollback
```

生产镜像应固定版本，不使用 `latest`。反向代理上游使用 `http://127.0.0.1:<APP_PORT>`，`TRUSTED_HOSTS` 必须包含公网域名，否则会出现 `Invalid host header`。

## 7. AI 环境变量

三家可同时配置，页面按任务选择：

```dotenv
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
MIMO_API_KEY=
MIMO_MODEL=mimo-v2.5-pro
MINIMAX_API_KEY=
MINIMAX_MODEL=MiniMax-M2.7
AI_TIMEOUT_SECONDS=180
```

所有提供商都通过后端请求 `<BASE_URL>/chat/completions`。兼容性策略依次尝试 `json_schema`、`json_object` 和普通 JSON 提示，适配三家响应格式差异。

## 8. 安全与数据边界

- 公网仅开放 HTTPS 反向代理，不开放 Docker API、SQLite、上传目录和备份目录。
- 容器默认只读、删除全部 Linux capabilities、禁止提权，仅 `/app/data` 和 `/tmp` 可写。
- `SECRET_KEY` 留空时在持久卷生成；不要在多台生产机器共用公开默认值。
- AI 原文可能包含甲方联系人和现场资料，调用前应确认公司数据策略。
- 用户导入不能绑定系统账号、项目经理或技术负责人，避免通过 JSON 绕过权限。
- 删除项目需要申请；系统备份与恢复需要系统管理员权限。

## 9. 下一阶段建议

- 排程 Skill 目前为审核建议模式。若要自动应用，应增加“差异预览 -> 逐条选择 -> 保留锁定项 -> 新版本下达”的事务接口，不应直接批量覆盖。
- AI 任务队列当前为单进程内存队列，适合单容器单 worker。未来改多 worker 时再引入数据库任务表或 Redis。
- SQLite 适合当前 100 项目规模；当持续并发写入、跨区域部署或数据量显著增长时，再迁移 PostgreSQL。
- 上线前仍应做一次真实 NAS 备份恢复演练，并用实际 DeepSeek/MiMo/MiniMax 账号各验证一份脱敏资料。

## 10. 发布验收

发布前执行：

```bash
pytest -q backend/tests
cd frontend && npm run build
cd .. && bash docker/scripts/verify.sh
```

还应人工检查桌面与手机：项目列表、日程、问题、现场物品、现场交接、全局物品总览，以及 AI 进度显示。完整清单见 `docs/release-checklist.md`。

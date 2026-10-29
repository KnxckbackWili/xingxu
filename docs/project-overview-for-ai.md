# AGV 项目管理系统 — 项目说明（供外部 AI 分析）

> 本文件是项目的自包含总览，更新于 2026-08-14（版本 1.9.0）。迁移操作、当前边界与下一步见 `docs/project-handoff-v1.9.0.md`。

---

## 一、项目是什么

为**小型 AGV（自动导引车）实施团队**打造的项目管理工具，部署在客户/团队的 NAS 上（单容器，离线可用）。

核心工作流：**项目经理配置项目与模板 → 系统自动生成任务与日程 → 现场人员用手机/平板填报数量 → 系统自动统计进度与交付物审核**。

典型场景：工厂部署 AGV 搬运系统（进场准备 → 到货检查 → 单车调试 → 地图与站点 → 系统部署 → 系统联调 → 试运行 → 培训验收），一个项目 5-30 天、数人参与、数十个任务。

## 二、技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.0 + SQLite（WAL 模式，单 worker uvicorn） |
| 前端 | React 18 + Ant Design 5 + Vite + TypeScript，react-router 6，ECharts |
| 部署 | 单 Docker 容器（前后端同源托管）+ docker-compose，目标 NAS（群晖/QNAP） |
| PWA | vite-plugin-pwa：离线可用、Service Worker 缓存、版本号驱动缓存失效 |
| 测试 | 后端 pytest 181+ 用例 + docker/scripts/verify.sh 容器端到端烟测 |
| 认证 | JWT（access + refresh）+ bcrypt；令牌版本失效机制（改密码全端下线） |

约束约定：所有写操作经 `log_change()` 记录审计日志；SQLite 无迁移框架——新表由 `create_all` 创建，旧表新增列由 `db.py::_migrate()` 通过 `PRAGMA table_info + ALTER TABLE ADD COLUMN` 幂等补齐。

## 三、目录结构

```
AGV-项目管理/
├── CLAUDE.md            # 项目说明（含全部迭代历史，最详细的当前状态）
├── README.md            # 对外简介
├── backend/
│   ├── app/
│   │   ├── main.py      # FastAPI 入口 + 前端静态托管 + /health
│   │   ├── models/      # SQLAlchemy 模型（27 张表）
│   │   ├── routers/     # 业务 API（含 inventory / ai_projects）
│   │   ├── services/    # 权限/任务生成/排程/进度/状态机/导入导出/节假日
│   │   └── seed/        # 种子数据（用户/模板树/准备项/采购项）
│   └── tests/           # pytest 181+ 用例
├── frontend/src/
│   ├── pages/pm/        # 管理端页面（项目/模板/人员/数据/用户）
│   ├── pages/worker/    # 现场端（今日/日程/问题/我的）
│   ├── constants/       # 状态/角色/问题分类 单一事实源
│   └── api/             # axios 封装 + 接口定义
├── docker/              # Dockerfile + docker-compose.yml + verify.sh
├── data/                # 运行时数据（SQLite + 上传文件）
└── docs/                # architecture / deployment / user-guide
```

## 四、角色体系

8 角色，分**管理端**与**现场端**：

| 角色 | 定位 | 主要能力 |
|---|---|---|
| admin 系统管理员 | 管理后台 | 用户/小组/模板/全部项目 |
| director 总监 | 管理端 | 全部项目可见与治理审批 |
| pm 项目经理 | 管理端 | 自己负责的项目全量管理 |
| lead 技术经理 | 管理端 | 被指定项目的计划/日程/技术问题/导出 |
| technician 技术工程师 | 现场端 | 填报/检查项/交付物（只读项目资料） |
| worker 实施工程师 | 现场端 | 同上（主要角色） |
| intern 实习工程师 | 现场端 | 同上 |

**权限框架**：`project_capabilities(user, project)` 返回项目级能力集合（update/members/plan/schedule/issues/inventory/export/archive/delete），`require_project_capability()` 做依赖注入；可见性由 `ensure_project_visible()` 保证。项目协管可在期限内共同维护执行过程，但不能删除、移交或继续授权。

## 五、数据模型（27 表）

- **User**（token_version 令牌版本 / group_id 小组 / is_active）
- **OrgGroup**（组织小组：大组→小组两级，leader_id 组长）
- **Project**（状态机相邻流转：日程确认 planning→ready；进度 80%/90%/95% 每次最多自动推进一档至 acceptance；acceptance→completed 需人工确认且进度 100%；completed→archived 仍人工；schedule_version 日程版本；prep_conditions 准备条件；template_id/template_version 记录模板来源；readiness_state 进场就绪状态）
- **Vehicle / Phase / Module / Task / CheckItem**（模板树与项目任务）
- **ScheduleEntry**（排程条目，可锁定/下达版本）
- **DailyProgress**（现场填报流水，离线队列批量同步）
- **Issue**（问题台账：分类专属字段存 extra JSON，SLA 超时标记）
- **Attachment**（附件挂载 project/task/issue，10MB 上限）
- **Notification**（消息通知）
- **TemplatePreparationItem / TemplateProcurementItem**（模板级准备项/采购项，condition 分组）
- **ProjectPreparationItem**（项目准备项：四日期/责任双层/评审快照）
- **ProjectReadinessReview**（进场评审历史+快照）
- **ProjectInventoryItem / ProjectInventoryMovement**（现场物品当前态与不可丢失的流转历史）
- **TemplateDoc**（模板任务参考文档）
- **TeamTemplate / ChangeLog**（团队模板 / 审计日志）

## 六、核心业务流程

### 1. 模板配置（模板中心）
（当前页面见[模板阶段主线](template-stage-backbone.md)：模板库 + 全宽编辑页，工作分组挂在第 4–9 阶段。以下为旧版树形编辑器的历史描述。）9 阶段树（项目准备/进场准备/到货检查/单车调试/地图与站点/系统部署/系统联调/试运行/培训验收）→ 阶段→模块→任务→检查项 4 级树，在线编辑器（默认只读，「开始编辑」后增删改，保存树整体提交）。任务可配：数量规则（按车辆/手动/固定）、适用车型、安全标记、**提交文件**（交付物要求：名称/必需/文件类型/说明）、**参考文档**（上传文件，生成时自动复制）、准备属性（项目准备阶段任务）。

模板中心另有平级区块：
- **准备清单**（TemplatePreparationItem）：分类（范围资料/采购/车辆/软件/进场条件）+ 生成条件（default/need_wms/need_charging/client_server/new_vehicles/overseas）+ 责任方/阻塞/风险
- **采购清单**（TemplateProcurementItem）：物料/数量/单位/规格/**需求周期（相对计划进场 ±N 周）**/生成条件——项目创建时自动生成「项目采购」准备项，需求日期按进场日自动换算

模板支持：版本管理（草稿/已发布 vN + 使用计数）、复制（自动带走树/准备项/采购项）、Excel 导出导入、JSON 导出。

### 2. 项目创建与任务生成
创建项目：名称/客户/地点/周期/**内部启动会、发车、全部到场的计划日期和调度平台**/条件选项（WMS/充电/服务器/新造车辆/海外）→ 自动播种准备项+采购项。然后按模块勾选生成任务：per_vehicle 数量按车型配置自动计算；生成后任务可编辑（名称/目标数量/单位）。

### 3. 自动排程
按 阶段顺序 + 标准工时估算（历史填报统计+默认值）→ 生成排程条目（日期×任务×人员），支持：锁定期（已下达版本不受影响）、休息规则（休周日/周六日 + 中国法定节假日内置 2024-2026 表）、手动补充休息日、拖拽调整、**排程预览**（事务内模拟生成再回滚，确认才落库）、日程版本 vN 下达通知全员。

### 4. 现场工作台（PWA 离线）
Worker 今日任务折叠卡片：填报数量（防超填）、检查项三态（通过/不通过必填原因/不适用）、交付物提交（拍照上传）、问题上报、**参考文档下载**、离线队列（本地保存→联网同步，退出登录前未同步警告）。

### 5. 进度与统计
计划 vs 实际自动统计；项目状态相邻流转（日程确认 planning→ready；进度 80%/90%/95% 每次最多自动推进一档至 acceptance；acceptance→completed 需人工确认且进度 100%，completed→archived 仍人工）；PM 数据总览一屏巡检（风险指标带 RAG + 逾期/未解决内联 Top5 + 项目状态表）。

### 6. 准备与进场评审
准备项独立状态机（preparing→risky→pending_confirm→ready，就绪失效自动回退+通知 PM）；四日期（要求/承诺/预计/实际）；责任双层（责任方 5 类 + 内部跟进人）；评审流（清单→三选一结论+风险项+**当时快照**）。

### 7. 交付物审核流
deliverables 状态机 pending→submitted→approved/rejected（PM 审核，退回必填原因）；成员提交后勾选锁定。

### 8. 分域 AI 与现场物品
项目建档、计划排程、问题研判、现场物品、交接归档、文档归类使用 6 个独立 Skill。AI 请求通过服务端兼容 DeepSeek、MiMo、MiniMax，异步进度可见；结果都要经过结构与业务校验。物品在项目内维护，在全局按可见项目聚合，区分我方/甲方/第三方并保留出入库流水。

## 七、部署

```bash
# 本机/服务器构建启动（项目根目录）
docker compose --env-file .env -f docker/docker-compose.yml up -d --build

# 端到端验证（独立临时容器，不污染数据，9 步烟测）
bash docker/scripts/verify.sh
```

- 单容器：Nginx 不需要，FastAPI 直接托管前端 dist
- 数据持久化：`data/` 挂载卷（SQLite + UPLOAD_DIR 上传文件）
- `SECRET_KEY` 持久化到 `data/secret.key`（重启不失效，NAS 迁移拷贝该文件）
- `SEED_DEMO_USERS=0` 环境变量：生产只建 admin，不建演示账号
- fresh 生产库必须设置 `INITIAL_ADMIN_PASSWORD`；`SECRET_KEY` 留空时自动生成并持久化
- `bash docker/scripts/backup.sh` 在线一致性备份数据库、附件与密钥
- 部署细节见 `docs/deployment.md`（含 NAS 磁盘/内存/备份建议）

演示模式账号：`admin/admin123`、`pm/pm123`、`worker1/worker2/worker123`。生产模式仅创建 `admin`，密码取 `INITIAL_ADMIN_PASSWORD`。

## 八、设计决策与演进记录（要点）

1. **版本策略**：前端 package.json 版本号是 PWA 缓存失效的唯一驱动（每次功能迭代必 bump，否则用户会继续看到旧 UI）；发布检查会同步校验后端、Docker 与前端版本
2. **SQLite 无迁移框架**：`ensure_column()` 幂等补列 + user_version 守卫；模型变更重部署前备份 data/
3. **模板驱动的准备/采购**：准备项、采购项都定义在模板里，项目创建时按条件实例化——"配置一次，项目自动带"
4. **任务自包含**：参考文档/交付物生成时复制到项目任务（JSON + 物理文件），模板后续修改不影响已有项目
5. **能力型权限 + 项目关系**：技术角色必须被项目明确指定，实施角色必须被加入成员
6. **审计全链路**：写操作 log_change → 项目动态页可追溯
7. **项目工作区**：8 个过程型 Tab（总览/准备/计划/日程/现场信息/问题/交付/动态），编辑和导出为独立工具页。

## 九、测试与质量

- 后端 pytest 181+ 用例（权限矩阵/准备系统/排程规则/物品流水/AI任务/参考文档/采购项/导入导出/安全边界/离线幂等等）
- `docker/scripts/verify.sh` 9 步端到端：健康检查→登录→建项目→生成任务→排程→调整→问题→导出→PWA（独立临时容器，无卷，不污染生产数据）
- 前端 `npx tsc --noEmit` + `npm run build` 双门禁

## 十、给 AI 的建议提问方向（示例）

- 架构评审：SQLite 单容器在 100 项目/50 用户规模下的瓶颈与优化
- 功能评审：模板系统（9 阶段树 + 准备项 + 采购项 + 参考文档）还有什么高频场景没覆盖
- 移动端体验：现场端 PWA 的离线填报与冲突处理
- 安全评审：JWT 双令牌 + 令牌版本失效 + 能力型权限的组合设计
- 报表：进度统计/甘特图/交付物审核的维度扩展

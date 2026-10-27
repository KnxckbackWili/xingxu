# 技术架构

React / TypeScript 前端构建为静态文件，由 FastAPI 同源提供页面和 `/api/*`。业务服务通过 SQLAlchemy 访问 SQLite 或 PostgreSQL；启动时先执行 Alembic 迁移，再初始化缺省模板及管理员。迁移约定见仓库 `CLAUDE.md`，不通过应用启动补列或 `create_all` 绕过版本迁移。

## 运行方式

- 本地开发和单进程测试可使用 SQLite，启用 WAL 与 busy timeout。
- PostgreSQL 支持独立数据库部署及多 Web worker；项目锁、版本校验与审计在同一事务提交。
- 容器分别管理 Web、调度与健康监测进程。数据库由 `DATABASE_URL` 选择；具体部署配置见 [部署说明](deployment.md)。
- 认证使用 JWT 与账号会话版本；业务能力、系统权限和项目可见性共同约束请求。

## 业务服务

| 服务 | 职责 |
|---|---|
| `projects` / `project_lifecycle` | 项目资料、成员及显式生命周期操作 |
| `tasks` / `scheduler` | 实施任务、工作规则、日程生成与分配 |
| `availability` | 人员不可用时段及跨项目安排提示，按所有者与授权保护隐私 |
| `worker` / `progress` | 现场填报、离线幂等同步、可追溯修正及进度汇总 |
| `issues` / `inventory` / `vehicle_*` | 项目问题、现场物品、单车事件与履历 |
| `project_documents` / `generated_document_forms` / `report_forms` | 项目资料规则、真实文件版本与业务表单 |
| `project_deletion` / `project_retention` | 可恢复删除、历史文件引用与归档保全 |
| `ai_project_assistant` / `ai_jobs` | 项目、排程、物品、问题及交接的结构化整理任务 |
| `ai_mcp` / `agent` | 外部只读查询与事务内排程模拟 |
| `report_scheduler` | 周报、问题超时提醒和通知投递 |

## 接口入口

用户账号管理使用 `/api/users`，不可用时段使用 `/api/users/:id/unavailability`。项目、执行任务、日程、填报、问题、物品、文件、导入导出和审计保持各自业务路由。准确参数以部署实例的 OpenAPI 文档 `/docs` 为准。

AI 整理入口位于 `/api/ai-projects`，保留状态、能力清单、结构化整理、持久任务查询及 Skill 下载。外部工具入口见 [Agent 接入](ai-internal-api.md)，工具目录通过 `GET /api/agent/tools` 按令牌范围返回。

## 数据与历史

当前 ORM 仅声明仍在运行的业务模型。历史迁移使用冻结快照，避免随现版本模型变化而破坏升级。T03 对退休数据先导出、验证，再删除旧表与字段；正式项目、账号安全字段和附件逐项对账。历史数据读取与文件处置见 [功能下线说明](retired-features.md)。

数据库备份、附件、持久 `SECRET_KEY` 与迁移导出应按同一恢复流程保存。项目文件删除仍检查活动引用和旧归档快照，避免破坏可恢复数据。

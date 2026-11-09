# 技术架构

## 运行方式

- 本地开发和单进程测试可使用 SQLite，启用 WAL 与 busy timeout。
- PostgreSQL 支持独立数据库部署及多 Web worker；项目锁、版本校验与审计在同一事务提交。
- 容器分别管理 Web、调度与健康监测进程。数据库由 `DATABASE_URL` 选择；具体部署配置见 [部署说明](deployment.md)。
- 认证使用 JWT 与账号会话版本；账号只有员工和系统管理员两种，见[账号与权限](accounts.md)。

## 业务服务

| 服务 | 职责 |
|---|---|
| `projects` / `project_lifecycle` / `project_transfer` | 项目资料、负责人及显式生命周期操作 |
| `template_items` / `work_items` | 模板段落与事项、项目阶段与工作项 |
| `weekly_plans` | 周计划、初稿与发布 |
| `field_operations` / `field_week` / `progress` | 现场实际登记、离线幂等同步、修订及进度汇总 |
| `issues` / `inventory` / `vehicle_*` | 项目问题、现场物品、单车事件与履历 |
| `project_documents` / `generated_document_forms` / `report_forms` | 项目资料规则、真实文件版本与业务表单 |
| `project_deletion` / `project_retention` | 可恢复删除、历史文件引用与归档保全 |
| `report_scheduler` | 周报、问题超时提醒和通知投递 |

## 接口入口

用户账号管理使用 `/api/users`。项目、工作项、周计划、现场登记、问题、物品、文件、导入导出和审计保持各自业务路由。准确参数以部署实例的 OpenAPI 文档 `/docs` 为准。

## 数据与历史

当前 ORM 仅声明仍在运行的业务模型。历史迁移使用冻结快照，避免随现版本模型变化而破坏升级。T03 对退休数据先导出、验证，再删除旧表与字段；正式项目、账号安全字段和附件逐项对账。历史数据读取与文件处置见 功能下线说明。

数据库备份、附件、持久 `SECRET_KEY` 与迁移导出应按同一恢复流程保存。项目文件删除仍检查活动引用和旧归档快照，避免破坏可恢复数据。

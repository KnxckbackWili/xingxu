# 行序开发指引

## 目录与命令

- `backend/app/models`：当前模型；`routers`：接口；`services`：业务；`backend/migrations`：冻结历史与增量迁移；`backend/tests`：回归。
- `frontend/src`：React 页面、API、离线队列与组件；`frontend/package.json`：前端命令。
- `docker`：镜像、受管部署、宿主更新和备份；`docs/index.md`：主题文档；[术语表](docs/glossary.md)：业务名称与边界。
- 后端使用 Python 3.12 和虚拟环境；本地入口 `python -m uvicorn app.main:app --reload --port 8000`。前端 `npm run dev`、`npm test`、`npm run build`。
- 后端 SQLite 回归只用临时目录里的文件库（与 CI 相同；连接池参数不支持 `sqlite://` 内存库）。首个用例完成全链迁移后，其余用例从同一快照恢复：

```sh
cd backend
task_data_dir="$(mktemp -d)"
env -u DATABASE_URL DATA_DIR="$task_data_dir" .venv/bin/python -m pytest tests
```

**pytest fixture 会清空全部表；PostgreSQL 测试仅使用新建专用测试库，绝不能指向真实备份恢复库或业务库。** 真实迁移验证和运维按独立脚本及部署说明执行。

## 编码约定

- 沟通和业务文案使用中文。新文档按主题放 `docs/`；QA 原件放仓库外，更新[证据清单](docs/evidence-archive.md)。
- 业务写入在同一事务中完成当前身份、项目归属、能力和版本复核，并通过 `log_change()` 留痕。新增写路由时先读[权限声明](docs/route-permissions.md)；声明必须对应真实 handler 动作，保留认证和资源检查。
- 改资料、文件、导出或后台任务时先读[项目资料](docs/project-documents.md)、[保密边界](docs/confidential-documents.md)和[存储清理](docs/resumable-storage.md)。当前文件与全部引用家族共同决定可见性；生成文档同样核对来源和输出范围。
- 改状态、门禁或日期时先读[人工状态与签单](docs/project-lifecycle-v3.md)、[完成核对](docs/completion-review.md)和[截止规则](docs/document-deadlines.md)。使用真实来源和现场时区；登记时间、业务日期、计划日期分别表达。
- 改车辆或进度时先读[车辆进度](docs/vehicle-progress.md)与[逐车检查](docs/vehicle-checks.md)。旧数量、未知车号和只读来源不转成新发生的完成事实。
- 所有 schema 与旧数据转换通过单链 Alembic；历史修订使用冻结 SQL/schema，不导入未来 ORM。新库与存量 SQLite/PostgreSQL 均核对，包含数据迁移的修订必须在线运行，不能用 stamp 或离线 DDL 跳过。
- 改删除、恢复或退役数据时先读[项目保全](docs/project-retention.md)、[加密备份](docs/encrypted-backups.md)和[功能下线](docs/retired-features.md)。原件、快照、版本和已授权清理凭据一起保全。

完成变更后跑触达模块和必要迁移/并发校验；前端构建通过后再交接。保留既有明确授予/禁止、历史来源与真实附件；报告区分代码实现、自动测试、实际网页验收和部署结果。

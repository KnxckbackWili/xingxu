# 行序开发指引

## 目录与命令

- `backend/app/models`：当前模型；`routers`：接口；`services`：业务；`backend/migrations`：从基线开始的迁移；`backend/tests`：回归。
- `frontend/src`：React 页面、API、离线队列与组件；`frontend/package.json`：前端命令。
- `docker`：镜像、受管部署、宿主更新和备份；`docs/index.md`：主题文档；[术语表](docs/glossary.md)：业务名称与边界。
- 后端使用 Python 3.12 和虚拟环境；本地入口 `python -m uvicorn app.main:app --reload --port 8000`。前端 `npm run dev`、`npm test`、`npm run build`。
- 后端 SQLite 回归只用临时目录里的文件库（与 CI 相同；连接池参数不支持 `sqlite://` 内存库）。首个用例从基线建库并写入种子数据，其余用例从同一快照恢复：

```sh
cd backend
task_data_dir="$(mktemp -d)"
env -u DATABASE_URL DATA_DIR="$task_data_dir" .venv/bin/python -m pytest tests
```

PostgreSQL 回归同样只在首个用例建库，其余用例按内存中的行快照 TRUNCATE 后 COPY 恢复；用例改动过表结构时自动回退为全量重建。

**pytest fixture 会清空全部表；PostgreSQL 测试仅使用新建专用测试库，绝不能指向真实备份恢复库或业务库。** 真实迁移验证和运维按独立脚本及部署说明执行。

## 不背旧数据

- 不为旧数据、旧格式、旧接口做兼容。改一个功能时直接改成新的样子，用不上的表、字段、接口、页面和测试一起删掉。
- 数据库从基线修订 `h0b0000000001` 开始。基线之前的数据库，启动时会原样挪开：SQLite 文件移到 `DATA_DIR/old-<时间>/`，PostgreSQL 移到 `old_<时间>` 架构，上传文件跟着移走，然后系统从空库开始。迁移前的加密备份照常生成。
- 发布前改表结构：用 `alembic` 自动生成的方式重新生成基线（修订号不变），不叠加迁移。基线发布后再改表结构，才在基线之上新增修订；新增修订只管表结构，不搬运旧数据。

## 编码约定

- 沟通和业务文案使用中文。新文档按主题放 `docs/`；QA 原件放仓库外，更新[证据清单](docs/evidence-archive.md)。
- 业务写入在同一事务中完成当前身份、项目归属、能力和版本复核，并通过 `log_change()` 留痕。新增写路由时先读[权限声明](docs/route-permissions.md)；声明必须对应真实 handler 动作，保留认证和资源检查。
- 改资料、文件、导出或后台任务时先读[项目资料](docs/project-documents.md)、[保密边界](docs/confidential-documents.md)和[存储清理](docs/resumable-storage.md)。当前文件与全部引用家族共同决定可见性；生成文档同样核对来源和输出范围。
- 改状态、门禁或日期时先读[人工状态与签单](docs/project-lifecycle-v3.md)、[完成核对](docs/completion-review.md)和[截止规则](docs/document-deadlines.md)。使用真实来源和现场时区；登记时间、业务日期、计划日期分别表达。
- 改车辆或进度时先读[车辆进度](docs/vehicle-progress.md)与[逐车检查](docs/vehicle-checks.md)。
- 改删除或恢复时先读[项目保全](docs/project-retention.md)和[加密备份](docs/encrypted-backups.md)。

完成变更后跑触达模块的测试；前端构建通过后再交接。报告区分代码实现、自动测试、实际网页验收和部署结果。

# 行序开发指引

行序只做记录和查看：每个项目的车辆、工作、问题、资料、物品，多人同时编辑，首页显示缺口。不加审批、角色、截止日期、通知这类管控功能，除非用户明确要求。

## 目录与命令

- `backend/app/models.py`：16 张表；`records.py`：各类记录的栏目声明；`routers`：接口；`services`：缺口、Excel、文件、清理，以及沿用的登录、备份、更新；`backend/migrations`：从基线开始的迁移；`backend/tests`：测试。
- `frontend/src`：`components/Grid.tsx` 是全站唯一的可编辑表格；`sync/` 是自动同步和按格子保存；`pages/` 是页面。
- `docker`：镜像、部署、宿主更新和备份；`docs/index.md`：文档入口；[术语表](docs/glossary.md)。
- 后端使用 Python 3.12 和虚拟环境；本地入口 `python -m uvicorn app.main:app --reload --port 8000`（空库首次启动加 `SEED_DEMO_USERS=1` 或 `INITIAL_ADMIN_PASSWORD`）。前端 `npm run dev`、`npm test`、`npm run build`。
- 后端 SQLite 测试只用临时目录里的文件库：

```sh
cd backend
task_data_dir="$(mktemp -d)"
env -u DATABASE_URL DATA_DIR="$task_data_dir" .venv/bin/python -m pytest tests
```

首个用例从基线建库并写入初始数据，其余用例从同一快照恢复。PostgreSQL 同理，把 `DATABASE_URL` 指向测试库即可。

**pytest fixture 会清空全部表；PostgreSQL 测试仅使用新建专用测试库，绝不能指向真实备份恢复库或业务库。**

## 不背旧数据

- 不为旧数据、旧格式、旧接口做兼容。改一个功能时直接改成新的样子，用不上的表、字段、接口、页面和测试一起删掉。
- 数据库从基线修订 `i0c0000000001` 开始。基线之前的数据库，启动时原样挪开（SQLite 文件移到 `DATA_DIR/old-<时间>/`，PostgreSQL 移到 `old_<时间>` 架构，上传文件跟着移走），只把账号带进新库，然后系统从空的开始。见[从 3.x 升级到 4.0](docs/upgrade-to-4.md)。
- 基线已发布：改表结构只在基线之上新增修订，修订只管表结构，不搬运旧数据。

## 编码约定

- 沟通和业务文案使用中文。新文档按主题放 `docs/`，只写现在的规则；检查记录、整改清单这类过程材料不进仓库。
- **加一个栏目或一类记录**：改 `models.py` 和 `records.py` 的声明，再加迁移修订。接口、项目快照、Excel、操作记录都读这份声明，不要在别处重复写栏目规则。先读[数据表](docs/data-model.md)。
- **每次写入**在同一事务里：确认账号 → 确认项目存在且未删除 → 比对原值 → 写入 → `log_change()` → 项目 `rev` 加 1。漏了 `rev` 别人的页面就不会更新。先读[多人编辑](docs/multi-user-editing.md)。
- **每个接口**必须声明谁能调用：依赖 `get_current_user`、`require_admin`，或 `@public("原因")`。漏声明应用启动不了。先读[接口](docs/api.md)。
- **删除**一律软删除（`deleted_at`），30 天后由 `services/cleanup.py` 清除；带文件的记录清除时连文件一起删。
- **“缺”的规则**只有五条，后端在 `services/gaps.py`，前端在 `pages/project/context.ts`，两处必须一致。
- **页面**：清单一律用 `components/Grid.tsx`，不另写表格和弹窗表单；颜色只用 `styles/tokens.css` 的变量；人名用 `Person`。先读[界面样式](docs/visual-style.md)。每个页面都要在手机宽度下看一眼。
- 改备份、软件更新、部署脚本前先读[加密备份](docs/encrypted-backups.md)、[软件更新](docs/software-updates.md)和[部署](docs/deployment.md)。

完成变更后跑触达模块的测试；前端构建通过后再交接。报告区分代码实现、自动测试、实际网页验收和部署结果。

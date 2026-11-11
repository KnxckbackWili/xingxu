# 数据表

一共 16 张表，定义在 `backend/app/models.py`，迁移从基线 `i0c0000000001` 开始。

除账号、车型、勾和操作记录外，每张表都有 `id`（客户端生成的 UUID）、`created_at`、`created_by`、`updated_at`、`deleted_at`。`deleted_at` 有值表示在回收站里。

| 表 | 存什么 | 主要字段 |
| --- | --- | --- |
| `users` | 账号 | username、display_name、password_hash、role（admin / employee）、is_active、token_version |
| `login_failures` | 登录限速（PostgreSQL 下多个进程共用） | key、bucket、count |
| `projects` | 项目 | name、contract_no、customer、note、is_closed、**rev** |
| `project_steps` | 项目的车辆环节列 | project_id、name、sort_order |
| `vehicles` | 车辆 | project_id、vehicle_no、fleet_no、model、config_no、note、sort_order |
| `vehicle_marks` | 车辆环节的勾 | vehicle_id、step_id（联合唯一）、done_by、done_at。有这一行就是做了 |
| `vehicle_records` | 车辆记录 | vehicle_id、happened_on、category、content、recorded_by_name、recorded_on |
| `work_items` | 工作 | project_id、stage、name、note、done、done_by、done_at、sort_order |
| `issues` | 问题 | project_id、vehicle_id（可空）、description、resolution、is_closed、closed_by、closed_at |
| `documents` | 资料清单项 | project_id、name、note、sort_order |
| `items` | 物品 | project_id、name、spec、quantity、unit、arrived、arrived_by、arrived_at、note、sort_order |
| `files` | 上传的文件 | project_id、owner_kind（document / issue / other）、owner_id、filename、size、mime、sha256、storage_path |
| `templates` | 模板 | name、note、rev |
| `template_rows` | 模板的四张清单 | template_id、kind（work / document / step / item）、stage、name、spec、quantity、unit、sort_order |
| `vehicle_types` | 车型库 | name（唯一）、note、is_enabled、sort_order |
| `change_logs` | 操作记录 | seq（自增）、project_id、user_id、user_name、kind、row_id、row_label、action、field、old_value、new_value、detail |

## 约定

- **`rev`**：项目（或模板）里的任何写入，在同一事务里把它加 1。页面靠它判断有没有变化，见[多人编辑](multi-user-editing.md)。
- **字段规则只写一处**：`backend/app/records.py` 里每类记录一份声明（栏目、类型、长度、是否必填、打勾时记谁）。接口、项目快照、Excel 和操作记录都读这份声明。新增或修改栏目只改这里和 `models.py`。
- **车辆编号唯一**由代码在未删除的车辆里检查，不建数据库唯一约束（回收站里的车不占用编号）。
- **文件**在磁盘上是 `DATA_DIR/uploads/<项目>/<文件编号>`，原始文件名只在数据库里。
- **操作记录**不设外键，项目被彻底清除后记录仍在。
- **清理**：`services/cleanup.py` 每小时把回收站里满 30 天的记录、文件和项目彻底删除。

## 改表结构

基线发布后，改表结构一律在基线之上新增修订，修订只管表结构。旧数据库不升级，见[从 3.x 升级到 4.0](upgrade-to-4.md)。

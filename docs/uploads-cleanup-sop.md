# 附件清理 SOP（运维手册）

> 对应 HYPE-39《突发状态应对方案》修订版「建议改造清单」第 7 项（报告基线 `30f0e34`）。
> 本文是**运维人员执行手册**，只覆盖「磁盘空间紧张、扩容不可行」时的最后手段——附件清理。
> 本文**不进入任何自动化预案，不提供自动删除脚本**（见 §9）。
> 2026-10-01 第六轮补正：保留期归档中的文件仍有业务所有权，不得因原附件行被清理而当作孤儿。数据库快照/哈希不包含文件字节，完整系统备份仍不可省略。

## 1. 目的与适用范围

在系统数据卷磁盘空间紧张、且扩容无法立即实施时，运维人员按本文流程**人工逐项清理过期附件**，并在清理前强制备份、清理后保留审计。

适用范围：Multica 验收部署（单容器，容器名 `agv-pm-8002`，容器内 PostgreSQL，数据卷 `agv-pm-multica-data` 挂载为 `/app/data`）。依据：

- 容器名与端口：`docker/docker-compose.multica.yml:20`（`container_name: ${AGV_CONTAINER_NAME:-agv-pm-8002}`）、`:22`（`0.0.0.0:${APP_PORT:-8002}:8000`）。
- 数据卷：`docker/docker-compose.multica.yml` 命名卷 `agv-pm-multica-data` 挂载到 `/app/data`；容器内数据根目录由 `DATA_DIR=/app/data` 指定（`:41`）。
- 容器内 PostgreSQL：`docker/docker-compose.multica.yml:43`（`USE_POSTGRES=1`）、`docker/start.sh:40`（`DATABASE_URL=postgresql+psycopg2://agv:agv@127.0.0.1:5432/agvpm`）。

## 2. 触发前提：扩容优先，清理是最后手段（D2 场景）

**先扩容，后清理。** 只有扩容不可行（宿主机磁盘整体紧张、无额外卷可挂）时才进入本文流程。

判断「磁盘紧张」的信号：

1. `df -h` 数据卷使用率接近满（建议 ≥80% 即告警预防）。
2. 上传、备份或写库报 `No space left on device`。
3. PostgreSQL 写事务失败（数据卷内 `pgdata`）。

**扩容手段（优先）**：

- 为数据卷 `agv-pm-multica-data` 扩容（宿主磁盘/LVM/存储池扩卷），随后 `docker compose -f docker/docker-compose.multica.yml up -d` 重建容器，`make status` 确认健康。
- 扩容后写路径自动恢复；**不要**在扩容方案确定前去动 `uploads/`。

**进入清理流程的唯一前提**：已确认当前无法扩容，且磁盘空间不足已影响业务写路径。此判断须记录在审计单（§7）中。

## 3. 「过期附件」判定标准

### 3.1 存储与数据模型

- 附件文件实体统一存放在 `UPLOAD_DIR`，容器内路径为 `/app/data/uploads`；`backend/app/config.py:48-49`（`UPLOAD_DIR = DATA_DIR / "uploads"`，启动即建目录）。
- 附件元数据在 `attachments` 表（`backend/app/models/__init__.py:510`）：`entity_type` 仅可为 `project/task/issue`（`:515`），`entity_id` 指向挂载对象（`:516`），磁盘文件名 `stored_name`（`:519`，上传时由 `uuid4().hex + 原扩展名` 生成，见 `backend/app/routers/attachments.py:101`），上传人 `uploaded_by`（`:522`），上传时间 `uploaded_at`（`:523`）。
- 文件写入与读取都只经 `UPLOAD_DIR / stored_name`（`backend/app/routers/attachments.py:102-103, 135-136`）。**因此清理必须同时处理 DB 行与磁盘文件，且磁盘文件名只能通过 `stored_name` 对应，不允许按业务文件名猜测。**

### 3.2 判定对象：两类可清理目标 + 明确的排除范围

**目标 A —— 过期附件**（`attachments` 表中满足「业务对象已终态 + 超过保留期 + 未被归档/验收/交付/生命周期引用」的记录）：

业务对象终态按代码字段判定：

| 挂载对象 | 终态判定字段 | 依据 |
|---|---|---|
| `entity_type='issue'` | 所属 issue 的 `status = 'closed'` | `backend/app/models/__init__.py:436`（`# open / processing / resolved / closed`） |
| `entity_type='project'` 或 `'task'` | 所属项目 `status = 'archived'`（终态） | `backend/app/models/__init__.py:100`（注释 `draft -> … -> completed -> archived`）；Task 无状态字段（`:327`，`class Task` 无 `status` 列），任务附件一律以所属项目状态为准 |

时间字段统一取附件自身的 `uploaded_at`（`:523`）。**保留期**为运维参数，本 SOP 默认 **180 天**（`uploaded_at < now() - INTERVAL '180 days'`）；调大调小由执行人在审计单（§7）中写明。

**明确排除（不得作为目标 A 清理）**——下列引用会导致删除后下载 404、破坏交付/验收/归档证据：

- `archive_checklists.attachment_id` 引用的附件（`backend/app/models/__init__.py:557`，交付归档资料）。
- `acceptance_records.attachment_id` 引用的附件（`:576`，验收报告/照片）。
- `inbox_documents.archived_attachment_id` 引用的附件（`:864`，AI 收件箱归档到项目的附件）。
- `vehicle_lifecycle_events.attachment_id` 引用的附件（`:204`，车辆生命周期事件证据）。任务交付物按 `entity_type='task'` 上传并把附件 ID 写回 `tasks.deliverables[].attachment_id`（`:345`；上传入口见 `frontend/src/pages/pm/project/TaskPlanPage.tsx:133-140`、`frontend/src/pages/worker/TodayPage.tsx:266-271`），删除后交付物下载会 404（`frontend/src/pages/pm/project/DeliveryPage.tsx:115-116`），同样必须排除。
- 回收站项目的附件：项目不会自动到期，不得因 deleted_at 时间较旧而清理文件。仅在管理员已明确永久删除且加密项目备份独立验证完整后，才能继续核对孤儿文件。升级前旧归档的留存快照 `type=agvpm-project-retention` 的 `project_archives.snapshot.binary_files.manifest[]` 继续拥有对应文件。**原附件行消失不意味着文件成为孤儿**。清单保存 `stored_name`、`filename`、`references[{table,id}]`、`available_at_purge`、`sha256` 和 `size`；不嵌入文件字节。
- 任何 `project_archives.snapshot.binary_files.manifest[].stored_name` 命中的文件均排除，即使 `available_at_purge=false` 或当前文件有问题，也不能自行删除后掩盖证据缺失。旧归档没有清单时，旧四处引用查询无法证明文件无留存价值；先与清理前备份/旧归档来源逐项核对，无法判定则保留，不批量按孤儿处理。

**目标 B —— 孤儿文件**（`/app/data/uploads` 下存在、但无任何 DB 或 JSON 引用的文件）：

磁盘文件的所有合法引用来源（5 类）都不命中，且旧归档兼容核对已完成，才可列为孤儿候选：

1. `attachments.stored_name`（`:519`）
2. `template_docs.stored_name`（`:822`，模板任务参考文档）
3. `inbox_documents.stored_name`（`:853`，AI 收件箱文件）
4. `tasks.reference_docs` JSON 数组内的 `stored_name`（任务参考资料）
5. `project_archives.snapshot.binary_files.manifest` JSON 数组内的 `stored_name`（物理清理后的项目证据文件）

> 注意：模板参考、收集箱原件、任务参考及项目留存归档中**仍被引用**的文件均不属于清理范围。归档 JSON 与 `verify` 校验成功不能代替文件存在/内容校验，也不能用作删除其清单文件的理由。

### 3.3 判定 SQL（只读，列候选清单）

先定义容器内 psql 便捷调用（容器内 psql 不在 PATH，须全路径；版本目录用通配符，约定见 `docker/start.sh:12`）：

```bash
psql() { docker exec agv-pm-8002 sh -c 'PGPASSWORD=agv /usr/lib/postgresql/*/bin/psql -h 127.0.0.1 -U agv -d agvpm "$@"' _ "$@"; }
```

数据库角色 `agv`、库 `agvpm`，连接串依据 `docker/start.sh:40`。以下查询均**只读**，不产生任何删除副作用。

**候选 A-1：已关闭 issue 的附件**

```sql
SELECT a.id, p.name AS 项目, a.entity_type AS 挂载类型, a.entity_id AS 挂载ID,
       a.category AS 分类, a.filename AS 文件名, a.file_size AS 大小,
       a.uploaded_at AS 上传时间, i.title AS 问题标题, i.resolved_at AS 问题解决时间
FROM attachments a
JOIN issues   i ON i.id = a.entity_id AND a.entity_type = 'issue'
JOIN projects p ON p.id = a.project_id
WHERE i.status = 'closed'
  AND p.deleted_at IS NULL
  AND a.uploaded_at < now() - INTERVAL '180 days'
  AND a.id NOT IN (SELECT attachment_id FROM archive_checklists  WHERE attachment_id IS NOT NULL)
  AND a.id NOT IN (SELECT attachment_id FROM acceptance_records WHERE attachment_id IS NOT NULL)
  AND a.id NOT IN (SELECT archived_attachment_id FROM inbox_documents WHERE archived_attachment_id IS NOT NULL)
  AND a.id NOT IN (SELECT attachment_id FROM vehicle_lifecycle_events WHERE attachment_id IS NOT NULL)
  AND NOT EXISTS (
      SELECT 1
      FROM project_archives pa
      CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN jsonb_typeof(pa.snapshot::jsonb->'binary_files'->'manifest') = 'array'
               THEN pa.snapshot::jsonb->'binary_files'->'manifest'
               ELSE '[]'::jsonb END
      ) AS archived_file(value)
      WHERE archived_file.value->>'stored_name' = a.stored_name
  )
  AND NOT EXISTS (
      SELECT 1
      FROM tasks t
      CROSS JOIN LATERAL jsonb_array_elements(t.deliverables::jsonb) d
      WHERE t.deliverables IS NOT NULL
        AND jsonb_typeof(t.deliverables::jsonb) = 'array'
        AND d->>'attachment_id' = a.id
  )
ORDER BY a.uploaded_at;
```

**候选 A-2：已归档项目下的附件**

```sql
SELECT a.id, p.name AS 项目, a.entity_type AS 挂载类型, a.entity_id AS 挂载ID,
       a.category AS 分类, a.filename AS 文件名, a.file_size AS 大小, a.uploaded_at AS 上传时间
FROM attachments a
JOIN projects p ON p.id = a.project_id
WHERE p.status = 'archived'
  AND p.deleted_at IS NULL
  AND a.uploaded_at < now() - INTERVAL '180 days'
  AND a.id NOT IN (SELECT attachment_id FROM archive_checklists  WHERE attachment_id IS NOT NULL)
  AND a.id NOT IN (SELECT attachment_id FROM acceptance_records WHERE attachment_id IS NOT NULL)
  AND a.id NOT IN (SELECT archived_attachment_id FROM inbox_documents WHERE archived_attachment_id IS NOT NULL)
  AND a.id NOT IN (SELECT attachment_id FROM vehicle_lifecycle_events WHERE attachment_id IS NOT NULL)
  AND NOT EXISTS (
      SELECT 1
      FROM project_archives pa
      CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN jsonb_typeof(pa.snapshot::jsonb->'binary_files'->'manifest') = 'array'
               THEN pa.snapshot::jsonb->'binary_files'->'manifest'
               ELSE '[]'::jsonb END
      ) AS archived_file(value)
      WHERE archived_file.value->>'stored_name' = a.stored_name
  )
  AND NOT EXISTS (
      SELECT 1
      FROM tasks t
      CROSS JOIN LATERAL jsonb_array_elements(t.deliverables::jsonb) d
      WHERE t.deliverables IS NOT NULL
        AND jsonb_typeof(t.deliverables::jsonb) = 'array'
        AND d->>'attachment_id' = a.id
  )
ORDER BY a.uploaded_at;
```

**候选 B：孤儿文件（磁盘有、引用无）**

```bash
# 1) 磁盘文件清单（UPLOAD_DIR = /app/data/uploads）
docker exec agv-pm-8002 ls -1 /app/data/uploads | sort > /tmp/uploads_disk.txt

# 2) 全部合法引用 stored_name（5 类来源；旧归档缺清单时仍须人工核对）
psql -tA -c \
"SELECT stored_name FROM attachments
 UNION SELECT stored_name FROM template_docs
 UNION SELECT stored_name FROM inbox_documents
 UNION SELECT ref->>'stored_name' FROM tasks,
       jsonb_array_elements(tasks.reference_docs::jsonb) ref
 WHERE tasks.reference_docs IS NOT NULL
   AND jsonb_typeof(tasks.reference_docs::jsonb) = 'array'
 UNION SELECT archived_file.value->>'stored_name'
 FROM project_archives pa
 CROSS JOIN LATERAL jsonb_array_elements(
     CASE WHEN jsonb_typeof(pa.snapshot::jsonb->'binary_files'->'manifest') = 'array'
          THEN pa.snapshot::jsonb->'binary_files'->'manifest'
          ELSE '[]'::jsonb END
 ) AS archived_file(value)
 WHERE archived_file.value->>'stored_name' IS NOT NULL" \
  | sort > /tmp/uploads_ref.txt

# 3) 差集 = 孤儿文件（仅列清单，不删除）
comm -23 /tmp/uploads_disk.txt /tmp/uploads_ref.txt
```

以上查询均**只读**，不产生任何删除副作用。

## 4. 人工确认流程

**不允许批量盲删。** 候选清单的每一项都必须经人逐项确认：

1. **列清单**：执行 §3.3 的三组查询，得到候选文件列表（附件 ID + 文件名 + 上传时间，或磁盘文件名）。
2. **逐项核对**：对每个候选附件，在系统内打开对应项目 → 「交付与验收 → 项目文件」（`frontend/src/pages/pm/project/DeliveryPage.tsx:125` 内嵌 `FilesPage`），按文件名/时间定位后**下载预览**，确认其业务上下文（问题已关闭、项目已归档、或纯属误传/重复/无用文件）。
3. **二次确认**：删除必须由**两名运维人员共同确认**（一人核对业务上下文、一人复核不在 §3.2 排除引用中），或由项目负责人（PM）在系统内确认。
4. **逐项决策**：每个候选文件单独打勾/打叉，**未确认的一律保留**，不因清单批量生成而批量放行。

## 5. 清理前强制备份

**执行任何删除前必须先做一次全量备份，且必须备份成功、校验通过后才允许进入 §6。**

- **命令**：在项目根目录执行 `make backup`（`Makefile:46` 的 `backup` target），或等价地 `AGV_CONTAINER=agv-pm-8002 bash docker/scripts/backup.sh`。
- **备份范围**：数据库一致性快照（PostgreSQL 走 `pg_dump -Fc`，见 `backend/app/services/system_backup.py:23-38` 与 `docker/scripts/backup.sh`）、`secret.key`、**完整 `uploads/` 目录**（附件文件实体全部在内）。
- **校验**：备份脚本会同时生成 `.sha256` 校验文件（`docker/scripts/backup.sh:104-108`）；执行人须核对校验值后再继续。
- **留存**：本次「清理前备份」归档保留至清理完成、§8 验证通过并写入审计后，才可按 `docs/deployment.md:248` 的保留建议（每日 30 份 / 每月 12 份）纳入轮转；**在任何验证完成前不得删除该备份包**。（备份包的自动轮转属改造 4 范围，不在本文流程内。）

## 6. 执行清理（逐项、经系统删除功能）

### 6.1 目标 A（过期附件）—— 使用系统删除功能，保留系统审计

系统删除端点先核对业务/共享引用，在同一事务中删除 DB 行并记录 `change_logs`；提交成功后才清理没有其他引用的磁盘文件。文件清理失败保留为待运维核对，不把已成功业务删除误报为失败。**因此目标 A 必须走系统删除，禁止直接 `rm` 或直接改表。**

归档项目为只读，正常附件删除接口会拒绝。候选查询不是绕过归档保护的授权；如业务确需先恢复项目，须由有权人员按正常恢复流程明确办理，并重新核对全部证据引用。不得为清空间直接改状态、删表或绕过 API。已被验收/归档留存引用的证据仍不能清理。

- **方式一（推荐，界面逐项删）**：系统内打开对应项目 → 「交付与验收 → 项目文件」，对清单中每一项点删除按钮（`frontend/src/pages/pm/project/FilesPage.tsx:45` 调 `DELETE /api/attachments/{id}`）。
- **方式二（单条 API）**：删除端点需要登录鉴权（`backend/app/deps.py` 要求 `Authorization: Bearer` 或 `agvpm_access` Cookie），裸 `curl -X DELETE` 会 401。两种做法：
  - 在**已登录的浏览器会话**里执行：浏览器开发者工具 Console 中执行 `fetch('/api/attachments/<附件ID>', {method:'DELETE'})`（自动带 Cookie）；
  - 或使用接口调用令牌显式携带鉴权头：
  ```bash
  curl -X DELETE \
    -H "Authorization: Bearer <access_token>" \
    http://127.0.0.1:8002/api/attachments/<附件ID>
  ```
  逐条执行，一次一条，ID 取自 §3.3 候选清单。
- **权限**：删除需项目能力 `C_UPDATE`（`backend/app/routers/attachments.py:152` 调 `authorize_project(…, C_UPDATE)`）；`C_UPDATE` 授予 admin、项目负责人（pm/lead）与项目协管（`backend/app/services/permissions.py:31, 47-58, 64`）。无权限人员只能发起、不能执行。

### 6.2 目标 B（孤儿文件）—— 逐条 `rm`，禁止脚本

孤儿文件无 DB 行、无系统删除入口，只能人工逐条删除磁盘文件。**每删除一条前，先在本机用 `ls`/`file` 复核该文件名确实在 §3.3 候选 B 的差集里。**

```bash
# 逐条删除示例（一条命令一个文件，严禁写成循环/批处理）
docker exec agv-pm-8002 rm /app/data/uploads/<孤儿文件名>
```

删除后须在 §7 审计单中逐条记录文件名与删除时间。

## 7. 审计记录

**系统侧**：目标 A 每次删除会自动写入 `change_logs`（`backend/app/services/change_log.py:9-23`，字段见 `backend/app/models/__init__.py:604-611`：`entity_type='attachment'`、`action='delete'`、`operator_id`、`detail='删除附件：{文件名}'`、`created_at`）。查询审计：

```sql
SELECT cl.created_at AS 删除时间, u.display_name AS 操作人,
       cl.entity_id AS 附件ID, cl.detail AS 内容
FROM change_logs cl
LEFT JOIN users u ON u.id = cl.operator_id
WHERE cl.entity_type = 'attachment' AND cl.action = 'delete'
ORDER BY cl.created_at DESC;
```

**人工侧（系统不保存确认依据，必须人工留存）**：执行人维护一份《附件清理审计单》，逐项记录：

1. 触发前提：磁盘紧张证据、扩容不可行的原因（§2）。
2. 判定依据：保留期取值、候选清单对应的查询与时间点（§3）。
3. 确认记录：每项由谁核对、由谁复核（§4）。
4. 备份：清理前备份文件名与 `.sha256` 值（§5）。
5. 删除：删除时间、被删附件 ID/文件名、执行人（§6）。
6. 验证：§8 各项验证结果与验证人。

## 8. 验证与收尾

1. `df -h` 确认数据卷空间已释放到可用水位。
2. 上传冒烟：向任一项目上传一个临时小文件后删除，确认写路径正常。
3. 下载冒烟：抽查仍保留的普通附件及物理清理后项目留存文件。新归档文件由有权管理员/总监调用 `GET /api/archives/projects/{project_id}/files/{stored_name}` 读取；路径必须来自该项目 manifest，接口核对路径/文件哈希。校验失败时保留证据并排查，不能用删除解决。旧归档没有文件清单时不可假定该接口能恢复旧文件。
4. 审计可查：执行 §7 系统查询，确认本次删除全部落账。
5. 备份校验：确认 §5 备份包与校验和仍在，且已按留存要求保存。
6. 收尾：把《附件清理审计单》归档到运维记录；**不创建任何定时/自动清理任务**。

## 9. 明确声明（不自动化、不提供自动删除脚本）

- 本文是**人工运维 SOP**，不进入任何自动化预案（调度器、cron、CI、`docker-compose` 启动链均不接入本流程）。
- 本文**不提供任何自动删除脚本**：不提供对候选清单的批量删除、循环删除、`find … -delete` 或定时触发删除。
- 所有删除动作均为人工逐项执行、逐项确认（§4、§6），且以 §5 备份为前提。
- 若未来需要自动化附件保留策略，应另立改造项走评审，不在本文范围内。

## 附录 A：SQLite 开发环境差异

基线 `docker-compose.yml`（SQLite 单文件 `DATA_DIR/agvpm.db`，`backend/app/config.py:20`）仅用于本地开发，不是本文 SOP 的执行环境。如需在 SQLite 下复现候选清单：

- 时间函数用 `datetime('now','-180 days')` 替代 `now() - INTERVAL '180 days'`。
- 引用查询用 SQLAlchemy 读取并精确解析 JSON，覆盖 `tasks.reference_docs` 与 `project_archives.snapshot.binary_files.manifest`；不要用文本 `LIKE` 作为“可安全删除”的判据。PostgreSQL 的 `jsonb_array_elements` SQL 不可原样用于 SQLite。
- 磁盘路径为宿主机 `data/uploads`（`DATA_DIR` 默认 `BASE_DIR/data`，`backend/app/config.py:12`）。

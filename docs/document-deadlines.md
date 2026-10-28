# 资料截止、提醒与周报（T23）

资料要求的项目快照是规则来源；`project_documents` 是实际义务和提交状态。任务数量、填报完成量和未完成安排继续表示进度，不再推导“资料逾期”。已有日程不会因事件或资料日期变化而自动移动。

## 日历、事实与预计

截止持久化为 UTC 时间，`due_basis` 同时保存项目现场 IANA 时区、规则、锚点和精度。界面按保存的依据时区展示，避免已提交快照在项目更换时区后改变含义。

| 规则 | 实例和截止依据 |
| --- | --- |
| before_event / after_event / on_milestone | 优先真实事件；仅有计划日期时按现场日历日零点作为计算锚点，明确 `due_is_estimated=true`。小时偏移按真实经过小时计算。实际时间清除后，未提交项恢复预计或等待事件。 |
| vehicle_arrival / arrival_all | T20 到场字段是日期。`actual_date_anchor`、`precision=date` 与 `actual_date` 明确这是日历锚点；不会声明事件于午夜实际发生。 |
| weekly | ISO 周、现场周一为起点。标准种子每周日 23:59 截止；自建规则尊重 `timing_weekday`。数据库使用该分钟末尾，以免 23:59 内提前算逾期。 |
| lifetime | 实际内部启动会登记后建档，无普通日期截止；归档前检查。尚未建档的必需定义也在归档检查中显示，不能因缺少实例绕过。 |
| on_trigger | 只接收真实 `trigger_ref` 与 `triggered_at`，由事件调用方核验本项目来源。按真实触发时间和规则偏移计算；当前没有允许客户端伪造该事实的公开接口。 |
| on_demand | 无截止；资料页单列“抽查”，不进入逾期。 |
| legacy | 保留历史来源，待明确分类；不自动补造新 4–9 阶段义务。 |

`services/document_deadlines.calculate` 是纯计算接口。`refresh_project` 在调用方的项目锁及同一事务内，只重算 `pending` 实例；`submitted`、`waived` 保存提交时的规则和截止快照。真实差异才增加实例版本并写审计。GET 只投影持久化状态，不生成周次、不改截止、不写审计。

实际逾期和“预计截止已过”分开统计、分开措辞。工作台、概况和跨项目看板从同一个权限过滤后的聚合读取本周待交及实际逾期，跨项目读取批量查资料和用户，不逐项发请求。

## 周期生成与调度

活跃且未删除的项目由真实调度器每 60 秒维护。周义务按项目定义、平台与真实车辆生成，组标题不生成实例。补期从定义真实创建时间、项目开始日、车辆真实创建时间的最晚者开始；候选截止还必须不早于该启用时刻，因此周二新建的“周一截止”规则不会追造昨天的义务。跨年使用 ISO 周年，DST 以现场日历划周、UTC 计算经过小时。唯一实例标识与项目锁保证重跑和并发幂等，前周未提交实例继续保留。

第6阶段（现场实施）的周资料只从项目真实进入现场实施开始生成：开始时刻取第一条把状态改为 `executing` 的状态审计；缺少结构化审计的已在现场实施/验收/完成/归档的项目回退为项目开始日。准备阶段的项目不生成第6阶段周资料，首周也不早于现场实施开始日，因此不会在进场前就出现逾期的现场周报类资料。

事件计划变更、实际事件登记/清除、车辆到场变化、项目规则或时区更新均使用同一维护服务。后台停止期间遗漏的已启用周次在恢复后补齐，不借 GET 修改数据。

`REPORT_WEEKLY_TIME` 默认 `20:00`，配置 HH:MM 表示每个项目当地周日晚的发送时间；调度器每分钟检查。每项目/ISO 周只有一个 `project_report_receipts`。首次启用只补最近已到时的周期；有真实投递游标后，重启会补齐游标之后的遗漏周期。已有相同周期的历史周报消息可接续为投递凭据。

周报按现场周期边界汇总真实版本提交、资料提交情况、当前资料逾期，以及真实 `VehicleLifecycleEvent` 的车辆状态变化。车辆阶段定义扩展由后续车辆任务接入；本服务不根据周数或数量编造状态。

缺少活跃且有读取权限的 PM 时，凭据保留 `delivery_pending=true`、`delivered_at=null`，给有权管理员发一次站内配置提示；修复负责人后重试同一个周期。发送成功会保留之前的等待信息。站内消息及选配通知使用既有 outbox，测试只写隔离数据库，不进行实际外部投递。

## 负责人和提醒

项目定义和实例均可指定 `owner_id`，默认为活跃技术负责人，再回退活跃 PM。显式指派只允许有读取权限的本项目活跃成员/负责人；停用、离项、缺失或没有保密查看权限的负责人会在资料页显示原因，并回退有权人员。指派本身不授予保密访问权。

资料页和规则编辑器提供负责人选择。独立调整实例负责人使用：

```text
PUT /api/projects/{project_id}/documents/{document_id}/owner
{"owner_id": "成员ID或null", "version": 当前实例版本}
```

路由要求 `project.manage_plan`，使用真实认证依赖、项目锁后权限复核、乐观版本和审计。未传 `owner_id` 的请求拒绝；`null` 明确恢复默认负责人。

截止前 24 小时提醒负责人；超过截止提醒负责人并升级 PM。预计项消息明确标“预计”。无有效接收人时保留待处理凭据和审计，不静默丢失；管理员的显式读取禁止仍有效。保密名称只在有权接收人的站内消息中出现，不进入外部通知渠道。

`document_notice_receipts` 对“实例、接收人、提醒类型、截止时间、预计标记”唯一。项目串行锁加数据库唯一约束避免双调度事务重复发消息。截止真正变化后可产生新提醒；重复扫描同一截止不会重复。消息导航定位真实资料 ID。

## 文件版本、保留与迁移

提交记录时间与业务事件时间分开。项目锁内每份资料的新 `uploaded_at` 采用 `max(当前UTC, 上个记录时间+1微秒)`，保证冻结或回退时钟下最新版仍可确定；旧记录的空时间排在新记录之前。原件、下载、版本历史和门禁取同一最新版。业务事件的真实发生时间不做这种调整。

迁移 `g3a23b000001` 增加定义/实例负责人、实例截止依据和触发时间，以及两张项目持久表：

| 表 | 项目及其他外键 | 文件关系 |
| --- | --- | --- |
| document_notice_receipts | project_id → projects CASCADE；project_document_id → project_documents CASCADE；recipient_id → users SET NULL | 无新文件 |
| project_report_receipts | project_id → projects CASCADE；recipient_id → users SET NULL | summary 是元数据，无新文件 |

两个 owner_id → users SET NULL；新表加入 `project_retention.RETAINED_MODELS`。既有附件和项目空白模板原件继续遵循 UPLOAD_DIR 平级 stored_name 和已有 SHA manifest 契约。根集成 #85 永久删除时需覆盖上述两表。

SQLite 在线迁移在事务内批量改两张表，保留 ID、原版本及附件 RESTRICT 外键，并验证 FK。离线增量承诺仅为“该命名 revision 的实际 down_revision → g3a23b000001”：复制源 schema 冻结在迁移中，只复用冻结的 g22 迁移列定义，不导入未来 ORM。生成 SQL 将 PRAGMA foreign_keys=OFF 放在 BEGIN 前，迁移、版本更新和 foreign_key_check 放在同一事务，成功后 COMMIT 并恢复 FK。执行器遇 SQL 错误须 rollback 并恢复 FK；测试真实执行 SQL，同时验证失败没有丢原行。历史全链包含在线数据核对，仍必须在线运行，不可 stamp 跳过。

## 后续事件接缝

T24 调用 `project_documents.instantiate(..., trigger_ref=真实来源, triggered_at=真实时间)`，并在同一项目锁事务内刷新截止。事件来源的存在、项目归属和去重由真实事件写入方验证。

T28 将增加普通 ProjectEvent 的 date-only 事实时，需要扩展 `document_deadlines._calculate` 的实际事件分支，使用 `calendar_anchor` 并保留 date 精度；实际日期优先于计划日期。`project_documents.instantiate` 与 `materialize_static` 的 lifetime 启动会条件目前检查 `actual_at IS NOT NULL`，届时需扩为真实 `actual_at OR actual_date`。`missing_lifetime_requirements` 继续检查缺失实例即可。上传时间不能替代签单所载业务日期。

# AGV 项目导入字段规范

## 目录

1. AI 响应信封
2. 项目基础信息
3. 甲方组织与入场方式
4. 人员需求
5. 车型与单车问题
6. 准备和采购
7. 现场物品
8. 实施任务、排班与进度
9. 项目问题
10. 交付归档
11. 枚举与分流规则

## 1. AI 响应信封

```json
{
  "draft": {"type": "agvpm-project", "version": "2.3"},
  "missing_fields": ["缺少的事实或必须由人确认的内容"],
  "conflicts": ["多份资料之间无法自动判断的冲突"],
  "assumptions": ["为保持结构而采用、但未作为事实落库的解释"],
  "change_summary": ["本轮新增、修改或删除的内容"]
}
```

`draft` 必须完整保留模板顶层结构。其余四项均为字符串数组。

## 2. 项目基础信息

`project`：

| 字段 | 类型 | 说明 |
|---|---|---|
| name | string | 项目正式名称，必填 |
| abbreviation | string | 项目简称 |
| client | string | 甲方公司名称 |
| location | string | 实施现场地址 |
| start_date/end_date | YYYY-MM-DD | 项目计划周期，必填 |
| dispatch_platform | NDC/GRACE/integrated/null | 调度平台，integrated 为集成 |
| planned_entry_date | YYYY-MM-DD/null | 旧备份只读字段；仅旧格式导入时转为发车计划 |
| description | string | 范围、目标、边界、关键接口和当前状态 |
| status | enum | draft/planning/executing/pilot/archived，导入默认 draft |
| rest_mode | enum | none/one/two；不休/周日休/周末休 |
| rest_days | string[] | 额外休息日期 |
| skip_holidays | boolean | 排班是否跳过法定节假日 |
| conditions | object | need_wms/need_charging/client_server/new_vehicles/overseas 五个布尔条件 |

## 3. 甲方组织与入场方式

`project.client_contacts[]`：department、team、name、title、phone、email、responsibility、decision_scope、notes、is_primary。只记录甲方或现场外部联系人，不创建系统用户。

`project.entry_plan`：

- `mode`: collective/staggered/self_arranged/client_pickup/resident/other。
- `meeting_time`、`meeting_point`。旧备份 `entry_date` 仅在没有 `project_events` 时转为全部到场计划，新文件请使用关键事件。
- `client_contact`、`contact_phone`。
- `transport`、`accommodation`。
- `access_requirements`：门禁、证件、培训、电脑/工具报备。
- `tools_ppe`：安全帽、安全鞋、反光衣、工具和仪器要求。
- `network_access`：现场网络接入方式和限制。
- `notes`：轮班、禁入时段、拍照限制等。

## 4. 人员需求

人员需求作为 `project.staffing_notes` 文字供负责人确认。

AI 不得写 `members`、`manager_id`、`technical_manager_id` 或 `co_managers`。资料中出现姓名时，可写入 `project.staffing_notes` 供人工分配参考，但不得视为系统账号。

## 5. 车型与单车问题

`vehicles[]` 表示项目车型汇总：`vehicle_type`、`model_name`、`quantity`、`configuration`、`notes`。

`vehicle_units[]` 仅在有真实车辆编号时创建：

- asset_code、serial_number、vehicle_type、model_name。
- current_stage：planned/production/factory_test/shipping/on_site/commissioning/running/maintenance/retired。
- current_status：normal/attention/fault/stopped/retired。
- location、warranty_end、commissioned_at、note。
- events：该车现场问题与维修履历。

`events[]`：event_type、event_date、title、description、fault_part、cause、action_taken、replaced_parts、downtime_hours、verification、handler、is_closed、stage_after、status_after、location_after。

`event_type`：created/production/test/shipment/arrival/commission/handover/maintenance/repair/inspection/fault/retire/other。现场问题通常使用 fault/repair/maintenance/inspection/other。`replaced_parts[]` 包含 name、model、quantity、serial_number、supplier、notes。

车辆问题与项目问题不可重复创建：能定位到具体车辆并涉及故障/换件时，只写车辆事件；影响整体交付但不属于单车维修时写项目问题。

## 6. 准备和采购

`preparations[]` 是独立提醒，不进入任务计划和甘特图：

- category：scope/procurement/vehicle/software/site。
- name、is_required、blocks_entry、status、owner_party。
- required_date、committed_date、forecast_date、actual_date。
- risk、note、extra、sort_order。

状态：not_started/in_progress/pending/passed/failed/na。责任方：project/client/procurement/production/software。

采购项使用 `category=procurement`，`extra` 可含：quantity、unit、specification、supplier、order_status、request_date、order_date、expected_arrival、actual_arrival、budget、purchase_order_no。`order_status` 使用 未申请/已下单/采购中/已到货。

只有合同、清单、会议结论或用户明确要求的采购才可录入。普通行业惯例只可放入 `missing_fields` 作为待确认建议。

## 7. 现场物品

`inventory_items[]` 记录已经明确属于项目现场管理范围的实物和数字载体：

- item_code、name、category、specification、serial_number。
- ownership：company 我方、client 甲方、third_party 第三方。
- tracking_mode：quantity 按数量、serial 按序列号；serial 数量只能为 0 或 1。
- quantity、minimum_quantity、unit、status、location、custodian。
- supplier、received_date、expected_return_date、note、extra。
- category：equipment/tool/spare_part/material/consumable/document/other。
- status：expected/in_transit/on_site/in_use/loaned/consumed/returned/lost/damaged/scrapped。

采购需求仍放在 `preparations`；采购物品实际确定或到货后才进入 `inventory_items`。甲方借给现场使用的电脑、工具、钥匙和资料同样需要登记为 `client`。

## 8. 实施任务、排班与进度

`modules[]`：phase_name、name、category(core/optional)、tasks。

建议阶段：方案设计、生产与发运、到货检查、单车调试、地图与站点、接口与系统联调、试运行、培训验收。按资料实际内容调整，不生成“项目准备”阶段任务。

`tasks[]`：name、description、quantity_type、target_quantity、unit、standard_hours、safety_flag、sort_order、acceptance_criteria、deliverables、check_items。

quantity_type：fixed/per_vehicle/manual。站点、接口等计量使用 `manual` 并填写 target_quantity 和 unit。`check_items[]`：name、is_required、is_safety_critical、acceptance_standard、evidence_required。

`schedule[]`：task_name、work_date、planned_quantity、status(planned/done/skipped)、notes。没有可靠日期不要生成。

`progress[]`：task_name、work_date、completed_quantity、note。仅迁移已发生事实，新项目通常为空。

## 9. 项目问题

`issues[]`：title、description、issue_type、severity、status、resolution、extra。

- issue_type：hardware/software/environment/process/safety/other。
- severity：critical/high/medium/low。
- status：open/processing/resolved/closed。
- 涉及具体车辆故障时改写到车辆事件，不重复写入这里。
- resolved/closed 应有 resolution；证据不足则保持 open/processing。

## 10. 交付归档

`archive_checklist[]`：category、item_name、is_required、is_done、doc_type、version_requirement、signoff_required、notes、sort_order。

常见分类：设计资料、配置备份、测试记录、问题汇总、培训资料、操作维护手册、验收文件。只记录资料要求，不伪造“已完成”。

## 11. 分流决策

1. “服务器需在入场前到位”是准备项；“安装服务器系统”是任务。
2. “购买交换机 2 台”是采购项；“配置交换机 VLAN”是任务。
3. “AGV-03 驱动轮异响并更换轴承”是车辆事件；“无线覆盖不足影响全场联调”是项目问题。
4. “需要操作手册 PDF 并签字”是归档清单；“编写操作手册”可同时是任务，但两者职责不同。
5. “张工负责实施”只进入 staffing_notes，不映射系统账号。


## 关键事件和逐台到场

`project_events[]`：`event_key`、`planned_date`、`actual_at`、`note`。事件键为 internal_kickoff / ship / arrival_all / delivery_signed / commissioning_done / go_live / training_done / acceptance / handover，同项目不可重复。计划日期使用 YYYY-MM-DD，实际时间使用带时区的 ISO 日期时间；未知实际时间必须为 null，不能从计划日期推定。`vehicle_units[].arrived_at` 使用 YYYY-MM-DD。

arrival_all 的实际值按完整车型数量和逐台到场记录汇总，禁止凭部分车辆编造全部到场。导入文件若给出该实际值，必须与完整车辆证据一致。新格式 `project_events` 的存在表示采用新日期来源，清空的新计划不会被旧只读字段重新填回。克隆只复制平台和计划日期，不复制实际发生记录。

# 使用与维护文档

这些文档说明 v3 开发分支的操作和数据边界；最终旧数据迁移、周计划/本人页面及部署仍待总验收。历史实现过程见 [CHANGELOG](../CHANGELOG.md)，不作为当前在线证明。

## 按角色开始

- [项目经理：准备资料、核对进度与人工推进](quickstart-project-manager.md)
- [实施工程师：车辆、问题与资料提交](quickstart-engineer.md)
- [管理员：账号、安全、备份与存储](quickstart-admin.md)
- [外部人员：使用只读分享](quickstart-external.md)
- [术语表](glossary.md)

## 按业务查规则

| 需要了解 | 说明 |
|---|---|
| 项目人工状态、实际签单日期 | [项目状态](project-lifecycle-v3.md)、[关键事件](project-events.md)、[完成核对](completion-review.md)、[发车前资料](pre-dispatch-documents.md) |
| 资料要求、文件、截止与触发 | [模板阶段主线](template-stage-backbone.md)、[资料要求模板](document-requirement-templates.md)、[项目清单](project-documents.md)、[截止提醒](document-deadlines.md)、[事故/质量/离场触发](triggered-documents.md) |
| 表单与车辆事实 | [生成 Excel/Word](generated-document-forms.md)、[车辆进度](vehicle-progress.md)、[逐车检查](vehicle-checks.md)、[逐车资料](vehicle-documents.md) |
| 权限与分享 | [账号预设](permission-presets.md)、[保密](confidential-documents.md)、[外部查看](external-view.md)、[二次验证](two-factor-auth.md) |
| 上传、清理与数据保全 | [续传和存储](resumable-storage.md)、[加密备份](encrypted-backups.md)、[回收站](project-retention.md)、[功能下线](retired-features.md) |
| 现场本周、本人记录、人员周视图 | [实际操作与修订](field-week.md) |
| 周计划、日历与消息 | [周计划](weekly-plans.md)、[年度节假日](holiday-calendars.md)、[消息规则](notifications.md) |
| 开发和运维 | [编码指引](../CLAUDE.md)、[接口权限声明](route-permissions.md)、[部署](deployment.md)、[更新与恢复](software-updates.md) |

历史 QA 原件已移出 Git；按[归档索引与 SHA 清单](evidence-archive.md)查找。T33/T40 最终页面稳定后补齐周计划和本人页面操作，本轮不把未验收页面写成已发布能力。

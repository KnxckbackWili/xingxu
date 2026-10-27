# 资料表单生成 T35

资料页6.2在项目现场时区当前ISO周提供“由系统生成本周生命周期表”，6.9.3选择已有物品申请生成内部联系单Word，9.2继续由物品与真实收发流水生成。生成后直接保存真实附件与资料新版本，原提交、审核、文件和源记录都保留。归档/权限撤销/不适用范围不能写；历史周次不由当前数据回造，仍需上传对应真实原件。

三项使用同一`generated_document_forms.generate`提交事务。服务在项目锁内取来源、创建产物、末次复核账号会话/资料资格/来源范围，然后`create_attachment`、统一独立保密helper、`docs.submit`与审计一起提交；失败回滚附件、版本、状态和新文件。完整SHA-256使用真实生成字节。`DocumentVersion.review_metadata.generated`保留生成时刻、生成者、来源记录ID、原日期依据、当期/时区与SHA，后续可选审核在同一metadata上追加，不覆盖生成来源。未新增表或迁移，现有项目快照、备份与版本导出已包含这些事实。

6.2复用`report_forms.lifecycle_to_excel`和原11列`LIFECYCLE_HEADERS`、Sheet1/模板9导入契约，只选择现场周一至周日内原`VehicleLifecycleEvent.event_date`，不使用上传/生成时间替代问题日期。空周只产生原表头，不捏造事件。所有字符串作为Excel文本，避免真实问题标题以等号开头时变成公式。原全履历Excel导入导出与质量反馈单Excel版式保留。

6.9.3复用原内部联系单字段与顺序，申请日期原样保留，缺失日期保持空白，不把资料提交当成申请审批。Word段后距适度收紧并把签名两行放在一起，标题采用黑色Title样式且清除默认蓝线；普通多行需求可在一页完整阅读。

9.2复用原物品/不可变流水表头与字段，时间列改为“发生时间（按时间依据）”。已证实UTC记录带UTC偏移，`legacy_local`和未知历史墙钟保留原字符串，不冒充UTC。原数量、发生时间与时间依据不改写。

## 权限与来源

生成目标须通过当前资料家族ACL；独立私密输出复用T26负责人+C_PLAN授权和指定人员校验。默认整行排除私密来源，即使操作者是可读该来源的负责人；缺失、无权限或跨项目原件别名也排除，不披露被排除来源的名称、摘要或数量。

明确选择私密输出时，独立文件的全部指定读者（含当前负责人，以及暂时被目标家族挡住的人）都必须能读来源文件，才可纳入该私密来源。否则仍排除，避免今后家族扩权激活潜在副本。文件限制与目标家族继续取交集，不修改任何原家族范围。

联系单使用既有生成版本的真实申请ID追踪来源约束；旧私密Word缺少可靠申请身份时，不从标题或同名文件猜对应关系，保守约束所有候选申请。公开选择器不显示不适用来源。旧生命周期/Word直接下载入口同样按当前操作者的独立文件与家族交集过滤，并记录实际保密导出审计；它们只向当前操作者下载，不创建更宽的公共资料副本。

## 接口

以下均以`/api/projects/{pid}/documents/{did}`开头。写动作沿用`worker.deliver`，资源可见性、项目成员资格、当前ACL及归档边界仍服务端检查。

| 方法 | 路径 | 请求与结果 |
| --- | --- | --- |
| POST | `/generate-lifecycle` | `{note?, confidential?, confidential_user_ids?}`；仅6.2 project weekly且当前现场ISO周；返回完整当前ProjectDocument |
| POST | `/generate-contact` | 同上加必填`application_id`；仅6.9.3 project on_demand；返回ProjectDocument |
| POST | `/generate-inventory` | 旧路径保留，公共字段同上；仅9.2 project lifetime；返回ProjectDocument |
| GET | `/generation-sources` | 可选query `confidential=true&confidential_user_ids=id`（多值重复键）；返回当前输出范围允许的`[{id,title,item_name,apply_date,status}]` |

响应`Cache-Control: private, no-store`。错误范围/归档400、无资格403、不可读或不存在的联系单404、旧周次或生成中权限变化409、会话失效401、非法body422，失败无新提交事实。

## 原件保全补强

元数据盘点确认仅三类旧业务`attachment_id`尚无FK：VehicleLifecycleEvent、ArchiveChecklist、AcceptanceRecord。存储清理现按真实Attachment ID显式保护这三类引用；同名的不同原件不受牵连，不凭跨项目字符串猜测释放原件。保留archive manifest和独立空白资产归属继续保护。预览后新增真实引用导致409，重预览后仅清理无引用旧周次。

## 验证

T35专项覆盖现场跨年周边界、Excel原表头/日期/文本、私密源不流入公共文件、独立scope和目标scope的潜在扩权、联系单真实来源/未知私密来源、旧export旁路、真实文件SHA、多版本/审核来源保留、错误回滚、归档与显式禁止、UTC/历史墙钟保留。另有三类非FK真实引用的候选/确认端到端，以及保留archive/空白资产回归。

真实API产出的Word样张已用bundled LibreOffice渲染并逐页检查，最终一页、中文完整、无标题蓝线或签名孤页。运行时默认fontconfig缺CJK，QA使用只读系统字体目录配置后验证原产物，不使用桌面LibreOffice，不改系统字体或业务数据。内部验收记录见audit-artifacts/v3-t35-handoff.md。

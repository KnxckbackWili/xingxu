import { Progress, Tag, Typography } from 'antd'
import type { VehicleSummary } from '../api/workbench'
/** `compact` is a single line of text for lists that already show overall progress. */
export default function VehicleProgressSummary({value,compact=false}:{value?:VehicleSummary;compact?:boolean}) {
  if(!value)return <Typography.Text type="secondary">车辆进度未读取</Typography.Text>
  if(compact)return <Typography.Text type="secondary" className="vehicle-progress-compact">{value.quantity_unknown||value.progress_known===false||typeof value.percent!=='number'?'车辆范围待核对':!value.target?'暂无车辆范围':`车辆环节 ${value.completed}/${value.target}`}</Typography.Text>
  if(value.quantity_unknown||value.progress_known===false||typeof value.percent!=='number'||!Number.isFinite(value.percent))return <Tag>车辆范围待核对</Tag>
  if(!value.target)return <Typography.Text type="secondary">暂无车辆范围</Typography.Text>
  return <div><Progress percent={value.percent} size="small"/><Typography.Text type="secondary">{value.completed}/{value.target} 个车辆环节</Typography.Text>{!!value.unidentified_completed&&<Tag>含迁移记录，待补车号</Tag>}</div>
}

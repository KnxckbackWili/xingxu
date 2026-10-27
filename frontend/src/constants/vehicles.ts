/** 车型与台数：新建项目第一步收集，先落库再生成任务，避免总览整屏误报。
 *  HYPE-63：可选车型统一由后端字典提供（见 hooks/useVehicleTypes.ts），不再硬编码列表；
 *  此处仅保留新建表单的初始草稿（默认车型为预置字典首项「潜伏式」）。 */
export interface VehicleDraft {
  vehicle_type: string
  model_name: string
  quantity: number
  notes?: string
}

export const DEFAULT_VEHICLE_DRAFT: VehicleDraft = {
  vehicle_type: '潜伏式',
  model_name: '',
  quantity: 1,
  notes: '',
}

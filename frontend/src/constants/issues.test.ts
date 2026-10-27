import { describe, expect, it } from 'vitest'
import { extraSummary } from './issues'

describe('extraSummary', () => {
  it('已知分类专属字段渲染为中文摘要', () => {
    expect(extraSummary({ device: 'AGV-01', affects_schedule: '影响' })).toBe(
      '设备/部位：AGV-01 · 是否影响工期：影响',
    )
    expect(extraSummary({ module_version: 'v2.1' })).toBe('涉及模块/版本：v2.1')
    expect(extraSummary({ dept_contact: '王工' })).toBe('涉及部门/接口人：王工')
  })

  it('未知键不泄漏原始字段名（质量问题反馈单导入的 project_name/reporter_name 等被过滤）', () => {
    expect(extraSummary({ project_name: '天津环晟', reporter_name: '孙晓' })).toBe('')
    expect(
      extraSummary({
        project_name: '天津环晟',
        reporter_name: '孙晓',
        vehicle_model: 'X1',
        vehicle_no: 'AGV-03',
        source: '客户反馈',
        part: '传感器',
        feedback_date: '2026-08-12',
      }),
    ).toBe('')
  })

  it('空值/缺失字段不渲染', () => {
    expect(extraSummary({ device: '', affects_schedule: null, part: undefined })).toBe('')
    expect(extraSummary({})).toBe('')
    expect(extraSummary(null)).toBe('')
    expect(extraSummary(undefined)).toBe('')
  })

  it('混合已知与未知键：只输出有标签的字段', () => {
    expect(extraSummary({ device: 'AGV-01', project_name: '某项目', affects_schedule: '不影响' })).toBe(
      '设备/部位：AGV-01 · 是否影响工期：不影响',
    )
  })
})

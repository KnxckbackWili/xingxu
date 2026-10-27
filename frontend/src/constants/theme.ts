/** 设计 token 唯一事实源（F1/F2：页面禁止硬编码 hex 色值与散落字号，统一走这里）。
 * 色值与 AntD 默认主题 token 对齐；如后续换主题只改本文件。
 */
export const COLOR = {
  primary: '#1764e8',      // AntD colorPrimary
  primaryBg: '#edf4ff',    // AntD colorPrimaryBg
  selectedBg: '#edf4ff',   // 列表选中行浅蓝底
  success: '#52c41a',      // AntD colorSuccess
  warning: '#faad14',      // AntD colorWarning
  warningBg: '#fffbe6',    // AntD colorWarningBg（未读高亮底）
  danger: '#f5222d',       // AntD colorError
  purple: '#722ed1',       // 治理/角色紫色（AntD purple-6）
  border: '#f0f0f0',       // AntD colorBorderSecondary
}

/** 字号 token（与页面常用小号一致） */
export const FONT = {
  caption: 11,  // 次要说明
  small: 12,    // 表格/正文小字
  body: 13,     // 列表标题等
  base: 14,     // 默认正文字号
}

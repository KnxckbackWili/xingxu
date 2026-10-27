/** 前端断点单一事实源：收敛为 3 档，消灭 767/768 夹缝。
 *  CSS 媒体查询与 JS useMediaQuery 必须共用这里导出的数值。 */
export const BREAKPOINTS = {
  /** 移动端上限：≤ 640px 使用触屏布局 */
  mobile: 640,
  /** 平板/窄屏上限：≤ 1024px 使用紧凑布局 */
  tablet: 1024,
  /** 桌面断点：> 1024px 使用完整布局 */
  desktop: 1025,
} as const

export type BreakpointName = keyof typeof BREAKPOINTS

/** 常用媒体查询字符串（供 CSS-in-JS / useMediaQuery 使用） */
export const MEDIA_QUERY = {
  mobile: `(max-width: ${BREAKPOINTS.mobile}px)`,
  tablet: `(max-width: ${BREAKPOINTS.tablet}px)`,
  desktop: `(min-width: ${BREAKPOINTS.desktop}px)`,
} as const

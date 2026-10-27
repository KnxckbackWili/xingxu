import { lazy, Suspense, type ComponentProps, type CSSProperties } from 'react'
import { Skeleton } from 'antd'

const Chart = lazy(() => import('./Chart'))

type ChartProps = ComponentProps<typeof Chart>

/** 图表懒加载：减少首屏 echarts 体积；未加载完成时显示骨架。 */
export default function LazyChart({ style, ...rest }: ChartProps & { style?: CSSProperties }) {
  return (
    <Suspense fallback={<Skeleton.Node active style={{ width: '100%', height: (style as CSSProperties)?.height ?? 280 }} />}>
      <Chart style={style} {...rest} />
    </Suspense>
  )
}

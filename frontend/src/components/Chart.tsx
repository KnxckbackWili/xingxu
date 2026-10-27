import type { ComponentProps } from 'react'
import EChartsReactCore from 'echarts-for-react/lib/core'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

type ChartProps = Omit<ComponentProps<typeof EChartsReactCore>, 'echarts'>

export default function Chart(props: ChartProps) {
  return <EChartsReactCore echarts={echarts} {...props} />
}

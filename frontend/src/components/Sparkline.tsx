/** 迷你趋势线：纯 SVG，避免为 KPI 卡引入 ECharts。 */
export default function Sparkline({ data, width = 96, height = 28, stroke = '#176b5b' }: {
  data: number[]
  width?: number
  height?: number
  stroke?: string
}) {
  if (!data || data.length < 2) {
    return (
      <svg width={width} height={height} aria-hidden="true">
        <line x1={0} y1={height / 2} x2={width} y2={height / 2} stroke="#dce3e1" strokeWidth={1.5} strokeDasharray="3 3" />
      </svg>
    )
  }

  const max = Math.max(...data)
  const min = Math.min(...data)
  const range = max - min || 1
  const step = width / (data.length - 1)
  const points = data.map((value, index) => {
    const x = index * step
    const y = height - 3 - ((value - min) / range) * (height - 6)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  const last = points[points.length - 1].split(',')
  const lastX = Number(last[0])
  const lastY = Number(last[1])

  return (
    <svg width={width} height={height} aria-hidden="true">
      <polyline
        points={points.join(' ')}
        fill="none"
        stroke={stroke}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={0.85}
      />
      <circle cx={lastX} cy={lastY} r={2.2} fill={stroke} />
    </svg>
  )
}

import { useEffect, useState } from 'react'
import { Alert, Button, Modal, Space, Spin, Tag, Typography } from 'antd'
import { api, errMsg } from '../../../api/client'
import { formatDateTime } from '../../../utils/date'
interface Review {
  project_version: number; allowed: boolean; target: string
  blockers: Array<{ type: string; message: string; url: string }>
  ordinary_check_overrides: Array<{ task_id: string; task_name: string; reason: string; actor_name: string; recorded_at: string | null; url: string; checks: Array<{ check_id: string; name: string; failed_reason: string; still_current: boolean }> }>
}
// Server messages read "原因：甲、乙、丙…"; long lists show a short preview and fold the rest.
const PREVIEW = 6
function splitBlocker(message: string) {
  const at = message.indexOf('：')
  const items = at < 0 ? [] : message.slice(at + 1).split('、').map(item => item.trim()).filter(Boolean)
  if (items.length <= 2) return { head: message, items: [] }
  const head = message.slice(0, at)
  return { head: /\d/.test(head) ? head : `${head}（${items.length} 项）`, items }
}
export default function CompletionReview({ projectId, target, open, onClose }: { projectId: string; target: 'completed' | 'archived'; open: boolean; onClose: () => void }) {
  const [data, setData] = useState<Review | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!open) return
    const controller = new AbortController(); setLoading(true); setData(null); setError('')
    api.get(`/projects/${encodeURIComponent(projectId)}/completion-review`, { params: { target }, signal: controller.signal }).then(response => {
      if (controller.signal.aborted) return
      const value = response.data
      if (!Array.isArray(value?.blockers) || !Array.isArray(value?.ordinary_check_overrides) || typeof value.allowed !== 'boolean') throw new Error('Incomplete review response')
      setData(value)
    }).catch(failure => { if (!controller.signal.aborted) setError(errMsg(failure)) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [projectId, target, open, attempt])
  const link = (path: string) => path.startsWith(`/pm/projects/${projectId}/`) ? path : `/pm/projects/${projectId}/overview`
  return <Modal title={target === 'archived' ? '归档前核对' : '完成前核对'} open={open} onCancel={onClose} width={720} footer={<Button onClick={onClose}>关闭核对清单</Button>} destroyOnHidden>
    <Typography.Paragraph type="secondary">一次核对当前全部缺项；实际推进时仍会重新检查最新证据。</Typography.Paragraph>
    {loading && <Spin aria-label="正在核对完成条件" />}
    {error && <Alert type="error" showIcon message="核对清单加载失败" description={error} action={<Button onClick={() => setAttempt(value => value + 1)}>重新核对</Button>} />}
    {data && <>
      <Alert type={data.allowed ? 'success' : 'warning'} showIcon message={data.allowed ? '当前证据已齐备' : `还有 ${data.blockers.length} 类缺项需要处理`} />
      <ul className="completion-blockers">{data.blockers.map((item, index) => { const { head, items } = splitBlocker(item.message); return <li key={`${item.type}:${index}`} className="completion-blocker">
        <div className="completion-blocker-head"><Typography.Text strong>{head}</Typography.Text><a href={link(item.url)}>去核对相关记录</a></div>
        {items.length > 0 && <Typography.Paragraph type="secondary" className="completion-blocker-items">{items.slice(0, PREVIEW).join('、')}{items.length > PREVIEW && <details><summary>还有 {items.length - PREVIEW} 项</summary>{items.slice(PREVIEW).join('、')}</details>}</Typography.Paragraph>}
      </li> })}</ul>
      {data.ordinary_check_overrides.length > 0 && <Typography.Title level={5}>普通失败检查项的明确覆盖</Typography.Title>}
      {data.ordinary_check_overrides.map(row => <article key={row.task_id} className="field-record-card">
        <Typography.Text strong>{row.task_name}</Typography.Text><p>覆盖理由：{row.reason || '未记录，需重新核对'}</p>
        <Typography.Paragraph type="secondary">{row.actor_name} · {formatDateTime(row.recorded_at)}</Typography.Paragraph>
        <ul>{row.checks.map(check => <li key={check.check_id}><Space wrap><span>{check.name}：{check.failed_reason}</span><Tag color={check.still_current ? 'orange' : 'red'}>{check.still_current ? '已明确覆盖' : '检查事实已变化，需复核'}</Tag></Space></li>)}</ul>
        <a href={link(row.url)}>查看任务与检查记录</a>
      </article>)}
      <Typography.Paragraph type="secondary">安全检查项不能覆盖；问题只有关闭或作废才算闭环，已解决仍需确认关闭。</Typography.Paragraph>
    </>}
  </Modal>
}

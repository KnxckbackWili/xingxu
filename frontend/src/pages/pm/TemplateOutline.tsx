import type { ReactNode } from 'react'
import { STAGES } from '../../constants/stages'

export type OutlineStage = { key: string; name: string; count: number }

export const outlineStages = (counts: Record<string, number>, extra: OutlineStage[] = []): OutlineStage[] =>
  [...STAGES.map(s => ({ key: s.key, name: s.name, count: counts[s.key] ?? 0 })), ...extra]

/**
 * One template list laid out along the stage backbone: a sticky stage index on the left
 * (a scrolling chip row on phones) and one section per stage on the right.
 */
export function StageOutline({ id, label, stages, unit, children }: { id: string; label: string; stages: OutlineStage[]; unit: string; children: ReactNode }) {
  const jump = (key: string) => document.getElementById(`${id}-${key}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  return <div className="tpl-outline">
    <nav className="tpl-stage-nav" aria-label={`${label}阶段目录`}>
      <ol>{stages.map(s => <li key={s.key}>
        <button type="button" className={s.count ? '' : 'is-empty'} onClick={() => jump(s.key)} aria-label={`跳到${s.name}，${s.count} ${unit}`}>
          <span className="tpl-stage-key">{s.key === 'legacy' ? '?' : s.key}</span><span className="tpl-stage-name">{s.name}</span><span className="tpl-stage-count">{s.count}</span>
        </button>
      </li>)}</ol>
    </nav>
    <div className="tpl-outline-body">{children}</div>
  </div>
}

export function StageSection({ outlineId, stage, title, meta, actions, children }: { outlineId: string; stage: string; title: string; meta?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return <section id={`${outlineId}-${stage}`} className="tpl-stage-section" aria-label={title}>
    <header className="tpl-stage-head">
      <h3><span className="tpl-stage-key">{stage === 'legacy' ? '?' : stage}</span>{title.replace(/^\d · /, '')}</h3>
      {meta && <span className="tpl-stage-meta">{meta}</span>}
      {actions && <span className="tpl-stage-actions">{actions}</span>}
    </header>
    {children}
  </section>
}

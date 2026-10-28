import type { ReactNode } from 'react'
import { InfoHint } from './IconAction'

/** A task-oriented heading: one main action, followed by optional tools. */
export function WorkPageHeader({ title, description, primary, tools, meta }: {
  title: string
  description?: string
  primary?: ReactNode
  tools?: ReactNode
  meta?: ReactNode
}) {
  return <header className="work-page-header">
    <div className="work-page-heading"><div className="work-title-row"><h1>{title}</h1>{description && <InfoHint text={description} />}</div>{meta && <div className="work-page-meta">{meta}</div>}</div>
    {(primary || tools) && <div className="work-page-actions">{primary}{tools}</div>}
  </header>
}

export function WorkSection({ title, description, extra, filters, children, className = '' }: {
  title?: string
  description?: string
  extra?: ReactNode
  filters?: ReactNode
  children: ReactNode
  className?: string
}) {
  return <section className={`work-section ${className}`}>
    {(title || extra) && <div className="work-section-heading"><div className="work-title-row">{title && <h2>{title}</h2>}{description && <InfoHint text={description} />}</div>{extra && <div className="work-section-actions">{extra}</div>}</div>}
    {filters && <div className="work-section-filters">{filters}</div>}
    <div className="work-section-body">{children}</div>
  </section>
}

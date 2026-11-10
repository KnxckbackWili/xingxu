/** A person's initial in a steady colour, optionally followed by the name. Shows who did what at a glance. */
const COLORS = ['#2563eb', '#0e9f6e', '#c2410c', '#7c3aed', '#0891b2', '#be185d', '#4d7c0f', '#b45309']

export function personColor(name: string): string {
  let hash = 0
  for (const char of name) hash = (hash * 31 + char.codePointAt(0)!) >>> 0
  return COLORS[hash % COLORS.length]
}

export function PersonAvatar({ name, large = false }: { name?: string | null; large?: boolean }) {
  const label = (name ?? '').trim()
  // Chinese names read best by their last character; Latin names by their first letter.
  const initial = !label ? '?' : /[一-鿿]/.test(label) ? label.slice(-1) : label[0].toUpperCase()
  return <span className={`person-avatar${large ? ' is-lg' : ''}`} style={{ background: label ? personColor(label) : 'var(--agv-text-secondary)' }} aria-hidden="true">{initial}</span>
}

export default function Person({ name, fallback = '—' }: { name?: string | null; fallback?: string }) {
  if (!name) return <>{fallback}</>
  return <span className="person"><PersonAvatar name={name} /><span className="person-name">{name}</span></span>
}

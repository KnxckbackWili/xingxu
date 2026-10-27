import './BrandMark.css'

export default function BrandMark({ subtitle = false, prominent = false }: { subtitle?: boolean; prominent?: boolean }) {
  return <span className={`brand-signature${prominent ? ' brand-signature--prominent' : ''}`}>
    <img className="brand-signature-icon" src="/xingxu-icon-192.png" alt="" width={prominent ? 48 : 32} height={prominent ? 48 : 32} draggable={false} />
    <span className="brand-signature-copy">
      <strong>行序</strong>
      {subtitle && <small>项目工作台</small>}
    </span>
  </span>
}

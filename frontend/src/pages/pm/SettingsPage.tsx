import { Empty, Tooltip } from 'antd'
import { Link } from 'react-router-dom'
import { useAuth } from '../../stores/auth'
import { WorkPageHeader } from '../../components/WorkPage'
import { MENU_GROUPS } from '../../layouts/pmMenu'
import './SettingsPage.css'

/** All settings on one page, grouped; each entry keeps its own route permission. */
export default function SettingsPage() {
  const { user } = useAuth()
  const groups = MENU_GROUPS(user)
  return <div className="settings-hub">
    <WorkPageHeader title="设置" description="只显示你有权限的设置项。" />
    {groups.length ? <div className="settings-hub-groups">
      {groups.map(group => <section key={group.key} className={`settings-hub-group settings-hub-group--${group.key}`} aria-labelledby={`settings-${group.key}`}>
        <h2 id={`settings-${group.key}`}>{group.label}</h2>
        <ul className="settings-hub-tiles">{group.children.map(entry => <li key={entry.key}><Tooltip title={entry.description} placement="bottom"><Link to={entry.key}>
          <span className="settings-hub-icon" aria-hidden="true">{entry.icon}</span>
          <strong>{entry.label}</strong><span className="sr-only">{entry.description}</span>
        </Link></Tooltip></li>)}</ul>
      </section>)}
    </div> : <Empty description="当前账号没有可用的设置项" />}
  </div>
}

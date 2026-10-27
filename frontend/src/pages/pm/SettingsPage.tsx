import { Empty } from 'antd'
import { RightOutlined } from '@ant-design/icons'
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
    {groups.length ? <div className="settings-hub-grid">
      {groups.map(group => <section key={group.key} className="settings-hub-group" aria-labelledby={`settings-${group.key}`}>
        <h2 id={`settings-${group.key}`}>{group.label}</h2>
        <ul>{group.children.map(entry => <li key={entry.key}><Link to={entry.key}>
          <span className="settings-hub-icon" aria-hidden="true">{entry.icon}</span>
          <span className="settings-hub-copy"><strong>{entry.label}</strong><small>{entry.description}</small></span>
          <RightOutlined aria-hidden="true" />
        </Link></li>)}</ul>
      </section>)}
    </div> : <Empty description="当前账号没有可用的设置项" />}
  </div>
}

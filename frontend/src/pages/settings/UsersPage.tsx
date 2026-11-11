import { useCallback, useEffect, useState } from 'react'
import { Button, Form, Input, Modal, Select, Skeleton, Tag, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import type { User } from '../../api/types'
import Person from '../../components/Person'
import { useAuth } from '../../stores/auth'

const ROLES = [{ value: 'employee', label: '员工' }, { value: 'admin', label: '系统管理员' }]

export default function UsersPage() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<User[] | null>(null)
  const [editing, setEditing] = useState<User | 'new' | null>(null)
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()
  const load = useCallback(() => api.get('/users').then(({ data }) => setUsers(data)).catch((failure) => message.error(errMsg(failure))), [])
  useEffect(() => { void load() }, [load])
  const open = (target: User | 'new') => {
    setEditing(target)
    form.setFieldsValue(target === 'new' ? { username: '', display_name: '', role: 'employee', password: '' } : { display_name: target.display_name, role: target.role, password: '' })
  }
  const save = async () => {
    const values = await form.validateFields()
    setBusy(true)
    try {
      if (editing === 'new') await api.post('/users', values)
      else if (editing) await api.put(`/users/${editing.id}`, { display_name: values.display_name, role: values.role, ...(values.password ? { password: values.password } : {}) })
      message.success('已保存')
      setEditing(null)
      await load()
    } catch (failure) {
      message.error(errMsg(failure))
    } finally {
      setBusy(false)
    }
  }
  const toggle = async (target: User) => {
    try { await api.put(`/users/${target.id}`, { is_active: !target.is_active }); await load() } catch (failure) { message.error(errMsg(failure)) }
  }
  return <section aria-label="账号">
    <header className="section-head settings-head"><div><h2>账号</h2><p>账号只有两种：系统管理员和员工。员工能做除“设置”以外的一切。</p></div>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => open('new')}>新建账号</Button></header>
    {!users && <Skeleton active />}
    {users && <ul className="settings-list">{users.map((item) => <li key={item.id} className={item.is_active ? '' : 'is-off'}>
      <span className="settings-main"><Person name={item.display_name} /><small>{item.username}</small></span>
      <Tag color={item.role === 'admin' ? 'blue' : undefined}>{item.role === 'admin' ? '系统管理员' : '员工'}</Tag>
      {!item.is_active && <Tag color="red">已停用</Tag>}
      <span className="settings-actions">
        <Button size="small" onClick={() => open(item)}>修改</Button>
        {item.id !== me?.id && <Button size="small" danger={item.is_active} onClick={() => void toggle(item)}>{item.is_active ? '停用' : '启用'}</Button>}
      </span>
    </li>)}</ul>}
    <Modal open={!!editing} title={editing === 'new' ? '新建账号' : '修改账号'} okText="保存" cancelText="取消" confirmLoading={busy} onOk={() => void save()} onCancel={() => setEditing(null)} destroyOnClose>
      <Form form={form} layout="vertical">
        {editing === 'new' && <Form.Item name="username" label="用户名" extra="登录时用，只能是字母、数字和 _ . - @" rules={[{ required: true, pattern: /^[A-Za-z0-9_.@-]{1,50}$/, message: '请用字母、数字或 _ . - @' }]}><Input autoComplete="off" /></Form.Item>}
        <Form.Item name="display_name" label="姓名" rules={[{ required: true, whitespace: true, message: '请填写姓名' }]}><Input maxLength={100} /></Form.Item>
        <Form.Item name="role" label="账号类型"><Select options={ROLES} /></Form.Item>
        <Form.Item name="password" label={editing === 'new' ? '初始密码' : '重置密码'} extra={editing === 'new' ? '至少 8 位' : '不改就留空。重置后这个账号已登录的设备都会退出。'}
          rules={[{ required: editing === 'new', min: 8, message: '密码至少 8 位' }]}><Input.Password autoComplete="new-password" /></Form.Item>
      </Form>
    </Modal>
  </section>
}

import { useState } from 'react'
import { Modal, Form, Input, message } from 'antd'
import { api } from '../api/client'

/**
 * 修改密码（v1.2.1 接线后端已有 PUT /auth/password）。
 * 修改成功后由后端失效旧会话，下次请求会要求重新登录。
 */
export default function ChangePasswordModal({ open, onClose, afterClose }: { open: boolean; onClose: () => void; afterClose?: () => void }) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await api.put('/auth/password', {
        old_password: values.old_password,
        new_password: values.new_password,
      })
      message.success('密码已修改')
      form.resetFields()
      onClose()
    } catch (e: any) {
      message.error(e.response?.data?.detail ?? '修改失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="修改密码"
      open={open}
      afterClose={afterClose}
      onCancel={() => { form.resetFields(); onClose() }}
      onOk={submit}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      width={400}
    >
      <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
        <Form.Item
          name="old_password"
          label="当前密码"
          rules={[{ required: true, message: '请输入当前密码' }]}
        >
          <Input.Password placeholder="当前密码" autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          name="new_password"
          label="新密码"
          rules={[
            { required: true, message: '请输入新密码' },
            { min: 6, message: '至少 6 位' },
          ]}
        >
          <Input.Password placeholder="新密码（至少 6 位）" autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm_password"
          label="确认新密码"
          dependencies={['new_password']}
          rules={[
            { required: true, message: '请再次输入新密码' },
            ({ getFieldValue }) => ({
              validator: (_, v) =>
                !v || getFieldValue('new_password') === v
                  ? Promise.resolve()
                  : Promise.reject(new Error('两次输入不一致')),
            }),
          ]}
        >
          <Input.Password placeholder="再次输入新密码" autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

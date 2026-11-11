import { Input, Modal } from 'antd'

/** Ask for one line of text. Resolves with the trimmed text, or null when cancelled or empty. */
export function promptText(title: string, initial = '', placeholder = ''): Promise<string | null> {
  return new Promise((resolve) => {
    let value = initial
    const modal = Modal.confirm({
      title, icon: null, okText: '确定', cancelText: '取消',
      content: <Input autoFocus defaultValue={initial} placeholder={placeholder} aria-label={title} maxLength={100}
        onChange={(event) => { value = event.target.value }}
        onPressEnter={() => { modal.destroy(); resolve(value.trim() || null) }} />,
      onOk: () => resolve(value.trim() || null),
      onCancel: () => resolve(null),
    })
  })
}

import { hashBlob } from './hashCore'

self.addEventListener('message', async (event: MessageEvent<{ file: Blob; chunkSize: number }>) => {
  try {
    const result = await hashBlob(event.data.file, event.data.chunkSize,
      bytes => self.postMessage({ type: 'progress', bytes }))
    self.postMessage({ type: 'done', result })
  } catch (error) {
    self.postMessage({ type: 'error', message: error instanceof Error ? error.message : '无法读取所选文件' })
  }
})

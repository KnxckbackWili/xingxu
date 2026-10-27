import { beforeEach, expect, it } from 'vitest'
import { clearPendingIntent, pendingIntentKey, readPendingIntent, writePendingIntent } from './pendingIntent'
beforeEach(() => sessionStorage.clear())
it('business retry intent survives reread and is partitioned by account/project/entity/action', () => {
  const key = pendingIntentKey('inventory', 'a', 'p1', 'i1')
  writePendingIntent(key, { client_uuid: 'one-operation', quantity: 2 })
  expect(readPendingIntent(key)).toEqual({ client_uuid: 'one-operation', quantity: 2 })
  for (const other of [pendingIntentKey('inventory', 'b', 'p1', 'i1'), pendingIntentKey('inventory', 'a', 'p2', 'i1'), pendingIntentKey('inventory', 'a', 'p1', 'i2'), pendingIntentKey('adjustment', 'a', 'p1', 'i1')]) expect(readPendingIntent(other)).toBeUndefined()
  clearPendingIntent(key)
  expect(readPendingIntent(key)).toBeUndefined()
})
it('anonymous contexts do not persist an intent and corrupt storage does not crash a form', () => {
  const key = pendingIntentKey('inventory', undefined, 'p1', 'i1')
  writePendingIntent(key, { quantity: 2 })
  expect(sessionStorage.length).toBe(0)
  sessionStorage.setItem('bad', '{')
  expect(readPendingIntent('bad')).toBeUndefined()
})

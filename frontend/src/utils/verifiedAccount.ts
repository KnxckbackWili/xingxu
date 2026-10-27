import { getOfflineAccount } from '../offline/queue'

/** A second tab can replace the cookie session before this view re-renders. */
export function ensureVerifiedAccount(userId: string | undefined) {
  if (!userId || getOfflineAccount() !== userId) throw new Error('登录账号已变化或尚未核验，请重新登录；填写内容已保留。')
}

import pkg from '../package.json'

/** 前端版本：单一事实源取自 package.json（构建时注入）。
 *  main.tsx 用它作为 PWA 缓存键，登录页用它展示版本号，避免硬编码。 */
export const APP_VERSION = 'v' + pkg.version

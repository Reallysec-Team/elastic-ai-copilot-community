import { useSyncExternalStore } from 'react'

import { getPrefs, PREFS_EVENT } from '@/lib/prefs'

function subscribe(cb: () => void): () => void {
  window.addEventListener(PREFS_EVENT, cb)
  return () => window.removeEventListener(PREFS_EVENT, cb)
}

/** 当前账号的头像（data URL），没设过就是 undefined。
 *
 * 单独一个 hook 而不是让组件自己读 `getPrefs()`：头像在两个地方同时显示
 * （顶栏和个人资料抽屉），改完要立刻一起变。prefs 是 localStorage + 一个事件，
 * 所以订阅走 useSyncExternalStore，和语言那套是同一个形状。 */
export function useAvatar(): string | undefined {
  return useSyncExternalStore(
    subscribe,
    () => getPrefs().avatar,
    () => undefined,
  )
}

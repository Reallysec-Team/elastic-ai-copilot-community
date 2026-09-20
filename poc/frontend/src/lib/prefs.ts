/*
 * Per-user UI preferences (Wave 2 #10): default index, result page size, and
 * the visible column set per index. Server-backed (kind `pref`, key `ui`) with a
 * localStorage cache so reads are synchronous + offline-safe, and writes mirror
 * to the server best-effort for cross-device continuity.
 */

import { api } from '@/lib/api'
import { markSyncFailed, markSyncOk } from '@/lib/syncHealth'

export interface UiPrefs {
  /** 界面语言。存在 per-user prefs 而不是 settings.yml：后者是全局的，一个管理员
      切成英文会把所有人的界面一起切掉。 */
  lang?: 'zh' | 'en'
  /** 头像：客户端缩到 96×96 再重编码出来的 data URL。存 prefs 而不是单开一个
      上传接口 —— 它跟语言、默认索引是同一类东西（这台账号自己的偏好），跨设备
      同步走同一条路。重编码过一遍是关键：进来的字节不会原样存下去。 */
  avatar?: string
  defaultIndex?: string
  pageSize?: number
  /** 「深度思考」开关（components/ThinkingToggle.tsx）。默认 off。 */
  thinking?: 'on' | 'off'
  /** Visible columns keyed by index name (column sets are index-specific). */
  columns?: Record<string, string[]>
  /** Last local change to a scalar field (defaultIndex/pageSize). Lets a stale
   * GET avoid clobbering a pref the user just changed (read-after-write race). */
  updatedAt?: number
  /** Per-index last-change ts for the columns map — used to keep offline column
   * additions while still letting cross-device deletions propagate. */
  columnsUpdatedAt?: Record<string, number>
}

const KEY = 'rst.uiPrefs'

/** prefs 变了 —— 订阅它的组件（头像）据此重渲染。语言有自己的一套事件。 */
export const PREFS_EVENT = 'rst-prefs-changed'

function announce(): void {
  try {
    window.dispatchEvent(new CustomEvent(PREFS_EVENT))
  } catch {
    /* 没有 window 的环境（单测） */
  }
}

function readLocal(): UiPrefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? (parsed as UiPrefs) : {}
  } catch {
    return {}
  }
}

function writeLocal(p: UiPrefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(p))
  } catch {
    /* quota / private mode — server is then the only store */
  }
}

/** Synchronous snapshot from the local cache (for instant initial render). */
export function getPrefs(): UiPrefs {
  return readLocal()
}

/** Merge a patch into prefs: update the local cache now, mirror to the server.
 * Stamps `updatedAt` so a later (stale) GET won't revert this change. */
export function savePref(patch: Partial<UiPrefs>): void {
  const next: UiPrefs = { ...readLocal(), ...patch, updatedAt: Date.now() }
  writeLocal(next)
  announce()
  void api.statePut('pref', 'ui', next).then(
    () => markSyncOk('prefs'),
    () => markSyncFailed('prefs'),
  )
}

export function getColumns(index: string): string[] | null {
  return readLocal().columns?.[index] ?? null
}

export function saveColumns(index: string, cols: string[]): void {
  const cur = readLocal()
  const ts = Date.now()
  savePref({
    columns: { ...(cur.columns ?? {}), [index]: cols },
    columnsUpdatedAt: { ...(cur.columnsUpdatedAt ?? {}), [index]: ts },
  })
}

/** 清空所有索引的列集。不能只写 `columns: {}`：`mergeColumns` 会把别的设备
 * （或同步失败时本机）缓存的、时间戳比服务端最新值新的列集再推回来，重置
 * 悄悄失效。留一个 `__reset__` 时间戳当墓碑，让 serverNewest 落在「现在」，
 * 所有旧列集都算过期。`__reset__` 永远不会作为索引名被 getColumns 查到。 */
export function resetColumns(): void {
  savePref({ columns: {}, columnsUpdatedAt: { __reset__: Date.now() } })
}

/** Merge columns: server is authoritative for membership (deletions propagate),
 * but local index column-sets newer than anything the server has seen are kept
 * (offline additions not yet mirrored) — mirrors history's serverNewest rule. */
export function mergeColumns(
  local: UiPrefs,
  server: UiPrefs,
): { columns: Record<string, string[]>; columnsUpdatedAt: Record<string, number> } {
  const serverCols = server.columns ?? {}
  const serverColTs = server.columnsUpdatedAt ?? {}
  const localCols = local.columns ?? {}
  const localColTs = local.columnsUpdatedAt ?? {}
  const serverNewest = Object.values(serverColTs).reduce((m, t) => Math.max(m, t ?? 0), 0)
  const columns: Record<string, string[]> = {}
  const columnsUpdatedAt: Record<string, number> = {}
  // 墓碑没有对应的列集，下面按 columns 建表会把它丢掉；丢了之后这台设备下一次
  // savePref 就把没有墓碑的版本推回服务端，第三台设备上更老的列集又会被合并
  // 回来 —— 重置只撑到下一跳。两边谁的墓碑新取谁。
  const tomb = Math.max(serverColTs.__reset__ ?? 0, localColTs.__reset__ ?? 0)
  if (tomb > 0) columnsUpdatedAt.__reset__ = tomb
  for (const [idx, cols] of Object.entries(serverCols)) {
    // 本机刚重置、服务端那份还没跟上（慢 GET）：比墓碑老的服务端列集也不要。
    if ((serverColTs[idx] ?? 0) <= (localColTs.__reset__ ?? 0)) continue
    columns[idx] = cols
    columnsUpdatedAt[idx] = serverColTs[idx] ?? 0
  }
  for (const [idx, cols] of Object.entries(localCols)) {
    if ((localColTs[idx] ?? 0) > serverNewest) {
      columns[idx] = cols
      columnsUpdatedAt[idx] = localColTs[idx] ?? 0
    }
  }
  return { columns, columnsUpdatedAt }
}

/** Pull server prefs into the local cache. Read-after-write safe:
 *   • Scalar fields (defaultIndex/pageSize): if the local cache is *newer* than
 *     the server snapshot (`updatedAt`), we keep the local value so a slow GET
 *     can't revert a pref the user just changed; otherwise the server wins.
 *   • columns: merged so cross-device deletions still propagate (server is
 *     authoritative for membership) while offline additions aren't lost.
 * Pure read — never markSyncOk (that would mask write failures). Never throws.
 * Call once on app mount. */
export async function syncPrefsFromServer(): Promise<void> {
  try {
    const { value } = await api.stateGet<UiPrefs>('pref', 'ui')
    if (!value || typeof value !== 'object') return
    const local = readLocal()
    const localTs = local.updatedAt ?? 0
    const serverTs = value.updatedAt ?? 0
    const localScalarNewer = localTs > serverTs
    const { columns, columnsUpdatedAt } = mergeColumns(local, value)
    const merged: UiPrefs = {
      // lang / avatar 也按标量规则合并。以前这里没列它们，而 writeLocal 是整份
      // 覆盖 —— 于是每次启动同步都会把语言偏好抹掉，下一次 savePref 再把这个
      // "没有语言" 的版本推回服务端。表现是选了英文、刷新又回中文。
      lang: localScalarNewer ? (local.lang ?? value.lang) : (value.lang ?? local.lang),
      avatar: localScalarNewer ? (local.avatar ?? value.avatar) : (value.avatar ?? local.avatar),
      defaultIndex: localScalarNewer
        ? (local.defaultIndex ?? value.defaultIndex)
        : (value.defaultIndex ?? local.defaultIndex),
      pageSize: localScalarNewer
        ? (local.pageSize ?? value.pageSize)
        : (value.pageSize ?? local.pageSize),
      columns,
      columnsUpdatedAt,
      updatedAt: Math.max(localTs, serverTs),
    }
    writeLocal(merged)
    announce()
  } catch {
    /* offline / no server — local cache stands */
  }
}

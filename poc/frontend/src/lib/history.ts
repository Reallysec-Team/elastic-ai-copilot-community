/*
 * Local query-history store. Lives in localStorage so it survives reloads
 * but doesn't leak across browsers. Replaces the legacy /static UI's
 * HISTORY_KEY pattern.
 *
 * The "pending" channel lets other surfaces queue input for the 查询页 (ChatPage)
 * (used by FieldDictPage's "插入到查询" and the History drawer's replay).
 * Storage key holds one JSON blob:
 *   { question, index?, dsl?, confidence?, prompt_version? }
 *
 * When `dsl` is present in the pending payload, 查询页 (ChatPage) will short-circuit
 * the LLM call and reuse the cached DSL (for "重放" — saves tokens + latency).
 */

import { api } from '@/lib/api'
import { markSyncFailed, markSyncOk } from '@/lib/syncHealth'
import { translate } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'

const HISTORY_KEY = 'rst-query-history'
const HISTORY_MAX = 30

const isHistoryEntry = (e: unknown): e is HistoryEntry =>
  !!e &&
  typeof (e as HistoryEntry).question === 'string' &&
  typeof (e as HistoryEntry).index === 'string'

/** Merge a local list with the server's, keeping both sides. The server is
 * authoritative for membership (so deletions made elsewhere don't get revived),
 * while local entries newer than anything the server has seen are unsynced adds
 * we must keep. Newest `ts` wins per (question,index) key. Shared by the
 * read-path sync and the read-merge-write mirror. */
function mergeHistory(local: HistoryEntry[], server: HistoryEntry[]): HistoryEntry[] {
  const serverNewest = server.reduce((m, e) => Math.max(m, e.ts ?? 0), 0)
  const localUnsynced = local.filter((e) => (e.ts ?? 0) > serverNewest)
  const byKey = new Map<string, HistoryEntry>()
  for (const e of [...server, ...localUnsynced]) {
    const k = `${e.question}::${e.index}`
    const cur = byKey.get(k)
    if (!cur || (e.ts ?? 0) > (cur.ts ?? 0)) byKey.set(k, e)
  }
  return [...byKey.values()]
    .sort((a, b) => (b.ts ?? 0) - (a.ts ?? 0))
    .slice(0, HISTORY_MAX)
}

// Best-effort mirror of the full list to the server (kind `history`, key
// `list`), so history follows the user across devices. Plain overwrite — used
// by *removal* paths (delete/clear) where the local list is the authoritative
// new membership and the removal must propagate. Fire-and-forget; reports sync
// health so a silent server-write failure surfaces globally.
function mirror(list: HistoryEntry[]): void {
  void api.statePut('history', 'list', list).then(
    () => markSyncOk('history'),
    () => markSyncFailed('history'),
  )
}

// Read-merge-write mirror for the *add* path. A plain overwrite here would clobber
// entries another device/tab added concurrently (lost update): pushHistory writes
// the local list, then this would blindly PUT it. Instead we GET the latest server
// list, merge (keeping both sides), PUT the merged result, and reflect it locally.
// No loop risk: statePut doesn't trigger reads, and the change event only re-renders.
async function mirrorMerged(list: HistoryEntry[]): Promise<void> {
  try {
    const { value } = await api.stateGet<HistoryEntry[]>('history', 'list')
    const server = Array.isArray(value) ? value.filter(isHistoryEntry) : []
    const merged = mergeHistory(list, server)
    await api.statePut('history', 'list', merged)
    // Surface any remote entries the merge pulled in.
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(merged))
      window.dispatchEvent(new Event('rst-history-changed'))
    } catch {
      // ignore quota errors
    }
    markSyncOk('history')
  } catch {
    markSyncFailed('history')
  }
}

const PENDING_KEY = 'rst-pending'
const PENDING_Q_LEGACY = 'rst-pending-question'
const PENDING_IDX_LEGACY = 'rst-pending-index'

export interface HistoryEntry {
  id: string
  ts: number
  question: string
  index: string
  /** Best-effort cached DSL so the history can replay without re-asking the LLM. */
  dsl?: Record<string, unknown> | null
  prompt_version?: string | null
  confidence?: 'low' | 'medium' | 'high' | null
}

export function loadHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (e): e is HistoryEntry =>
        e && typeof e.question === 'string' && typeof e.index === 'string',
    )
  } catch {
    return []
  }
}

export function pushHistory(entry: Omit<HistoryEntry, 'id' | 'ts'>): HistoryEntry {
  const e: HistoryEntry = {
    ...entry,
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    ts: Date.now(),
  }
  const prev = loadHistory()
  // Dedup: drop earlier entries with the same (question, index) pair.
  const filtered = prev.filter(
    (p) => !(p.question === e.question && p.index === e.index),
  )
  const next = [e, ...filtered].slice(0, HISTORY_MAX)
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
    window.dispatchEvent(new Event('rst-history-changed'))
  } catch {
    // ignore quota errors
  }
  void mirrorMerged(next)
  return e
}

/** Pull the server's history (cross-device) and merge it into the local cache.
 *
 * The full list is mirrored to the server on every change, so on a *successful*
 * fetch the server blob is authoritative for membership: an entry deleted on
 * another device is absent from the server and must NOT be revived from this
 * device's stale local cache (which would also re-upload it on the next push).
 * We only keep local entries newer than anything the server has seen — those
 * are offline additions not yet mirrored. On fetch failure the local cache
 * stands untouched. Call once on app mount. */
export async function syncHistoryFromServer(): Promise<void> {
  try {
    const { value } = await api.stateGet<HistoryEntry[]>('history', 'list')
    if (!Array.isArray(value)) return // read path: never clears a write failure
    const server = value.filter(isHistoryEntry)
    const merged = mergeHistory(loadHistory(), server)
    localStorage.setItem(HISTORY_KEY, JSON.stringify(merged))
    window.dispatchEvent(new Event('rst-history-changed'))
    // NB: this is a pure read — do NOT markSyncOk here (would mask write failures).
  } catch {
    /* offline / no server — local cache stands */
  }
}

export function deleteHistory(id: string): void {
  const prev = loadHistory()
  const next = prev.filter((p) => p.id !== id)
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
    window.dispatchEvent(new Event('rst-history-changed'))
  } catch {
    // ignore
  }
  mirror(next)
}

export function clearHistory(): void {
  try {
    localStorage.removeItem(HISTORY_KEY)
    window.dispatchEvent(new Event('rst-history-changed'))
  } catch {
    // ignore
  }
  mirror([])
}

/** Ask a mounted 查询页 (ChatPage) to start a fresh query (clear question, result,
 * conversation). Navigating to `/` is not enough on its own: when the user is
 * already there the route doesn't remount and nothing resets. */
export const NEW_QUERY_EVENT = 'rst-new-query'

export function requestNewQuery(): void {
  window.dispatchEvent(new Event(NEW_QUERY_EVENT))
}

export interface PendingPayload {
  question: string
  index?: string | null
  /** Cached DSL — when present, 查询页 (ChatPage) skips the LLM call on hydrate. */
  dsl?: Record<string, unknown> | null
  confidence?: 'low' | 'medium' | 'high' | null
  prompt_version?: string | null
}

export function setPending(payload: PendingPayload): void {
  if (!payload.question) return
  try {
    localStorage.setItem(PENDING_KEY, JSON.stringify(payload))
    // Clear any legacy keys in case both schemes co-exist briefly.
    localStorage.removeItem(PENDING_Q_LEGACY)
    localStorage.removeItem(PENDING_IDX_LEGACY)
    window.dispatchEvent(new Event('rst-pending-changed'))
  } catch {
    // ignore quota / private mode failures
  }
}

export function takePending(): PendingPayload | null {
  try {
    const raw = localStorage.getItem(PENDING_KEY)
    if (raw) {
      localStorage.removeItem(PENDING_KEY)
      try {
        const parsed = JSON.parse(raw) as PendingPayload
        if (parsed && typeof parsed.question === 'string') return parsed
      } catch {
        // malformed — fall through
      }
    }
    // Legacy fallback (FieldDictPage previously wrote string keys directly).
    const q = localStorage.getItem(PENDING_Q_LEGACY)
    const i = localStorage.getItem(PENDING_IDX_LEGACY)
    if (q) {
      localStorage.removeItem(PENDING_Q_LEGACY)
      if (i) localStorage.removeItem(PENDING_IDX_LEGACY)
      return { question: q, index: i }
    }
    return null
  } catch {
    return null
  }
}

/*
 * 后端的时间戳有两种形状：ISO 串（ES 里的记录）和 epoch 秒（llm_router 的
 * `time.time()`）。都归成毫秒；解析不了返回 null，调用方画「—」而不是抛
 * RangeError 把整页炸掉（AI 配置页出过一次：`Date.parse(1789233720.9)` 是 NaN）。
 */
export function toMs(v: string | number | null | undefined): number | null {
  if (v == null || v === '' || v === 0) return null
  const n = typeof v === 'number' ? (v < 1e12 ? v * 1000 : v) : Date.parse(v)
  return Number.isFinite(n) ? n : null
}

export function relativeTime(ts: number): string {
  if (!Number.isFinite(ts)) return '—'
  const diff = Date.now() - ts
  if (diff < 60_000) return translate(commonCopy, 'justNow')
  if (diff < 3_600_000)
    return translate(commonCopy, 'minutesAgo', { n: Math.floor(diff / 60_000) })
  if (diff < 86_400_000)
    return translate(commonCopy, 'hoursAgo', { n: Math.floor(diff / 3_600_000) })
  if (diff < 7 * 86_400_000)
    return translate(commonCopy, 'daysAgo', { n: Math.floor(diff / 86_400_000) })
  return new Date(ts).toISOString().slice(0, 10)
}

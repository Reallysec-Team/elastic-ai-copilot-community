/*
 * Disposition state (未处置 / 已处置 / 误报 / 升级).
 *
 * TEAM-shared via the server state store (owner `_team`), so a mark by one
 * analyst is visible to the whole shift instead of being trapped in one
 * browser's localStorage. localStorage is kept as an offline cache + instant-
 * paint fallback: writes go through to the server best-effort and always update
 * the local cache, and `loadStatuses` merges server (authoritative) over local
 * so a deployment with no ES write / no gateway still works exactly as before.
 *
 * Two surfaces need this over different subjects — triage clusters and
 * real-time alerts — so the store is parameterised by its server kind and
 * localStorage key rather than copied. The namespaces MUST stay separate: an
 * alert id colliding with a cluster id would leak one surface's mark into the
 * other's list.
 */

import { api } from '@/lib/api'
import { translate } from '@/lib/i18n'
import { commonCopy, type CommonKey } from '@/locales/common'
import { markSyncFailed, markSyncOk } from '@/lib/syncHealth'

export type TriageStatus = 'open' | 'handled' | 'fp' | 'escalated'

/* 存的是文案键：这四个词在分诊页的筛选、分诊卡的一排按钮、并排对比、深入调查
   弹窗四处显示。取名走 `statusLabel()`，和 `severityLabel()` 同一个做法。 */
export const STATUS_KEYS: Record<TriageStatus, CommonKey> = {
  open: 'stOpen',
  handled: 'stHandled',
  fp: 'stFp',
  escalated: 'stEscalated',
}

export function statusLabel(status: TriageStatus): string {
  return translate(commonCopy, STATUS_KEYS[status])
}

export const STATUS_ORDER: TriageStatus[] = ['open', 'handled', 'fp', 'escalated']

// ── localStorage cache (offline fallback) ───────────────────────────────────
//
// Each entry carries an `updatedAt` timestamp and a `pending` flag so we can
// reconcile against the server without (a) losing a fresh local write under a
// stale server snapshot, or (b) reviving an entry another device deleted.
//   • status === 'open' is a *tombstone* (a cleared disposition).
//   • pending === true  means "this write hasn't been confirmed by the server".

interface LocalEntry {
  status: TriageStatus
  updatedAt: number
  pending?: boolean
}

type LocalMap = Record<string, LocalEntry>

function parseTs(iso: string | null): number {
  if (!iso) return 0
  const t = Date.parse(iso)
  return Number.isNaN(t) ? 0 : t
}

/** Project entries to the plain status map callers consume; tombstones drop out. */
function toStatusMap(all: LocalMap): Record<string, TriageStatus> {
  const out: Record<string, TriageStatus> = {}
  for (const [k, e] of Object.entries(all)) {
    if (e.status !== 'open') out[k] = e.status
  }
  return out
}

export interface StatusStore {
  /** Synchronous best-guess from the local cache (for instant first paint). */
  getStatusLocal: (id: string) => TriageStatus
  loadStatuses: () => Promise<Record<string, TriageStatus>>
  saveStatus: (id: string, status: TriageStatus) => Promise<boolean>
  probeSync: () => Promise<boolean>
}

function createStatusStore(kind: string, storageKey: string, surface: string): StatusStore {
  function readLocalEntries(): LocalMap {
    try {
      const raw = localStorage.getItem(storageKey)
      if (!raw) return {}
      const parsed = JSON.parse(raw)
      if (!parsed || typeof parsed !== 'object') return {}
      const out: LocalMap = {}
      for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
        if (typeof v === 'string') {
          // Legacy format: bare status string. Treat as oldest so the server wins.
          out[k] = { status: v as TriageStatus, updatedAt: 0 }
        } else if (v && typeof v === 'object' && 'status' in v) {
          const e = v as LocalEntry
          out[k] = {
            status: e.status,
            updatedAt: typeof e.updatedAt === 'number' ? e.updatedAt : 0,
            ...(e.pending ? { pending: true } : {}),
          }
        }
      }
      return out
    } catch {
      return {}
    }
  }

  function writeLocalEntries(all: LocalMap): void {
    try {
      localStorage.setItem(storageKey, JSON.stringify(all))
    } catch {
      /* localStorage disabled — server is then the only store */
    }
  }

  /** Load all dispositions, reconciling server (authoritative) with local.
   *
   * Merge rules per key:
   *   • both present  → keep whichever has the newer `updatedAt` (a local write
   *                     made while this request was in flight therefore wins).
   *   • server only   → take the server value.
   *   • local only    → the server *succeeded* and has no such key, so it was
   *                     cleared elsewhere → drop it (don't revive). The only
   *                     exception is a still-`pending` local write the server
   *                     hasn't seen yet — keep that so we don't lose it.
   *
   * Never throws — on a network failure the local cache is returned untouched
   * (absence is NOT treated as a delete in that case).
   */
  async function loadStatuses(): Promise<Record<string, TriageStatus>> {
    try {
      const { items } = await api.stateList<TriageStatus>(kind)
      const server: Record<string, LocalEntry> = {}
      for (const it of items) {
        if (it.key && it.value) server[it.key] = { status: it.value, updatedAt: parseTs(it.updated_at) }
      }
      // Re-read local AFTER the await so writes made during the request are seen.
      const local = readLocalEntries()
      const merged: LocalMap = {}
      for (const key of new Set([...Object.keys(local), ...Object.keys(server)])) {
        const l = local[key]
        const s = server[key]
        if (l && s) {
          merged[key] = l.updatedAt >= s.updatedAt ? l : s
        } else if (s) {
          merged[key] = s
        } else if (l?.pending) {
          merged[key] = l // unsynced local write the server hasn't caught up to
        }
        // local-only & not pending → cleared on another device → drop it.
      }
      writeLocalEntries(merged)
      // Pure read — do NOT markSyncOk (would mask a pending write failure).
      return toStatusMap(merged)
    } catch {
      // Pure read failure isn't a write failure; leave sync health untouched.
      return toStatusMap(readLocalEntries())
    }
  }

  /** Persist one subject's disposition. Updates the local cache immediately
   * (timestamped + marked pending), then writes through to the server. Returns
   * true when the server write succeeded — false means the mark is LOCAL-ONLY
   * (offline / no ES write), so the caller can warn the analyst rather than let
   * them believe the team can see it. */
  async function saveStatus(id: string, status: TriageStatus): Promise<boolean> {
    const ts = Date.now()
    // Write through locally first, marked pending. 'open' is kept as a tombstone
    // (not deleted) so a concurrent loadStatuses can't revive an older server value.
    const before = readLocalEntries()
    before[id] = { status, updatedAt: ts, pending: true }
    writeLocalEntries(before)
    try {
      if (status === 'open') await api.stateDelete(kind, id)
      else await api.statePut(kind, id, status)
      // Confirm sync: clear the pending flag (re-read to keep any newer write).
      const after = readLocalEntries()
      const cur = after[id]
      if (cur && cur.updatedAt === ts) {
        if (status === 'open') delete after[id] // tombstone confirmed → clean up
        else after[id] = { status, updatedAt: ts }
        writeLocalEntries(after)
      }
      markSyncOk(surface)
      return true
    } catch {
      markSyncFailed(surface)
      return false
    }
  }

  /** True when the server-side store is reachable (used to warn that
   * disposition is local-only). Never throws. */
  async function probeSync(): Promise<boolean> {
    // Pure connectivity read: report reachability to the caller but don't touch
    // global sync health — a read succeeding must not clear a write failure (the
    // "reads work, ES has no write" case), and a read failing isn't a write fail.
    try {
      await api.stateList<TriageStatus>(kind)
      return true
    } catch {
      return false
    }
  }

  return {
    getStatusLocal: (id: string) => readLocalEntries()[id]?.status ?? 'open',
    loadStatuses,
    saveStatus,
    probeSync,
  }
}

// ── instances ───────────────────────────────────────────────────────────────

const triage = createStatusStore('triage_status', 'rst.triageStatus', 'triage')

// Named re-exports keep every existing triage call site unchanged.
export const getStatusLocal = triage.getStatusLocal
export const loadStatuses = triage.loadStatuses
export const saveStatus = triage.saveStatus
export const probeSync = triage.probeSync

/** Disposition for real-time alerts. Separate kind + storage key from triage. */
export const alertStatus = createStatusStore('alert_status', 'rst.alertStatus', 'alerts')

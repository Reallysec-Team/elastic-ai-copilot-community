/*
 * Named saved queries (Wave 2 #5). A query the analyst runs daily can be saved
 * with a name and replayed from the landing page. Server-backed (kind
 * `saved_query`, one doc per query) with a localStorage cache for instant paint
 * + offline. Fires `rst-saved-queries-changed` so the landing list refreshes.
 */

import { api } from '@/lib/api'
import { markSyncFailed, markSyncOk } from '@/lib/syncHealth'

export interface SavedQuery {
  id: string
  name: string
  question: string
  index: string
  dsl?: Record<string, unknown> | null
  ts: number
}

const KEY = 'rst.savedQueries'
const EVENT = 'rst-saved-queries-changed'

function readLocal(): SavedQuery[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as SavedQuery[]) : []
  } catch {
    return []
  }
}

function writeLocal(list: SavedQuery[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(list))
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(EVENT))
}

export const SAVED_QUERIES_EVENT = EVENT

export function listSavedLocal(): SavedQuery[] {
  return readLocal().sort((a, b) => (b.ts ?? 0) - (a.ts ?? 0))
}

/** Server list (authoritative) merged into the local cache. Never throws.
 *
 * On a successful fetch the server is authoritative for membership: a query
 * deleted on another device is absent from the server and must NOT be revived
 * from this device's stale cache. We only retain local entries that are newer
 * than anything the server has seen — offline adds not yet mirrored. On failure
 * the local cache stands (and we flag the sync as failed). */
export async function loadSaved(): Promise<SavedQuery[]> {
  try {
    const { items } = await api.stateList<SavedQuery>('saved_query')
    const server = items
      .map((it) => it.value)
      .filter((v): v is SavedQuery => !!v && typeof v.question === 'string')
    const serverIds = new Set(server.map((s) => s.id))
    const serverNewest = server.reduce((m, s) => Math.max(m, s.ts ?? 0), 0)
    const localUnsynced = readLocal().filter(
      (s) => !serverIds.has(s.id) && (s.ts ?? 0) > serverNewest,
    )
    writeLocal([...server, ...localUnsynced])
    // Pure read — do NOT markSyncOk (would mask a pending write failure).
    return listSavedLocal()
  } catch {
    // Pure read failure isn't a write failure; leave sync health untouched.
    return listSavedLocal()
  }
}

export async function addSaved(
  input: Omit<SavedQuery, 'id' | 'ts'>,
): Promise<SavedQuery> {
  const sq: SavedQuery = {
    ...input,
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    ts: Date.now(),
  }
  writeLocal([sq, ...readLocal()])
  try {
    await api.statePut('saved_query', sq.id, sq)
    markSyncOk('saved')
  } catch {
    markSyncFailed('saved') // offline — local cache holds it, but flag it
  }
  return sq
}

export async function removeSaved(id: string): Promise<void> {
  writeLocal(readLocal().filter((s) => s.id !== id))
  try {
    await api.stateDelete('saved_query', id)
    markSyncOk('saved')
  } catch {
    markSyncFailed('saved')
  }
}

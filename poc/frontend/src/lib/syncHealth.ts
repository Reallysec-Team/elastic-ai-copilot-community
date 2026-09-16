/*
 * Global server-state sync health. The per-owner state writes (history, prefs,
 * saved queries, triage disposition) fall back to localStorage when the server
 * is unreachable / has no ES write — useful, but the analyst shouldn't silently
 * believe their data is saved server-side. AppShell renders a small "未同步"
 * chip while degraded.
 *
 * Health is modelled as a set of *surfaces* whose last WRITE failed (e.g.
 * 'history', 'prefs', 'saved', 'triage'). `degraded` is simply "the set is
 * non-empty". This is deliberately keyed per surface so that:
 *   • a successful write to surface X clears only X's failure flag, and
 *   • a successful *read* on any surface does NOT clear another surface's write
 *     failure — reads must never call markSyncOk (the classic case is "reads
 *     work but ES has no write": writes fail, the chip must stay up).
 *
 * Callers without a meaningful surface may omit it; a shared default bucket is
 * used so legacy call sites keep working.
 */

import { translate } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'

const failed = new Set<string>()
const DEFAULT_SURFACE = 'global'
const EVENT = 'rst-sync-health'

export const SYNC_HEALTH_EVENT = EVENT

export function isSyncDegraded(): boolean {
  return failed.size > 0
}

function emit(): void {
  try {
    window.dispatchEvent(new Event(EVENT))
  } catch {
    /* non-browser context */
  }
}

/** A server-state WRITE for `surface` succeeded — clear that surface's flag.
 * Only call from write paths; reads must not clear write failures. */
export function markSyncOk(surface: string = DEFAULT_SURFACE): void {
  if (failed.delete(surface)) emit()
}

/*
 * One wording for "this change is local-only". It had drifted into four
 * variants across AppShell / TriagePage (×2) / RealtimeAlertsPage — the same
 * failure told four different ways, two of them byte-identical copy-paste.
 * Some variants gave the consequence, others gave the fix; the analyst needs
 * both every time, so this says both.
 */
export function syncWarning(what: string): string {
  return translate(commonCopy, 'syncWarning', { what })
}

/** A server-state WRITE for `surface` failed — the change is local-only. */
export function markSyncFailed(surface: string = DEFAULT_SURFACE): void {
  if (!failed.has(surface)) {
    failed.add(surface)
    emit()
  }
}

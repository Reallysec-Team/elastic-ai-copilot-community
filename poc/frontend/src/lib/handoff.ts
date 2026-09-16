/*
 * Cross-page handoff channel (Round 12).
 *
 * Lets one page stage a richer payload for another page — e.g. "send these
 * query hits to the triage page". Distinct from `lib/history.ts`'s pending
 * channel (which is only question/index/dsl for the 查询页 (ChatPage)).
 *
 * One-shot: the target page consumes it on mount and clears it. Keyed by
 * target route so two handoffs to different pages don't collide.
 */

const KEY_PREFIX = 'rst-handoff:'

export type HandoffTarget = 'triage' | 'detection-rule'

interface HandoffPayloads {
  triage: {
    /** Raw alert docs to pre-fill the triage paste box. */
    alerts: Record<string, unknown>[]
    /** Where the alerts came from — shown as a note. */
    sourceNote?: string
  }
  'detection-rule': {
    question: string
    index?: string
  }
}

export function setHandoff<T extends HandoffTarget>(
  target: T,
  payload: HandoffPayloads[T],
): void {
  try {
    sessionStorage.setItem(KEY_PREFIX + target, JSON.stringify(payload))
  } catch {
    // sessionStorage can be unavailable (private mode) — handoff just no-ops.
  }
}

export function takeHandoff<T extends HandoffTarget>(
  target: T,
): HandoffPayloads[T] | null {
  try {
    const raw = sessionStorage.getItem(KEY_PREFIX + target)
    if (!raw) return null
    sessionStorage.removeItem(KEY_PREFIX + target)
    return JSON.parse(raw) as HandoffPayloads[T]
  } catch {
    return null
  }
}

/**
 * Expand a dotted ES field path + value into a nested object.
 * `expandPath('source.ip', '1.2.3.4')` → `{ source: { ip: '1.2.3.4' } }`
 * Used to synthesise an alert doc from a triage cluster summary.
 */
export function expandPath(path: string, value: unknown): Record<string, unknown> {
  const parts = path.split('.')
  const root: Record<string, unknown> = {}
  let cur = root
  for (let i = 0; i < parts.length - 1; i++) {
    const next: Record<string, unknown> = {}
    cur[parts[i]] = next
    cur = next
  }
  cur[parts[parts.length - 1]] = value
  return root
}

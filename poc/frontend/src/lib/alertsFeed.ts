import type { RealtimeAlert } from '@/lib/api'

/* Pure display/filter logic behind 实时告警. Lives outside the page so it can be
 * tested without a DOM: the page keeps the data flow (SSE, paging, refs), this
 * file keeps the decisions. */

export interface Filters {
  severity: string
  rule: string // already debounced
  /** 序列化的时间范围：'' | '5m' | … | 'custom:<since>..<until>'（见 time-range-picker） */
  timeRange: string
}

/* Flat display-item model the virtualizer iterates over. A 'group' item is a
 * collapsed run of consecutive same-key alerts (head = latest). When expanded,
 * its members follow as 'row' items (child) — so expansion is just more flat
 * items, keeping virtualization trivial. */
export type DisplayItem =
  | { id: string; kind: 'group'; groupKey: string; head: RealtimeAlert; count: number; expanded: boolean }
  | { id: string; kind: 'row'; alert: RealtimeAlert; child: boolean }

export function groupKeyOf(a: RealtimeAlert): string {
  return `${a.rule_id || a.rule_name}|${a.subject_field ?? ''}=${a.subject_value ?? ''}`
}

export function buildDisplayItems(
  alerts: RealtimeAlert[],
  grouped: boolean,
  expanded: Set<string>,
): DisplayItem[] {
  if (!grouped) return alerts.map((a) => ({ id: a.alert_id, kind: 'row', alert: a, child: false }))
  const out: DisplayItem[] = []
  let i = 0
  while (i < alerts.length) {
    const key = groupKeyOf(alerts[i])
    let j = i + 1
    while (j < alerts.length && groupKeyOf(alerts[j]) === key) j++
    const run = alerts.slice(i, j)
    if (run.length === 1) {
      out.push({ id: run[0].alert_id, kind: 'row', alert: run[0], child: false })
    } else {
      const expKey = key + ':' + run[0].alert_id
      const isExp = expanded.has(expKey)
      out.push({ id: 'g:' + run[0].alert_id, kind: 'group', groupKey: expKey, head: run[0], count: run.length, expanded: isExp })
      if (isExp) for (const m of run) out.push({ id: 'm:' + m.alert_id, kind: 'row', alert: m, child: true })
    }
    i = j
  }
  return out
}

// Client-side gate for live SSE alerts, mirroring the active server filters.
export function matchesFilters(
  a: RealtimeAlert,
  f: Filters,
  sinceIso?: string,
  untilIso?: string,
): boolean {
  if (f.severity && a.severity !== f.severity) return false
  if (f.rule) {
    const q = f.rule.toLowerCase()
    if (!`${a.rule_name} ${a.rule_id}`.toLowerCase().includes(q)) return false
  }
  // ponytail: lexical ISO compare — safe for the Z-normalized @timestamp the gateway emits.
  if (sinceIso && a['@timestamp'] < sinceIso) return false
  // 自定义区间有上界：窗口结束之后新来的实时告警不该插进这一屏 —— 用户正在看的
  // 是一段历史，不是「现在」。
  if (untilIso && a['@timestamp'] > untilIso) return false
  return true
}

export function formatTs(s?: string): string {
  if (!s) return '—'
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return s
    return d.toLocaleString()
  } catch {
    return s
  }
}

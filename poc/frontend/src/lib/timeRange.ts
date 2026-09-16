/*
 * How far the data in an index actually reaches.
 *
 * A live test asked "最近 30 天登录失败的事件" on 2026-09-02 against an index
 * whose newest document was 2026-08-08. The product said nothing about that,
 * and the 0-hit handling went straight to blaming the index — when the real
 * answer was "you asked about a window that is almost entirely after the data
 * ends". A stale index is the most common cause of an empty result in a
 * customer deployment, and it is the one thing nothing on screen ever said.
 *
 * Costs one `min`/`max` aggregation for the whole scope, not one per index.
 */

import { api, type ExecuteResponse } from '@/lib/api'
import { friendlyIndexName } from '@/lib/searchScope'

const RANGE_AGG = '__rst_time_range'

export interface TimeRange {
  /** Epoch millis of the oldest / newest document. */
  lo: number
  hi: number
}

/** One request: bucket by `_index`, take min/max of the time field in each. */
export function buildRangeDsl(timeField = '@timestamp'): Record<string, unknown> {
  return {
    size: 0,
    aggs: {
      [RANGE_AGG]: {
        terms: { field: '_index', size: 50 },
        aggs: {
          lo: { min: { field: timeField } },
          hi: { max: { field: timeField } },
        },
      },
    },
  }
}

export function parseRanges(result: ExecuteResponse): Record<string, TimeRange> {
  const agg = (result.aggregations as Record<string, unknown> | undefined)?.[RANGE_AGG]
  const buckets = (agg as { buckets?: unknown } | undefined)?.buckets
  if (!Array.isArray(buckets)) return {}
  const out: Record<string, TimeRange> = {}
  for (const raw of buckets) {
    const b = raw as { key?: unknown; lo?: { value?: unknown }; hi?: { value?: unknown } }
    if (typeof b.key !== 'string') continue
    const lo = b.lo?.value
    const hi = b.hi?.value
    if (typeof lo !== 'number' || typeof hi !== 'number') continue
    out[b.key] = { lo, hi }
  }
  return out
}

/** `2026-08-08` — the precision an operator needs when judging staleness. */
export function formatDay(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export function formatRange(r: TimeRange): string {
  return `${formatDay(r.lo)} → ${formatDay(r.hi)}`
}

const MATH_UNITS: Record<string, number> = {
  s: 1000,
  m: 60_000,
  h: 3_600_000,
  H: 3_600_000,
  d: 86_400_000,
  w: 604_800_000,
  M: 30 * 86_400_000, // ES rounds by calendar; a day-based month is close enough
  y: 365 * 86_400_000,
}

/**
 * Resolve the subset of ES date math the generator actually emits:
 * `now`, `now-30d`, `now-1h/w/M/y`, an epoch-millis number, or an ISO string.
 * Returns null for anything else rather than guessing — a wrong resolution
 * would produce a confidently wrong "your window is stale" claim.
 */
export function resolveDateMath(expr: unknown, now: number = Date.now()): number | null {
  if (typeof expr === 'number') return Number.isFinite(expr) ? expr : null
  if (typeof expr !== 'string') return null
  const s = expr.trim()
  if (!s) return null
  // Rounding suffixes (`now-1d/d`) only widen the window; drop them.
  const noRounding = s.replace(/\/[smhHdwMy]$/, '')
  if (noRounding === 'now') return now
  const m = /^now([+-])(\d+)([smhHdwMy])$/.exec(noRounding)
  if (m) {
    const unit = MATH_UNITS[m[3]]
    if (!unit) return null
    const delta = Number(m[2]) * unit
    return m[1] === '-' ? now - delta : now + delta
  }
  const parsed = Date.parse(s)
  return Number.isNaN(parsed) ? null : parsed
}

/** The lower bound of the first `range` clause in a DSL, resolved to millis. */
export function extractQueryStart(
  dsl: Record<string, unknown>,
  now: number = Date.now(),
): number | null {
  let found: number | null = null
  const walk = (node: unknown): void => {
    if (found !== null || node === null || typeof node !== 'object') return
    if (Array.isArray(node)) {
      node.forEach(walk)
      return
    }
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      if (found !== null) return
      if (key === 'range' && value && typeof value === 'object') {
        for (const bound of Object.values(value as Record<string, unknown>)) {
          if (!bound || typeof bound !== 'object') continue
          const gte = (bound as Record<string, unknown>).gte ?? (bound as Record<string, unknown>).gt
          const resolved = resolveDateMath(gte, now)
          if (resolved !== null) {
            found = resolved
            return
          }
        }
      }
      walk(value)
    }
  }
  walk(dsl)
  return found
}

/**
 * Did the question ask about a window that ends after the data does?
 * Only true when the query starts strictly after the newest document — that is
 * the case where the empty result is fully explained by staleness.
 */
export function isWindowAfterData(queryStart: number | null, range: TimeRange | null): boolean {
  if (queryStart === null || !range) return false
  return queryStart > range.hi
}

/* 未来的日志不存在。索引里出现比当前时间还晚的数据，只有两个原因：采集端把本地
   时间当 UTC 写入（整体偏移，常见是 8 小时），或者数据源主机时钟快了。

   为什么单独判它：这种情况下「最近 1 小时」查出 0 条，而 `isWindowAfterData`
   不会触发 —— 查询起点（now-1h）确实早于数据终点（now+8h）。用户拿到的是一个
   没有任何解释的空结果，而原因跟他的查询无关。

   容差 5 分钟：几分钟的领先是正常的时钟微漂和采集抖动，不值得每次查询都说一句。 */
export const FUTURE_TOLERANCE_MS = 5 * 60_000

export function dataReachesIntoFuture(
  range: TimeRange | null,
  now: number = Date.now(),
): boolean {
  return !!range && range.hi > now + FUTURE_TOLERANCE_MS
}

/** 领先多少小时 —— 接近整数小时（尤其 8）基本可以断定是时区，不是时钟漂移。 */
export function hoursAhead(range: TimeRange, now: number = Date.now()): number {
  return (range.hi - now) / 3_600_000
}

/**
 * Fold backing indices into the names the user actually picks from. A data
 * stream reports one bucket per generation (`.ds-...-000001`, `-000002`), so the
 * stream's real span is the widest of them.
 */
export function mergeRangesByName(
  ranges: Record<string, TimeRange>,
  known: string[],
): Record<string, TimeRange> {
  const out: Record<string, TimeRange> = {}
  for (const [raw, r] of Object.entries(ranges)) {
    const name = friendlyIndexName(raw, known)
    const prev = out[name]
    out[name] = prev ? { lo: Math.min(prev.lo, r.lo), hi: Math.max(prev.hi, r.hi) } : r
  }
  return out
}

/* Ranges are per index and move only as fast as ingestion; one fetch per page
 * load is plenty, and it keeps the picker from re-aggregating on every open. */
let cache: Promise<Record<string, TimeRange>> | null = null

export function fetchTimeRanges(scope: string): Promise<Record<string, TimeRange>> {
  cache ??= api
    .execute({ index: scope, dsl: buildRangeDsl() })
    .then((r) => mergeRangesByName(parseRanges(r), scope.split(',')))
    .catch(() => ({}))
  return cache
}

export function resetTimeRangeCache(): void {
  cache = null
}

/*
 * Whether a search answered "nothing matched".
 *
 * A live test asked "最近 24 小时每个事件 ID 各有多少条" against an index whose
 * data stops weeks earlier. The 0-hit handling only fired for document answers
 * (`!r.aggregations`), so the aggregation path rendered a header-only table
 * with an "导出 CSV" button next to it and explained nothing — the exact dead
 * end the 0-hit rescue exists to remove.
 */

import type { ExecuteResponse } from '@/lib/api'

export function countHits(r: ExecuteResponse): number {
  const t = r.hits?.total
  if (typeof t === 'number') return t
  if (t && typeof t === 'object') return t.value ?? 0
  return 0
}

/**
 * A metric aggregation (avg / cardinality) always carries a value, so only
 * bucket aggregations can be empty — and every one of them has to be empty
 * before the answer counts as a miss. An aggregation shape we don't recognise
 * is left alone: showing it is better than hiding a real answer.
 */
export function isEmptyResult(r: ExecuteResponse): boolean {
  if (countHits(r) > 0) return false
  if (!r.aggregations) return true
  const bucketed = Object.values(r.aggregations)
    .map((b) => (b as Record<string, unknown> | null)?.buckets)
    .filter(Array.isArray)
  return bucketed.length > 0 && bucketed.every((b) => b.length === 0)
}

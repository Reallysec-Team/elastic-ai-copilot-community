/*
 * One number out of a sub-aggregation.
 *
 * Metrics (`avg`, `cardinality`, …) carry `.value`; a `filter` sub-aggregation
 * carries `.doc_count`. Only the first was recognised, so the standard
 * no-script way to put "成功次数 / 失败次数" in their own columns —
 * terms(source.ip) + two filter sub-aggs — rendered as a bare doc_count and the
 * split the analyst asked for silently vanished. A nested `terms` is
 * `{buckets: [...]}` with no top-level count, so it still falls through here —
 * `subAggCols` reports it as `nested` so the table can say so out loud.
 */
export function subAggValue(v: unknown): number | undefined {
  const o = v as Record<string, unknown> | null | undefined
  if (typeof o?.value === 'number') return o.value
  if (typeof o?.doc_count === 'number') return o.doc_count
  return undefined
}

const BUCKET_META = new Set(['key', 'key_as_string', 'doc_count'])

export interface SubAggCols {
  /** Sub-aggregations that reduce to one number — one column each. */
  cols: string[]
  /** Sub-aggregations we can't put in a cell (nested `terms`, …). Named in the
   * UI rather than dropped, because a missing column looks like a fine answer. */
  nested: string[]
}

/**
 * Which sub-aggregation columns a bucket list has.
 *
 * Sampling only `buckets[0]` was the bug: ES omits a sub-aggregation key from a
 * bucket that has nothing in it, so one empty first bucket erased the column
 * for all 200 rows — a table that still looks complete. Take the union over
 * every bucket; the buckets that genuinely lack a value render as `—`.
 */
export function subAggCols(buckets: Record<string, unknown>[]): SubAggCols {
  const numeric = new Set<string>()
  const order: string[] = []
  for (const b of buckets) {
    for (const k of Object.keys(b)) {
      if (BUCKET_META.has(k)) continue
      if (!order.includes(k)) order.push(k)
      if (subAggValue(b[k]) !== undefined) numeric.add(k)
    }
  }
  return {
    cols: order.filter((k) => numeric.has(k)),
    nested: order.filter((k) => !numeric.has(k)),
  }
}

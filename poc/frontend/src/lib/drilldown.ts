/*
 * Aggregation drill-down.
 *
 * A `size:0` aggregation answer is a table of counts with no next step — every
 * downstream action (解释 / 调查 / 送去分诊) needs raw hits. Drilling rebuilds
 * the SAME query with one bucket's own constraint appended and the aggs
 * dropped, so what comes back is exactly "the documents behind this number"
 * rather than a fresh guess at what the user meant.
 */

export interface DrillDown {
  /** Executable DSL: original query AND the bucket constraint, hits only. */
  dsl: Record<string, unknown>
  /** Human label for the drill banner, e.g. `source.ip = 10.252.121.4`. */
  label: string
}

/**
 * Build the drill-down query for one aggregation bucket.
 *
 * Returns null when the aggregation isn't bucketed by a field (filters /
 * global / nested aggs have no single value to filter on) or the name isn't a
 * top-level aggregation of `base`.
 *
 * @param base    the DSL that produced the aggregation
 * @param aggName top-level aggregation name the bucket came from
 * @param bucket  the ES bucket (`key`, optional `key_as_string`)
 * @param nextKey the FOLLOWING bucket's key — bounds a histogram bucket; pass
 *                undefined/null for the last bucket to leave it open-ended
 * @param size    how many documents to fetch
 */
export function buildDrillDsl(
  base: Record<string, unknown>,
  aggName: string,
  bucket: Record<string, unknown>,
  nextKey: unknown,
  size: number,
): DrillDown | null {
  const spec = (base.aggs ?? base.aggregations) as Record<string, unknown> | undefined
  const agg = spec?.[aggName] as Record<string, unknown> | undefined
  const terms = agg?.terms as { field?: string } | undefined
  const hist = (agg?.date_histogram ?? agg?.histogram) as { field?: string } | undefined
  const field = terms?.field ?? hist?.field
  if (!field) return null

  // Filter on the RAW key — `key_as_string` is a display rendering (a formatted
  // date, a boolean's "true") and won't match. It's only good for the label.
  const clause: Record<string, unknown> = hist?.field
    ? {
        // A histogram bucket is the half-open interval [key, nextKey).
        range: {
          [field]: nextKey == null ? { gte: bucket.key } : { gte: bucket.key, lt: nextKey },
        },
      }
    : { term: { [field]: bucket.key } }

  const baseQuery = (base.query as Record<string, unknown> | undefined) ?? { match_all: {} }

  return {
    dsl: {
      size,
      query: { bool: { filter: [baseQuery, clause] } },
      sort: [{ '@timestamp': { order: 'desc', unmapped_type: 'date' } }],
    },
    label: `${field} = ${String(bucket.key_as_string ?? bucket.key)}`,
  }
}

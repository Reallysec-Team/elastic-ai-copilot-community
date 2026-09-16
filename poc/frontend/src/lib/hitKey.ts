/*
 * Stable per-row key for an ES hit.
 *
 * `_id` alone is NOT unique across a multi-index search (`logs-*`): two indices
 * can hand back the same `_id`, and the result table keys row selection off
 * this string — so a collision silently checks the wrong row, and "导出这 5 行"
 * exports someone else's documents. Qualify with `_index` whenever ES gave us
 * one. Positional fallback only when the hit carries no id at all.
 */
export function hitKey(hit: { _id?: string; _index?: string }, i: number): string {
  if (hit._id == null) return `row-${i}`
  return hit._index ? `${hit._index}:${hit._id}` : hit._id
}

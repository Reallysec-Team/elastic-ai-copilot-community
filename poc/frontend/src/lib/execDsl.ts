/*
 * Final shaping of a generated DSL right before execution.
 *
 * Lifted out of QueryPage when the query surface became the chat page — the
 * rules are the same, they just now apply per answer instead of per page.
 */

import type { SortDir } from '@/components/ResultTable'
import { translate } from '@/lib/i18n'
import { libCopy } from '@/locales/lib'

/**
 * Inject the chosen size + a real sort into the DSL, so the result table
 * reflects a true top-N over the whole match set rather than a client-side
 * reorder of the first N fetched rows. `track_total_hits` makes the hit count
 * exact (ES otherwise caps the reported total at 10,000).
 */
export function buildExecDsl(
  base: Record<string, unknown>,
  size: number,
  sort: { col: string; dir: SortDir } | null,
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...base }
  const hasAggs = !!(next.aggs ?? next.aggregations)
  if (typeof next.size === 'number') {
    // An explicit size (incl. 0) is always respected — LLM Top-N, a hand-edit
    // in DslPreview, or a legit {aggs, size:N} that wants both stats and a
    // sample of hits. Don't clobber it.
  } else if (hasAggs) {
    // Aggregation query without an explicit size — the user wants the stats,
    // not raw hits. Default size:0 so the agg table renders (it only shows when
    // there are no hits) and we skip transferring documents we won't display.
    next.size = 0
  } else {
    // Plain query with no size in the DSL — fall back to the size control.
    next.size = size
  }
  next.track_total_hits = true
  if (sort) next.sort = [{ [sort.col]: { order: sort.dir } }]
  return next
}

/** Per-generation cost line: elapsed time + tokens (or output chars). */
export function genCostText(c: {
  duration_ms?: number
  output_chars?: number
  usage?: {
    prompt_tokens?: number | null
    completion_tokens?: number | null
    total_tokens?: number | null
  } | null
}): string {
  const parts: string[] = []
  if (c.duration_ms != null) parts.push(`${(c.duration_ms / 1000).toFixed(1)}s`)
  const u = c.usage
  if (u && u.total_tokens != null) {
    const io =
      u.prompt_tokens != null && u.completion_tokens != null
        ? ` (in ${u.prompt_tokens}/out ${u.completion_tokens})`
        : ''
    parts.push(`${u.total_tokens} tok${io}`)
  } else if (c.output_chars != null) {
    parts.push(translate(libCopy, 'outputChars', { n: c.output_chars }))
  }
  return parts.join(' · ')
}

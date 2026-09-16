/*
 * Cross-index search scope — the answer to "我不知道数据在哪个索引里".
 *
 * ES treats `index` as a comma-separated list, and the gateway's whitelist
 * validates every segment independently (backend/index_whitelist.py), so a
 * multi-index scope is a plain string the whole existing pipeline already
 * accepts — no sentinel value, no special case in /api/execute.
 *
 * Two uses:
 *   • the 全部日志 option in the picker, for a user who cannot answer "which
 *     index" before asking their question;
 *   • the 0-hit rescue — re-probe the same query across the scope and report
 *     which index actually holds the data, instead of a dead-end empty table.
 */

import { api, type ExecuteResponse } from '@/lib/api'
import { translate } from '@/lib/i18n'
import { libCopy } from '@/locales/lib'

export interface ScopeIndex {
  name: string
  doc_count: number
}

/** Agg name for the probe. Prefixed so it can never collide with a model-generated agg. */
const PROBE_AGG = '__rst_by_index'

/**
 * How many indices a scope string may name. ES has no hard limit, but the
 * string ends up in URLs, audit records and the picker trigger — and a scope of
 * the 20 busiest indices covers the realistic "where is my data" question while
 * staying readable.
 */
const SCOPE_LIMIT = 20

/** Comma-joined scope over the busiest indices. Pure — the caller supplies the list. */
export function buildScope(indices: ScopeIndex[], limit: number = SCOPE_LIMIT): string {
  return [...indices]
    .sort((a, b) => (b.doc_count ?? 0) - (a.doc_count ?? 0))
    .slice(0, limit)
    .map((i) => i.name)
    .join(',')
}

/** True when `value` names more than one target (a scope rather than one index). */
export function isMultiIndex(value: string): boolean {
  return value.includes(',')
}

/** Short label for a scope string, which is far too long to show verbatim. */
export function scopeLabel(value: string): string {
  if (!isMultiIndex(value)) return value
  return translate(libCopy, 'scopeAllLogs', { n: value.split(',').filter(Boolean).length })
}

/**
 * Turn a query into a "which index holds this?" probe: same filter, no
 * documents, one terms aggregation over the `_index` metafield. One request,
 * exact counts, no hits transferred.
 */
export function buildProbeDsl(dsl: Record<string, unknown>): Record<string, unknown> {
  return {
    query: (dsl.query as Record<string, unknown> | undefined) ?? { match_all: {} },
    size: 0,
    aggs: { [PROBE_AGG]: { terms: { field: '_index', size: 10 } } },
  }
}

export interface IndexHitCount {
  index: string
  count: number
}

/** Read the probe's buckets back out. Returns [] for any other response shape. */
export function parseProbe(result: ExecuteResponse): IndexHitCount[] {
  const agg = (result.aggregations as Record<string, unknown> | undefined)?.[PROBE_AGG]
  const buckets = (agg as { buckets?: unknown } | undefined)?.buckets
  if (!Array.isArray(buckets)) return []
  return buckets
    .map((b) => b as { key?: unknown; doc_count?: unknown })
    .filter((b) => typeof b.key === 'string' && typeof b.doc_count === 'number')
    .map((b) => ({ index: b.key as string, count: b.doc_count as number }))
    .filter((b) => b.count > 0)
}

/**
 * Which indices the hits on THIS page came from. Counts the returned page, not
 * the whole result set — callers must word it that way.
 */
export function hitsDistribution(result: ExecuteResponse): IndexHitCount[] {
  const counts = new Map<string, number>()
  for (const h of result.hits?.hits ?? []) {
    const name = h._index
    if (!name) continue
    counts.set(name, (counts.get(name) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([index, count]) => ({ index, count }))
    .sort((a, b) => b.count - a.count)
}

/**
 * Map a concrete index back to the name the user actually picks from.
 *
 * A terms agg over `_index` reports BACKING indices — a data stream shows up as
 * `.ds-logs-system.security-default-2026.08.08-000001`. Offering that name back
 * would be unreadable, and a deployment whose whitelist is `logs-*` would 403 on
 * it. So resolve it to the data stream it belongs to whenever we know one.
 */
export function friendlyIndexName(raw: string, known: string[]): string {
  if (known.includes(raw)) return raw
  if (raw.startsWith('.ds-')) {
    // Longest match wins: two streams can share a prefix.
    const hit = known
      .filter((k) => raw.startsWith(`.ds-${k}`))
      .sort((a, b) => b.length - a.length)[0]
    if (hit) return hit
  }
  return raw
}

/*
 * The queryable scope, fetched once per page load. The index list moves on a
 * timescale of days; re-fetching it per query would add a round trip to every
 * question for no new information.
 */
let scopeCache: Promise<string> | null = null

export function fetchScope(): Promise<string> {
  scopeCache ??= api
    .indices()
    .then((r) => buildScope(r.indices))
    .catch(() => '')
  return scopeCache
}

/** Drop the memoised scope — call after the user refreshes the index list. */
export function resetScopeCache(): void {
  scopeCache = null
}

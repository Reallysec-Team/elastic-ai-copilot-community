import { translate } from '@/lib/i18n'
import { libCopy } from '@/locales/lib'

/*
 * Why a query with zero hits found nothing.
 *
 * A live run asked 「有没有进程被 OOM killer 杀掉」 and the model wrote
 * `match_phrase message:"OOM"` AND `match_phrase message:"killed"`. The logs say
 * "Out of memory: Killed process 2841 (mysqld)" — the abbreviation "OOM" never
 * appears, so the answer came back as a flat 「命中 0 条」. Dropping that one
 * clause returns 2 documents, both on db-prod-01, which is exactly the answer.
 *
 * The same shape killed 「有没有 GC 停顿超过 2 秒」: a range on a field the GC
 * documents do not carry removed every row.
 *
 * That failure mode is the dangerous one — a false negative that looks like a
 * normal answer. An operator who does not read DSL has no way to tell "nothing
 * happened" from "one clause was wrong", so the product has to check: drop each
 * top-level clause in turn and report the ones that would have found something.
 */

export interface Relaxation {
  /** Human description of the clause that was dropped. */
  label: string
  /** The original query with that one clause removed. */
  query: Record<string, unknown>
}

/** Cap the probes: each one is a real search, and past a handful the list stops
 *  being a hint and becomes another wall of options. */
const MAX_RELAXATIONS = 6

type Obj = Record<string, unknown>

const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v)

function firstEntry(o: Obj): [string, unknown] | null {
  const k = Object.keys(o)[0]
  return k === undefined ? null : [k, o[k]]
}

function quote(v: unknown): string {
  if (typeof v === 'string') return `"${v}"`
  if (Array.isArray(v)) return `[${v.slice(0, 3).map(quote).join(', ')}${v.length > 3 ? ', …' : ''}]`
  return String(v)
}

function rangeLabel(field: string, body: unknown): string {
  if (!isObj(body)) return field
  const parts: string[] = []
  // `gte: now-1h` reads as a window; `gte: 2000000` reads as a threshold. Both
  // are worth naming exactly, because "too narrow" and "wrong unit" are the two
  // ways a range silently empties a result.
  if (body.gte !== undefined) parts.push(`≥ ${body.gte}`)
  if (body.gt !== undefined) parts.push(`> ${body.gt}`)
  if (body.lte !== undefined) parts.push(`≤ ${body.lte}`)
  if (body.lt !== undefined) parts.push(`< ${body.lt}`)
  return `${field} ${parts.join(translate(libCopy, 'rqAnd')) || translate(libCopy, 'rqRangeCondition')}`
}

/** One clause, described the way an operator would say it out loud. */
export function describeClause(clause: unknown): string {
  if (!isObj(clause)) return translate(libCopy, 'rqOneCondition')
  const e = firstEntry(clause)
  if (!e) return translate(libCopy, 'rqOneCondition')
  const [kind, body] = e
  switch (kind) {
    case 'match_phrase':
    case 'match':
    case 'match_phrase_prefix': {
      if (!isObj(body)) return kind
      const f = firstEntry(body)
      if (!f) return kind
      const raw = isObj(f[1]) ? (f[1] as Obj).query : f[1]
      return translate(libCopy, 'rqContains', { field: f[0], value: quote(raw) })
    }
    case 'term':
    case 'terms': {
      if (!isObj(body)) return kind
      const f = firstEntry(body)
      if (!f) return kind
      const raw = isObj(f[1]) ? (f[1] as Obj).value : f[1]
      return `${f[0]} = ${quote(raw)}`
    }
    case 'range': {
      if (!isObj(body)) return kind
      const f = firstEntry(body)
      return f ? rangeLabel(f[0], f[1]) : kind
    }
    case 'exists':
      return translate(libCopy, 'rqFieldExists', { field: isObj(body) ? String(body.field) : '' })
    case 'wildcard':
    case 'prefix':
    case 'regexp': {
      if (!isObj(body)) return kind
      const f = firstEntry(body)
      if (!f) return kind
      const raw = isObj(f[1]) ? (f[1] as Obj).value : f[1]
      return translate(libCopy, 'rqMatches', { field: f[0], value: quote(raw) })
    }
    case 'query_string':
      return translate(libCopy, 'rqFullText', { value: quote(isObj(body) ? body.query : body) })
    case 'bool':
      return translate(libCopy, 'rqCombined')
    default:
      return kind
  }
}

/**
 * Every "same query minus one clause" worth probing.
 *
 * Only top-level `must` / `filter` entries are dropped: those are the ANDs, and
 * an AND is what turns one wrong guess into zero rows. `should` is already a
 * relaxation, and dropping a `must_not` would widen into noise rather than
 * explain the miss. Returns [] when there is nothing to loosen (a single-clause
 * query that matched nothing really did match nothing).
 */
export function relaxations(dsl: Record<string, unknown>): Relaxation[] {
  const query = dsl.query
  if (!isObj(query)) return []
  const bool = query.bool
  if (!isObj(bool)) return []

  const out: Relaxation[] = []
  for (const slot of ['must', 'filter'] as const) {
    const arr = bool[slot]
    if (!Array.isArray(arr) || arr.length < 2) continue // dropping the only clause proves nothing
    for (let i = 0; i < arr.length; i++) {
      const rest = arr.filter((_, j) => j !== i)
      out.push({
        label: describeClause(arr[i]),
        query: { bool: { ...bool, [slot]: rest } },
      })
    }
  }
  return out.slice(0, MAX_RELAXATIONS)
}

/** Count-only body for probing one relaxed query. */
export function buildRelaxProbe(query: Record<string, unknown>): Record<string, unknown> {
  return { query, size: 0, track_total_hits: true }
}

/*
 * The same false negative, one level down.
 *
 * A cross-index question is written as one `should` branch per data source with
 * `minimum_should_match: 1`. The total then hides the miss: ask 「结账链路上
 * Java 和 nginx 各报了什么错」 and the nginx branch can return 8000 rows while
 * the Java branch returns 0 — total 8000, page renders, and half the question
 * silently went unanswered. Usual cause is a value spelled the way another
 * index writes it (`log.level: "error"` where that index only writes `ERROR`)
 * or a keyword hung on a field this index barely populates.
 *
 * The counts are not in the search response, so one extra request is needed —
 * but only one: a `filters` aggregation counts every branch at once, inside the
 * original query context, so bucket i is exactly "rows this branch contributed".
 */

const BRANCH_AGG = 'rst_should_branches'

export interface ShouldBranch {
  /** Stable key, also the aggregation bucket name. */
  key: string
  label: string
  clause: Obj
}

export interface DeadBranch extends ShouldBranch {
  /** Ways to loosen this one branch, as a full query ready for buildRelaxProbe. */
  relaxations: Relaxation[]
}

/** Describe a branch — a branch is usually a small bool, not a single clause. */
function describeBranch(clause: unknown): string {
  const inner = innerClauses(clause)
  if (inner.length === 0) return describeClause(clause)
  return inner
    .slice(0, 3)
    .map((e) => describeClause(e.clause))
    .join(translate(libCopy, 'rqAnd'))
}

/** The AND-ed clauses inside a branch, with where they live so one can be swapped. */
function innerClauses(clause: unknown): { slot: 'must' | 'filter'; i: number; clause: unknown }[] {
  if (!isObj(clause) || !isObj(clause.bool)) return []
  const out: { slot: 'must' | 'filter'; i: number; clause: unknown }[] = []
  for (const slot of ['must', 'filter'] as const) {
    const arr = (clause.bool as Obj)[slot]
    if (Array.isArray(arr)) arr.forEach((c, i) => out.push({ slot, i, clause: c }))
  }
  return out
}

/**
 * The top-level `should` branches, when `should` really is the disjunction.
 *
 * `should` next to a `must`/`filter` and no `minimum_should_match` is optional
 * scoring, not a data source per branch — a 0-hit branch there is normal, so
 * those return [] rather than a false alarm. A single branch is degenerate too:
 * it is the whole query, which `relaxations` already covers.
 */
export function shouldBranches(dsl: Record<string, unknown>): ShouldBranch[] {
  const query = dsl.query
  if (!isObj(query)) return []
  const bool = query.bool
  if (!isObj(bool)) return []
  const should = bool.should
  if (!Array.isArray(should) || should.length < 2) return []
  const hasHard = (['must', 'filter'] as const).some(
    (s) => Array.isArray(bool[s]) && (bool[s] as unknown[]).length > 0,
  )
  if (bool.minimum_should_match === undefined && hasHard) return []
  return should.map((clause, i) => ({
    key: `b${i}`,
    label: describeBranch(clause),
    clause: (isObj(clause) ? clause : { match_all: {} }) as Obj,
  }))
}

/** One count-everything request: the original query, plus a per-branch filters agg. */
export function buildBranchProbe(dsl: Record<string, unknown>): Record<string, unknown> | null {
  const branches = shouldBranches(dsl)
  if (branches.length === 0) return null
  const filters: Obj = {}
  for (const b of branches) filters[b.key] = b.clause
  return {
    query: dsl.query,
    size: 0,
    track_total_hits: false,
    aggs: { [BRANCH_AGG]: { filters: { filters } } },
  }
}

/** Same clause with its string value re-cased — the `ERROR` / `error` miss. */
function caseVariant(clause: unknown): { label: string; clause: Obj } | null {
  if (!isObj(clause)) return null
  const e = firstEntry(clause)
  if (!e) return null
  const [kind, body] = e
  if (kind !== 'term' && kind !== 'match' && kind !== 'match_phrase') return null
  if (!isObj(body)) return null
  const f = firstEntry(body)
  if (!f) return null
  const [field, raw] = f
  const holder = isObj(raw) ? raw : null
  const key = kind === 'term' ? 'value' : 'query'
  const val = holder ? holder[key] : raw
  // Only a bare word: `error` / `ERROR` is a real spelling difference between
  // indices, while `WEB-01` or `JAVA.APP` is noise nobody ever needs.
  if (typeof val !== 'string' || !/^[A-Za-z]+$/.test(val)) return null
  const alt = val === val.toUpperCase() ? val.toLowerCase() : val.toUpperCase()
  if (alt === val) return null
  return {
    label: translate(libCopy, 'rqUseInstead', { field, alt: quote(alt) }),
    clause: { [kind]: { [field]: holder ? { ...holder, [key]: alt } : alt } },
  }
}

/** Rebuild the whole query with this branch as the only branch. */
function onlyBranch(bool: Obj, branch: unknown): Record<string, unknown> {
  return { bool: { ...bool, should: [branch], minimum_should_match: 1 } }
}

/** Same branch with clause `at` replaced, or dropped when `next` is null. */
function swapInner(
  branch: Obj,
  at: { slot: 'must' | 'filter'; i: number },
  next: unknown | null,
): Obj {
  const inner = branch.bool as Obj
  const arr = inner[at.slot] as unknown[]
  const rest = next === null ? arr.filter((_, j) => j !== at.i) : arr.map((c, j) => (j === at.i ? next : c))
  return { bool: { ...inner, [at.slot]: rest } }
}

function branchRelaxations(bool: Obj, branch: Obj): Relaxation[] {
  const inner = innerClauses(branch)
  const out: Relaxation[] = []
  for (const e of inner) {
    const v = caseVariant(e.clause)
    if (v) out.push({ label: v.label, query: onlyBranch(bool, swapInner(branch, e, v.clause)) })
  }
  if (inner.length >= 2) {
    for (const e of inner) {
      out.push({
        label: translate(libCopy, 'rqDropClause', { clause: describeClause(e.clause) }),
        query: onlyBranch(bool, swapInner(branch, e, null)),
      })
    }
  }
  return out.slice(0, MAX_RELAXATIONS)
}

/**
 * Which branches contributed nothing, given the probe response.
 *
 * Feed it the body from `buildBranchProbe`; a response without the aggregation
 * (probe skipped, or the branch shape was not the disjunction) yields [].
 */
export function deadBranches(
  dsl: Record<string, unknown>,
  probeResponse: unknown,
): DeadBranch[] {
  const branches = shouldBranches(dsl)
  if (branches.length === 0) return []
  const aggs = isObj(probeResponse) ? probeResponse.aggregations : null
  const agg = isObj(aggs) ? aggs[BRANCH_AGG] : null
  const buckets = isObj(agg) ? agg.buckets : null
  if (!isObj(buckets)) return []
  const bool = (dsl.query as Obj).bool as Obj
  const dead: DeadBranch[] = []
  for (const b of branches) {
    const bucket = buckets[b.key]
    if (!isObj(bucket) || typeof bucket.doc_count !== 'number') continue // no count, no claim
    if (bucket.doc_count > 0) continue
    dead.push({ ...b, relaxations: branchRelaxations(bool, b.clause) })
  }
  return dead
}

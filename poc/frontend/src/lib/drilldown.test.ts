import { describe, expect, it } from 'vitest'
import { buildDrillDsl, type DrillDown } from './drilldown'

type Clause = Record<string, unknown>

/** The drill's `bool.filter` array — [original query, bucket constraint]. */
function filtersOf(d: DrillDown): Clause[] {
  return (d.dsl.query as { bool: { filter: Clause[] } }).bool.filter
}

/** The range bounds the bucket constraint applied to `field`. */
function rangeOf(d: DrillDown, field: string): Record<string, unknown> {
  const clause = filtersOf(d)[1] as { range: Record<string, Record<string, unknown>> }
  return clause.range[field]
}

/*
 * The drill query is the bridge between an aggregation answer and every
 * downstream action (解释 / 调查 / 送去分诊). It has to hold two properties:
 * the original filters survive (otherwise the drill shows different documents
 * than the bucket counted), and the filter uses the bucket's RAW key.
 */

const TERMS_DSL = {
  size: 0,
  query: { bool: { filter: [{ range: { '@timestamp': { gte: 'now-1h' } } }] } },
  aggs: {
    failures_by_source_ip: { terms: { field: 'source.ip', size: 10 } },
    failures_over_time: { date_histogram: { field: '@timestamp', fixed_interval: '1m' } },
  },
}

describe('buildDrillDsl — terms bucket', () => {
  const out = buildDrillDsl(
    TERMS_DSL,
    'failures_by_source_ip',
    { key: '10.252.121.4', doc_count: 1390 },
    undefined,
    50,
  )!

  it('filters on the bucket value with a term clause', () => {
    expect(out).not.toBeNull()
    expect(filtersOf(out)).toContainEqual({ term: { 'source.ip': '10.252.121.4' } })
  })

  it('keeps the original query so the drill matches what the bucket counted', () => {
    expect(filtersOf(out)[0]).toEqual(TERMS_DSL.query)
  })

  it('drops the aggregations and asks for hits', () => {
    expect(out.dsl.aggs).toBeUndefined()
    expect(out.dsl.size).toBe(50)
  })

  it('labels the drill with field = value', () => {
    expect(out.label).toBe('source.ip = 10.252.121.4')
  })
})

describe('buildDrillDsl — date_histogram bucket', () => {
  const BUCKET = { key: 1_753_082_880_000, key_as_string: '2026-07-21T07:28:00.000Z', doc_count: 352 }

  it('bounds the bucket as a half-open interval using the next bucket key', () => {
    const out = buildDrillDsl(TERMS_DSL, 'failures_over_time', BUCKET, 1_753_082_940_000, 50)!
    expect(filtersOf(out)).toContainEqual({
      range: { '@timestamp': { gte: 1_753_082_880_000, lt: 1_753_082_940_000 } },
    })
  })

  it('leaves the last bucket open-ended when there is no next key', () => {
    const out = buildDrillDsl(TERMS_DSL, 'failures_over_time', BUCKET, undefined, 50)!
    const range = rangeOf(out, '@timestamp')
    expect(range).toEqual({ gte: 1_753_082_880_000 })
    expect(range).not.toHaveProperty('lt')
  })

  it('filters on the raw epoch key but labels with the readable one', () => {
    // key_as_string is a display rendering — filtering on it would not match.
    const out = buildDrillDsl(TERMS_DSL, 'failures_over_time', BUCKET, null, 50)!
    expect(rangeOf(out, '@timestamp').gte).toBe(1_753_082_880_000)
    expect(out.label).toBe('@timestamp = 2026-07-21T07:28:00.000Z')
  })
})

describe('buildDrillDsl — refuses what it cannot express', () => {
  it('returns null for an unknown aggregation name', () => {
    expect(buildDrillDsl(TERMS_DSL, 'nope', { key: 'x' }, undefined, 50)).toBeNull()
  })

  it('returns null for an aggregation with no single field to filter on', () => {
    const dsl = { aggs: { by_kind: { filters: { filters: { a: { match_all: {} } } } } } }
    expect(buildDrillDsl(dsl, 'by_kind', { key: 'a' }, undefined, 50)).toBeNull()
  })

  it('returns null when the DSL carries no aggregations at all', () => {
    expect(buildDrillDsl({ size: 10 }, 'anything', { key: 'x' }, undefined, 50)).toBeNull()
  })
})

describe('buildDrillDsl — edge shapes', () => {
  it('accepts the `aggregations` spelling as well as `aggs`', () => {
    const dsl = { aggregations: { by_ip: { terms: { field: 'src' } } } }
    expect(buildDrillDsl(dsl, 'by_ip', { key: '1.2.3.4' }, undefined, 50)?.label).toBe(
      'src = 1.2.3.4',
    )
  })

  it('falls back to match_all when the base DSL has no query', () => {
    const dsl = { aggs: { by_ip: { terms: { field: 'src' } } } }
    const out = buildDrillDsl(dsl, 'by_ip', { key: '1.2.3.4' }, undefined, 50)!
    expect(filtersOf(out)[0]).toEqual({ match_all: {} })
  })

  it('preserves a falsy-but-real bucket key (0) instead of dropping it', () => {
    const dsl = { aggs: { by_code: { terms: { field: 'code' } } } }
    const out = buildDrillDsl(dsl, 'by_code', { key: 0 }, undefined, 50)!
    expect(filtersOf(out)[1]).toEqual({ term: { code: 0 } })
  })
})

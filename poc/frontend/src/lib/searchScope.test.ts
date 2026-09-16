import { describe, expect, it } from 'vitest'

import {
  buildProbeDsl,
  buildScope,
  friendlyIndexName,
  hitsDistribution,
  isMultiIndex,
  parseProbe,
  scopeLabel,
} from './searchScope'

describe('buildScope', () => {
  it('orders by doc count and caps the list', () => {
    const scope = buildScope(
      [
        { name: 'small', doc_count: 1 },
        { name: 'big', doc_count: 900 },
        { name: 'mid', doc_count: 50 },
      ],
      2,
    )
    expect(scope).toBe('big,mid')
  })

  it('is empty for an empty cluster', () => {
    expect(buildScope([])).toBe('')
  })
})

describe('isMultiIndex / scopeLabel', () => {
  it('leaves a single index untouched', () => {
    expect(isMultiIndex('logs-app')).toBe(false)
    expect(scopeLabel('logs-app')).toBe('logs-app')
  })

  it('summarises a scope instead of printing it', () => {
    expect(isMultiIndex('a,b,c')).toBe(true)
    expect(scopeLabel('a,b,c')).toContain('3')
  })
})

describe('buildProbeDsl', () => {
  it('keeps the filter, drops the documents and aggregates by _index', () => {
    const probe = buildProbeDsl({
      query: { term: { 'user.name': 'root' } },
      size: 50,
      aggs: { by_ip: { terms: { field: 'source.ip' } } },
      sort: [{ '@timestamp': 'desc' }],
    })
    expect(probe.query).toEqual({ term: { 'user.name': 'root' } })
    expect(probe.size).toBe(0)
    // The model's own aggregation and sort must not ride along — the probe only
    // answers "which index", and a sort on a field missing elsewhere would 400.
    expect(Object.keys(probe.aggs as object)).toEqual(['__rst_by_index'])
    expect(probe.sort).toBeUndefined()
  })

  it('falls back to match_all when the DSL has no query', () => {
    expect(buildProbeDsl({ size: 10 }).query).toEqual({ match_all: {} })
  })
})

describe('parseProbe', () => {
  it('reads buckets and drops empty ones', () => {
    const parsed = parseProbe({
      aggregations: {
        __rst_by_index: {
          buckets: [
            { key: 'logs-a', doc_count: 12 },
            { key: 'logs-b', doc_count: 0 },
          ],
        },
      },
    })
    expect(parsed).toEqual([{ index: 'logs-a', count: 12 }])
  })

  it('returns nothing for an unexpected shape', () => {
    expect(parseProbe({})).toEqual([])
    expect(parseProbe({ aggregations: { __rst_by_index: {} } })).toEqual([])
  })
})

describe('hitsDistribution', () => {
  it('counts hits per index, busiest first', () => {
    expect(
      hitsDistribution({
        hits: {
          hits: [
            { _index: 'a', _source: {} },
            { _index: 'b', _source: {} },
            { _index: 'a', _source: {} },
            { _source: {} },
          ],
        },
      }),
    ).toEqual([
      { index: 'a', count: 2 },
      { index: 'b', count: 1 },
    ])
  })
})

describe('friendlyIndexName', () => {
  const known = ['logs-system.security-default', 'logs-system.security-default-eu', 'plain-index']

  it('resolves a backing index to its data stream', () => {
    expect(
      friendlyIndexName('.ds-logs-system.security-default-2026.08.08-000001', known),
    ).toBe('logs-system.security-default')
  })

  it('prefers the longest matching stream name', () => {
    expect(
      friendlyIndexName('.ds-logs-system.security-default-eu-2026.08.08-000001', known),
    ).toBe('logs-system.security-default-eu')
  })

  it('passes through a name it already knows', () => {
    expect(friendlyIndexName('plain-index', known)).toBe('plain-index')
  })

  it('passes through an unknown name unchanged', () => {
    expect(friendlyIndexName('.ds-something-else-000001', known)).toBe('.ds-something-else-000001')
  })
})

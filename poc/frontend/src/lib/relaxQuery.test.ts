import { beforeEach, describe, expect, it } from 'vitest'

import {
  buildBranchProbe,
  buildRelaxProbe,
  deadBranches,
  describeClause,
  relaxations,
  shouldBranches,
} from './relaxQuery'
import { setLang } from '@/lib/i18n'

/* 这些断言比的是中文文案，所以先把语言钉死 —— 不钉的话它按 `navigator.language`
   回落，node 环境里是 en。 */
beforeEach(() => setLang('zh'))


describe('describeClause', () => {
  it('names the clause the way an operator would say it', () => {
    expect(describeClause({ match_phrase: { message: 'OOM' } })).toBe('message 里包含 "OOM"')
    expect(describeClause({ term: { 'log.logger': 'gc' } })).toBe('log.logger = "gc"')
    expect(describeClause({ range: { 'transaction.duration.us': { gte: 2000000 } } })).toBe(
      'transaction.duration.us ≥ 2000000',
    )
    expect(describeClause({ range: { '@timestamp': { gte: 'now-1h', lt: 'now' } } })).toBe(
      '@timestamp ≥ now-1h 且 < now',
    )
    expect(describeClause({ exists: { field: 'source.ip' } })).toBe('存在字段 source.ip')
    expect(describeClause({ bool: { should: [] } })).toBe('一组组合条件')
  })

  it('unwraps the verbose forms', () => {
    expect(describeClause({ match: { message: { query: 'killed' } } })).toBe('message 里包含 "killed"')
    expect(describeClause({ term: { 'host.name': { value: 'db-prod-01' } } })).toBe(
      'host.name = "db-prod-01"',
    )
  })
})

describe('relaxations', () => {
  // The live miss: "OOM" is not in the log text, "Out of memory" is.
  it('offers dropping each must clause', () => {
    const dsl = {
      size: 20,
      query: {
        bool: {
          must: [{ match_phrase: { message: 'OOM' } }, { match_phrase: { message: 'killed' } }],
        },
      },
    }
    const r = relaxations(dsl)
    expect(r.map((x) => x.label)).toEqual(['message 里包含 "OOM"', 'message 里包含 "killed"'])
    expect(r[0].query).toEqual({ bool: { must: [{ match_phrase: { message: 'killed' } }] } })
  })

  it('relaxes filter clauses too, keeping the rest of the bool intact', () => {
    const dsl = {
      query: {
        bool: {
          filter: [{ term: { 'log.logger': 'gc' } }, { range: { 'transaction.duration.us': { gte: 2000000 } } }],
          must_not: [{ term: { level: 'debug' } }],
        },
      },
    }
    const r = relaxations(dsl)
    expect(r).toHaveLength(2)
    expect((r[1].query.bool as Record<string, unknown>).must_not).toEqual([
      { term: { level: 'debug' } },
    ])
  })

  it('stays quiet when there is nothing to loosen', () => {
    expect(relaxations({ query: { match_all: {} } })).toEqual([])
    expect(relaxations({ query: { bool: { must: [{ term: { a: 1 } }] } } })).toEqual([])
    expect(relaxations({})).toEqual([])
  })

  it('caps how many probes it will ask for', () => {
    const must = Array.from({ length: 12 }, (_, i) => ({ term: { [`f${i}`]: i } }))
    expect(relaxations({ query: { bool: { must } } })).toHaveLength(6)
  })
})

// Cross-index: one should branch per data source, minimum_should_match: 1.
const branchDsl = (mm: unknown = 1) => ({
  size: 20,
  query: {
    bool: {
      filter: [{ range: { '@timestamp': { gte: 'now-1h' } } }],
      should: [
        {
          bool: {
            filter: [
              { term: { 'data_stream.dataset': 'nginx.error' } },
              { match: { message: 'checkout' } },
            ],
          },
        },
        {
          bool: {
            filter: [
              { term: { 'data_stream.dataset': 'java.app' } },
              { term: { 'log.level': 'error' } },
            ],
          },
        },
      ],
      ...(mm === null ? {} : { minimum_should_match: mm }),
    },
  },
})

const probeWith = (counts: Record<string, number>) => ({
  aggregations: {
    rst_should_branches: {
      buckets: Object.fromEntries(
        Object.entries(counts).map(([k, v]) => [k, { doc_count: v }]),
      ),
    },
  },
})

describe('shouldBranches', () => {
  it('names each data-source branch', () => {
    expect(shouldBranches(branchDsl()).map((b) => b.label)).toEqual([
      'data_stream.dataset = "nginx.error" 且 message 里包含 "checkout"',
      'data_stream.dataset = "java.app" 且 log.level = "error"',
    ])
  })

  it('ignores should that is only scoring, not a disjunction', () => {
    // No minimum_should_match next to a filter: these branches are optional,
    // a 0-hit one is normal and must not be reported.
    expect(shouldBranches(branchDsl(null))).toEqual([])
  })

  it('says nothing for a single branch or a query with no should', () => {
    expect(
      shouldBranches({ query: { bool: { should: [{ term: { a: 1 } }], minimum_should_match: 1 } } }),
    ).toEqual([])
    expect(shouldBranches({ query: { bool: { must: [{ term: { a: 1 } }] } } })).toEqual([])
    expect(shouldBranches({ query: { match_all: {} } })).toEqual([])
    expect(shouldBranches({})).toEqual([])
  })

  it('treats a should nested inside filter as out of scope, not as branches', () => {
    const dsl = {
      query: {
        bool: {
          filter: [{ bool: { should: [{ term: { a: 1 } }, { term: { b: 2 } }], minimum_should_match: 1 } }],
        },
      },
    }
    expect(shouldBranches(dsl)).toEqual([])
    expect(buildBranchProbe(dsl)).toBeNull()
  })
})

describe('buildBranchProbe', () => {
  it('counts every branch in one request, inside the original query', () => {
    const dsl = branchDsl()
    const probe = buildBranchProbe(dsl) as Record<string, any>
    expect(probe.query).toBe(dsl.query)
    expect(probe.size).toBe(0)
    expect(Object.keys(probe.aggs.rst_should_branches.filters.filters)).toEqual(['b0', 'b1'])
    expect(probe.aggs.rst_should_branches.filters.filters.b1).toEqual(
      (dsl.query.bool.should as unknown[])[1],
    )
  })

  it('is null when there is nothing to split', () => {
    expect(buildBranchProbe({ query: { bool: { must: [{ term: { a: 1 } }] } } })).toBeNull()
  })
})

describe('deadBranches', () => {
  // The dangerous case: 8000 hits on screen, half the question unanswered.
  it('finds the branch that contributed nothing to a healthy total', () => {
    const dead = deadBranches(branchDsl(), probeWith({ b0: 8000, b1: 0 }))
    expect(dead).toHaveLength(1)
    expect(dead[0].key).toBe('b1')
    expect(dead[0].label).toContain('java.app')
  })

  it('does not cry wolf when every branch has hits', () => {
    expect(deadBranches(branchDsl(), probeWith({ b0: 8000, b1: 3 }))).toEqual([])
  })

  it('suggests the case variant and dropping each clause of the dead branch', () => {
    const dead = deadBranches(branchDsl(), probeWith({ b0: 8000, b1: 0 }))
    expect(dead[0].relaxations.map((r) => r.label)).toEqual([
      'log.level 改用 "ERROR"',
      '去掉「data_stream.dataset = "java.app"」',
      '去掉「log.level = "error"」',
    ])
    // A suggestion is a full query: the outer time filter stays, the branch is
    // narrowed to the fixed one so the count answers for that branch alone.
    const fixed = dead[0].relaxations[0].query.bool as Record<string, any>
    expect(fixed.filter).toEqual([{ range: { '@timestamp': { gte: 'now-1h' } } }])
    expect(fixed.minimum_should_match).toBe(1)
    expect(fixed.should).toEqual([
      {
        bool: {
          filter: [
            { term: { 'data_stream.dataset': 'java.app' } },
            { term: { 'log.level': 'ERROR' } },
          ],
        },
      },
    ])
    expect(buildRelaxProbe(fixed as Record<string, unknown>).size).toBe(0)
  })

  it('handles a flat branch and one with a single clause without inventing advice', () => {
    const dsl = {
      query: {
        bool: {
          minimum_should_match: 1,
          should: [
            { term: { 'host.name': 'web-01' } },
            { bool: { filter: [{ term: { 'host.name': 'db-01' } }] } },
          ],
        },
      },
    }
    const dead = deadBranches(dsl, probeWith({ b0: 0, b1: 0 }))
    expect(dead.map((d) => d.label)).toEqual(['host.name = "web-01"', 'host.name = "db-01"'])
    expect(dead[0].relaxations).toEqual([]) // nothing to drop, no case variant
    expect(dead[1].relaxations).toEqual([]) // single inner clause: dropping it empties the branch
  })

  it('claims nothing without counts', () => {
    expect(deadBranches(branchDsl(), {})).toEqual([])
    expect(deadBranches(branchDsl(), probeWith({}))).toEqual([])
    expect(deadBranches(branchDsl(), null)).toEqual([])
  })
})

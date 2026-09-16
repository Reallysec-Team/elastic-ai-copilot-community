import { describe, expect, it } from 'vitest'

import type { ExecuteResponse } from './api'
import { countHits, isEmptyResult } from './emptyResult'

const res = (r: Partial<ExecuteResponse>) => r as ExecuteResponse

describe('countHits', () => {
  it('reads both the number and the {value} total shapes', () => {
    expect(countHits(res({ hits: { total: 7, hits: [] } }))).toBe(7)
    expect(countHits(res({ hits: { total: { value: 600 }, hits: [] } }))).toBe(600)
    expect(countHits(res({}))).toBe(0)
  })
})

describe('isEmptyResult', () => {
  it('treats hits as the answer when there are any', () => {
    expect(isEmptyResult(res({ hits: { total: { value: 600 }, hits: [] } }))).toBe(false)
  })

  it('calls a document answer with no hits empty', () => {
    expect(isEmptyResult(res({ hits: { total: { value: 0 }, hits: [] } }))).toBe(true)
  })

  // The regression: a size:0 aggregation reports 0 hits by design, so the old
  // `!r.aggregations` guard let an all-empty bucket list through as an answer.
  it('calls an aggregation whose buckets are all empty a miss', () => {
    expect(
      isEmptyResult(res({ hits: { total: { value: 0 }, hits: [] }, aggregations: { by_event_id: { buckets: [] } } })),
    ).toBe(true)
  })

  it('keeps an aggregation that found something', () => {
    expect(
      isEmptyResult(
        res({
          hits: { total: { value: 0 }, hits: [] },
          aggregations: { by_event_id: { buckets: [{ key: '4625', doc_count: 720 }] } },
        }),
      ),
    ).toBe(false)
  })

  it('keeps a metric aggregation, whose value is a real answer even at zero', () => {
    expect(
      isEmptyResult(res({ hits: { total: { value: 0 }, hits: [] }, aggregations: { uniq: { value: 0 } } })),
    ).toBe(false)
  })

  it('keeps a partly-empty aggregation — one populated bucket list is an answer', () => {
    expect(
      isEmptyResult(
        res({
          hits: { total: { value: 0 }, hits: [] },
          aggregations: { by_host: { buckets: [] }, by_code: { buckets: [{ key: '4625' }] } },
        }),
      ),
    ).toBe(false)
  })
})

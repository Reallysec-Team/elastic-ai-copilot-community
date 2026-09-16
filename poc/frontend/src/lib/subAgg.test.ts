import { describe, expect, it } from 'vitest'

import { subAggCols, subAggValue } from './subAgg'

describe('subAggValue', () => {
  it('reads a metric sub-aggregation', () => {
    expect(subAggValue({ value: 42 })).toBe(42)
    expect(subAggValue({ value: 0 })).toBe(0)
  })

  // The regression: terms(source.ip) + filter(success) + filter(fail) is the
  // no-script way to split counts into columns, and the filter buckets were
  // being dropped because they carry doc_count rather than value.
  it('reads a filter sub-aggregation', () => {
    expect(subAggValue({ doc_count: 7 })).toBe(7)
    expect(subAggValue({ doc_count: 0 })).toBe(0)
  })

  it('leaves a nested bucket aggregation to the JSON fallback', () => {
    expect(subAggValue({ buckets: [{ key: 'a', doc_count: 3 }] })).toBeUndefined()
    expect(subAggValue(null)).toBeUndefined()
    expect(subAggValue(undefined)).toBeUndefined()
    expect(subAggValue(5)).toBeUndefined()
  })
})

describe('subAggCols', () => {
  // The regression: columns came from buckets[0] alone, so a first bucket that
  // ES returned without `failed` erased that column for every other bucket —
  // and the table still looked like a complete answer.
  it('unions the columns over every bucket', () => {
    expect(
      subAggCols([
        { key: 'a', doc_count: 1, ok: { doc_count: 1 } },
        { key: 'b', doc_count: 2, ok: { doc_count: 2 }, failed: { doc_count: 2 } },
      ]).cols,
    ).toEqual(['ok', 'failed'])
  })

  it('keeps a column whose first bucket has no value', () => {
    expect(subAggCols([{ key: 'a', doc_count: 1 }, { key: 'b', avg_ms: { value: 3 } }]).cols).toEqual(
      ['avg_ms'],
    )
  })

  it('never treats bucket metadata as a column', () => {
    expect(subAggCols([{ key: 'a', key_as_string: 'A', doc_count: 1 }])).toEqual({
      cols: [],
      nested: [],
    })
  })

  it('reports a nested bucket aggregation instead of dropping it', () => {
    expect(subAggCols([{ key: 'a', doc_count: 1, by_host: { buckets: [{ key: 'h' }] } }])).toEqual({
      cols: [],
      nested: ['by_host'],
    })
  })

  it('handles no buckets', () => {
    expect(subAggCols([])).toEqual({ cols: [], nested: [] })
  })
})

import { describe, expect, it } from 'vitest'

import {
  extractQueryStart,
  formatRange,
  dataReachesIntoFuture,
  hoursAhead,
  isWindowAfterData,
  mergeRangesByName,
  parseRanges,
  resolveDateMath,
} from './timeRange'

const NOW = Date.parse('2026-09-02T00:00:00Z')
const DAY = 86_400_000

describe('resolveDateMath', () => {
  it('resolves the forms the generator actually emits', () => {
    expect(resolveDateMath('now', NOW)).toBe(NOW)
    expect(resolveDateMath('now-30d', NOW)).toBe(NOW - 30 * DAY)
    expect(resolveDateMath('now-1h', NOW)).toBe(NOW - 3_600_000)
    expect(resolveDateMath('now+1d', NOW)).toBe(NOW + DAY)
    expect(resolveDateMath('2026-08-08T00:00:00Z', NOW)).toBe(Date.parse('2026-08-08T00:00:00Z'))
    expect(resolveDateMath(NOW, NOW)).toBe(NOW)
  })

  it('ignores a rounding suffix, which only widens the window', () => {
    expect(resolveDateMath('now-1d/d', NOW)).toBe(NOW - DAY)
  })

  it('returns null rather than guessing at anything else', () => {
    expect(resolveDateMath('yesterday', NOW)).toBeNull()
    expect(resolveDateMath('now-3fortnights', NOW)).toBeNull()
    expect(resolveDateMath(null, NOW)).toBeNull()
    expect(resolveDateMath('', NOW)).toBeNull()
  })
})

describe('extractQueryStart', () => {
  it('finds the lower bound inside a nested bool query', () => {
    const dsl = {
      query: {
        bool: {
          filter: [
            { term: { 'event.code': '4625' } },
            { range: { '@timestamp': { gte: 'now-30d' } } },
          ],
        },
      },
    }
    expect(extractQueryStart(dsl, NOW)).toBe(NOW - 30 * DAY)
  })

  it('accepts gt as well as gte', () => {
    expect(extractQueryStart({ range: { ts: { gt: 'now-1h' } } }, NOW)).toBe(NOW - 3_600_000)
  })

  it('is null when the query has no time bound', () => {
    expect(extractQueryStart({ query: { match_all: {} } }, NOW)).toBeNull()
    // A range on a numeric field resolves to nothing, and must not be mistaken
    // for a timestamp.
    expect(extractQueryStart({ range: { bytes: { gte: 500 } } }, NOW)).toBe(500)
  })
})

describe('isWindowAfterData', () => {
  const range = { lo: Date.parse('2026-05-10T00:00:00Z'), hi: Date.parse('2026-08-08T00:00:00Z') }

  it('flags a window that starts after the newest document', () => {
    expect(isWindowAfterData(Date.parse('2026-08-20T00:00:00Z'), range)).toBe(true)
  })

  it('stays quiet when the window overlaps the data', () => {
    expect(isWindowAfterData(Date.parse('2026-08-03T00:00:00Z'), range)).toBe(false)
  })

  it('stays quiet when anything is unknown', () => {
    expect(isWindowAfterData(null, range)).toBe(false)
    expect(isWindowAfterData(NOW, null)).toBe(false)
  })
})

describe('parseRanges / mergeRangesByName', () => {
  const resp = {
    aggregations: {
      __rst_time_range: {
        buckets: [
          { key: '.ds-logs-sec-2026.05.10-000001', lo: { value: 100 }, hi: { value: 200 } },
          { key: '.ds-logs-sec-2026.08.08-000002', lo: { value: 300 }, hi: { value: 400 } },
          { key: 'plain', lo: { value: 5 }, hi: { value: 9 } },
        ],
      },
    },
  }

  it('reads the buckets', () => {
    expect(parseRanges(resp).plain).toEqual({ lo: 5, hi: 9 })
  })

  it('widens a data stream to span all of its backing indices', () => {
    const merged = mergeRangesByName(parseRanges(resp), ['logs-sec', 'plain'])
    expect(merged['logs-sec']).toEqual({ lo: 100, hi: 400 })
    expect(merged.plain).toEqual({ lo: 5, hi: 9 })
  })

  it('survives an unexpected shape', () => {
    expect(parseRanges({})).toEqual({})
  })
})

describe('formatRange', () => {
  it('renders days, which is the precision staleness is judged at', () => {
    expect(formatRange({ lo: Date.parse('2026-05-10T12:00:00'), hi: Date.parse('2026-08-08T12:00:00') }))
      .toBe('2026-05-10 → 2026-08-08')
  })
})

describe('dataReachesIntoFuture', () => {
  const NOW = Date.parse('2026-09-06T12:00:00Z')

  it('spots the 8-hour offset that a timezone misconfiguration leaves behind', () => {
    // 采集端把本地时间当 UTC 写入 —— 整个索引跑到未来 8 小时。
    const range = { lo: NOW - 86_400_000, hi: NOW + 8 * 3_600_000 }
    expect(dataReachesIntoFuture(range, NOW)).toBe(true)
    expect(Math.round(hoursAhead(range, NOW))).toBe(8)
  })

  it('tolerates a few minutes of clock jitter', () => {
    // 每次查询都为两分钟的漂移说一句，等于把这个提示训练成噪音。
    expect(dataReachesIntoFuture({ lo: NOW - 1000, hi: NOW + 2 * 60_000 }, NOW)).toBe(false)
  })

  it('says nothing about a normal, slightly stale index', () => {
    expect(dataReachesIntoFuture({ lo: NOW - 86_400_000, hi: NOW - 3_600_000 }, NOW)).toBe(false)
  })

  it('is independent of isWindowAfterData', () => {
    /* 这正是加它的理由：数据在未来时，问「最近 1 小时」查出 0 条，而查询起点
       （now-1h）确实早于数据终点（now+8h）—— 陈旧判据不会触发，用户拿到的是一个
       没有任何解释的空结果。 */
    const range = { lo: NOW - 86_400_000, hi: NOW + 8 * 3_600_000 }
    const queryStart = NOW - 3_600_000
    expect(isWindowAfterData(queryStart, range)).toBe(false)
    expect(dataReachesIntoFuture(range, NOW)).toBe(true)
  })
})

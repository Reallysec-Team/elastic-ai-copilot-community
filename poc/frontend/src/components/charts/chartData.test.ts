import { describe, expect, it } from 'vitest'
import {
  actionAxisMax,
  actionBarData,
  barChartHeight,
  categoryAxis,
  truncTick,
} from './chartData'

describe('categoryAxis', () => {
  it('fits the longest label without truncating it', () => {
    const labels = ['critical', 'high', 'medium', 'low', 'informational']
    const { width, maxChars } = categoryAxis(labels)
    expect(maxChars).toBeGreaterThanOrEqual('informational'.length)
    expect(width).toBeLessThan(180)
    for (const l of labels) expect(truncTick(l, maxChars)).toBe(l)
  })

  it('caps the width and falls back to a right-side ellipsis', () => {
    const long = 'a'.repeat(200)
    const { width, maxChars } = categoryAxis([long])
    expect(width).toBe(180)
    expect(maxChars).toBeLessThan(long.length)
    expect(truncTick(long, maxChars)).toMatch(/…$/)
    expect(truncTick(long, maxChars)).toHaveLength(maxChars)
  })

  it('keeps a floor for empty / tiny label sets', () => {
    expect(categoryAxis([]).width).toBe(48)
    expect(categoryAxis(['a']).width).toBe(48)
  })
})

describe('barChartHeight', () => {
  it('grows with rows and keeps a floor for 0/1 rows', () => {
    expect(barChartHeight(0)).toBe(80)
    expect(barChartHeight(1)).toBe(80)
    expect(barChartHeight(8)).toBe(248)
  })
})

describe('actionBarData', () => {
  it('scales against the max bucket and floors tiny bars', () => {
    const rows = actionBarData([
      { key: 'search', count: 100 },
      { key: 'export', count: 1 },
    ])
    expect(rows[0].bar).toBe(100)
    expect(rows[1].bar).toBe(2) // 2% of 100
    expect(rows[1].label).toBe('1')
  })

  it('survives an all-zero set (no divide-by-zero axis)', () => {
    expect(actionAxisMax([{ key: 'a', count: 0 }])).toBe(1)
    expect(actionBarData([{ key: 'a', count: 0 }])[0].bar).toBe(0.02)
  })

  it('survives an empty set', () => {
    expect(actionAxisMax([])).toBe(1)
    expect(actionBarData([])).toEqual([])
  })
})

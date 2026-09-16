import { beforeAll, describe, expect, it } from 'vitest'

import { setLang } from '@/lib/i18n'
import { buildExecDsl, genCostText } from './execDsl'

// node 环境的 navigator.language 是 en，不钉住的话比的是英文文案。
beforeAll(() => setLang('zh'))

describe('buildExecDsl', () => {
  it('applies the size control to a plain query', () => {
    expect(buildExecDsl({ query: { match_all: {} } }, 50, null)).toEqual({
      query: { match_all: {} },
      size: 50,
      track_total_hits: true,
    })
  })

  it('respects an explicit size, including 0', () => {
    expect(buildExecDsl({ size: 5 }, 200, null).size).toBe(5)
    expect(buildExecDsl({ size: 0 }, 200, null).size).toBe(0)
  })

  it('defaults an aggregation query to size 0', () => {
    expect(buildExecDsl({ aggs: { a: {} } }, 200, null).size).toBe(0)
    expect(buildExecDsl({ aggregations: { a: {} } }, 200, null).size).toBe(0)
  })

  it('pushes the sort down to ES', () => {
    expect(buildExecDsl({}, 10, { col: 'bytes', dir: 'desc' }).sort).toEqual([
      { bytes: { order: 'desc' } },
    ])
  })

  it('does not mutate the input', () => {
    const base = { query: { match_all: {} } }
    buildExecDsl(base, 10, null)
    expect(base).toEqual({ query: { match_all: {} } })
  })
})

describe('genCostText', () => {
  it('prefers tokens and shows the in/out split', () => {
    expect(
      genCostText({
        duration_ms: 2400,
        usage: { prompt_tokens: 900, completion_tokens: 100, total_tokens: 1000 },
      }),
    ).toBe('2.4s · 1000 tok (in 900/out 100)')
  })

  it('falls back to output chars when no usage is reported', () => {
    expect(genCostText({ duration_ms: 1000, output_chars: 320 })).toBe('1.0s · 320 字符')
  })

  it('is empty when nothing was reported', () => {
    expect(genCostText({})).toBe('')
  })
})

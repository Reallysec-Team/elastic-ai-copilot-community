import { describe, expect, it } from 'vitest'

import { hitKey } from './hitKey'

describe('hitKey', () => {
  // The regression: `_id` alone collides across a `logs-*` search, so selecting
  // a row in one index silently ticked a row in another.
  it('qualifies the id with the index', () => {
    expect(hitKey({ _id: 'abc', _index: 'logs-2026.01' }, 0)).toBe('logs-2026.01:abc')
    expect(hitKey({ _id: 'abc', _index: 'logs-2026.02' }, 1)).not.toBe(
      hitKey({ _id: 'abc', _index: 'logs-2026.01' }, 0),
    )
  })

  it('falls back to the bare id when ES gave no index', () => {
    expect(hitKey({ _id: 'abc' }, 3)).toBe('abc')
  })

  it('falls back to the position when the hit has no id', () => {
    expect(hitKey({}, 3)).toBe('row-3')
    expect(hitKey({ _index: 'logs-2026.01' }, 3)).toBe('row-3')
  })
})

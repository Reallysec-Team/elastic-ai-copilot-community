import { describe, expect, it } from 'vitest'
import { settingsDiff } from './settingsDiff'

describe('settingsDiff', () => {
  it('returns nothing when the draft is untouched', () => {
    const s = { a: '1', b: '' }
    expect(settingsDiff(s, s)).toEqual({})
  })

  it('sends only the changed keys', () => {
    expect(settingsDiff({ a: '2', b: 'x' }, { a: '1', b: 'x' })).toEqual({ a: '2' })
  })

  it('sends an explicit clear', () => {
    expect(settingsDiff({ a: '' }, { a: '1' })).toEqual({ a: '' })
  })

  it('never echoes a masked secret back to the backend', () => {
    expect(
      settingsDiff({ h: '<set · 42 chars>' }, { h: 'Authorization:Bearer old' }),
    ).toEqual({})
  })

  it('still sends a real value typed over a masked one', () => {
    expect(settingsDiff({ h: 'X-Source:rst' }, { h: '<set · 42 chars>' })).toEqual({
      h: 'X-Source:rst',
    })
  })
})

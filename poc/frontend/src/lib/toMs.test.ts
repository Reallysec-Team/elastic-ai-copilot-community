import { describe, expect, it } from 'vitest'
import { relativeTime, toMs } from './history'

/* 后端两种时间戳形状（ISO 串 / epoch 秒）都要能进 relativeTime；坏值不能抛。 */
describe('toMs', () => {
  it('epoch seconds → ms', () => {
    expect(toMs(1789233720.9)).toBe(1789233720900)
  })
  it('epoch ms stays ms', () => {
    expect(toMs(1789233720900)).toBe(1789233720900)
  })
  it('ISO string parses', () => {
    expect(toMs('2026-09-05T11:55:00Z')).toBe(Date.parse('2026-09-05T11:55:00Z'))
  })
  it('garbage / empty / 0 → null, and relativeTime never throws on NaN', () => {
    expect(toMs('nope')).toBeNull()
    expect(toMs('')).toBeNull()
    expect(toMs(0)).toBeNull()
    expect(toMs(null)).toBeNull()
    expect(relativeTime(Number.NaN)).toBe('—')
  })
})

import { describe, expect, it } from 'vitest'
import { extractToken } from './licenseToken'

const A = 'a'.repeat(24)
const B = 'b'.repeat(30)
const TOKEN = `${A}.${B}`

describe('extractToken', () => {
  it('returns empty for empty / whitespace input', () => {
    expect(extractToken('')).toBe('')
    expect(extractToken('   \n ')).toBe('')
  })

  it('reads the JSON wrapper keys', () => {
    expect(extractToken(JSON.stringify({ license_token: TOKEN }))).toBe(TOKEN)
    expect(extractToken(JSON.stringify({ license_key: TOKEN }))).toBe(TOKEN)
    expect(extractToken(JSON.stringify({ token: TOKEN }))).toBe(TOKEN)
  })

  it('ignores non-string JSON values and falls back to the scan', () => {
    expect(extractToken(JSON.stringify({ license_token: 42, note: TOKEN }))).toBe(TOKEN)
  })

  it('picks the token out of a labelled raw delivery', () => {
    expect(extractToken(`# issued 2026-01-01\nToken: ${TOKEN}\n`)).toBe(TOKEN)
  })

  it('prefers the longest candidate when several appear', () => {
    const long = `${A}.${'c'.repeat(80)}`
    expect(extractToken(`${TOKEN}\n${long}\n`)).toBe(long)
  })

  it('returns empty when nothing looks like a token', () => {
    expect(extractToken('这不是一个 license 文件')).toBe('')
    expect(extractToken('short.short')).toBe('')
  })
})

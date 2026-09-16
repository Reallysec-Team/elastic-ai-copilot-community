import { afterEach, describe, expect, it, vi } from 'vitest'

import { modKeyCombo, modKeyLabel } from './platformKey'

function stubPlatform(platform: string, useAgentData = false) {
  const nav: Record<string, unknown> = { platform, userAgent: platform }
  if (useAgentData) nav.userAgentData = { platform }
  vi.stubGlobal('navigator', nav)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('modKeyLabel', () => {
  it('shows the Command glyph on macOS', () => {
    stubPlatform('MacIntel')
    expect(modKeyLabel()).toBe('⌘')
  })

  it('shows Ctrl on Windows — the badge must name a key the keyboard has', () => {
    stubPlatform('Win32')
    expect(modKeyLabel()).toBe('Ctrl')
  })

  it('shows Ctrl on Linux', () => {
    stubPlatform('Linux x86_64')
    expect(modKeyLabel()).toBe('Ctrl')
  })

  it('prefers userAgentData over the deprecated platform field', () => {
    stubPlatform('MacIntel', true)
    expect(modKeyLabel()).toBe('⌘')
  })

  it('falls back to Ctrl when there is no navigator (SSR / prerender)', () => {
    vi.stubGlobal('navigator', undefined)
    expect(modKeyLabel()).toBe('Ctrl')
  })
})

describe('modKeyCombo', () => {
  it('joins with a plus off macOS — CtrlK reads as a word, not a shortcut', () => {
    stubPlatform('Win32')
    expect(modKeyCombo('K')).toBe('Ctrl+K')
  })

  it('keeps the Command glyph tight against the key', () => {
    stubPlatform('MacIntel')
    expect(modKeyCombo('K')).toBe('⌘K')
  })
})

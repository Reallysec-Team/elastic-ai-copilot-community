/**
 * Label for the command-palette / submit modifier, matching the key that
 * actually works on this platform.
 *
 * The handlers have always accepted both (`e.metaKey || e.ctrlKey`), but the
 * badges rendered a hardcoded `⌘`. On the Windows hosts this ships to that
 * reads as a key the keyboard does not have — and the one Windows key shaped
 * like it, ⊞, does something else entirely.
 */
export function modKeyLabel(): string {
  if (typeof navigator === 'undefined') return 'Ctrl'
  // userAgentData is the non-deprecated source; fall back to platform/UA.
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } }
  const p = nav.userAgentData?.platform || navigator.platform || navigator.userAgent || ''
  return /mac|iphone|ipad|ipod/i.test(p) ? '⌘' : 'Ctrl'
}

/**
 * The modifier plus a key, joined the way each platform writes it: `⌘K` on
 * macOS (the glyph already reads as one chord), `Ctrl+K` elsewhere — a bare
 * `CtrlK` reads as one word, not a shortcut.
 */
export function modKeyCombo(key: string): string {
  const mod = modKeyLabel()
  return mod === '⌘' ? `${mod}${key}` : `${mod}+${key}`
}

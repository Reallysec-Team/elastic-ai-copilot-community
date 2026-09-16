/*
 * Theme controller (Round 14 — dark mode).
 *
 * Three modes: 'light' | 'dark' | 'system'. 'system' follows the OS
 * prefers-color-scheme and re-evaluates live. The resolved value toggles
 * a `.dark` class on <html>, which every `--t-*` token + `dark:` variant
 * keys off.
 *
 * The no-flash boot is in index.html's inline <script> — it must apply
 * the class before first paint. This module is the runtime controller
 * the toggle UI uses.
 */

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'rst-theme'

export function getThemeMode(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    // ignore
  }
  return 'system'
}

function systemPrefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** The actual light/dark in effect, resolving 'system'. */
export function resolvedTheme(mode: ThemeMode = getThemeMode()): 'light' | 'dark' {
  if (mode === 'system') return systemPrefersDark() ? 'dark' : 'light'
  return mode
}

function apply(mode: ThemeMode): void {
  const dark = resolvedTheme(mode) === 'dark'
  document.documentElement.classList.toggle('dark', dark)
}

export function setThemeMode(mode: ThemeMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    // ignore
  }
  apply(mode)
  window.dispatchEvent(new Event('rst-theme-changed'))
}

/** Call once at startup — applies stored theme + wires the system listener. */
export function initTheme(): void {
  apply(getThemeMode())
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  mq.addEventListener('change', () => {
    if (getThemeMode() === 'system') {
      apply('system')
      window.dispatchEvent(new Event('rst-theme-changed'))
    }
  })
}

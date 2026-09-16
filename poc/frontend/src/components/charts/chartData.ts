/*
 * Pure shaping helpers for the ReportsPage charts. Kept out of the component so
 * the bits with actual rules (the 2% visibility floor, the empty/all-zero
 * fallback, chart height) are testable without rendering recharts.
 */

/** Horizontal bar charts grow with their row count instead of a fixed aspect. */
export function barChartHeight(rowCount: number): number {
  return Math.max(80, rowCount * 28 + 24)
}

// Geist Mono at 12px is ~7.2px/char; 7.5 leaves slack so nothing gets clipped.
const TICK_CHAR_W = 7.5
const TICK_PAD = 12
const TICK_AXIS_MAX = 180

/**
 * Category axis wide enough for the longest label in *this* batch, capped so a
 * pathological action name can't eat the plot. `maxChars` is derived from the
 * width that survived the cap, so labels only get an ellipsis once the cap bites
 * — same "…" behaviour the old CSS truncate had, never a left-side clip.
 */
export function categoryAxis(labels: string[]): { width: number; maxChars: number } {
  const longest = Math.max(0, ...labels.map((l) => l.length))
  const width = Math.min(TICK_AXIS_MAX, Math.max(48, longest * TICK_CHAR_W + TICK_PAD))
  return { width, maxChars: Math.max(1, Math.floor((width - TICK_PAD) / TICK_CHAR_W)) }
}

export function truncTick(value: string, maxChars: number): string {
  return value.length > maxChars ? `${value.slice(0, maxChars - 1)}…` : value
}

/**
 * `bar` carries the 2% floor the old hand-rolled bars used so a near-zero
 * severity stays visible; `count`/`pct` stay untouched for the printed label.
 */
export type ActionBucket = { key: string; count: number }
export type ActionDatum = ActionBucket & { bar: number; label: string }

/**
 * Old behaviour: width = count / max * 100, floored at 2%, with max forced to
 * at least 1 so an all-zero set does not divide by zero. Same rule, expressed
 * against a [0, max] axis domain — see `actionAxisMax`.
 */
export function actionBarData(buckets: ActionBucket[]): ActionDatum[] {
  const max = actionAxisMax(buckets)
  return buckets.map((b) => ({
    ...b,
    bar: Math.max(max * 0.02, b.count),
    label: b.count.toLocaleString(),
  }))
}

export function actionAxisMax(buckets: ActionBucket[]): number {
  return Math.max(1, ...buckets.map((b) => b.count))
}

/** Read at render time; no listener needed for a one-shot entry animation. */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

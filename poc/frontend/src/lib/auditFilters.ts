import { translate } from '@/lib/i18n'
import { libCopy } from '@/locales/lib'

/* Filter maths behind /v2/audit. Pure so the validation rules (which decide
 * whether a query is sent at all) are testable without a DOM. */

export type AuditRange = '1h' | '24h' | '7d' | 'custom'

// Committed filter portion of an audit query (everything except size/offset).
export interface AuditFilterParams {
  from_ts?: string
  to_ts?: string
  action?: string
  outcome?: string
  user?: string
  target_index?: string
}

export interface AuditFilterInput {
  range: AuditRange
  customFrom: string
  customTo: string
  action: string
  outcome: string
  user: string
  targetIndex: string
}

export function computeRange(
  range: AuditRange,
  customFrom: string,
  customTo: string,
  now: number = Date.now(),
): { from_ts: string | null; to_ts: string | null } {
  if (range === 'custom') {
    return {
      from_ts: customFrom ? new Date(customFrom).toISOString() : null,
      to_ts: customTo ? new Date(customTo).toISOString() : null,
    }
  }
  const ms =
    range === '1h'
      ? 60 * 60 * 1000
      : range === '24h'
        ? 24 * 60 * 60 * 1000
        : 7 * 24 * 60 * 60 * 1000
  return {
    from_ts: new Date(now - ms).toISOString(),
    to_ts: null,
  }
}

/* Build filter params from the live filter state. Returns an error string for
 * invalid custom ranges rather than silently degrading to full/empty. */
export function buildAuditFilters(
  f: AuditFilterInput,
  now: number = Date.now(),
): { params?: AuditFilterParams; error?: string } {
  if (f.range === 'custom') {
    if (!f.customFrom && !f.customTo) {
      return { error: translate(libCopy, 'afNeedOneBound') }
    }
    if (
      f.customFrom &&
      f.customTo &&
      new Date(f.customFrom).getTime() > new Date(f.customTo).getTime()
    ) {
      return { error: translate(libCopy, 'afStartAfterEnd') }
    }
  }
  const { from_ts, to_ts } = computeRange(f.range, f.customFrom, f.customTo, now)
  const params: AuditFilterParams = {}
  if (from_ts) params.from_ts = from_ts
  if (to_ts) params.to_ts = to_ts
  if (f.action) params.action = f.action
  if (f.outcome) params.outcome = f.outcome
  if (f.user.trim()) params.user = f.user.trim()
  if (f.targetIndex.trim()) params.target_index = f.targetIndex.trim()
  return { params }
}

import { beforeEach, describe, expect, it } from 'vitest'
import { buildAuditFilters, computeRange, type AuditFilterInput } from './auditFilters'
import { setLang } from '@/lib/i18n'

/* 这些断言比的是中文文案，所以先把语言钉死 —— 不钉的话它按 `navigator.language`
   回落，node 环境里是 en。 */
beforeEach(() => setLang('zh'))


const NOW = Date.parse('2026-09-04T00:00:00.000Z')

function input(over: Partial<AuditFilterInput> = {}): AuditFilterInput {
  return {
    range: '24h',
    customFrom: '',
    customTo: '',
    action: '',
    outcome: '',
    user: '',
    targetIndex: '',
    ...over,
  }
}

describe('computeRange', () => {
  it('turns a relative range into a from_ts and an open end', () => {
    expect(computeRange('1h', '', '', NOW)).toEqual({
      from_ts: '2026-09-03T23:00:00.000Z',
      to_ts: null,
    })
    expect(computeRange('24h', '', '', NOW).from_ts).toBe('2026-09-03T00:00:00.000Z')
    expect(computeRange('7d', '', '', NOW).from_ts).toBe('2026-08-28T00:00:00.000Z')
  })

  it('leaves an unfilled side of a custom range null', () => {
    expect(computeRange('custom', '', '', NOW)).toEqual({ from_ts: null, to_ts: null })
    expect(computeRange('custom', '2026-01-01T00:00', '', NOW).to_ts).toBeNull()
  })
})

describe('buildAuditFilters', () => {
  it('omits every empty filter', () => {
    expect(buildAuditFilters(input(), NOW).params).toEqual({
      from_ts: '2026-09-03T00:00:00.000Z',
    })
  })

  it('trims free-text filters', () => {
    const { params } = buildAuditFilters(
      input({ user: '  alice  ', targetIndex: ' logs-* ', action: 'generate', outcome: 'fail' }),
      NOW,
    )
    expect(params).toMatchObject({
      user: 'alice',
      target_index: 'logs-*',
      action: 'generate',
      outcome: 'fail',
    })
  })

  it('drops whitespace-only free text rather than querying for it', () => {
    expect(buildAuditFilters(input({ user: '   ' }), NOW).params).not.toHaveProperty('user')
  })

  it('rejects an entirely empty custom range', () => {
    const r = buildAuditFilters(input({ range: 'custom' }), NOW)
    expect(r.params).toBeUndefined()
    expect(r.error).toContain('请至少填写')
  })

  it('rejects an inverted custom range', () => {
    const r = buildAuditFilters(
      input({ range: 'custom', customFrom: '2026-09-02T10:00', customTo: '2026-09-01T10:00' }),
      NOW,
    )
    expect(r.error).toContain('不能晚于')
  })

  it('accepts a one-sided custom range', () => {
    const r = buildAuditFilters(input({ range: 'custom', customTo: '2026-09-01T10:00' }), NOW)
    expect(r.error).toBeUndefined()
    expect(r.params).toHaveProperty('to_ts')
    expect(r.params).not.toHaveProperty('from_ts')
  })
})

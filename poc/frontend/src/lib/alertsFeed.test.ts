import { describe, expect, it } from 'vitest'
import type { RealtimeAlert } from '@/lib/api'
import { buildDisplayItems, formatTs, groupKeyOf, matchesFilters } from './alertsFeed'

function alert(over: Partial<RealtimeAlert> & { alert_id: string }): RealtimeAlert {
  return {
    rule_id: 'r1',
    rule_name: 'Suspicious login',
    severity: 'high',
    '@timestamp': '2026-09-04T00:00:00.000Z',
    origin: 'poll',
    ...over,
  }
}

describe('groupKeyOf', () => {
  it('keys on rule + subject, falling back to the rule name when there is no id', () => {
    expect(groupKeyOf(alert({ alert_id: 'a', subject_field: 'host.name', subject_value: 'web1' })))
      .toBe('r1|host.name=web1')
    expect(groupKeyOf(alert({ alert_id: 'a', rule_id: '' }))).toBe('Suspicious login|=')
  })
})

describe('buildDisplayItems', () => {
  const a = alert({ alert_id: 'a', subject_value: 'x', subject_field: 'f' })
  const b = alert({ alert_id: 'b', subject_value: 'x', subject_field: 'f' })
  const c = alert({ alert_id: 'c', rule_id: 'r2' })

  it('emits a flat row per alert when grouping is off', () => {
    const items = buildDisplayItems([a, b, c], false, new Set())
    expect(items).toHaveLength(3)
    expect(items.every((i) => i.kind === 'row')).toBe(true)
  })

  it('only groups a run of two or more consecutive same-key alerts', () => {
    const items = buildDisplayItems([a, b, c], true, new Set())
    expect(items.map((i) => i.kind)).toEqual(['group', 'row'])
    const group = items[0]
    if (group.kind !== 'group') throw new Error('expected a group head')
    expect(group.count).toBe(2)
    expect(group.head).toBe(a)
    expect(group.expanded).toBe(false)
  })

  it('does not merge a non-consecutive run', () => {
    const items = buildDisplayItems([a, c, b], true, new Set())
    expect(items.map((i) => i.kind)).toEqual(['row', 'row', 'row'])
  })

  it('appends every member as a child row when the group is expanded', () => {
    const key = groupKeyOf(a) + ':' + a.alert_id
    const items = buildDisplayItems([a, b, c], true, new Set([key]))
    expect(items.map((i) => i.kind)).toEqual(['group', 'row', 'row', 'row'])
    expect(items.slice(1, 3).every((i) => i.kind === 'row' && i.child)).toBe(true)
    // ids stay unique even though the head appears twice
    expect(new Set(items.map((i) => i.id)).size).toBe(items.length)
  })
})

describe('matchesFilters', () => {
  const a = alert({ alert_id: 'a' })
  const none = { severity: '', rule: '', timeRange: '' }

  it('passes everything when no filter is set', () => {
    expect(matchesFilters(a, none)).toBe(true)
  })

  it('gates on exact severity', () => {
    expect(matchesFilters(a, { ...none, severity: 'high' })).toBe(true)
    expect(matchesFilters(a, { ...none, severity: 'low' })).toBe(false)
  })

  it('matches the rule text case-insensitively against name and id', () => {
    expect(matchesFilters(a, { ...none, rule: 'SUSPICIOUS' })).toBe(true)
    expect(matchesFilters(a, { ...none, rule: 'r1' })).toBe(true)
    expect(matchesFilters(a, { ...none, rule: 'nope' })).toBe(false)
  })

  it('drops alerts older than the since cursor', () => {
    expect(matchesFilters(a, none, '2026-09-03T00:00:00.000Z')).toBe(true)
    expect(matchesFilters(a, none, '2026-09-05T00:00:00.000Z')).toBe(false)
  })
})

describe('formatTs', () => {
  it('renders an em dash for a missing value and echoes an unparseable one', () => {
    expect(formatTs()).toBe('—')
    expect(formatTs('not a date')).toBe('not a date')
  })
})

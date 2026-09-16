import { describe, expect, it } from 'vitest'
import { filterCommands } from './CommandPalette'

const cmds = [
  { label: '批量分诊', keywords: 'triage fenzhen alert 告警 批量', hint: '/triage' },
  { label: '检测规则', keywords: 'detection rule jiance guize kibana', hint: '/detection-rules' },
  { label: '新建查询', keywords: 'new query xinjian 新建' },
]

describe('filterCommands', () => {
  it('returns everything for an empty / whitespace query', () => {
    expect(filterCommands(cmds, '')).toHaveLength(3)
    expect(filterCommands(cmds, '   ')).toHaveLength(3)
  })

  it('matches the Chinese label', () => {
    expect(filterCommands(cmds, '分诊').map((c) => c.label)).toEqual(['批量分诊'])
  })

  it('matches pinyin / english keywords, case-insensitively', () => {
    expect(filterCommands(cmds, 'KIBANA').map((c) => c.label)).toEqual(['检测规则'])
  })

  it('matches the hint (route path)', () => {
    expect(filterCommands(cmds, '/triage').map((c) => c.label)).toEqual(['批量分诊'])
  })

  it('requires every term, not just one (AND, not OR)', () => {
    expect(filterCommands(cmds, 'detection rule')).toHaveLength(1)
    expect(filterCommands(cmds, 'detection triage')).toHaveLength(0)
  })

  it('does not mutate or alias the input array', () => {
    const out = filterCommands(cmds, '')
    expect(out).not.toBe(cmds)
  })
})

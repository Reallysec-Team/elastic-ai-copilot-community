import { afterEach, describe, expect, it } from 'vitest'
import { setLang } from './i18n'
import { severityLabel } from './severity'

afterEach(() => setLang('zh'))

describe('severityLabel', () => {
  it('五个已知档位跟着界面语言走', () => {
    setLang('zh')
    expect(severityLabel('critical')).toBe('严重')
    expect(severityLabel('high')).toBe('高')
    expect(severityLabel('medium')).toBe('中')
    expect(severityLabel('low')).toBe('低')
    expect(severityLabel('info')).toBe('提示')

    setLang('en')
    expect(severityLabel('critical')).toBe('Critical')
    expect(severityLabel('info')).toBe('Info')
  })

  it('大小写不敏感 —— 后端有些地方回的是 HIGH', () => {
    setLang('zh')
    expect(severityLabel('HIGH')).toBe('高')
  })

  it('不认识的档位原样返回，不吞成空白', () => {
    expect(severityLabel('bizarre')).toBe('bizarre')
  })

  it('空值给一个占位符而不是 undefined', () => {
    expect(severityLabel(null)).toBe('—')
    expect(severityLabel(undefined)).toBe('—')
    expect(severityLabel('')).toBe('—')
  })
})

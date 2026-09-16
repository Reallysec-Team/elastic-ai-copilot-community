import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setLang } from '@/lib/i18n'
import { alertTitle } from './InvestigationDialog'

/* 兜底那句现在跟着界面语言走，所以断言之前先把语言钉死 —— 不钉的话它取的是
   `navigator.language`，在 node 环境里是 en。 */
beforeEach(() => setLang('zh'))
afterEach(() => setLang('zh'))

describe('alertTitle', () => {
  it('模型给了类型就用它', () => {
    expect(alertTitle('暴力破解', null)).toBe('暴力破解')
  })

  it('后端把缺失兜成 "unknown" —— 那不是标题，退回规则名', () => {
    expect(alertTitle('unknown', { rule: { name: '敏感文件访问' } })).toBe('敏感文件访问')
    expect(alertTitle('', { 'kibana.alert.rule.name': '权限提升' })).toBe('权限提升')
  })

  it('_source 包一层也认', () => {
    expect(alertTitle(undefined, { _source: { rule_name: '异常外联' } })).toBe('异常外联')
  })

  it('什么都没有时给一句兜底，不是 unknown', () => {
    expect(alertTitle('unknown', {})).toBe('告警调查')
    expect(alertTitle(null, null)).toBe('告警调查')

    setLang('en')
    expect(alertTitle('unknown', {})).toBe('Alert investigation')
  })
})

import { beforeEach, describe, expect, it } from 'vitest'
import { followUpQuestion, recordTitle } from './analysisFollowUp'
import { setLang } from '@/lib/i18n'

/* 这些断言比的是中文文案，所以先把语言钉死 —— 不钉的话它按 `navigator.language`
   回落，node 环境里是 en。 */
beforeEach(() => setLang('zh'))


describe('followUpQuestion', () => {
  it('调查记录：拿受影响资产接出一句问题', () => {
    expect(
      followUpQuestion({ kind: 'investigation', subject: { type: 'host', value: 'host-2' } }),
    ).toBe('最近 24 小时与 host-2 有关的日志')
  })

  it('结果解读记录：主体就是当初那句问题，原样接回去', () => {
    expect(
      followUpQuestion({ kind: 'result_explain', subject: { type: 'query', value: '谁在暴力破解' } }),
    ).toBe('谁在暴力破解')
  })

  it('分诊记录接不出问题 —— 主体是「9 clusters」，不是一个能查的东西', () => {
    expect(
      followUpQuestion({ kind: 'triage', subject: { type: 'triage', value: '9 clusters' } }),
    ).toBeNull()
  })

  it('主体缺失或空白时不给按钮', () => {
    expect(followUpQuestion({ kind: 'investigation' })).toBeNull()
    expect(followUpQuestion({ kind: 'investigation', subject: { type: 'host', value: '  ' } })).toBeNull()
  })
})

describe('recordTitle', () => {
  it('有标题就用标题', () => {
    expect(recordTitle({ kind: 'investigation', title: '暴力破解' })).toBe('暴力破解')
  })

  it('后端写的 "unknown" 不是标题 —— 退回主体', () => {
    expect(
      recordTitle({ kind: 'investigation', title: 'unknown', subject: { type: 'host', value: 'host-2' } }),
    ).toBe('host-2')
  })

  it('分诊记录的主体是「9 clusters」，不拿它当标题', () => {
    expect(
      recordTitle({ kind: 'triage', title: 'unknown', subject: { type: 'triage', value: '9 clusters' } }),
    ).toBe('告警分诊')
  })

  it('什么都没有时按类型说一句中文', () => {
    expect(recordTitle({ kind: 'investigation', title: 'unknown' })).toBe('告警调查')
  })
})

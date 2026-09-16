import { describe, expect, it } from 'vitest'

import { setLang } from '@/lib/i18n'
import { apiErrorMessage } from '@/locales/errors'

const body = {
  detail: '用户 alice 不存在。',
  code: 'user_not_found',
  params: { name: 'alice' },
}

describe('apiErrorMessage', () => {
  it('中文界面直接用后端的 detail —— 那是唯一真源', () => {
    setLang('zh')
    expect(apiErrorMessage(body)).toBe('用户 alice 不存在。')
  })

  it('英文界面按码取模板并填参数', () => {
    setLang('en')
    expect(apiErrorMessage(body)).toBe('User alice does not exist.')
  })

  it('没带码的老错误退回 detail，不能变成空白', () => {
    setLang('en')
    expect(apiErrorMessage({ detail: '某个第三方中间件的话' })).toBe('某个第三方中间件的话')
  })

  it('码没有英文文案时同样退回 detail', () => {
    setLang('en')
    expect(apiErrorMessage({ detail: '中文原文', code: 'not_a_real_code' })).toBe('中文原文')
  })

  it('渠道名跟着翻 —— 中文文案里它是「钉钉」', () => {
    setLang('en')
    const m = apiErrorMessage({ code: 'webhook_must_be_https', params: { channel: '钉钉' } })
    expect(m).toBe('The DingTalk webhook must use https.')
  })

  it('缺参数时占位符原样留着，不渲染成 undefined', () => {
    setLang('en')
    expect(apiErrorMessage({ code: 'rate_limited', params: {} })).toContain('{seconds}')
  })

  it('完全不是对象的响应体走 fallback', () => {
    setLang('en')
    expect(apiErrorMessage(null, 'HTTP 502')).toBe('HTTP 502')
  })
})

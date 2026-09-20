import { describe, expect, it } from 'vitest'

import { verifyCertsOn } from './es-connection'

/*
 * verify_certs 的默认值必须和后端 `_verify_certs()` 一致：未设置时校验证书（true）。
 * 这条闸挡的是那个真 bug —— 空开关按 false 解释会让「测试连接」用不校验、实际查询
 * 用校验，自签名 https 集群测通却处处连不上。
 */
describe('verifyCertsOn', () => {
  it('未设置（空串）按后端默认：校验', () => {
    expect(verifyCertsOn('')).toBe(true)
    expect(verifyCertsOn('   ')).toBe(true)
  })

  it('显式 false 才不校验', () => {
    expect(verifyCertsOn('false')).toBe(false)
    expect(verifyCertsOn('False')).toBe(false)
  })

  it('显式 true 校验', () => {
    expect(verifyCertsOn('true')).toBe(true)
    expect(verifyCertsOn('TRUE')).toBe(true)
  })
})

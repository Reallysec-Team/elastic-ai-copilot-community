import { describe, expect, it } from 'vitest'

import { gateFor } from '@/components/gated-button'

/*
 * 权限闸的真值表。
 *
 * 之所以值得钉：界面上以前只有一档「不是 viewer」，而后端有 39 条路由要的是
 * admin —— analyst 于是看到一整排亮着、按下去必然 403 的按钮。这张表把两档的
 * 差别写死，改错级别会在这里红，而不是在客户的 analyst 账号上红。
 */

const admin = { role: 'admin', is_admin: true }
const analyst = { role: 'analyst', is_admin: false }
const viewer = { role: 'viewer', is_admin: false }
// 这套部署对调用者没有角色意见（ops token / 代理头身份）—— 不是一个角色。
const noOpinion = { role: null, is_admin: false }

describe('gateFor', () => {
  it('admin 两档都放行', () => {
    expect(gateFor(admin, 'write').allowed).toBe(true)
    expect(gateFor(admin, 'admin').allowed).toBe(true)
  })

  it('analyst 能写，但管理员那一档挡住，并说得出为什么', () => {
    expect(gateFor(analyst, 'write').allowed).toBe(true)
    const g = gateFor(analyst, 'admin')
    expect(g.allowed).toBe(false)
    expect(g.reasonKey).toBe('adminOnlyAction')
  })

  it('viewer 两档都挡，写那一档给的是只读的说法', () => {
    const w = gateFor(viewer, 'write')
    expect(w.allowed).toBe(false)
    expect(w.reasonKey).toBe('readOnlyRole')
    expect(gateFor(viewer, 'admin').allowed).toBe(false)
  })

  it('没有角色意见时放行，交给后端答复', () => {
    expect(gateFor(noOpinion, 'write').allowed).toBe(true)
    expect(gateFor(noOpinion, 'admin').allowed).toBe(true)
  })

  it('/api/me 还没回来时先放行，避免按钮先灰一下再亮', () => {
    expect(gateFor(null, 'admin').allowed).toBe(true)
  })

  it('放行时不带原因文案', () => {
    expect(gateFor(admin, 'admin').reasonKey).toBeNull()
  })
})

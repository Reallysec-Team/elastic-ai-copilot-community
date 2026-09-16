import { test, expect } from '@playwright/test'
import { ROUTES } from './_shared'

/*
 * 版式探针 —— 量几何，不比像素。
 *
 * 两类都踩过不止一次，而且「看起来跟写对了一模一样」：
 *   ⑨  box-shadow 画的环被 overflow 容器裁掉半圈（现象是「方框显示不全」）；
 *   ⑨c 单行标题被 items-end 吊在按钮上沿（有说明时底对齐是对的，没说明时不是）。
 *
 * 每个探针先自检：造一个已知的坏例子，抓不到就整组不算数 —— 否则「其它地方没报」
 * 只说明探针没工作。
 *
 * 环画在元素盒子外面，放进任何 overflow-* 容器时四边要留 ≥ 环宽的内边距，否则
 * 只缺半圈 —— 现象是「方框显示不全」。这里量的是实测几何，不是代码形状。
 */

const PROBE = `(() => {
  const RING = /^rgb[^)]*\\)\\s+0px\\s+0px\\s+0px\\s+(\\d+(?:\\.\\d+)?)px/
  const scrollable = (el) => {
    const s = getComputedStyle(el)
    return /auto|scroll|hidden|clip/.test(s.overflowX + ' ' + s.overflowY)
  }
  const label = (el) => {
    const cls = (el.className && el.className.baseVal) || el.className || ''
    return el.tagName.toLowerCase() + (typeof cls === 'string' ? '.' + cls.trim().split(/\\s+/).slice(0, 3).join('.') : '')
  }
  const out = []
  for (const el of document.querySelectorAll('*')) {
    const s = getComputedStyle(el)
    const m = RING.exec(s.boxShadow)
    if (!m) continue
    const ring = parseFloat(m[1])
    if (!ring) continue
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) continue
    let p = el.parentElement
    while (p && !scrollable(p)) p = p.parentElement
    if (!p) continue
    const pr = p.getBoundingClientRect()
    const ps = getComputedStyle(p)
    const pad = (v) => parseFloat(v) || 0
    const gaps = {
      left: r.left - (pr.left + pad(ps.borderLeftWidth)),
      right: (pr.right - pad(ps.borderRightWidth)) - r.right,
      top: r.top - (pr.top + pad(ps.borderTopWidth)),
      bottom: (pr.bottom - pad(ps.borderBottomWidth)) - r.bottom,
    }
    const clipped = Object.entries(gaps).filter(([side, g]) => {
      // 只看那条轴真的会裁的方向
      const axis = side === 'left' || side === 'right' ? ps.overflowX : ps.overflowY
      return /auto|scroll|hidden|clip/.test(axis) && g < ring
    })
    if (clipped.length) {
      out.push({
        el: label(el),
        parent: label(p),
        ring,
        sides: clipped.map(([s2, g]) => s2 + ':' + g.toFixed(1)).join(' '),
      })
    }
  }
  return out
})()`

test.describe('⑨ 环被裁探针', () => {
  test('探针自检 —— 造一个坏例子必须被抓到', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => {
      const box = document.createElement('div')
      box.style.cssText = 'overflow:auto;width:200px;height:60px;padding:0'
      box.id = 'probe-bad-box'
      const inner = document.createElement('div')
      inner.style.cssText = 'box-shadow: rgb(0,0,0) 0px 0px 0px 1px; width:180px;height:40px'
      box.appendChild(inner)
      document.body.appendChild(box)
    })
    const found = (await page.evaluate(PROBE)) as Array<{ el: string }>
    expect(found.length, '探针自己抓不到已知的坏例子 —— 后面的"没报"都不算数').toBeGreaterThan(0)
  })

  // ROUTES 只有 11 条，实际路由有 19 条 —— 把没覆盖的那几条补上
  const EXTRA = [
    { path: '/v2/analysis', name: 'analysis' },
    { path: '/v2/posture', name: 'posture' },
    { path: '/v2/alerts', name: 'alerts' },
    { path: '/v2/baseline', name: 'baseline' },
    { path: '/v2/platform', name: 'platform' },
    { path: '/v2/notify', name: 'notify' },
    { path: '/v2/ai-settings', name: 'ai-settings' },
  ]

  for (const r of [...ROUTES, ...EXTRA]) {
    test(`${r.name} — 页面上的环没被裁`, async ({ page }) => {
      await page.goto(r.path, { waitUntil: 'domcontentloaded' })
      await page.locator('h1').first().waitFor({ timeout: 15_000 })
      await page.waitForTimeout(600)
      const found = await page.evaluate(PROBE)
      expect(JSON.stringify(found, null, 1)).toBe('[]')
    })
  }

  test('查询历史抽屉内部', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await page.locator('h1').first().waitFor({ timeout: 15_000 })
    const opener = page.getByRole('button', { name: /历史|History/ }).first()
    if ((await opener.count()) === 0) test.skip(true, '这个视口没有历史按钮')
    await opener.click()
    await page.waitForTimeout(700)
    const found = await page.evaluate(PROBE)
    expect(JSON.stringify(found, null, 1)).toBe('[]')
  })
})

test.describe('⑨b 弹窗 / 抽屉内部', () => {
  test('告警详情抽屉', async ({ page }) => {
    await page.goto('/v2/alerts', { waitUntil: 'domcontentloaded' })
    await page.locator('h1').first().waitFor({ timeout: 15_000 })
    await page.waitForTimeout(1500)
    const row = page.locator('[role="row"], [data-alert-row], li, tr').filter({ hasText: /\S/ })
    const n = await row.count()
    if (n === 0) test.skip(true, '本机没有告警数据')
    for (let i = 0; i < Math.min(n, 6); i++) {
      await row.nth(i).click({ timeout: 3000 }).catch(() => {})
      await page.waitForTimeout(500)
      if (await page.locator('[role="dialog"]').count()) break
    }
    if ((await page.locator('[role="dialog"]').count()) === 0) {
      test.skip(true, '点不开详情（没有可点的告警行）')
    }
    const found = await page.evaluate(PROBE)
    expect(JSON.stringify(found, null, 1)).toBe('[]')
  })
})

/*
 * 第二类：单行标题被 items-end 吊在按钮上沿。
 * 判据：flex 容器 align-items:flex-end，里面有一个单行文本子元素，且它比最高的
 * 兄弟矮 >= 8px —— 那条基线对齐在「没有说明」时读起来就是没对齐。
 */
const PROBE_ALIGN = `(() => {
  const out = []
  const oneLine = (el) => {
    const s = getComputedStyle(el)
    const lh = parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.2
    return el.getBoundingClientRect().height <= lh * 1.4
  }
  const label = (el) => {
    const cls = typeof el.className === 'string' ? el.className : ''
    return el.tagName.toLowerCase() + '.' + cls.trim().split(/\\s+/).slice(0, 3).join('.')
  }
  for (const el of document.querySelectorAll('*')) {
    const s = getComputedStyle(el)
    if (!/flex/.test(s.display) || s.alignItems !== 'flex-end') continue
    const kids = [...el.children].filter((k) => k.getBoundingClientRect().height > 0)
    if (kids.length < 2) continue
    const heights = kids.map((k) => k.getBoundingClientRect().height)
    const tallest = Math.max(...heights)
    kids.forEach((k, i) => {
      if (tallest - heights[i] < 8) return
      if (!(k.textContent || '').trim()) return
      if (!oneLine(k)) return
      out.push({ box: label(el), kid: label(k), kidH: heights[i], tallest })
    })
  }
  return out
})()`

test.describe('⑨c 单行标题的底对齐', () => {
  test('探针自检', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => {
      const box = document.createElement('div')
      box.style.cssText = 'display:flex;align-items:flex-end;gap:8px'
      const title = document.createElement('span')
      title.textContent = '单行标题'
      title.style.cssText = 'font-size:16px;line-height:20px'
      const tall = document.createElement('div')
      tall.style.cssText = 'height:44px;width:80px'
      tall.textContent = '按钮'
      box.append(title, tall)
      document.body.appendChild(box)
    })
    const found = (await page.evaluate(PROBE_ALIGN)) as unknown[]
    expect(found.length, '探针抓不到已知坏例子').toBeGreaterThan(0)
  })

  for (const r of ROUTES) {
    test(`${r.name}`, async ({ page }) => {
      await page.goto(r.path, { waitUntil: 'domcontentloaded' })
      await page.locator('h1').first().waitFor({ timeout: 15_000 })
      await page.waitForTimeout(600)
      const found = await page.evaluate(PROBE_ALIGN)
      expect(JSON.stringify(found, null, 1)).toBe('[]')
    })
  }
})

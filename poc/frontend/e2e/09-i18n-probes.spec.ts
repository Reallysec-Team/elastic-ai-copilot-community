import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { test, expect } from '@playwright/test'
import { ROUTES } from './_shared'

/*
 * i18n 探针 —— 界面上不该出现文案键本身。
 *
 * 踩过的是这一种：`label: 'tabDocs'` 这类数组直接 `{it.label}` 渲染，键原样画到
 * 页面上（处置手册那两个页签）。TypeScript 拦不住它 —— 键就是字符串，类型完全
 * 合法；单测也拦不住，因为组件确实渲染了「一个字符串」。只有把页面打开、拿渲染
 * 出来的文字跟文案表的键去比，才能看见。
 *
 * 判据：某个文本节点的全部内容 **恰好等于** 一个 camelCase 文案键。
 * 只认 camelCase（含至少一个大写字母）是为了不误伤真实数据 —— ES 字段名
 * `message`、`status` 这种纯小写词在字段字典和表格里是正当内容。
 *
 * 照 08 的规矩：先自检，造一个已知的坏例子，抓不到就整组不算数。
 */

const LOCALES = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'locales')

/** 文案表里的键：`    tabDocs: '...'` 这样的四格缩进赋值行。 */
function localeKeys(): string[] {
  const keys = new Set<string>()
  for (const f of readdirSync(LOCALES)) {
    if (!f.endsWith('.ts') || f.endsWith('.test.ts')) continue
    const src = readFileSync(join(LOCALES, f), 'utf8')
    for (const m of src.matchAll(/^ {4}([a-z][A-Za-z0-9]*):/gm)) {
      const k = m[1]
      if (/[A-Z]/.test(k)) keys.add(k)   // 纯小写的词可能是真实数据，不认
    }
  }
  return [...keys]
}

const KEYS = localeKeys()

const PROBE = `((keys) => {
  const set = new Set(keys)
  const out = []
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = (n.textContent || '').trim()
    if (!set.has(text)) continue
    const el = n.parentElement
    if (!el) continue
    const style = getComputedStyle(el)
    if (style.display === 'none' || style.visibility === 'hidden') continue
    const cls = (typeof el.className === 'string' ? el.className : '') || ''
    out.push({ key: text, el: el.tagName.toLowerCase() + '.' + cls.trim().split(/\\s+/).slice(0, 3).join('.') })
  }
  return out
})`

async function probe(page: import('@playwright/test').Page) {
  return page.evaluate(`(${PROBE})(${JSON.stringify(KEYS)})`)
}

test.describe('⑩ 文案键漏到界面上', () => {
  test('探针自检 —— 键的数量和一个人造的坏例子', async ({ page }) => {
    expect(KEYS.length, '一个键都没扫到 = 正则跟文案表对不上了').toBeGreaterThan(200)
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await page.evaluate((key) => {
      const bad = document.createElement('span')
      bad.id = 'probe-bad-key'
      bad.textContent = key
      document.body.appendChild(bad)
    }, KEYS[0])
    const found = (await probe(page)) as Array<{ key: string }>
    expect(found.length, '探针自己抓不到已知的坏例子 —— 后面的"没报"都不算数').toBeGreaterThan(0)
  })

  // 与 08 一样：ROUTES 只有 11 条，把其余路由补齐。
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
    test(`${r.name} — 页面上没有文案键`, async ({ page }) => {
      await page.goto(r.path, { waitUntil: 'domcontentloaded' })
      await page.locator('h1').first().waitFor({ timeout: 15_000 })
      await page.waitForTimeout(600)
      const found = await probe(page)
      expect(JSON.stringify(found, null, 1)).toBe('[]')
    })
  }

  test('处置手册的页签 —— 键原样渲染就是在这儿发现的', async ({ page }) => {
    await page.goto('/v2/knowledge-base', { waitUntil: 'domcontentloaded' })
    await page.locator('h1').first().waitFor({ timeout: 15_000 })
    await page.waitForTimeout(600)
    const found = await probe(page)
    expect(JSON.stringify(found, null, 1)).toBe('[]')
  })
})

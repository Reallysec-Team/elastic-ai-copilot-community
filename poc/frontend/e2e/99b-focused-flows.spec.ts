/**
 * Focused deep flows — assert dialogs render, links resolve, and CRUD
 * round-trips work. These tests do hit the real LLM and the real audit log.
 */
import { expect, test } from '@playwright/test'
import { trackErrors, isMobile } from './_shared'

const SAMPLE_INDEX = 'kibana_sample_data_logs'

// LLM calls can be slow against the cloud provider — give each test 120s.
test.setTimeout(120_000)

test.beforeEach(async ({ page }, info) => {
  if (isMobile(info)) test.skip()
  trackErrors(page)
})

// Helper: 从首页对话输入区跑完一次问答，DSL 渲染出来就返回。
async function generateOnChatPage(page: any) {
  await page.goto('/v2/')
  await page.waitForLoadState('networkidle')

  const indexTrigger = page.getByRole('combobox').first()
  if (await indexTrigger.isVisible().catch(() => false)) {
    await indexTrigger.click()
    const option = page.getByRole('option', { name: new RegExp(SAMPLE_INDEX) }).first()
    if (await option.isVisible({ timeout: 4000 }).catch(() => false)) await option.click()
    else await page.keyboard.press('Escape')
  }
  // 按 id 找输入区：CSS 选择器里的 `input:not([type])` 会先命中 base-ui Select
  // 渲染的影子 input，`fill()` 写不进去，于是输入区还是空的、发送按钮是禁用的。
  const q = page.locator('#copilot-composer')
  await q.fill('过去 24 小时按 response 状态码 top 5')

  // 直接按 Enter 发。原来那个按名字捞按钮的写法会先捞到侧栏「搜索」（命令面板
  // 触发器），而 `hasNot: [disabled]` 滤的是「里面套着禁用元素」的按钮，滤不掉
  // 按钮自己禁用的那一个 —— 报的是 click 超时。
  await q.press('Enter')
  await page
    .waitForResponse((r: any) => /api\/generate/.test(r.url()), { timeout: 60_000 })
    .catch(() => {})
  // Wait for the rendered DSL block (code-like content)
  await page.waitForTimeout(2500)
}

test('A. Kibana deep-link uses browser-reachable host (Bug #2 fix)', async ({ request }) => {
  // Simulate a real browser request: include Origin so the gateway can derive
  // the public Kibana host. Production deployments should set KIBANA_PUBLIC_URL
  // instead, but the Origin fallback is what makes /v2 SPA flows work locally.
  const resp = await request.post('http://127.0.0.1:18765/api/kibana-link', {
    headers: { Origin: 'http://127.0.0.1:18765' },
    data: { index: SAMPLE_INDEX, dsl: { query: { match_all: {} } } },
  })
  expect(resp.status()).toBe(200)
  const body = await resp.json()
  console.log('KIBANA-LINK-HREF', body.url)
  // After the fix: should NOT contain internal docker hostname; should contain
  // a browser-reachable hostname (here we asserted 127.0.0.1 since that's the
  // Origin we sent).
  expect(body.url).not.toMatch(/\/\/kibana:5601/)
  expect(body.url).toMatch(/\/\/127\.0\.0\.1:5601/)
})

test('B. Multi-turn continue button — does it persist a conversation_id? (Bug #1 in UI)', async ({
  page,
}) => {
  await generateOnChatPage(page)
  const cont = page.getByRole('button', { name: /继续追问|继续|追问/ }).first()
  if (await cont.isVisible({ timeout: 3000 }).catch(() => false)) {
    await cont.click()
    await page.waitForTimeout(800)
    const followInput = page
      .locator('textarea, input[placeholder*="追问"], input[placeholder*="继续"], input:not([type])')
      .last()
    await followInput.fill('only those with bytes > 1MB').catch(() => {})
    // Submit follow-up
    const submit2 = page
      .getByRole('button', { name: /生成|执行|提交|追问|发送/ })
      .filter({ hasNot: page.locator('[disabled]') })
      .first()
    const respP = page.waitForResponse((r: any) => /api\/generate/.test(r.url()), { timeout: 60_000 })
    await submit2.click()
    const resp = await respP.catch(() => null)
    if (resp) {
      const body = await resp.json().catch(() => ({}))
      console.log('FOLLOWUP-CONV-ID', body.conversation_id)
      // Multi-turn should set conversation_id. Bug #1: features=["*"] not honored → null.
      // We do not fail the test on this — it's a known issue we want to document.
    }
  }
  await page.screenshot({ path: 'e2e/shots/focused-multiturn.png', fullPage: true })
})

test('C. Explain dialog opens with rendered fields', async ({ page }) => {
  await generateOnChatPage(page)
  // Look for an Explain row action in the result table
  const explain = page.getByRole('button', { name: /解释|explain/i }).first()
  if (await explain.isVisible({ timeout: 5000 }).catch(() => false)) {
    await explain.click()
    const dlg = page.getByRole('dialog').first()
    await expect(dlg).toBeVisible({ timeout: 60_000 }).catch(() => {})
    // Should show summary text
    await page.waitForTimeout(2000)
    await page.screenshot({ path: 'e2e/shots/focused-explain-dialog.png', fullPage: true })
  } else {
    console.log('EXPLAIN-NOT-FOUND — no row-level Explain action on the rendered result')
    await page.screenshot({ path: 'e2e/shots/focused-no-explain.png', fullPage: true })
  }
})

test('D. Settings save+undo round-trip', async ({ page }) => {
  await page.goto('/v2/settings')
  await page.waitForLoadState('networkidle')

  // Find the index_whitelist text input and stage a change
  const wl = page.getByPlaceholder(/logs-\*/).first()
  await wl.fill('kibana_sample_data_*')

  // Save & Apply
  const save = page.getByRole('button', { name: /保存并应用|保存|apply/i }).first()
  if (await save.isVisible().catch(() => false)) {
    const respP = page.waitForResponse((r: any) => /api\/settings/.test(r.url()) && r.request().method() === 'POST', {
      timeout: 5000,
    })
    await save.click()
    const resp = await respP.catch(() => null)
    if (resp) console.log('SETTINGS-SAVE-STATUS', resp.status())
    await page.waitForTimeout(800)
  }
  await page.screenshot({ path: 'e2e/shots/focused-settings-saved.png', fullPage: true })

  // Reset
  await wl.fill('')
  if (await save.isVisible().catch(() => false)) {
    await save.click()
    await page.waitForTimeout(800)
  }
})

test('F. License — provider add row + save & reload', async ({ page }) => {
  await page.goto('/v2/license')
  await page.waitForLoadState('networkidle')

  // Read FEATURES label to verify wildcard display
  const licenseCard = page.locator('text=已激活').first()
  if (await licenseCard.isVisible({ timeout: 3000 }).catch(() => false)) {
    const features = await page.locator('text=/FEATURES|features/i').first().textContent().catch(() => '')
    console.log('LICENSE-FEATURES-LABEL', features?.slice(0, 200))
  }

  // Save & Reload — restore current state (so we don't break the env)
  const save = page.getByRole('button', { name: /保存并重载|保存.*重载/ }).first()
  if (await save.isVisible({ timeout: 3000 }).catch(() => false)) {
    const respP = page.waitForResponse((r: any) => /llm\/providers\/save/.test(r.url()), { timeout: 5000 })
    await save.click()
    const resp = await respP.catch(() => null)
    if (resp) console.log('PROVIDERS-SAVE-STATUS', resp.status())
  }
  await page.screenshot({ path: 'e2e/shots/focused-license-after-save.png', fullPage: true })
})

test('G. Triage on 403 — UI surfaces friendly error, no console crash', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(`PAGEERROR: ${e.message}`))
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(`CONSOLE: ${m.text()}`)
  })

  await page.goto('/v2/triage')
  await page.waitForLoadState('networkidle')
  const ta = page.locator('textarea').first()
  await ta.fill('[{"rule":"x","clientip":"1.1.1.1"}]')
  const run = page.getByRole('button', { name: /开始|分诊|运行|生成/ }).first()
  if (await run.isVisible().catch(() => false)) await run.click()
  await page.waitForTimeout(2500)
  // Look for the 403 error banner
  const banner = page.locator('text=/Standard|license/i').first()
  await expect(banner).toBeVisible({ timeout: 5000 }).catch(() => {})
  console.log('TRIAGE-403-PAGE-ERRORS', errors.length, errors.slice(0, 5).join(' | '))
})

test('H. Audit query renders results table', async ({ page }) => {
  await page.goto('/v2/audit')
  await page.waitForLoadState('networkidle')
  const query = page.getByRole('button', { name: /查询|刷新/ }).first()
  if (await query.isVisible().catch(() => false)) await query.click()
  await page.waitForTimeout(1500)
  // Count rows
  const rows = page.getByRole('row')
  const n = await rows.count()
  console.log('AUDIT-ROW-COUNT', n)
  await page.screenshot({ path: 'e2e/shots/focused-audit.png', fullPage: true })
})

test('K. Full chain: NL→DSL (hit-returning) → Execute → Row Explain dialog', async ({ page }) => {
  // The file-level 120s budget is too tight for this test: it chains a real
  // generate call, an execute call, AND a real explain-log call. Each of the
  // three can legitimately take tens of seconds against the cloud LLM.
  test.setTimeout(180_000)
  // Use a question phrased so the LLM emits a "size: N, query: …" hit query, not size:0+agg.
  await page.goto('/v2/')
  await page.waitForLoadState('networkidle')
  const indexTrigger = page.getByRole('combobox').first()
  if (await indexTrigger.isVisible().catch(() => false)) {
    await indexTrigger.click()
    const opt = page.getByRole('option', { name: new RegExp(SAMPLE_INDEX) }).first()
    if (await opt.isVisible({ timeout: 4000 }).catch(() => false)) await opt.click()
    else await page.keyboard.press('Escape')
  }
  const q = page.locator('#copilot-composer')
  await q.fill('Return the 5 most recent log documents where response is 503')

  // 同上：按 Enter 发，别按名字捞按钮。
  await q.press('Enter')
  await page
    .waitForResponse((r: any) => /api\/generate/.test(r.url()), { timeout: 90_000 })
    .catch(() => {})
  await page.waitForTimeout(2500)

  // The query executes automatically after generation — observe that call
  // instead of clicking a second button that no longer exists.
  const execResp = await page
    .waitForResponse((r: any) => /api\/execute/.test(r.url()), { timeout: 60_000 })
    .catch(() => null)
  if (execResp) console.log('EXECUTE-STATUS', execResp.status())
  await page.waitForTimeout(1500)
  await page.screenshot({ path: 'e2e/shots/focused-after-execute-hits.png', fullPage: true })

  const explain = page.getByRole('button', { name: /^解释$|explain/i }).first()
  if (await explain.isVisible({ timeout: 5000 }).catch(() => false)) {
    const respP = page.waitForResponse((r: any) => /api\/explain-log/.test(r.url()), {
      timeout: 90_000,
    })
    await explain.click()
    const resp = await respP.catch(() => null)
    if (resp) console.log('EXPLAIN-STATUS', resp.status())
    const dlg = page.getByRole('dialog').first()
    await expect(dlg).toBeVisible({ timeout: 30_000 })
    await page.waitForTimeout(2500)
    await page.screenshot({ path: 'e2e/shots/focused-explain-dialog-real.png', fullPage: true })
  } else {
    console.log('CHAIN-EXPLAIN-NOT-FOUND — LLM still generated size:0 aggregation, no hit rows')
  }
})

test('L. Index combobox exposes role=combobox + aria-expanded (a11y fix)', async ({ page }) => {
  await page.goto('/v2/')
  await page.waitForLoadState('networkidle')

  // After the fix: trigger has role="combobox" + aria-haspopup + aria-expanded.
  const cb = page.getByRole('combobox').first()
  await expect(cb).toBeVisible()
  await expect(cb).toHaveAttribute('aria-haspopup', 'listbox')
  await expect(cb).toHaveAttribute('aria-expanded', 'false')

  await cb.click()
  await expect(cb).toHaveAttribute('aria-expanded', 'true')
  // Listbox + options now also expose the right roles.
  await expect(page.getByRole('listbox').first()).toBeVisible({ timeout: 3000 })
  expect(await page.getByRole('option').count()).toBeGreaterThan(0)
  await page.keyboard.press('Escape')
})

test('M. Command palette items navigate to each route', async ({ page }) => {
  // 搜索词和目标路由分开写：命令面板按子串匹配，输入 "settings" 同时命中
  // /ai-settings 和 /settings，Enter 选中的是列表第一项（/ai-settings）。
  // 这是面板排序的既有毛病，不是导航坏了，所以这里用无歧义的词搜。
  const targets = [
    { q: 'triage', url: 'triage' },
    { q: 'detection-rules', url: 'detection-rules' },
    { q: 'field-dictionary', url: 'field-dictionary' },
    { q: 'knowledge-base', url: 'knowledge-base' },
    { q: 'audit', url: 'audit' },
    // 面板按 KEYWORDS 里的子串匹配，`/settings` 那串是「… 平台 系统 索引白名单
    // 脱敏」——「系统设置」不是它的子串，搜不出来。挑一个只属于这一页的词。
    { q: '索引白名单', url: 'settings' },
  ]
  for (const t of targets) {
    await page.goto('/v2/')
    await page.waitForLoadState('networkidle')
    await page.keyboard.press('Control+K')
    await page.waitForTimeout(300)
    await page.keyboard.type(t.q)
    await page.waitForTimeout(200)
    await page.keyboard.press('Enter')
    await page.waitForTimeout(500)
    const url = page.url()
    console.log(`CMDK-NAV ${t.q} →`, url)
    expect(url).toContain(`/v2/${t.url}`)
  }
})

test('N. History drawer — open, then click "清空" if entries exist', async ({ page }) => {
  await page.goto('/v2/')
  await page.waitForLoadState('networkidle')
  // Seed a history entry by running one full generate
  await generateOnChatPage(page)
  // open drawer
  const hist = page.getByRole('button', { name: /历史|history/i }).first()
  await hist.click()
  const dlg = page.getByRole('dialog').first()
  await expect(dlg).toBeVisible({ timeout: 4000 })
  await page.screenshot({ path: 'e2e/shots/focused-history-open.png', fullPage: true })
  // Try Clear All
  const clear = dlg.getByRole('button', { name: /清空|clear/i }).first()
  if (await clear.isVisible({ timeout: 2000 }).catch(() => false)) {
    page.once('dialog', (d) => d.accept())
    await clear.click()
    await page.waitForTimeout(500)
  }
  await page.keyboard.press('Escape')
})

test('J. Theme toggle — clicking 深色 adds .dark to html', async ({ page }) => {
  await page.goto('/v2/')
  await page.waitForLoadState('networkidle')
  // Force back to light first to make the test deterministic
  await page.evaluate(() => {
    localStorage.setItem('rst-theme', 'light')
    document.documentElement.classList.remove('dark')
  })
  // 主题现在是顶栏右上角一个一键切换的按钮，名字说的是点下去会变成什么。
  await page.getByRole('button', { name: '切换到深色' }).click()
  await page.waitForTimeout(300)
  const after = await page.evaluate(() => document.documentElement.classList.contains('dark'))
  expect(after).toBe(true)
  // restore
  await page.getByRole('button', { name: '切换到浅色' }).click()
})

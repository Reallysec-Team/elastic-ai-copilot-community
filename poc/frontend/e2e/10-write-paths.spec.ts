import { test, expect, type Page } from '@playwright/test'
import { isMobile, trackErrors } from './_shared'

/*
 * ⑩ 写路径实跑 —— roster §7.1 一直欠着的那些：之前这些页的上传 / 保存 / 测试连接 /
 * 删除都只用 page.route() 假响应验过。这里**不 mock**，真写网关、真写 ES，所以：
 *
 *   - 只在 RST_E2E_WRITE=1 时跑（默认 skip），别混进日常那组。
 *   - 每条用例自己收尾：建了就删、改了就改回。
 *   - 串行（serial）：设置页的白名单一保存，整个网关的可查索引就变了。
 *
 * 跑：RST_E2E_WRITE=1 RST_E2E_PASSWORD='…' npx playwright test e2e/10-write-paths.spec.ts --project=desktop
 *
 * 没覆盖：产品激活（要一张真 license）、基线巡检（没有 osquery 采集结果）。
 */
test.describe.configure({ mode: 'serial' })
test.describe('⑩ 写路径实跑（真后端）', () => {
  test.beforeEach(({}, info) => {
    test.skip(isMobile(info), '仅桌面端')
    test.skip(!process.env.RST_E2E_WRITE, '真写后端，RST_E2E_WRITE=1 才跑')
  })

  async function serverPrefs(page: Page) {
    return (await (await page.request.get('/api/state/pref/ui')).json()).value as Record<string, any>
  }

  /** 「全部重置」只在有列集时出现：先往本机缓存塞一份（模拟在结果表里挑过列）。 */
  async function seedColumns(page: Page) {
    await page.evaluate(() => {
      const p = JSON.parse(localStorage.getItem('rst.uiPrefs') || '{}')
      p.columns = { 'logs-test': ['a', 'b'] }
      p.columnsUpdatedAt = { 'logs-test': Date.now() }
      localStorage.setItem('rst.uiPrefs', JSON.stringify(p))
    })
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByText('1 个索引')).toBeVisible()
  }

  test('偏好设置：每页行数 / 主题落到服务端，__reset__ 墓碑不被后端拒掉', async ({ page }) => {
    const errs = trackErrors(page)
    const before = await serverPrefs(page)
    await page.goto('/v2/preferences', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()

    // 每页行数 → 50
    await page.getByRole('combobox', { name: '每页行数' }).click()
    await page.getByRole('option', { name: '50' }).click()
    await expect.poll(async () => (await serverPrefs(page)).pageSize).toBe(50)

    // 主题 → 深色 → 恢复
    // ToggleGroup 的项是 button[aria-pressed]，不是 radio。
    const theme = page.getByRole('group', { name: '主题' })
    await theme.getByRole('button', { name: '深色' }).click()
    await expect(page.locator('html')).toHaveClass(/dark/)
    await theme.getByRole('button', { name: '浅色' }).click()
    await expect(page.locator('html')).not.toHaveClass(/dark/)

    // 重置列集：写 __reset__ 墓碑。后端 value_json 是不透明串，不该 4xx。
    await seedColumns(page)
    const put = page.waitForResponse(
      (r) => /\/api\/state\/pref\/ui/.test(r.url()) && r.request().method() === 'PUT',
    )
    await page.getByRole('button', { name: '全部重置' }).click()
    expect((await put).status()).toBe(200)
    await expect(page.getByText('列集已重置')).toBeVisible()
    const after = await serverPrefs(page)
    expect(after.columnsUpdatedAt.__reset__).toBeGreaterThan(0)
    expect(after.columns).toEqual({})

    // 恢复每页行数
    await page.getByRole('combobox', { name: '每页行数' }).click()
    await page.getByRole('option', { name: String(before.pageSize ?? 25), exact: true }).click()
    await expect.poll(async () => (await serverPrefs(page)).pageSize).toBe(before.pageSize ?? 25)
    expect(errs.pageErrors).toHaveLength(0)
  })

  test('偏好设置：两台设备 —— B 重置后 A 刷新，A 本机缓存的列集被墓碑压掉', async ({ browser, page }) => {
    // 设备 A：带一份比服务端新的本机列集（模拟离线改过、还没同步）。
    const a = await browser.newContext({ storageState: 'e2e/.auth/state.json' })
    const pa = await a.newPage()
    await pa.goto('/v2/preferences', { waitUntil: 'domcontentloaded' })
    await expect(pa.locator('h1').first()).toBeVisible()
    await seedColumns(pa)

    // 设备 B：也有一份（更旧的）列集，重置。
    await page.goto('/v2/preferences', { waitUntil: 'domcontentloaded' })
    await seedColumns(page)
    await page.getByRole('button', { name: '全部重置' }).click()
    await expect(page.getByText('列集已重置')).toBeVisible()
    await expect
      .poll(async () => (await serverPrefs(page)).columnsUpdatedAt.__reset__ ?? 0)
      .toBeGreaterThan(0)

    // 设备 A 刷新：syncPrefsFromServer 合并，墓碑比 A 的列集新 → A 的列集没了。
    await pa.reload({ waitUntil: 'domcontentloaded' })
    await expect(pa.getByText('还没有', { exact: true })).toBeVisible()
    const local = await pa.evaluate(() => JSON.parse(localStorage.getItem('rst.uiPrefs') || '{}'))
    expect(local.columns).toEqual({})
    // A 再写一次任意偏好：推回服务端的那份必须还带着墓碑，否则第三台设备上更老的
    // 列集下次同步又会活过来（实跑时抓到的：mergeColumns 原来把 __reset__ 丢了）。
    const beforeTomb = (await serverPrefs(page)).columnsUpdatedAt.__reset__
    await pa.getByRole('combobox', { name: '每页行数' }).click()
    await pa.getByRole('option', { name: '100' }).click()
    await expect.poll(async () => (await serverPrefs(page)).pageSize).toBe(100)
    expect((await serverPrefs(page)).columnsUpdatedAt.__reset__).toBe(beforeTomb)
    await pa.getByRole('combobox', { name: '每页行数' }).click()
    await pa.getByRole('option', { name: '25', exact: true }).click()
    await expect.poll(async () => (await serverPrefs(page)).pageSize).toBe(25)
    await a.close()
  })

  test('个人资料：换头像 → 落服务端 → 移除', async ({ page }) => {
    await page.goto('/v2/profile', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()
    // 1×1 PNG
    const png = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
      'base64',
    )
    await page
      .getByLabel('头像', { exact: true })
      .setInputFiles({ name: 'a.png', mimeType: 'image/png', buffer: png })
    await expect(page.getByRole('button', { name: '移除' })).toBeVisible()
    await expect.poll(async () => String((await serverPrefs(page)).avatar ?? '')).toMatch(/^data:image\//)
    await page.getByRole('button', { name: '移除' }).click()
    await expect(page.getByRole('button', { name: '移除' })).toHaveCount(0)
    await expect.poll(async () => (await serverPrefs(page)).avatar ?? null).toBeNull()
  })

  test('个人资料：改密码（用 auditor 账号，改完改回）', async ({ browser }) => {
    const user = process.env.RST_E2E_WRITE_USER || 'auditor'
    const pw = process.env.RST_E2E_WRITE_USER_PASSWORD || 'Viewer@12345'
    const tmp = pw + 'x1'
    const ctx = await browser.newContext({ storageState: undefined })
    const login = (p: string) =>
      ctx.request.post('/api/auth/login', { data: { username: user, password: p } })
    expect((await login(pw)).ok(), `${user} 登录失败 —— 审计时建的 viewer 账号不在了？`).toBeTruthy()
    const page = await ctx.newPage()
    try {
      await page.goto('/v2/profile', { waitUntil: 'domcontentloaded' })
      await page.locator('#cur-pw').fill(pw)
      await page.locator('#new-pw').fill(tmp)
      await page.locator('#new-pw2').fill(tmp)
      await page.getByRole('button', { name: '修改密码' }).click()
      await expect(page.getByText(/密码已修改/)).toBeVisible()
      // 新密码能登、旧密码不能。
      expect((await login(pw)).status()).toBe(401)
      expect((await login(tmp)).ok()).toBeTruthy()
    } finally {
      // 不管上面死在哪一步，都把密码改回去（两种密码都试）。
      for (const cur of [tmp, pw]) {
        const c2 = await browser.newContext({ storageState: undefined })
        const ok = (await c2.request.post('/api/auth/login', { data: { username: user, password: cur } })).ok()
        if (ok && cur !== pw) {
          const r = await c2.request.post('/api/auth/password', {
            data: { current_password: cur, new_password: pw },
            headers: { Origin: 'http://127.0.0.1:18765' },
          })
          expect(r.ok()).toBeTruthy()
        }
        await c2.close()
        if (ok) break
      }
      await ctx.close()
    }
  })

  test('对外通道：新增飞书目标（内网 URL 被白名单拒 → 假 token）→ 测试发送走错误路径 → AlertDialog 删除', async ({ page }) => {
    const name = `e2e-写路径-${Date.now()}`
    await page.goto('/v2/notify', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()
    await page.getByRole('button', { name: '新增目标' }).click()
    const dlg = page.getByRole('dialog')
    await dlg.getByRole('group', { name: '投递渠道' }).getByRole('button', { name: '飞书' }).click()
    await dlg.getByPlaceholder('SOC 值班群').fill(name)
    // 先喂一个内网地址：后端的 SSRF 白名单该 400，错误落在对话框里。
    await dlg.getByPlaceholder(/open\.feishu\.cn/).fill('https://127.0.0.1:9/open-apis/bot/v2/hook/e2e')
    await dlg.getByRole('button', { name: '保存' }).click()
    await expect(dlg.getByText(/主机不在白名单/)).toBeVisible()
    // 再换白名单内、但 token 是假的：保存成功，测试发送走飞书的错误返回。
    await dlg.getByPlaceholder(/open\.feishu\.cn/).fill('https://open.feishu.cn/open-apis/bot/v2/hook/e2e-invalid-token')
    const save = page.waitForResponse(
      (r) => /\/api\/notify\//.test(r.url()) && ['POST', 'PUT'].includes(r.request().method()),
    )
    await dlg.getByRole('button', { name: '保存' }).click()
    expect((await save).ok()).toBeTruthy()
    await expect(page.getByText(name)).toBeVisible()

    // 测试发送：连不上 127.0.0.1:9，应落到「测试失败：…」，不是崩。
    await page.getByRole('button', { name: `${name} 的操作` }).click()
    await page.getByRole('menuitem', { name: '测试发送' }).click()
    await expect(page.getByText(/测试失败：/)).toBeVisible({ timeout: 30_000 })

    // 删除：AlertDialog 确认。
    await page.getByRole('button', { name: `${name} 的操作` }).click()
    await page.getByRole('menuitem', { name: '删除' }).click()
    const adlg = page.getByRole('alertdialog')
    await expect(adlg.getByText(`删除「${name}」？`)).toBeVisible()
    await adlg.getByRole('button', { name: '删除' }).click()
    await expect(page.getByText(name)).toHaveCount(0)
    const cfg = await (await page.request.get('/api/notify/config')).json()
    expect(cfg.targets.some((t: any) => t.name === name)).toBe(false)
  })

  test('AI 配置：embedding 测试连接 → 保存；provider 保存并重载', async ({ page }) => {
    await page.goto('/v2/ai-settings', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()
    const before = await (await page.request.get('/api/embedding/config')).json()
    test.skip(!before.model, '本机没配 embedding')

    await page.getByRole('button', { name: '测试连接' }).click()
    await expect(page.getByText(new RegExp(`维度.*${before.dims}`))).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: '保存', exact: true }).click()
    await expect(page.getByText(new RegExp(`已保存.*${before.dims}`))).toBeVisible()
    const after = await (await page.request.get('/api/embedding/config')).json()
    expect(after.dims).toBe(before.dims)
    expect(after.api_key_set).toBe(before.api_key_set) // 空 api_key 不覆盖已存的

    const prov = await (await page.request.get('/api/llm/providers')).json()
    await page.getByRole('button', { name: '保存并重载' }).click()
    await expect(page.getByText('已保存并重载')).toBeVisible({ timeout: 30_000 })
    const prov2 = await (await page.request.get('/api/llm/providers')).json()
    expect(prov2.providers.map((p: any) => p.id)).toEqual(prov.providers.map((p: any) => p.id))
  })

  test('系统设置：ES 测试连接 → 白名单 / 脱敏模式保存并应用 → 改回', async ({ page }) => {
    const get = async () => (await (await page.request.get('/api/settings')).json()).settings
    const before = await get()
    await page.goto('/v2/settings', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()

    await page.getByRole('button', { name: '测试连接' }).click()
    await expect(page.getByText('已连接')).toBeVisible({ timeout: 30_000 })

    await page.locator('#index-whitelist').fill('logs-*,kibana_sample_data_logs')
    const masking = page.getByRole('group', { name: '字段脱敏模式' })
    const target = before.masking_mode === 'private' ? 'cloud' : 'private'
    await masking.getByRole('button', { name: new RegExp(target, 'i') }).click()
    await expect(page.getByText('有未保存的更改')).toBeVisible()
    await page.getByRole('button', { name: '保存并应用' }).click()
    await expect(page.getByText(/已保存/)).toBeVisible({ timeout: 30_000 })
    const mid = await get()
    expect(mid.index_whitelist).toBe('logs-*,kibana_sample_data_logs')
    expect(mid.masking_mode).toBe(target)
    expect((await (await page.request.get('/api/masking/info')).json()).current_mode).toBe(target)

    // 改回
    await page.locator('#index-whitelist').fill(before.index_whitelist)
    if (before.masking_mode) {
      await masking.getByRole('button', { name: new RegExp(before.masking_mode, 'i') }).click()
    } else {
      // 原来是空（跟随环境变量）：再点一次当前选中项把它取消。
      await masking.getByRole('button', { name: new RegExp(target, 'i') }).click()
    }
    await page.getByRole('button', { name: '保存并应用' }).click()
    await expect(page.getByText(/已保存/)).toBeVisible({ timeout: 30_000 })
    const after = await get()
    expect(after.index_whitelist).toBe(before.index_whitelist)
    expect(after.masking_mode).toBe(before.masking_mode)
  })

  test('知识库：上传 → embedding → 检索命中 → 删除', async ({ page }) => {
    const emb = await (await page.request.get('/api/embedding/config')).json()
    test.skip(emb.status !== 'enabled', '本机 embedding 没启用')
    const title = `e2e 勒索软件应急手册 ${Date.now()}`
    await page.goto('/v2/knowledge-base', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()
    await page.getByRole('button', { name: /上传/ }).first().click()
    await page.locator('#kb-title').fill(title)
    await page.getByPlaceholder(/粘贴 Markdown/).fill(
      '# 勒索软件应急手册\n\n发现加密勒索后第一步：断开受感染主机网络，保留内存镜像。\n\n' +
        '第二步：通过 EDR 查找同一哈希的横向传播痕迹，冻结相关账号。\n\n第三步：从离线备份恢复，恢复前核对备份完整性。\n',
    )
    await page.getByRole('button', { name: '提交并 embedding' }).click()
    await expect(page.getByText(/已上传 · \d+ 个片段/)).toBeVisible({ timeout: 120_000 })
    await expect(page.getByText(title)).toBeVisible({ timeout: 15_000 })

    // 检索
    await page.getByRole('tab', { name: '检索测试' }).click()
    await page.getByLabel('检索问题').fill('勒索软件第一步该做什么')
    await page.getByRole('button', { name: '检索', exact: true }).click()
    await expect(page.getByText(/断开受感染主机网络/).first()).toBeVisible({ timeout: 60_000 })

    // 删除（window.confirm）
    await page.getByRole('tab', { name: '文档库' }).click()
    page.once('dialog', (d) => void d.accept())
    await page.getByRole('button', { name: `删除 ${title}` }).click()
    await expect(page.getByText(`已删除「${title}」`)).toBeVisible()
    await expect
      .poll(async () => {
        const docs = await (await page.request.get('/api/kb/documents')).json()
        return docs.some((d: any) => d.title === title)
      })
      .toBe(false)
  })
})

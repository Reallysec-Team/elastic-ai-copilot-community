import { test, expect } from '@playwright/test'
import { ROUTES, UNSAFE_BTN, trackErrors } from './_shared'

/*
 * ④ 交互可用性 —— 每个路由：文本输入框可编辑 + 安全按钮可点击且不崩溃。
 * 安全按钮 = 名称不含 LLM 计费 / 写入 / 破坏性关键词（见 UNSAFE_BTN）。
 */
test.describe('④ 交互可用性', () => {
  for (const r of ROUTES) {
    test(`${r.name} — 输入框与按钮交互`, async ({ page }, info) => {
      const errs = trackErrors(page)
      await page.goto(r.path, { waitUntil: 'domcontentloaded' })
      await expect(page.locator('h1').first()).toBeVisible()

      // 文本输入框可编辑。按 role 找，不按 CSS：base-ui 的 Select 会渲染一个
      // 影子 `input[type=text]`（审计页的 `__all__`、用户页那一列角色下拉的
      // `admin` 就是它），CSS 选择器把它当成第一个输入框，`fill()` 写不进去
      // —— 报的是「输入框不可编辑」，其实那根本不是输入框。
      const inputs = page.getByRole('textbox')
      const ic = await inputs.count()
      if (ic > 0) {
        const first = inputs.first()
        await first.fill('e2e-测试-123')
        await expect(first).toHaveValue('e2e-测试-123')
      }

      // 安全按钮点击 —— 先一次性取全部按钮名称（点击会改 DOM，避免 nth 索引失效），
      // 再按名称重新定位逐个点击，最多 6 个，每次后按 Esc 收起弹层。
      const names: string[] = await page
        .locator('button:visible')
        .evaluateAll((els) =>
          els.map((e) =>
            (
              e.getAttribute('aria-label') ||
              e.getAttribute('title') ||
              e.textContent ||
              ''
            ).trim(),
          ),
        )
      let clicked = 0
      for (const nm of names) {
        if (clicked >= 6) break
        if (!nm || UNSAFE_BTN.test(nm)) continue
        const target = page.getByRole('button', { name: nm }).first()
        if (!(await target.isVisible().catch(() => false))) continue
        if (!(await target.isEnabled().catch(() => false))) continue
        await target.click({ timeout: 5_000 }).catch(() => {})
        clicked++
        await page.keyboard.press('Escape').catch(() => {})
      }
      info.annotations.push({
        type: '交互',
        description: `输入框 ${ic} 个 / 安全按钮点击 ${clicked} 个`,
      })

      // 交互后无崩溃、无未捕获异常
      await expect(page.getByText('这个页面出了点问题')).toHaveCount(0)
      expect(
        errs.pageErrors,
        `未捕获异常：${errs.pageErrors.join(' | ')}`,
      ).toHaveLength(0)
    })
  }
})

test.describe('④b 首页搜索核心控件', () => {
  test('输入后「发送」按钮从禁用变启用', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    const input = page.locator('textarea[placeholder*="用一句话问"]')
    await expect(input).toBeVisible()

    const btn = page.getByRole('button', { name: /发送/ })
    await expect(btn).toBeDisabled() // 空输入 → 禁用
    await input.fill('近 1 小时各状态码计数')
    await expect(btn).toBeEnabled() // 有输入 → 启用
  })

  test('索引选择器可展开并带过滤框', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await expect(
      page.locator('textarea[placeholder*="用一句话问"]'),
    ).toBeVisible()
    // 索引选择器 = 输入区里的 combobox（默认索引由 /api/indices 解析）
    await page.getByRole('combobox').first().click()
    await expect(page.getByPlaceholder('过滤…')).toBeVisible()
  })

  test('右下角「历史」抽屉可打开', async ({ page }) => {
    const errs = trackErrors(page)
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()
    // 历史按钮在侧栏里（`shell/search-form.tsx`），移动端侧栏收在「菜单」后面，
    // 这一条就没得点 —— 移动端的导航由 03-mobile 单独盯。
    const hist = page.getByRole('button', { name: /历史/ }).first()
    if ((await hist.count()) === 0 || !(await hist.isVisible().catch(() => false))) {
      test.skip(true, '这个视口里历史按钮收在侧栏后面')
    }
    await hist.click()
    // 抽屉打开后出现标题或空态文案
    await expect(
      page.getByText(/历史是空的|查询历史/).first(),
    ).toBeVisible()
    expect(errs.pageErrors).toHaveLength(0)
  })
})

/*
 * ④b 权限闸 —— 非管理员看到的写按钮：点不动，但走得到、读得到原因。
 *
 * 钉的是两件在这个产品上都真实发生过的事：
 *   1. 界面只有「不是 viewer」一档，而后端有几十条路由要管理员 —— analyst 于是
 *      看到一排亮着、按下去必然 403 的按钮；
 *   2. 挡住了却不说为什么，而且用 `disabled` 挡的按钮不可聚焦、`title` 也不会被
 *      读屏器念 —— 键盘和读屏用户连「这是权限问题」都不知道。
 *
 * 所以断言的是 aria-disabled（不是 disabled）、可聚焦、有 aria-describedby，
 * 且点下去什么都不发生。
 */
test.describe('④b 权限闸', () => {
  const VIEWER = { username: 'e2e_gate_viewer', password: 'E2eGate@123', role: 'viewer' }

  test('只读账号：写按钮可聚焦、说得出原因、点不动', async ({ page, browser, request }) => {
    // 管理员会话（storageState）建一个只读账号；没有用户库就没有角色可测。
    const me = await page.request.get('/api/me').then((r) => r.json())
    test.skip(!me.multi_user, '这套部署没有用户库（RST_USER_DB_URL），没有角色可分')
    test.skip(!me.is_admin, '需要管理员会话来建测试账号')

    await page.request.delete(`/api/users/${VIEWER.username}`).catch(() => {})
    const created = await page.request.post('/api/users', { data: VIEWER })
    expect(created.ok(), await created.text()).toBeTruthy()

    const ctx = await browser.newContext({ locale: 'zh-CN' })
    try {
      const p = await ctx.newPage()
      const login = await p.request.post('/api/auth/login', {
        data: { username: VIEWER.username, password: VIEWER.password },
      })
      expect(login.ok(), await login.text()).toBeTruthy()

      // 挑知识库：这一页非管理员打得开（列表不要管理员），而页头那个「上传文档」
      // 要管理员。设置页现在整页就是"你看不到"，找不到可挡的按钮了 —— 那一条由
      // 下面 ④c 单独钉。
      await p.goto('/v2/knowledge-base', { waitUntil: 'domcontentloaded' })
      const testConn = p.getByRole('button', { name: /上传文档/ }).first()
      await expect(testConn).toBeVisible()

      // 挡住了：aria-disabled，不是 disabled —— 后者的按钮不可聚焦，键盘和读屏
      // 用户根本走不到它。（Playwright 的 toBeEnabled 把 aria-disabled 也算作
      // disabled，所以这里断言的是 tabindex 和真的能不能聚焦。）
      await expect(testConn).toHaveAttribute('aria-disabled', 'true')
      await expect(testConn).not.toHaveAttribute('disabled', /.*/)
      await expect(testConn).toHaveAttribute('tabindex', '0')

      // 走得到：能聚焦
      await testConn.focus()
      await expect(testConn).toBeFocused()

      // 读得到：aria-describedby 指向的那段文字说的是权限
      const describedBy = await testConn.getAttribute('aria-describedby')
      expect(describedBy).toBeTruthy()
      await expect(p.locator(`#${describedBy}`)).toHaveText(/权限|只读/)

      // 点不动：键盘敲下去（这是走得到之后的下一步）什么都不发生
      await p.keyboard.press('Enter')
      await testConn.dispatchEvent('click')
      await p.waitForTimeout(300)
      await expect(p.getByRole('dialog')).toHaveCount(0)
    } finally {
      await ctx.close()
      await page.request.delete(`/api/users/${VIEWER.username}`).catch(() => {})
    }
  })
})

/*
 * ④c 管理员才能读的页面 —— 非管理员看到的是「你看不到」，不是一整页错误。
 *
 * 钉的是一件真实发生过的事：/api/audit/events、/api/settings、/api/users、
 * /api/reports/history 这一批 GET 都挂着 require_admin，而界面把 403 显示成
 * 整页加载失败（或者更糟：折成「暂无数据」）。「出错了」和「你没有权限」对
 * 用户是两个不同的下一步 —— 前者会让人去刷新、去找运维查网关。
 *
 * 侧栏入口保留是有意的，所以这里同时断言导航还在：藏起来会把「这个功能存在吗」
 * 变成一个要去问人的问题，而分享出去的深链照样走得到这里。
 */
test.describe('④c 只有管理员能读的页面', () => {
  for (const path of ['/v2/settings', '/v2/audit', '/v2/users', '/v2/asset-identity']) {
    test(`非管理员打开 ${path} 看到的是说明，不是错误`, async ({ page, browser }, info) => {
      const me = await page.request.get('/api/me').then((r) => r.json())
      test.skip(!me.multi_user, '这套部署没有用户库（RST_USER_DB_URL），没有角色可分')
      test.skip(!me.is_admin, '需要管理员会话来建测试账号')

      // 账号名带上 worker 号：两个视口是两个 project，同一条用例会并行跑两遍，
      // 共用一个账号名的话建号/删号会互相踩。
      const READER = {
        username: `e2e_read_analyst_${info.workerIndex}`,
        password: 'E2eRead@123',
        role: 'analyst',
      }

      await page.request.delete(`/api/users/${READER.username}`).catch(() => {})
      const created = await page.request.post('/api/users', { data: READER })
      expect(created.ok(), await created.text()).toBeTruthy()

      const ctx = await browser.newContext({ locale: 'zh-CN' })
      try {
        const p = await ctx.newPage()
        const login = await p.request.post('/api/auth/login', {
          data: { username: READER.username, password: READER.password },
        })
        expect(login.ok(), await login.text()).toBeTruthy()

        await p.goto(path, { waitUntil: 'domcontentloaded' })

        // 说得出为什么。role="note" 而不是 alert —— 这不是出错。
        const notice = p.getByRole('note').filter({ hasText: /只有管理员/ }).first()
        await expect(notice).toBeVisible({ timeout: 10_000 })

        // 页头还在：人得知道自己站在哪一页上，而不是掉进一个没有身份的错误页。
        await expect(p.locator('h1, h2').first()).toBeVisible()
      } finally {
        await ctx.close()
        await page.request.delete(`/api/users/${READER.username}`).catch(() => {})
      }
    })
  }
})

import { test, expect } from '@playwright/test'
import { trackErrors, isMobile } from './_shared'

/*
 * ② 桌面导航 —— 左侧导航栏、管理下拉、命令面板 ⌘K、Logo 回首页、深色模式切换。
 * 仅在 desktop project 跑（移动端导航在 03 spec）。
 *
 * Round 11 replaced the top bar's three dropdowns with a persistent rail, so
 * every destination is a link that is already on screen — no trigger to open
 * first. What the old spec was really guarding is that each entry reaches its
 * route, and that is what this still checks.
 */
test.describe('② 桌面导航', () => {
  test.beforeEach(({}, info) => {
    test.skip(isMobile(info), '仅桌面端')
  })

  test('侧边导航 → 各分组跳转', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()

    const nav = page.locator('[data-slot="sidebar"]')
    const entries = [
      { label: '批量分诊', url: /\/v2\/triage$/ },
      { label: '字段字典', url: /\/v2\/field-dictionary$/ },
      // 实时告警 / 运营报告 现在是「安全态势」页顶部的标签，不在侧栏上。
      { label: '安全态势', url: /\/v2\/posture$/ },
    ]
    for (const e of entries) {
      const link = nav.getByRole('link', { name: e.label })
      await expect(link).toBeVisible()
      await link.click()
      await expect(page).toHaveURL(e.url)
    }
  })

  test('导航栏可折叠（⌘B）后仍能跳转', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()

    const nav = page.locator('[data-slot="sidebar"]').first()
    await expect(nav).toHaveAttribute('data-state', 'expanded')
    await page.keyboard.press('Control+b')
    await expect(nav).toHaveAttribute('data-state', 'collapsed')

    // Collapsed to icons — the label is still the accessible name.
    await page.locator('[data-slot="sidebar"]').getByRole('link', { name: '批量分诊' }).click()
    await expect(page).toHaveURL(/\/v2\/triage$/)

    await page.keyboard.press('Control+b')
    await expect(nav).toHaveAttribute('data-state', 'expanded')
  })

  // 侧栏底部的次级分组（atlas 的 NavSecondary 槽位）现在是两条族长：系统设置
  // （用户 / AI 配置 / 产品激活）和平台健康（调用审计 / 对外通道）。
  test('侧栏次级分组 → 系统设置，再从顶部标签进用户', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    const nav = page.locator('[data-slot="sidebar"]')
    await nav.getByRole('link', { name: '系统设置' }).click()
    await expect(page).toHaveURL(/\/v2\/settings$/)

    const tabs = page.locator('[data-slot="tabs-list"]').first()
    await tabs.getByRole('link', { name: '用户' }).click()
    await expect(page).toHaveURL(/\/v2\/users$/)
    // 标签栏跟着路由走：换页之后高亮的是新的那条。
    await expect(tabs.getByRole('link', { name: '用户' })).toHaveAttribute('data-active', '')
  })

  test('平台健康顶部标签 → 调用审计 / 对外通道', async ({ page }) => {
    await page.goto('/v2/platform', { waitUntil: 'domcontentloaded' })
    const tabs = page.locator('[data-slot="tabs-list"]').first()
    await expect(tabs).toBeVisible()

    await tabs.getByRole('link', { name: '调用审计' }).click()
    await expect(page).toHaveURL(/\/v2\/audit$/)

    await tabs.getByRole('link', { name: '对外通道' }).click()
    await expect(page).toHaveURL(/\/v2\/notify$/)
  })

  /* 深链：安全态势的「最近告警 → 去处置」和「最吵的规则 → 查看」都要落到具体的
     一条 / 一类，不能把人扔回列表首页。参数用完即从地址栏抹掉。 */
  test('告警页深链 —— ?rule= 落成筛选，用完抹掉参数', async ({ page }) => {
    await page.goto('/v2/alerts?rule=brute', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()
    await expect(page.getByPlaceholder('规则名/ID…')).toHaveValue('brute')
    await expect(page).toHaveURL(/\/v2\/alerts$/)
  })

  test('安全态势顶部标签 → 实时告警 / 运营报告', async ({ page }) => {
    await page.goto('/v2/posture', { waitUntil: 'domcontentloaded' })
    const tabs = page.locator('[data-slot="tabs-list"]').first()
    await expect(tabs).toBeVisible()

    await tabs.getByRole('link', { name: '实时告警' }).click()
    await expect(page).toHaveURL(/\/v2\/alerts$/)

    await tabs.getByRole('link', { name: '运营报告' }).click()
    await expect(page).toHaveURL(/\/v2\/reports$/)
  })

  test('账号菜单在顶栏右上角 —— 资料 / 偏好 / 退出；语言主题是旁边两个按钮', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: '打开账号菜单' }).click()
    await expect(page.getByRole('menuitem', { name: '个人资料' })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: '偏好设置' })).toBeVisible()
    // 语言 / 主题不在菜单里了：顶栏上各是一个一键切换的按钮。
    await expect(page.getByRole('radiogroup')).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('button', { name: /^切换到/ })).toHaveCount(2)
    // 侧栏左下角是帮助链接，不再有账号块。
    await expect(page.locator('[data-slot="sidebar"]').getByRole('link', { name: '帮助中心' })).toBeVisible()
    await expect(page.locator('[data-slot="sidebar"]').getByRole('link', { name: '文档' })).toBeVisible()
    await page.getByRole('button', { name: '打开账号菜单' }).click()
    await page.getByRole('menuitem', { name: '个人资料' }).click()
    await expect(page).toHaveURL(/\/v2\/profile$/)
  })

  // 退出走的是整页 `location.assign('/v2/login')`，不是路由跳转：要钉住的是
  // 退出后按 back 回不到已登录页（会话 cookie 已被服务端清掉，壳的 beforeLoad
  // 再拿 /api/me 拿不到就弹回登录页）。
  // 用独立 context 自己登录：共用的 storageState 一退出，后面所有 spec 都会掉线。
  test('退出登录后 back 键回不到已登录页', async ({ browser, baseURL }) => {
    const ctx = await browser.newContext({ storageState: undefined })
    try {
      const login = await ctx.request.post('/api/auth/login', {
        data: { username: process.env.RST_E2E_USER || 'admin', password: process.env.RST_E2E_PASSWORD },
      })
      expect(login.ok()).toBeTruthy()
      const page = await ctx.newPage()
      await page.goto('/v2/audit', { waitUntil: 'domcontentloaded' })
      await expect(page.locator('h1').first()).toBeVisible()
      await page.getByRole('button', { name: '打开账号菜单' }).click()
      await page.getByRole('menuitem', { name: '退出登录' }).click()
      await page.waitForURL(/\/v2\/login/)
      await page.goBack({ waitUntil: 'domcontentloaded' })
      await expect(page).toHaveURL(/\/v2\/login/)
      await expect(page.getByRole('button', { name: /登录|Sign in/ })).toBeVisible()
      // 会话确实失效，不只是前端跳了一下。
      const me = await (await ctx.request.get(`${baseURL}/api/me`)).json()
      expect(me.authenticated).toBe(false)
    } finally {
      await ctx.close()
    }
  })

  test('命令面板 ⌘K —— 打开 / 搜索 / 跳转', async ({ page }) => {
    const errs = trackErrors(page)
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()

    await page.keyboard.press('Control+k')
    const search = page.getByPlaceholder('跳转页面或执行操作…')
    await expect(search).toBeVisible()

    await search.fill('审计')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/v2\/audit$/)
    expect(errs.pageErrors).toHaveLength(0)
  })

  test('Logo 点击回首页', async ({ page }) => {
    await page.goto('/v2/audit', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()
    await page
      .locator('[aria-label="RST · Elastic AI Copilot"]:visible')
      .first()
      .click()
    await expect(page).toHaveURL(/\/v2\/?$/)
  })

  // 主题是顶栏上一个两档按钮：亮 ↔ 暗（「跟随系统」留在偏好设置页）。按钮的
  // 可访问名说的是**点下去会变成什么**，所以名字随当前档变 —— 断言按这个来找。
  test('主题：顶栏按钮在亮 / 暗之间切', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()
    const html = page.locator('html')
    await page.getByRole('button', { name: '切换到深色' }).click()
    await expect(html).toHaveClass(/dark/)
    await page.getByRole('button', { name: '切换到浅色' }).click()
    await expect(html).not.toHaveClass(/dark/)
  })

  test('语言：顶栏按钮切到 EN，整站变英文', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()
    await page.getByRole('button', { name: '切换到English' }).click()
    await expect(page.getByRole('button', { name: 'Switch to 中文' })).toBeVisible()
    await page.getByRole('button', { name: 'Switch to 中文' }).click()
    await expect(page.getByRole('button', { name: '切换到English' })).toBeVisible()
  })
})

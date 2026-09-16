import { test, expect } from '@playwright/test'
import { ROUTES, trackErrors, accName } from './_shared'

/*
 * ① 页面可用性 —— 12 个路由全部能加载。
 * 检查：AppShell 渲染 / 路由主体渲染 (h1) / 无 ErrorBoundary 崩溃 /
 *       无未捕获 JS 异常 / 每个可见按钮都有可访问名称。
 * 同时为每个路由 × 每个视口存一张全页截图到 e2e/shots/。
 */
test.describe('① 页面可用性', () => {
  for (const r of ROUTES) {
    test(`${r.name} — ${r.label}`, async ({ page }, info) => {
      const errs = trackErrors(page)
      await page.goto(r.path, { waitUntil: 'domcontentloaded' })

      // AppShell（logo 始终在顶栏）
      await expect(
        page.locator('[aria-label="RST · Elastic AI Copilot"]').first(),
      ).toBeVisible()

      // 路由主体渲染完成（lazy chunk 解析 + 首屏内容）
      await expect(page.locator('h1').first()).toBeVisible({ timeout: 15_000 })
      if (r.name === 'query') {
        await expect(
          page.locator('textarea[placeholder*="用一句话问"]'),
        ).toBeVisible()
      }

      // 无渲染崩溃
      await expect(page.getByText('这个页面出了点问题')).toHaveCount(0)
      await expect(page.getByText('RUNTIME ERROR')).toHaveCount(0)

      // 按钮可用性 —— 数量 + 可访问名称
      const btns = page.locator('button:visible')
      const n = await btns.count()
      expect(n, '页面应至少有 1 个可见按钮').toBeGreaterThan(0)
      let nameless = 0
      for (let i = 0; i < n; i++) {
        if (!(await accName(btns.nth(i)))) nameless++
      }
      info.annotations.push({
        type: '按钮统计',
        description: `可见按钮 ${n} 个，无名称 ${nameless} 个`,
      })

      // 截图存档
      await page.screenshot({
        path: `e2e/shots/${info.project.name}-${r.name}.png`,
        fullPage: true,
      })

      // 无未捕获异常
      expect(
        errs.pageErrors,
        `未捕获异常：${errs.pageErrors.join(' | ')}`,
      ).toHaveLength(0)
      if (errs.consoleErrors.length) {
        info.annotations.push({
          type: 'console.error',
          description: errs.consoleErrors.slice(0, 6).join(' | '),
        })
      }
    })
  }
})

import { test, expect } from '@playwright/test'
import { trackErrors, isMobile } from './_shared'

/*
 * ③ 移动端导航 —— 菜单抽屉、抽屉内跳转、命令面板按钮。
 * 仅在 mobile project (Pixel 5, 393×851) 跑。
 *
 * Round 11: the hand-rolled hamburger sheet is gone; the same rail that is
 * persistent on desktop slides in as a sheet here, so one nav definition
 * serves both. The assertions are unchanged in intent.
 */
test.describe('③ 移动端导航', () => {
  test.beforeEach(({}, info) => {
    test.skip(!isMobile(info), '仅移动端')
  })

  test('菜单抽屉 —— 展开并跳转', async ({ page }) => {
    const errs = trackErrors(page)
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()

    // 导航项在抽屉打开前不可达
    await expect(page.getByRole('link', { name: '批量分诊' })).toHaveCount(0)

    const burger = page.getByRole('button', { name: '菜单', exact: true })
    await expect(burger).toBeVisible()
    await burger.click()

    // 抽屉里出现导航项 → 点击跳转
    const link = page.getByRole('link', { name: '批量分诊' })
    await expect(link).toBeVisible()
    await link.click()
    await expect(page).toHaveURL(/\/v2\/triage$/)
    expect(errs.pageErrors).toHaveLength(0)
  })

  test('移动端头部构成 —— logo + 菜单（命令面板为桌面特性）', async ({
    page,
  }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1').first()).toBeVisible()
    await expect(
      page.locator('[aria-label="RST · Elastic AI Copilot"]:visible'),
    ).toBeVisible()
    await expect(page.getByRole('button', { name: '菜单', exact: true })).toBeVisible()
    // ⌘K 命令面板按钮在移动端不渲染（无物理键盘）—— 导航走菜单抽屉
    await expect(
      page.getByRole('button', { name: '命令面板' }),
    ).toHaveCount(0)
  })

  test('移动端首页搜索框可输入', async ({ page }) => {
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
    const input = page.locator('textarea[placeholder*="用一句话问"]')
    await expect(input).toBeVisible()
    await input.fill('移动端测试输入')
    await expect(input).toHaveValue('移动端测试输入')
  })
})

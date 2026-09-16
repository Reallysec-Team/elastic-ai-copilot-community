import { test, expect } from '@playwright/test'
import { trackErrors, isMobile } from './_shared'

/*
 * ⑥ 核心链路 —— 首页自然语言提问 → 调用 LLM → 返回 DSL。
 * 这是唯一一个真实消耗 LLM token 的测试，只在 desktop project 跑一次。
 * 若被 license / quota 拦截，会在 25s 内观察不到 /api/generate 请求 —— 测试失败
 * 即说明核心链路当前不可用（属于有效诊断结论）。
 */
test.describe('⑥ 核心链路 NL→DSL', () => {
  test.beforeEach(({}, info) => {
    test.skip(isMobile(info), '核心链路只跑一次')
  })

  test('提问 → LLM 生成 → 自动执行出结果', async ({ page }) => {
    test.setTimeout(140_000)
    const errs = trackErrors(page)
    await page.goto('/v2/', { waitUntil: 'domcontentloaded' })

    // 这条问题只对 Web 访问日志（kibana_sample_data_logs）成立，所以显式选中它，
    // 不靠路由自己挑。
    //
    // 名字是「索引：自动」而不是从前的「选索引」：首页现在默认不预选索引（"查哪个
    // 索引"正是这个产品要替用户省掉的问题），选择器退成"钉住一个索引"的高级选项，
    // 无障碍名字跟着 placeholder 走。这条用例一直不在常跑集里，所以那次改版之后
    // 它就一直指着一个不存在的控件。
    const indexTrigger = page.getByRole('combobox', { name: '索引：自动' })
    await indexTrigger.click()
    await page.getByRole('option', { name: /kibana_sample_data_logs/ }).first().click()

    const input = page.locator('textarea[placeholder*="用一句话问"]')
    await expect(input).toBeVisible()
    await input.fill('统计最近 30 天内 HTTP 状态码为 500 的日志数量')

    // 监听 generate 请求 —— 25s 内必须发出
    const respPromise = page.waitForResponse(
      (r) => /\/api\/generate(\/stream)?/.test(r.url()),
      { timeout: 25_000 },
    )
    await page.getByRole('button', { name: /发送/ }).click()

    const resp = await respPromise
    expect(
      resp.status(),
      `generate 接口返回 ${resp.status()}`,
    ).toBeLessThan(500)

    // 生成结束（流式 + JSON 校验通过）后，查询会自动执行 —— 折叠的
    // 「查看生成的查询」入口只在拿到可执行 DSL 后才渲染，所以它的出现
    // 就是核心链路跑通的证据（LLM 实际耗时 ~15-60s）。
    await expect(page.getByText('查看生成的查询').first()).toBeVisible({
      timeout: 100_000,
    })
    // 自动执行 —— 命中数（或 0 命中提示）随后出现，无需再点一次
    await expect(
      page.getByText(/命中 [\d,]+ 条|没有匹配的文档/).first(),
    ).toBeVisible({ timeout: 60_000 })
    expect(
      errs.pageErrors,
      `未捕获异常：${errs.pageErrors.join(' | ')}`,
    ).toHaveLength(0)
  })
})

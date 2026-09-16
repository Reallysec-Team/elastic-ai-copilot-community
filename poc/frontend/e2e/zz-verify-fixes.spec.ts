/*
 * 验证本轮修复的三个 UI 行为(确定性 route mock,不依赖真实 LLM/ES):
 *   1. 排序列禁用 —— 长文本列表头不可排序,数字/日期/keyword 列可排序
 *   2. 聚合表渲染 —— 命中为空但有 aggregations 时渲染聚合表
 *   3. 调查降级提示 —— investigate 返回 degraded 时对话框显示降级横幅
 * 截图落在 e2e/shots/。
 */
import { test, expect, type Page } from '@playwright/test'

const SHOTS = 'e2e/shots'

function sse(frames: object[]): string {
  return frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join('')
}

// Make 生成 return a DSL. The query now executes automatically, so the execute
// response is mocked separately per scenario and the DSL shape here is irrelevant.
async function mockGenerate(page: Page, dsl: object) {
  await page.route('**/api/generate/stream', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: sse([
        { type: 'meta', conversation_id: null, prompt_version: 'test' },
        { type: 'done', dsl, explanation: 'ok', confidence: 'high', duration_ms: 3, output_chars: 5 },
      ]),
    })
  })
}

async function generateThenExecute(page: Page) {
  await page.goto('/v2/', { waitUntil: 'domcontentloaded' })
  await page.getByPlaceholder(/用一句话问/).fill('测试查询')
  await page.getByRole('button', { name: /发送/ }).click()
  // Generation now runs straight into execution — wait for the answer, not for
  // a second button to press.
  await expect(page.getByText('查看生成的查询').first()).toBeVisible({ timeout: 15_000 })
}

test.describe('修复回归验证', () => {
  test('1+排序列禁用: 长文本列不可排序,数字/日期列可排序', async ({ page }) => {
    await mockGenerate(page, { query: { match_all: {} }, size: 5 })
    await page.route('**/api/execute', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          took: 3,
          hits: {
            total: { value: 2, relation: 'eq' },
            hits: [
              {
                _id: '1',
                _source: {
                  '@timestamp': '2026-06-27T10:00:00Z',
                  status: 500,
                  level: 'error',
                  message:
                    'connection refused while talking to upstream payment service after three retries',
                },
              },
              {
                _id: '2',
                _source: {
                  '@timestamp': '2026-06-27T10:01:00Z',
                  status: 404,
                  level: 'warn',
                  message: 'resource not found for requested path /v1/users/42 with a long descriptive tail',
                },
              },
            ],
          },
        }),
      })
    })

    await generateThenExecute(page)

    const messageTh = page.locator('th', { hasText: 'message' }).first()
    const statusTh = page.locator('th', { hasText: 'status' }).first()
    const tsTh = page.locator('th', { hasText: '@timestamp' }).first()
    await expect(messageTh).toBeVisible({ timeout: 15_000 })

    // 换成 DataGrid 后可排序性由 th 的 aria-sort 表达：不可排序的列没有这个属性，
    // 可排序但未排的列是 "none"。鼠标提示仍在表头文字上（title）。
    // 长文本列:不可排序
    await expect(messageTh).not.toHaveAttribute('aria-sort')
    await expect(messageTh.locator('[title]').first()).toHaveAttribute('title', '该字段不支持排序')
    // 数字列 + 日期列:可排序
    await expect(statusTh).toHaveAttribute('aria-sort', 'none')
    await expect(tsTh).toHaveAttribute('aria-sort', 'none')
    await expect(statusTh.locator('[title]').first()).toHaveAttribute('title', '点击排序')

    await page.screenshot({ path: `${SHOTS}/verify-1-sort-disable.png`, fullPage: true })
  })

  test('2+聚合表渲染: 有 aggregations 即渲染聚合表', async ({ page }) => {
    await mockGenerate(page, { size: 0, aggs: { by_level: { terms: { field: 'level.keyword' } } } })
    await page.route('**/api/execute', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          took: 2,
          hits: { total: { value: 0, relation: 'eq' }, hits: [] },
          aggregations: {
            by_level: {
              buckets: [
                { key: 'error', doc_count: 2 },
                { key: 'warn', doc_count: 2 },
                { key: 'info', doc_count: 1 },
              ],
            },
          },
        }),
      })
    })

    await generateThenExecute(page)

    // 聚合表头 + 桶值。表头是「分组 / 条数」而不是 key / doc_count —— 那两个是
    // ES 的字段名，这张表是给看结果的人的（见 ResultTable 里那段注释）。这条
    // 用例一直不在常跑集里，所以改文案那次之后它就一直指着已经不存在的表头。
    await expect(page.locator('th', { hasText: '条数' }).first()).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('td', { hasText: 'error' }).first()).toBeVisible()
    await expect(page.locator('td', { hasText: 'warn' }).first()).toBeVisible()

    await page.screenshot({ path: `${SHOTS}/verify-2-agg-table.png`, fullPage: true })
  })

  test('3+调查降级提示: investigate degraded 显示降级横幅', async ({ page }) => {
    await mockGenerate(page, { query: { match_all: {} }, size: 5 })
    await page.route('**/api/execute', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          took: 3,
          hits: {
            total: { value: 1, relation: 'eq' },
            hits: [
              {
                _id: '1',
                _source: { '@timestamp': '2026-06-27T10:00:00Z', status: 500, message: 'connection refused' },
              },
            ],
          },
        }),
      })
    })
    // investigate 返回降级结果(结构合法 + degraded:true)。前端调的是
    // streamInvestigate() → POST /api/investigate-alert/stream(SSE 帧),
    // 不是普通 JSON 端点 —— 见 src/lib/streamingClient.ts:197,271。
    await page.route('**/api/investigate-alert/stream', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sse([
          {
            type: 'result',
            result: {
              summary: '模型本次输出无法解析,未能生成调查结论。请稍候重试,或换一条告警再试。',
              alert_type: '调查',
              severity: 'info',
              is_likely_false_positive: false,
              false_positive_reason: '',
              timeline: [],
              attack_chain: [],
              mitre_techniques: [],
              affected_assets: [],
              recommended_actions: [],
              confidence: 'low',
              context_count: 0,
              degraded: true,
            },
          },
        ]),
      })
    })

    await generateThenExecute(page)

    // 点行内"调查"按钮(title="把这条当作告警调查")
    await page.getByTitle('把这条当作告警调查').first().click()

    // 降级横幅
    await expect(page.getByText('AI 结果降级')).toBeVisible({ timeout: 15_000 })
    await page.screenshot({ path: `${SHOTS}/verify-3-degraded.png`, fullPage: true })
  })
})

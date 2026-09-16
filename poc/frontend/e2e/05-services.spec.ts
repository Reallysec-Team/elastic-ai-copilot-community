import { test, expect } from '@playwright/test'
import { isMobile } from './_shared'

/*
 * ⑤ 服务可用性 —— 后端 API。
 * 判定：服务存活 = 有响应且非 5xx。401/403 表示鉴权生效，同样算健康。
 * 只在 desktop project 跑一次（API 与视口无关）。
 */
const GET_ENDPOINTS = [
  '/healthz',
  '/readyz',
  '/api/license/status',
  '/api/license/server-guid',
  '/api/license/quota',
  '/api/llm/providers',
  '/api/audit/events',
  '/api/conversations',
  '/api/feedback/failed-cases',
  '/api/dashboards',
  '/api/engines',
  '/api/settings',
  '/api/indices',
  '/api/masking/info',
]

test.describe('⑤ 服务可用性', () => {
  test.beforeEach(({}, info) => {
    test.skip(isMobile(info), 'API 测试只跑一次')
  })

  for (const ep of GET_ENDPOINTS) {
    test(`GET ${ep}`, async ({ request }, info) => {
      const res = await request.get(ep)
      const code = res.status()
      info.annotations.push({ type: 'HTTP', description: `${code}` })
      expect(code, `${ep} 返回 ${code}`).toBeLessThan(500)
    })
  }

  test('SPA 入口 /v2/ 返回 HTML 外壳', async ({ request }) => {
    const res = await request.get('/v2/')
    expect(res.status()).toBe(200)
    expect(await res.text()).toContain('<div id="root">')
  })
})

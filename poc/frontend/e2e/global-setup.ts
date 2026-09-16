import { request } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/*
 * 登录一次，把会话 cookie 存成 storageState 给所有测试复用。
 *
 * 以前网关的认证是 Caddy Basic Auth（浏览器层，SPA 根本看不见），e2e 直接 goto
 * 就能进。改成 /v2 登录表单之后，未登录的请求全都渲染登录页，24 个 spec 会在
 * 第一句 `AppShell logo 可见` 上全灭 —— 不是页面坏了，是没登录。
 *
 * 密码只从环境变量取，不落仓库：
 *   $env:RST_E2E_PASSWORD='...'; npx playwright test
 */
// ESM: 这个包是 type=module，没有 __dirname。
const _dir = path.dirname(fileURLToPath(import.meta.url))
export const STATE_PATH = path.join(_dir, '.auth', 'state.json')

export default async function globalSetup() {
  const baseURL = process.env.RST_E2E_BASE_URL || 'http://127.0.0.1:18765'
  const username = process.env.RST_E2E_USER || 'admin'
  const password = process.env.RST_E2E_PASSWORD

  if (!password) {
    throw new Error(
      'e2e 需要登录：请设置 RST_E2E_PASSWORD（以及必要时 RST_E2E_USER，默认 admin）。\n' +
        "  PowerShell:  $env:RST_E2E_PASSWORD='<网关登录密码>'; npx playwright test",
    )
  }

  const ctx = await request.newContext({ baseURL })
  const resp = await ctx.post('/api/auth/login', { data: { username, password } })
  if (!resp.ok()) {
    throw new Error(
      `登录失败 (${resp.status()})：${await resp.text()}\n` +
        `网关 ${baseURL} / 账号 ${username} —— 检查密码，或确认网关已启动。`,
    )
  }

  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true })
  await ctx.storageState({ path: STATE_PATH })
  await ctx.dispose()
}

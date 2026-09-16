import { defineConfig, devices } from '@playwright/test'

/*
 * E2E 测试 — Elastic AI Copilot /v2 前端。
 *
 * 跑在已运行的网关上（默认 http://127.0.0.1:18765），不自行拉起服务。
 * 端口取 18765 而非 8765：8765 落在 Windows TCP 动态端口段（1024–15000）内，
 * Docker Desktop 运行时 winnat 会在该段动态保留子块、使 8765 偶发绑不上；
 * 18765 在动态段之上，不受影响。
 * 网关地址可用环境变量覆盖（指向本地 uvicorn 或任意端口的容器）：
 *   $env:RST_E2E_BASE_URL='http://127.0.0.1:9000'; npx playwright test
 * 两个 project：desktop (1440×900) 与 mobile (Pixel 5)。
 * 运行：  npx playwright test
 * 报告：  e2e/report/index.html   截图：e2e/shots/   结果：e2e/results.json
 */
export default defineConfig({
  testDir: './e2e',
  // 登录一次换 storageState，见 e2e/global-setup.ts（需要 RST_E2E_PASSWORD）
  globalSetup: './e2e/global-setup.ts',
  timeout: 60_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['json', { outputFile: 'e2e/results.json' }],
    ['html', { outputFolder: 'e2e/report', open: 'never' }],
  ],
  use: {
    baseURL: process.env.RST_E2E_BASE_URL || 'http://127.0.0.1:18765',
    // 默认用 playwright 自带的 headless shell。装不上它时（下载被墙）可以退回完整
    // chromium 或本机 Chrome：$env:RST_E2E_CHANNEL='chromium'; npx playwright test
    channel: process.env.RST_E2E_CHANNEL || undefined,
    // 界面语言没有 per-user 偏好时按 `navigator.language` 回落（见 lib/i18n.ts）。
    // Playwright 起的 Chrome 默认 en-US，整站会渲染成英文，而这套 spec 断言的是
    // 中文文案。声明中文浏览器 —— 这是这个产品的主战场，也是开发机上的真实情况。
    locale: 'zh-CN',
    storageState: './e2e/.auth/state.json',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    actionTimeout: 12_000,
    navigationTimeout: 25_000,
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'mobile',
      use: { ...devices['Pixel 5'] },
    },
  ],
})

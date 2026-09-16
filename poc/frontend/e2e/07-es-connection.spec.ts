import { test, expect } from '@playwright/test'

/*
 * ⑦ ES 连接卡 —— 安装后的第一步在这里完成，所以护的是「配错了还能配回来」：
 * 没测通就不许保存。存进一个连不上的地址，唯一能改回来的入口就是这个页面自己。
 */
test.describe('⑦ ES 连接', () => {
  test('https 才显示 TLS 两行；未测通不许保存；失败有说明', async ({ page }) => {
    await page.goto('/v2/settings', { waitUntil: 'domcontentloaded' })
    await page.getByText('Elasticsearch 连接').first().waitFor({ timeout: 20_000 })

    // http 集群上 TLS 两行无处生效，摆着只会让人以为漏配了什么
    await expect(page.getByText('校验服务端证书')).toHaveCount(0)
    await page.locator('#es-url').fill('https://es.corp.local:9243')
    await expect(page.getByText('校验服务端证书')).toBeVisible()
    await expect(page.locator('#es-ca')).toBeVisible()

    // 改了地址 → 回到「未验证」→ 保存闸关上
    await page.getByRole('button', { name: /保存并应用/ }).click()
    await expect(page.getByText('请先点「测试连接」')).toBeVisible({ timeout: 5_000 })

    // 连不上要说人话，不是一个红叉
    await page.getByRole('button', { name: /测试连接/ }).click()
    await expect(page.getByText('连不上')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText(/无法连接 Elasticsearch/)).toBeVisible()
    await page.screenshot({ path: 'e2e/shots/es-connection-failed.png' })
  })
})

import type { Page, TestInfo } from '@playwright/test'

/* 12 个路由 —— 与 src/App.tsx 一致 */
export interface RouteDef {
  path: string
  name: string
  label: string
}

export const ROUTES: RouteDef[] = [
  { path: '/v2/', name: 'query', label: '查询 / NL→DSL' },
  { path: '/v2/triage', name: 'triage', label: '批量分诊' },
  { path: '/v2/detection-rules', name: 'detection-rule', label: '检测规则' },
  { path: '/v2/field-dictionary', name: 'field-dict', label: '字段字典' },
  { path: '/v2/knowledge-base', name: 'kb', label: '处置手册' },
  { path: '/v2/asset-identity', name: 'asset-identity', label: '资产台账' },
  { path: '/v2/reports', name: 'reports', label: '报告' },
  { path: '/v2/audit', name: 'audit', label: '审计' },
  { path: '/v2/settings', name: 'settings', label: '网关设置' },
  { path: '/v2/users', name: 'users', label: '用户' },
  { path: '/v2/license', name: 'activate', label: 'License 激活' },
  { path: '/v2/profile', name: 'profile', label: '个人资料' },
  { path: '/v2/preferences', name: 'preferences', label: '偏好设置' },
]

/*
 * 不自动点击的按钮 —— 触发 LLM 计费、网络写入或破坏性操作。
 * 交互测试只点安全按钮（标签/筛选/展开/刷新等）。
 */
export const UNSAFE_BTN =
  /生成|分诊|分析|investigate|执行|运行|删除|清空|重载|reload|激活|保存|导出|下载|提交|发送|应用|确认|新建|添加/i

export interface ErrorSink {
  pageErrors: string[]
  consoleErrors: string[]
}

/** 挂载未捕获异常 + console.error 收集器 —— 必须在 goto 之前调用。 */
export function trackErrors(page: Page): ErrorSink {
  const sink: ErrorSink = { pageErrors: [], consoleErrors: [] }
  page.on('pageerror', (e) => sink.pageErrors.push(e.message))
  page.on('console', (m) => {
    if (m.type() === 'error') sink.consoleErrors.push(m.text())
  })
  return sink
}

export function isMobile(info: TestInfo): boolean {
  return info.project.name === 'mobile'
}

/** 一个按钮的可访问名称（aria-label → title → 文本）。带短超时，元素失效即返回空。 */
export async function accName(
  el: import('@playwright/test').Locator,
): Promise<string> {
  try {
    return (
      (await el.getAttribute('aria-label', { timeout: 2000 })) ??
      (await el.getAttribute('title', { timeout: 2000 })) ??
      (await el.textContent({ timeout: 2000 })) ??
      ''
    ).trim()
  } catch {
    return ''
  }
}

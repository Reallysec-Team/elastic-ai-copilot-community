import { createFileRoute } from '@tanstack/react-router'

import RealtimeAlertsPage from '@/pages/RealtimeAlertsPage'

/** 告警页的两个深链参数。`?alert=<id>` 直接打开某条告警的详情，`?rule=<关键字>`
 *  把列表预过滤到某条规则 —— 两者都是从别的页面（分析记录、检测规则）发过来的
 *  链接，必须继续工作。声明成 search schema 之后它们是有类型的路由输入，页面不
 *  再自己解析 URLSearchParams。 */
export interface AlertsSearch {
  alert?: string
  rule?: string
}

export const Route = createFileRoute('/_app/alerts')({
  validateSearch: (search: Record<string, unknown>): AlertsSearch => ({
    alert: typeof search.alert === 'string' && search.alert ? search.alert : undefined,
    rule: typeof search.rule === 'string' && search.rule ? search.rule : undefined,
  }),
  component: RealtimeAlertsPage,
})

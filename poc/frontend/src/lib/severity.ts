import { translate } from '@/lib/i18n'
import type { BadgeProps } from '@/components/reui/badge'
import { commonCopy, type CommonKey } from '@/locales/common'

/*
 * 严重度的说法，全站一份。
 *
 * 之前每个页面各写各的：告警页和通知配置有 SEV_LABEL（中文），分诊、分析记录、
 * 事件解读、深入调查直接打 `severity.toUpperCase()` —— 同一条告警在一个页面写
 * 「高」，点进弹窗变成 HIGH。
 *
 * 走 `translate()` 而不是 `useT()`：这个函数也在组件外被调用（排序、导出、
 * 拼提示串）。代价是它自己不订阅语言变化 —— 调用它的组件只要在别处用了
 * `useT()` 就会跟着重渲染，语言一改这里读到的就是新值。
 */
export const SEVERITY_ORDER = ['info', 'low', 'medium', 'high', 'critical'] as const

export type Severity = (typeof SEVERITY_ORDER)[number]

const LABEL_KEY: Record<string, CommonKey> = {
  info: 'sevInfo',
  low: 'sevLow',
  medium: 'sevMedium',
  high: 'sevHigh',
  critical: 'sevCritical',
}

/** 认识的按当前语言翻，不认识的原样返回（后端以后加档位时不会变成空白）。 */
export function severityLabel(sev: string | null | undefined): string {
  if (!sev) return '—'
  const key = LABEL_KEY[sev.toLowerCase()]
  return key ? translate(commonCopy, key) : sev
}

/*
 * 严重度的徽标颜色也只此一份（和 `Pill` 的 sev-* 映射同一张表）：一套刻度，
 * 不是调色板。全部 `-light` 淡底——和模板里所有状态徽标同一种质感；critical
 * 和 high 同色，靠 `SeverityBadge` 里的实心红点 + 加粗区分（实底红 / 实底黑都
 * 试过，放进一排淡底徽标里像贴错了地方）。
 */
const BADGE_VARIANT: Record<Severity, BadgeProps['variant']> = {
  critical: 'destructive-light',
  high: 'destructive-light',
  medium: 'warning-light',
  low: 'secondary',
  info: 'info-light',
}

export function severityBadgeVariant(sev: string | null | undefined): BadgeProps['variant'] {
  return BADGE_VARIANT[(sev ?? '').toLowerCase() as Severity] ?? 'secondary'
}

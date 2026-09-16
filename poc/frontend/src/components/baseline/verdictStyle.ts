/* Verdict label + swatch for baseline results.
 *
 * Its own module because a file that exports both components and constants
 * breaks React Fast Refresh — editing the constant forces a full reload and
 * drops component state, which is miserable when you are iterating on a table
 * three clicks deep in the app. */

import type { ComponentProps } from 'react'
import type { Badge } from '@/components/reui/badge'
import { translate } from '@/lib/i18n'
import { commonCopy, type CommonKey } from '@/locales/common'

type BadgeVariant = ComponentProps<typeof Badge>['variant']

/* 判定这套词汇自己拥有颜色（同 §3.5 的严重度刻度），但颜色由 Badge 的 variant
 * 给 —— 原来那套 emerald/red/amber/sky/slate 的字面色阶换主题时不跟着走，浅色
 * 下还是浅字压浅底。`fill` 是同一套判定给图表用的值。
 *
 * 存的是文案键不是文案：判定名在表格、环图、筛选下拉三处显示，写死中文就要翻
 * 三遍。取名走 `verdictLabel()`，和 `severityLabel()` 同一个做法。 */
export const VERDICT_STYLE: Record<string, { label: CommonKey; variant: BadgeVariant; fill: string }> = {
  pass: { label: 'verdictPass', variant: 'success-light', fill: 'var(--color-success)' },
  fail: { label: 'verdictFail', variant: 'destructive-light', fill: 'var(--color-destructive)' },
  error: { label: 'verdictError', variant: 'warning-light', fill: 'var(--color-warning)' },
  manual_review: { label: 'verdictManualReview', variant: 'info-light', fill: 'var(--color-info)' },
  // 主机失联或该项采集已停 —— 对当前状态没有证据，既不是通过也不是不合规。
  // 中性灰刻意不用 error 的警告色：那是「工具出错」，这是「没数据可判」。
  stale: { label: 'verdictStale', variant: 'secondary', fill: 'var(--color-muted-foreground)' },
}

/** 认识的按当前语言翻，不认识的原样返回。 */
export function verdictLabel(verdict: string): string {
  const style = VERDICT_STYLE[verdict]
  return style ? translate(commonCopy, style.label) : verdict
}

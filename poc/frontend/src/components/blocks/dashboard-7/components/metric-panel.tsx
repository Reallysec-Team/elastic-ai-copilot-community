import type { ReactNode } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { TradeDownIcon, TradeUpIcon } from '@hugeicons/core-free-icons'

import { cn } from '@/lib/utils'
import { Badge, type BadgeProps } from '@/components/reui/badge'
import { Frame, FramePanel } from '@/components/reui/frame'
import { IconContainer } from './icon-container'

/*
 * `@reui/dashboard-7` 的 KPI 卡：图标格 + 标题/说明 + 趋势徽标 + 大数字 + 右下角
 * 一排 sparkline 竖条。模板里数据是写死的 METRICS；这里改成 props，sparkline 可选
 * —— 安全态势四格里只有「告警总数」有时间序列，其余三格没有就不画。
 */

export type MetricTone = 'success' | 'info' | 'warning' | 'destructive'

export interface MetricCardData {
  id: string
  title: string
  detail: string
  value: string
  icon: ReactNode
  /** 右上角徽标；没有就不画。 */
  badge?: { label: string; tone: MetricTone; trend?: 'up' | 'down' }
  sparkline?: number[]
  tone?: MetricTone
}

const TONE_BADGES: Record<MetricTone, BadgeProps['variant']> = {
  success: 'success-light',
  info: 'info-light',
  warning: 'warning-light',
  destructive: 'destructive-light',
}

export function MetricGrid({ cards, className }: { cards: MetricCardData[]; className?: string }) {
  return (
    <div className={cn('grid gap-2 sm:grid-cols-2 @5xl:grid-cols-4 xl:gap-3', className)}>
      {cards.map((metric) => (
        <Frame key={metric.id}>
          <MetricPanel metric={metric} />
        </Frame>
      ))}
    </div>
  )
}

function MetricPanel({ metric }: { metric: MetricCardData }) {
  // 全是 0 的序列画出来是一排 16% 高的点，像有数据 —— 不画。
  const spark = (metric.sparkline ?? []).some((v) => v > 0) ? (metric.sparkline ?? []) : []
  const max = Math.max(1, ...spark)
  const tone = metric.tone ?? 'info'

  return (
    <FramePanel className="flex min-h-28 flex-col justify-between gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-3">
          <IconContainer icon={metric.icon} />
          <div className="min-w-0 pt-0.5">
            <span className="block truncate text-sm font-medium">{metric.title}</span>
            <span className="block truncate text-xs text-muted-foreground">{metric.detail}</span>
          </div>
        </div>
        {metric.badge && (
          <Badge variant={TONE_BADGES[metric.badge.tone]}>
            {metric.badge.trend && (
              <HugeiconsIcon
                icon={metric.badge.trend === 'down' ? TradeDownIcon : TradeUpIcon}
                strokeWidth={2}
                className="size-3"
                aria-hidden="true"
              />
            )}
            {metric.badge.label}
          </Badge>
        )}
      </div>

      <div className="grid grid-cols-[1fr_auto] items-end gap-2">
        <div className="min-w-0">
          <div className="text-xl font-semibold tracking-tight tabular-nums">{metric.value}</div>
        </div>
        {spark.length > 0 && (
          <div className="flex h-10 items-end gap-0.5" aria-hidden="true">
            {spark.map((point, index) => (
              <span
                key={`${metric.id}-${index}`}
                className="w-1 rounded-full bg-primary/20 data-[tone=destructive]:bg-destructive/30 data-[tone=info]:bg-info/30 data-[tone=success]:bg-success/30 data-[tone=warning]:bg-warning/30"
                data-tone={tone}
                style={{ height: `${Math.max((point / max) * 100, 16)}%` }}
              />
            ))}
          </div>
        )}
      </div>
    </FramePanel>
  )
}

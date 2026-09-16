import { Link } from '@tanstack/react-router'
import { useT, translate } from '@/lib/i18n'
import { componentsCopy } from '@/locales/components'
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react'
import {
  Activity02Icon, BellRingIcon, ClipboardCheckIcon, ScrollTextIcon,
} from '@hugeicons/core-free-icons'

import { usePostureSummary, type Loadable } from '@/hooks/usePostureSummary'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/reui/badge'
import {
  Frame, FrameFooter, FramePanel,
} from '@/components/reui/frame'

/*
 * 首页空态上的「今天要处理的」。
 *
 * 版式照 tempo 的 home（`features/dashboard/.../catalog-health/chart.tsx` 的
 * Performance Overview）：一张 Frame 切四格，格与格之间是竖线，每格是
 * 图标+名字 / 大数 / 一个 Badge 加一句话。
 *
 * 为什么放在这里而不是新开一页：`/` 是这个产品的对话面，是先前定下来的信息架构。
 * 但提问之前那一屏原来只有四条示例问题加一大片白 —— **打开产品的第一眼应该告诉你
 * 今天有什么要处理，而不是只问你想问什么。** 所以补在空态里：有事要处理时它在最
 * 上面，问出第一个问题之后整块消失，不占对话的地方。
 *
 * 四个数**不在这里算**：口径（哪些算高危、哪些检查项算异常、取不到怎么写）和安全
 * 态势整页共用 `usePostureSummary`。这四格曾经自己取过一遍数，于是同一个数字在两
 * 个页面上有两套算法，对不上的时候没人说得清哪个对。
 */

type Cell = {
  id: string
  label: string
  icon: IconSvgElement
  href: string
  /** null = 还在取；'error' = 取不到。 */
  value: number | null | 'error'
  badge?: { label: string; variant: 'secondary' | 'success-light' | 'warning-light' | 'destructive-light' }
  summary: string
}

const LOADING = '…'

/** Loadable → 这一格要显示的东西。取不到写 'error'，绝不写 0。 */
function cellValue<T extends number | null>(l: Loadable<T>): Cell['value'] {
  if (l.error !== null) return 'error'
  if (l.data === null) return null
  return l.data
}

export function OperatingOverview() {
  const t = useT(componentsCopy)
  const s = usePostureSummary({ range: '24h' })

  const alerts: Cell['value'] =
    s.stats.error !== null ? 'error' : s.stats.data ? s.stats.data.total : null
  // 一轮巡检都没跑过：不是「0 条不合规」，也不是「读不出来」—— 单独一档。
  const baselineNeverRan = s.baselineFail.error === null && s.baselineFail.data === null
  const baselineScore = s.baselineScore

  const cells: Cell[] = [
    {
      id: 'alerts',
      label: t('ovAlerts'),
      icon: BellRingIcon,
      href: '/alerts',
      value: alerts,
      badge:
        s.urgent > 0
          ? { label: t('ovUrgent', { n: s.urgent }), variant: 'destructive-light' }
          : { label: t('ovNoUrgent'), variant: 'success-light' },
      summary: t('ovAlertsSummary'),
    },
    {
      id: 'baseline',
      label: t('ovBaseline'),
      icon: ClipboardCheckIcon,
      href: '/baseline',
      value: baselineNeverRan ? 'error' : cellValue(s.baselineFail),
      badge:
        baselineScore == null
          ? { label: t('ovNotScored'), variant: 'secondary' }
          : baselineScore >= 80
            ? { label: t('ovScore', { score: baselineScore }), variant: 'success-light' }
            : { label: t('ovScore', { score: baselineScore }), variant: 'warning-light' },
      summary: baselineNeverRan ? t('ovNeverRan') : t('ovBaselineSummary'),
    },
    {
      id: 'platform',
      label: t('ovPlatform'),
      icon: Activity02Icon,
      href: '/platform',
      value: cellValue(s.platformBad),
      badge:
        s.platformBad.data === 0
          ? { label: t('ovAllPass'), variant: 'success-light' }
          : { label: t('ovNeedsWork'), variant: 'warning-light' },
      summary: t('ovPlatformSummary'),
    },
    {
      id: 'analysis',
      label: t('ovAnalysis'),
      icon: ScrollTextIcon,
      href: '/analysis',
      value: cellValue(s.analyses),
      badge: { label: t('ovReplayable'), variant: 'secondary' },
      summary: t('ovAnalysisSummary'),
    },
  ]

  /* 这张卡挂在对话面的空态里，不一定有 @container 祖先 —— @ 变体没有祖先时永远
     不匹配，而且看起来跟写对了一模一样，所以容器开在卡自己身上。 */
  return (
    <Frame dense className="@container w-full">
      <FramePanel>
        {/* 2×2，不是 tempo 的 1×4：它那排在全宽页面上，这里在对话面 672px 宽的
            那一列里 —— 四列并排会把每格挤到 160px，Badge 和后面那句话一起被截成
            「过…」「体检…」。手机上也是两列：竖排四行要占掉大半屏才看得到输入框。 */}
        <div className="grid grid-cols-2 items-stretch">
          {cells.map((cell, i) => (
            <MetricCell key={cell.id} cell={cell} index={i} isLast={i === cells.length - 1} />
          ))}
        </div>
      </FramePanel>
      <FrameFooter>
        <Link
          to="/posture"
          className="text-xs text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:underline"
        >
          {t('ovSeeAll')}
        </Link>
      </FrameFooter>
    </Frame>
  )
}

/* 一格。两列布局下：每行第二格画左竖线，第二行两格画上边线。 */
function MetricCell({ cell, index, isLast }: { cell: Cell; index: number; isLast: boolean }) {
  const hasDivider = index % 2 === 1
  const unreadable = cell.value === 'error'

  return (
    <Link
      to={cell.href}
      className={cn(
        'flex h-full min-h-0 w-full min-w-0 border-border/70 py-3 outline-none transition-colors',
        'rounded-md hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring/50',
        isLast ? 'pe-2' : 'pe-2 @xl:pe-5',
        index >= 2 && 'border-t',
      )}
    >
      {hasDivider && (
        <div
          className="mb-2 h-18 w-px shrink-0 self-center bg-border/70"
          aria-hidden="true"
        />
      )}
      <div className={cn('flex min-h-0 min-w-0 flex-1 flex-col', hasDivider ? 'ps-2.5 @xl:ps-5' : 'ps-1.5')}>
        <div className="mb-2 flex min-w-0 items-center gap-2">
          <HugeiconsIcon icon={cell.icon} strokeWidth={2} aria-hidden="true" className="size-4 text-muted-foreground" />
          <span className="text-xs font-medium whitespace-nowrap">{cell.label}</span>
        </div>

        <div className="flex min-h-0 flex-col gap-1.5">
          <span className="text-xl font-semibold tabular-nums">
            {cell.value === null ? LOADING : unreadable ? '—' : cell.value.toLocaleString()}
          </span>
          <div className="flex min-w-0 items-center gap-1.5">
            {unreadable ? (
              <Badge size="sm" variant="secondary">{translate(componentsCopy, 'ovUnreadable')}</Badge>
            ) : (
              cell.badge && (
                <Badge size="sm" variant={cell.badge.variant}>{cell.badge.label}</Badge>
              )
            )}
            {/* 手机上两列各 ~170px，Badge 之后再塞这句只会被截成「体检里非通…」；
                Badge 本身已经说清楚了，卡窄的时候直接不显示。 */}
            <span className="hidden truncate text-xs text-muted-foreground @xl:inline">{cell.summary}</span>
          </div>
        </div>
      </div>
    </Link>
  )
}

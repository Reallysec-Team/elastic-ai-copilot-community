import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  Activity02Icon,
  AlertCircleIcon,
  ClipboardCheckIcon,
  Loading03Icon,
  PauseIcon,
  PlayIcon,
  RefreshCwIcon,
  ShieldAlertIcon,
  TaskDone02Icon,
} from '@hugeicons/core-free-icons'

import { usePostureSummary } from '@/hooks/usePostureSummary'
import { useT } from '@/lib/i18n'
import { severityLabel } from '@/lib/severity'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { MetricGrid, type MetricCardData } from '@/components/blocks/dashboard-7/components/metric-panel'
import { RecentAlertsGrid } from '@/components/posture/RecentAlertsGrid'
import { TrendCard } from '@/components/blocks/chart-18/components/trend-card'
import { MixDonut } from '@/components/blocks/chart-13/components/mix-donut'
import { EntityList } from '@/components/blocks/list-8/components/entity-list'
import { PageHeader } from '@/components/shell/page-header'
import {
  parseRange, serializeRange, TimeRangePicker,
} from '@/components/shared/time-range-picker'
import { Button } from '@/components/ui/button'
import { commonCopy } from '@/locales/common'
import { postureCopy } from '@/locales/posture'

/*
 * 安全态势 —— 值班的第一屏：**此刻**在烧什么。
 *
 * 与运营报告的分界线是有意划的，否则这就是第四个显示同样四个数字的地方：
 *   运营报告  过去一段时间的**结论**。要生成、含 LLM 摘要和分诊、可投递可归档。
 *   这一页    此刻的**状态**。纯聚合、秒开、自动刷新、不调 LLM（不烧额度，
 *             所以挂在值班大屏上一天也没有代价）。
 *
 * 第二条规矩：**每个数字都要能点进去**。落到实时告警/基线/体检/分析记录的对应
 * 位置，否则它就只是一块好看的板子 —— 看到「6 条严重」之后没有下一步，等于没说。
 *
 * 版式照 `@reui/dashboard-7`：KPI 卡带 sparkline 和趋势徽标（metric-panel），
 * 时间线 + 严重度饼（chart-18 / chart-13），最吵规则（list-8），最新告警是一张
 * 带搜索的队列 DataGrid（order-table 的样子）。
 *
 * 取数不在这一页里：四个数的口径和首页那四格共用 `usePostureSummary`。
 */

const REFRESH_MS = 30_000
const DEFAULT_RANGE = '24h'

export function PosturePage() {
  const t = useT(postureCopy)
  const c = useT(commonCopy)
  const [rangeParam, setRangeParam] = useState(DEFAULT_RANGE)
  /* 自动刷新可暂停：正在看一张图的时候底下数字自己跳，比不刷新更烦人。 */
  const [live, setLive] = useState(true)
  const {
    stats, urgent, baselineFail, platformBad, analyses, recent,
    lastAt, refreshing, reload,
  } = usePostureSummary({
    range: rangeParam,
    refreshMs: live ? REFRESH_MS : undefined,
    recentLimit: 10,
  })
  const s = stats.data

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader
        title={t('title')}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <TimeRangePicker
              value={parseRange(rangeParam)}
              onChange={(v) => setRangeParam(serializeRange(v))}
              presets={['1h', '6h', '24h', '7d', '30d']}
              allowAll={false}
              className="h-8"
            />
            {/* 自动刷新可暂停：正在看一张图的时候底下数字自己跳，比不刷新更烦人。 */}
            <Button variant="outline" size="sm" onClick={() => setLive((v) => !v)}>
              <HugeiconsIcon
                icon={live ? PauseIcon : PlayIcon}
                strokeWidth={2}
                className="size-3.5"
              />
              {live ? t('pause') : t('resume')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => void reload()} disabled={refreshing}>
              <HugeiconsIcon
                icon={refreshing ? Loading03Icon : RefreshCwIcon}
                strokeWidth={2}
                className={cn('size-3.5', refreshing && 'animate-spin')}
              />
              {c('refresh')}
            </Button>
          </div>
        }
      />

      {stats.error && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{stats.error}</AlertDescription>
        </Alert>
      )}

      {/* 数据的更新时间跟着数据走 */}
      {lastAt && (
        <p className="-mb-2 text-xs text-muted-foreground">
          {t('updatedAt', { time: new Date(lastAt).toLocaleTimeString() })}
        </p>
      )}

      <section aria-label={t('secKpi')}>
        <MetricGrid
          cards={[
            {
              id: 'total',
              title: t('kpiTotalTitle'),
              detail: t('kpiTotalLabel'),
              value: s ? s.total.toLocaleString() : '—',
              icon: <HugeiconsIcon icon={ShieldAlertIcon} strokeWidth={2} aria-hidden="true" />,
              sparkline: (s?.over_time ?? []).map((pt) => pt.count),
              tone: 'info',
            },
            {
              id: 'urgent',
              title: t('kpiUrgentTitle'),
              detail: t('kpiUrgentLabel'),
              value: s ? String(urgent) : '—',
              icon: <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} aria-hidden="true" />,
              badge: urgent > 0
                ? { label: t('kpiUrgentBadge'), tone: 'destructive', trend: 'up' }
                : { label: t('kpiClearBadge'), tone: 'success' },
              tone: urgent > 0 ? 'destructive' : 'success',
            },
            {
              id: 'baseline',
              title: t('kpiBaselineTitle'),
              detail: baselineFail.data === null ? t('kpiBaselineNever') : t('kpiBaselineLabel'),
              value: baselineFail.data === null ? '—' : String(baselineFail.data),
              icon: <HugeiconsIcon icon={ClipboardCheckIcon} strokeWidth={2} aria-hidden="true" />,
              badge: (baselineFail.data ?? 0) > 0 ? { label: t('kpiNeedsWork'), tone: 'warning' } : undefined,
              tone: (baselineFail.data ?? 0) > 0 ? 'warning' : 'success',
            },
            {
              id: 'platform',
              title: t('kpiPlatformTitle'),
              detail: t('kpiPlatformLabel'),
              value: platformBad.data === null ? '—' : String(platformBad.data),
              icon: <HugeiconsIcon icon={Activity02Icon} strokeWidth={2} aria-hidden="true" />,
              badge: (platformBad.data ?? 0) > 0 ? { label: t('kpiNeedsWork'), tone: 'warning' } : undefined,
              tone: (platformBad.data ?? 0) > 0 ? 'warning' : 'success',
            },
          ] satisfies MetricCardData[]}
        />
      </section>

      <section
        aria-label={t('secTimeline')}
        className="grid auto-rows-fr items-stretch gap-5 @4xl:grid-cols-3"
      >
        <div className="min-w-0 @4xl:col-span-2">
          <TrendCard
            className="h-full"
            title={t('timelineTitle')}
            points={(s?.over_time ?? []).map((p) => ({
              period: new Date(p.ts).toLocaleString(undefined, {
                month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
              }),
              value: p.count,
            }))}
            valueLabel={t('unitAlerts')}
            empty={t('noAlertsInWindow')}
          />
        </div>
        <div className="min-w-0">
          <MixDonut
            className="h-full"
            title={t('severityMix')}
            centerLabel={t('unitAlerts')}
            slices={(s?.by_severity ?? []).map((b) => ({
              key: b.key,
              name: severityLabel(b.key),
              count: b.count,
            }))}
            emptyText={t('noAlertsInWindow')}
          />
        </div>
      </section>

      <section
        aria-label={t('secLists')}
        className="grid auto-rows-fr items-stretch gap-5 @4xl:grid-cols-2"
      >
        <div className="min-w-0">
          <EntityList
            className="h-full"
            title={t('noisyTitle')}
            rows={(s?.by_rule ?? []).map((b) => ({
              id: b.key,
              title: b.key,
              meta: t('noisyMeta', { n: b.count.toLocaleString() }),
              /* 带上规则筛选跳过去 —— 这一格说的是「这条规则太吵」，点进去当然该
                 只看这条规则的告警，而不是从头翻整个列表。 */
              action: (
                <Button
                  variant="ghost"
                  size="sm"
                  render={<Link to="/alerts" search={{ rule: b.key }} />}
                >
                  {c('view')}
                </Button>
              ),
            }))}
            footer={
              (s?.by_rule ?? []).length === 0 ? (
                <span className="text-13 text-muted-foreground">{t('noAlertsInWindow')}</span>
              ) : undefined
            }
          />
        </div>

        <div className="min-w-0">
          <RecentAlertsGrid
            title={t('recentTitle')}
            alerts={recent.data ?? []}
            emptyText={t('noAlertsInWindow')}
            actionLabel={t('goTriage')}
          />
        </div>
      </section>

      <section
        aria-label={t('secArchive')}
        className="flex flex-wrap items-center gap-2 text-12 text-muted-foreground"
      >
        <HugeiconsIcon icon={TaskDone02Icon} strokeWidth={2} className="size-3.5" />
        {t('archivedCount', { n: analyses.data ?? '—' })}
        <Button variant="ghost" size="sm" render={<Link to="/analysis" />}>
          {t('goArchive')}
        </Button>
      </section>
    </div>
  )
}

export default PosturePage

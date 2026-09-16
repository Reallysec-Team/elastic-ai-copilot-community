import { useEffect, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  Activity02Icon, AiBrain01Icon, AlertCircleIcon, Loading03Icon,
} from '@hugeicons/core-free-icons'

import { api } from '@/lib/api'
import { Badge } from '@/components/reui/badge'
import {
  Frame, FrameHeader, FramePanel, FrameTitle,
} from '@/components/reui/frame'
import { Separator } from '@/components/ui/separator'
import { useT } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'
import { useIsAdmin } from '@/components/gated-button'
import { aiSettingsCopy } from '@/locales/aiSettings'
import { toMs } from '@/lib/history'

/*
 * AI 运维概览 —— 版式照 tempo 的 `features/ai-ops`，只留指标卡那一段（链路和
 * 活动折线见下方注释：一个和「模型路由」重复，一个和调用审计重复），数据接
 * 本产品自己的两个来源：
 *   `/api/llm/providers`  每个 provider 的 total_calls / total_failures /
 *                         consec_failures / last_ok_at / last_fail_at / last_error
 *   `/api/audit`          过去 24 小时的调用直方图、失败数、p50/p95 耗时
 *
 * **和 tempo 的一处实质差别：它的第三块是 Token Activity，本产品画不出来。**
 * 审计事件里没有 token 用量 —— 流式响应的 `usage` 拿到了但没落审计索引。所以这里
 * 用同一个版式画「调用活动」（总调用 / 失败两条线）。要真画 token，得先给
 * `backend/audit.py` 的事件加 usage 字段，而且只对加完之后的数据生效。
 *
 * 「故障转移链路」也不是 tempo 那种事件流：本产品没有记录「A 挂了转到 B」的事件，
 * 只有每个 provider 身上的累计计数和最后一次错误。所以这里画的是**当前这条链路的
 * 状态**（按路由顺序：主 → 备 → 备），而不是历史事件 —— 它回答的是同一个问题
 * 「现在轮到谁、上一个为什么不行」，但不假装有历史。
 */

export type Provider = {
  id: string
  model: string
  enabled: boolean
  tags?: string[]
  consec_failures?: number
  total_calls?: number
  total_failures?: number
  last_ok_at?: number | string | null
  last_fail_at?: number | string | null
  last_error?: string | null
}

export type AuditSummary = {
  over_time: Array<{ ts: string; count: number; failed: number }>
  duration_p50_ms: number | null
  duration_p95_ms: number | null
}

/** 过去 24 小时。和调用审计页的默认窗口一致。 */
function since24h(): string {
  return new Date(Date.now() - 24 * 3600_000).toISOString()
}

/**
 * 这一页三块（指标卡、故障转移链、调用活动）共用同一份数据；hook 拉一次，
 * 页面分发，免得三块各发一遍 /api/llm/providers。
 */
export function useAiOpsData() {
  // 调用量那一路来自 GET /api/audit/events，那条要管理员。非管理员拿到的是 403，
  // 而 403 被折进 `auditOff` 就成了「审计没开」——一句不真的话：审计开着，是这个
  // 账号读不到。所以这里根本不发那个请求，卡片直接说「仅管理员可见」。
  const isAdmin = useIsAdmin()
  const [providers, setProviders] = useState<Provider[] | null>(null)
  const [summary, setSummary] = useState<AuditSummary | null>(null)
  const [auditOff, setAuditOff] = useState(false)

  useEffect(() => {
    let alive = true
    void api.llmProviders()
      .then((r) => { if (alive) setProviders(r.providers as Provider[]) })
      .catch(() => { if (alive) setProviders([]) })
    // 审计可能整个是关的（系统设置里的开关）。取不到就不画调用那一路，
    // 而不是画成 0 —— 「没记」和「没有调用」是两个答案。
    if (isAdmin) {
      void api.auditEvents({ from_ts: since24h(), size: 1 })
        .then((r) => {
          if (!alive) return
          if (r.audit_enabled === false) setAuditOff(true)
          if (r.summary) setSummary(r.summary as AuditSummary)
        })
        .catch(() => { if (alive) setAuditOff(true) })
    }
    return () => { alive = false }
  }, [isAdmin])

  return { isAdmin, providers, summary, auditOff }
}

export function AiOpsOverview({ data }: { data: ReturnType<typeof useAiOpsData> }) {
  const t = useT(aiSettingsCopy)
  const c = useT(commonCopy)
  const { isAdmin, providers, summary, auditOff } = data

  if (!providers) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
        <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />
        {t('ovLoading')}
      </div>
    )
  }

  const enabled = providers.filter((p) => p.enabled)
  const calls = enabled.reduce((n, p) => n + (p.total_calls ?? 0), 0)
  const fails = enabled.reduce((n, p) => n + (p.total_failures ?? 0), 0)
  // 一次都没调用过时不写「100%」—— 那是「还没试过」，不是「全都成功」。
  const okRate = calls > 0 ? ((calls - fails) / calls) * 100 : null
  const failing = enabled.filter((p) => (p.consec_failures ?? 0) >= 1)

  const windowCalls = summary?.over_time.reduce((n, b) => n + b.count, 0) ?? 0
  const windowFailed = summary?.over_time.reduce((n, b) => n + b.failed, 0) ?? 0

  return (
    <div className="flex w-full flex-col gap-5">
      {/* 指标卡之间 gap-6，比区块之间的 gap-5 大一档 —— 模板的做法。容器查询靠
          页根那层 `@container`，这里不再套一层。 */}
      <div className="grid auto-rows-fr items-stretch gap-6 @4xl:grid-cols-3">
        <MetricCard
          title={t('ovAvailability')}
          icon={<HugeiconsIcon icon={AiBrain01Icon} strokeWidth={2} aria-hidden="true" />}
          value={okRate == null ? '—' : okRate.toFixed(2)}
          valueFaint={okRate == null ? '' : '%'}
          badge={
            okRate == null
              ? { label: t('ovNoCallsYet'), variant: 'secondary' as const }
              : failing.length > 0
                ? { label: t('ovFailingN', { n: failing.length }), variant: 'destructive-light' as const }
                : { label: t('ovAllOk'), variant: 'success-light' as const }
          }
          /* provider 的计数器随网关重启清零，右边那张「调用量」读的是审计索引、
             跨重启。两张卡一个说「还没调用」一个说 291 次，看着像打架 —— 把口径
             写在描述里。 */
          description={t('ovEnabledOf', { enabled: enabled.length, total: providers.length })}
          comparisonLabel={t('ovFailoverChain')}
          comparisonValue={
            enabled.length > 0 ? t('ovChainLevels', { n: enabled.length }) : t('ovNoChain')
          }
        />

        <MetricCard
          title={t('ovCalls24h')}
          icon={<HugeiconsIcon icon={Activity02Icon} strokeWidth={2} aria-hidden="true" />}
          value={auditOff || !isAdmin ? '—' : windowCalls.toLocaleString()}
          valueFaint=""
          badge={
            !isAdmin
              ? { label: c('adminOnlyShort'), variant: 'secondary' as const }
              : auditOff
                ? { label: t('ovAuditOff'), variant: 'secondary' as const }
                : windowFailed > 0
                  ? { label: t('ovFailedN', { n: windowFailed }), variant: 'warning-light' as const }
                  : { label: t('ovNoFailures'), variant: 'success-light' as const }
          }
          description={
            !isAdmin ? c('adminOnlyView') : auditOff ? t('ovAuditOffDesc') : t('ovFromAudit')
          }
          comparisonLabel={t('ovP95')}
          // 没记到耗时不写 0：「没记」和「0 毫秒」是两个答案。
          comparisonValue={
            summary?.duration_p95_ms == null
              ? '—'
              : `${Math.round(summary.duration_p95_ms)} ms`
          }
        />

        <MetricCard
          title={t('ovTotalFailures')}
          icon={<HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} aria-hidden="true" />}
          value={fails.toLocaleString()}
          valueFaint={calls > 0 ? ` / ${calls.toLocaleString()}` : ''}
          badge={
            failing.length > 0
              ? { label: t('ovHasConsecutive'), variant: 'destructive-light' as const }
              : { label: t('ovNoConsecutive'), variant: 'success-light' as const }
          }
          description={t('ovTotalDesc')}
          comparisonLabel={t('ovLastFailure')}
          comparisonValue={latestFailure(providers) ?? t('ovNoRecord')}
        />
      </div>

      {/* 故障转移链和调用活动折线在 AiSettingsPage 里紧跟这一排（solution-ai-ops-1
          的第二行）；它们读的是同一份 useAiOpsData。 */}
    </div>
  )
}

/* ---------------- 指标卡 ---------------- */

function MetricCard({
  title, icon, value, valueFaint, badge, description, comparisonLabel, comparisonValue,
}: {
  title: string
  icon: React.ReactNode
  value: string
  valueFaint: string
  badge: { label: string; variant: 'secondary' | 'success-light' | 'warning-light' | 'destructive-light' }
  description: string
  comparisonLabel: string
  comparisonValue: string
}) {
  return (
    <Frame dense className="h-full min-w-0">
      {/* `flex-wrap` 是承重的：标题列是唯一能伸缩的子项，不给 wrap 窄屏下会被压扁。 */}
      <FrameHeader className="flex-row flex-wrap items-center justify-between gap-3 pb-[calc(var(--frame-panel-header-py)+2px)]">
        <FrameTitle className="text-balance">{title}</FrameTitle>
        <div className="[&_svg]:size-4 [&_svg]:text-muted-foreground">{icon}</div>
      </FrameHeader>
      <FramePanel className="flex flex-1 flex-col gap-2.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="text-2xl font-medium tracking-tight tabular-nums text-foreground">
            {value}
            <span className="font-medium text-muted-foreground/40">{valueFaint}</span>
          </span>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
        <Separator />
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">{description}</div>
          <div className="text-xs text-muted-foreground">
            {comparisonLabel}:{' '}
            <span className="font-medium text-foreground">{comparisonValue}</span>
          </div>
        </div>
      </FramePanel>
    </Frame>
  )
}

function latestFailure(providers: Provider[]): string | null {
  const stamps = providers
    .map((p) => toMs(p.last_fail_at))
    .filter((v): v is number => v != null)
    .sort((a, b) => a - b)
  if (stamps.length === 0) return null
  // 固定 MM-DD HH:mm，不走 toLocaleString —— 那个跟着浏览器语言走，
  // 同一台机器上会时而 "9/5/2026, 7:55:00 PM" 时而 "2026/9/5 19:55"。
  const d = new Date(stamps[stamps.length - 1])
  const p2 = (n: number) => String(n).padStart(2, '0')
  return `${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`
}


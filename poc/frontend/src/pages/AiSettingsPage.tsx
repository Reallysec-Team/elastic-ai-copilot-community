import { useMemo } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { Activity02Icon, AlertCircleIcon } from '@hugeicons/core-free-icons'

import { useT } from '@/lib/i18n'
import { aiSettingsCopy } from '@/locales/aiSettings'
import { AiOpsOverview, useAiOpsData } from '@/components/ai/AiOpsOverview'
import { FailoverChain } from '@/components/ai/FailoverChain'
import { ProvidersCard } from '@/components/ai/ProvidersCard'
import { EmbeddingCard } from '@/components/ai/EmbeddingCard'
import { TrendCard, type TrendStat } from '@/components/blocks/chart-18/components/trend-card'
import { PageHeader } from '@/components/shell/page-header'

/*
 * AI 配置 — 模型接入、路由和 RAG 向量配置的总入口。
 *
 * 版式照 `@reui/solution-ai-ops-1`：指标卡一排 → 左「故障转移链」右「调用活动」
 * → 路由表（这里是可编辑的 ProvidersCard，照 settings-8）→ Embedding。
 * 没照搬的：Token Activity —— 审计事件里没有 token 用量，画的是调用 / 失败两条线。
 */
export default function AiSettingsPage() {
  const t = useT(aiSettingsCopy)
  const data = useAiOpsData()
  const { summary, auditOff, isAdmin } = data

  const points = useMemo(
    () => (summary?.over_time ?? []).map((b) => ({ period: hourLabel(b.ts), value: b.count })),
    [summary],
  )
  const stats = useMemo<TrendStat[]>(() => {
    const calls = summary?.over_time.reduce((n, b) => n + b.count, 0) ?? 0
    const failed = summary?.over_time.reduce((n, b) => n + b.failed, 0) ?? 0
    return [
      { id: 'calls', label: t('actCalls'), value: calls.toLocaleString(), note: t('actCallsUnit'),
        icon: <HugeiconsIcon icon={Activity02Icon} strokeWidth={2} aria-hidden="true" /> },
      { id: 'failed', label: t('actFailed'), value: failed.toLocaleString(),
        note: calls > 0 ? `${((failed / calls) * 100).toFixed(1)}%` : '—',
        icon: <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} aria-hidden="true" /> },
    ]
  }, [summary, t])

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader title={t('title')} />
      <section aria-label={t('secOverview')}>
        <AiOpsOverview data={data} />
      </section>
      <section aria-label={t('secChain')} className="grid auto-rows-fr items-stretch gap-5 @4xl:grid-cols-3">
        <div className="min-w-0">
          <FailoverChain providers={data.providers ?? []} />
        </div>
        <div className="min-w-0 @4xl:col-span-2">
          <TrendCard
            className="h-full min-w-0"
            title={t('actTitle')}
            stats={stats}
            points={points}
            valueLabel={t('actCallsUnit')}
            empty={!isAdmin ? t('actAdminOnly') : auditOff ? t('actAuditOff') : t('actNoCalls')}
          />
        </div>
      </section>
      <section aria-label={t('secRouting')}>
        <ProvidersCard />
      </section>
      <section aria-label={t('secEmbedding')}>
        <EmbeddingCard />
      </section>
    </div>
  )
}

function hourLabel(ts: string): string {
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? ts : `${String(d.getHours()).padStart(2, '0')}:00`
}

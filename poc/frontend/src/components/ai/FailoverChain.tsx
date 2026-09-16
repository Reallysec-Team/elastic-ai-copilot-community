import { HugeiconsIcon } from '@hugeicons/react'
import { AlertCircleIcon, CheckmarkCircle02Icon, PauseIcon } from '@hugeicons/core-free-icons'

import { cn } from '@/lib/utils'
import { useT } from '@/lib/i18n'
import { relativeTime, toMs } from '@/lib/history'
import { aiSettingsCopy } from '@/locales/aiSettings'
import { Badge } from '@/components/reui/badge'
import { Frame, FrameDescription, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import {
  Timeline, TimelineContent, TimelineHeader, TimelineIndicator, TimelineItem, TimelineSeparator,
  TimelineTitle,
} from '@/components/reui/timeline'
import type { Provider } from './AiOpsOverview'

/*
 * 故障转移链 —— 照 `@reui/solution-ai-ops-1` 的 Provider Failover 时间线。
 *
 * 那个 block 画的是一串历史事件（谁在几点接手）；本产品没有记录「A 挂了转到 B」，
 * 只有每个 provider 身上的连续失败数和最后一次成功 / 出错。所以这里画的是**当前
 * 这条链路**（按路由顺序：主 → 备 → 备）：现在轮到谁、上一个为什么不行。
 * 它不假装有历史。要改顺序 / 开关去下面的「模型路由」。
 */

type Health = 'ok' | 'failing' | 'off'

function healthOf(p: Provider): Health {
  if (!p.enabled) return 'off'
  return (p.consec_failures ?? 0) >= 1 ? 'failing' : 'ok'
}

export function FailoverChain({ providers }: { providers: Provider[] }) {
  const t = useT(aiSettingsCopy)
  const enabled = providers.filter((p) => p.enabled)
  // 路由器按顺序试，第一个健康的就是「当前在用」。
  const activeIdx = providers.findIndex((p) => healthOf(p) === 'ok')
  const failing = enabled.filter((p) => healthOf(p) === 'failing').length

  return (
    <Frame dense className="h-full w-full min-w-0">
      <FrameHeader className="gap-0.5">
        <FrameTitle className="text-balance">{t('chainTitle')}</FrameTitle>
        <FrameDescription className="text-xs text-pretty">
          {providers.length === 0
            ? t('chainEmpty')
            : failing > 0
              ? t('chainDescFailing', { n: enabled.length, f: failing })
              : t('chainDescOk', { n: enabled.length })}
        </FrameDescription>
      </FrameHeader>
      <FramePanel className="flex flex-1 flex-col">
        {providers.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">{t('chainEmpty')}</p>
        ) : (
          <Timeline value={activeIdx + 1}>
            {providers.map((p, i) => {
              const h = healthOf(p)
              const isActive = i === activeIdx
              return (
                <TimelineItem key={p.id} step={i + 1} className="not-last:pb-5">
                  <TimelineHeader className="items-center">
                    <TimelineSeparator className="bg-border group-data-[orientation=vertical]/timeline:-left-6 group-data-[orientation=vertical]/timeline:h-[calc(100%-1.25rem-0.5rem)] group-data-[orientation=vertical]/timeline:translate-y-6" />
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <TimelineTitle className="truncate text-sm font-semibold">{p.id}</TimelineTitle>
                      {isActive && <Badge variant="primary-light" size="sm">{t('chainActive')}</Badge>}
                      {h === 'failing' && <Badge variant="destructive-light" size="sm">{t('chainFailing', { n: p.consec_failures ?? 0 })}</Badge>}
                      {h === 'off' && <Badge variant="secondary" size="sm">{t('prDisabled')}</Badge>}
                    </div>
                    <TimelineIndicator
                      className={cn(
                        'flex size-5 items-center justify-center border-none group-data-[orientation=vertical]/timeline:-left-6',
                        h === 'ok' && 'bg-success/15 text-success',
                        h === 'failing' && 'bg-destructive/15 text-destructive',
                        h === 'off' && 'bg-muted text-muted-foreground',
                        isActive && 'ring-2 ring-primary/30',
                      )}
                    >
                      <HugeiconsIcon
                        icon={h === 'ok' ? CheckmarkCircle02Icon : h === 'failing' ? AlertCircleIcon : PauseIcon}
                        strokeWidth={2}
                        className="size-3"
                        aria-hidden="true"
                      />
                    </TimelineIndicator>
                  </TimelineHeader>
                  <TimelineContent className="mt-1 flex flex-col gap-0.5 text-xs">
                    <span className="truncate font-mono">{p.model}</span>
                    <span>
                      {toMs(p.last_ok_at) != null
                        ? t('chainLastOk', { when: relativeTime(toMs(p.last_ok_at)!) })
                        : t('chainNeverCalled')}
                    </span>
                    {h === 'failing' && p.last_error && (
                      <span className="line-clamp-2 text-destructive" title={p.last_error}>{p.last_error}</span>
                    )}
                  </TimelineContent>
                </TimelineItem>
              )
            })}
          </Timeline>
        )}
      </FramePanel>
    </Frame>
  )
}

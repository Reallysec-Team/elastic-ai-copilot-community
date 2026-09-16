import { useEffect, useState } from 'react'
import { Link } from '@tanstack/react-router'

import { api, QUOTA_MAYBE_SPENT_EVENT } from '@/lib/api'
import { useT } from '@/lib/i18n'
import { shellCopy } from '@/locales/shell'
import { Frame, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { Progress } from '@/components/ui/progress'
import { SidebarGroup } from '@/components/ui/sidebar'

/*
 * roster's SpendingLimit slot (`app/layouts/spending-limit.tsx`), with this
 * product's meter in it: an unactivated deployment runs on a per-day call
 * quota, which is the same reading — a budget consumed against a ceiling that
 * re-baselines on a cycle.
 *
 * It replaces a chip in the top bar. A chip reading "试用 37/50" says how many
 * are left; the meter says how much of the day is gone, which is the thing that
 * decides whether an operator starts a batch triage now or activates first.
 *
 * Renders nothing on an activated license — there is no ceiling to report.
 */
export function TrialQuotaMeter() {
  const t = useT(shellCopy)
  const [quota, setQuota] = useState<{
    remaining: number
    limit: number
    active: boolean
    reset_at_local?: string
    timezone?: string
  } | null>(null)

  useEffect(() => {
    let alive = true
    const load = () => {
      void api
        .licenseQuota()
        .then((r) => { if (alive) setQuota(r) })
        .catch(() => {})
    }
    load()
    // 每花掉一次额度就重新拉。原来只在挂载时拉一次，于是跑几条查询之后这里还写着
    // 进页面那一刻的数字 —— 而这个数字存在的意义就是让人知道还剩多少。
    window.addEventListener(QUOTA_MAYBE_SPENT_EVENT, load)
    return () => {
      alive = false
      window.removeEventListener(QUOTA_MAYBE_SPENT_EVENT, load)
    }
  }, [])

  if (!quota || !quota.active || quota.limit <= 0) return null

  const used = Math.max(0, quota.limit - quota.remaining)
  const usedPct = Math.round((used / quota.limit) * 100)
  const leftPct = 100 - usedPct
  // Same threshold the chip used: the last tenth is when activation stops being
  // something to get around to.
  const low = quota.remaining <= Math.max(1, Math.floor(quota.limit * 0.1))

  return (
    <SidebarGroup className="overflow-hidden group-data-[collapsible=icon]:hidden">
      {/* 导航栏改成浅色之后，这张卡也跟着走 token。它原来是一整块写死的
          zinc-900，为的是在深色栏子里不发亮；换成浅色栏子后它反过来成了整个
          侧栏里唯一一块黑底，比它要报的事情本身响得多。 */}
      <Frame spacing="xs" dense className="shrink-0 overflow-hidden">
        <FrameHeader>
          <FrameTitle className="text-xs text-warning">{t('quotaTitle')}</FrameTitle>
        </FrameHeader>
        <FramePanel className="space-y-2">
          <p className="text-xs leading-snug text-muted-foreground">
            {/* 时区要显式说出来：这里的「每天」是网关的时区，不是看的人所在的时区。
                老网关不回这两个字段时按 UTC 0 点说，和它当时的行为一致。 */}
            {t('quotaRemaining', {
              remaining: quota.remaining,
              limit: quota.limit,
              reset: quota.reset_at_local ?? '00:00',
              tz: quota.timezone ?? 'UTC',
            })}
          </p>

          <div className="relative h-1.5 overflow-hidden rounded-sm bg-muted/55">
            <div
              className="pointer-events-none absolute inset-0 text-muted-foreground opacity-20"
              aria-hidden="true"
              style={{
                backgroundImage:
                  'repeating-linear-gradient(-45deg, currentColor 0, currentColor 1px, transparent 0, transparent 4px)',
              }}
            />
            <Progress
              value={usedPct}
              className={`absolute inset-0 gap-0 **:data-[slot=progress-indicator]:rounded-none **:data-[slot=progress-track]:h-full **:data-[slot=progress-track]:rounded-none **:data-[slot=progress-track]:bg-transparent ${
                low
                  ? '**:data-[slot=progress-indicator]:bg-destructive'
                  : '**:data-[slot=progress-indicator]:bg-success'
              }`}
            />
          </div>

          <div className="flex items-center justify-between text-xs leading-none text-muted-foreground">
            <div className="flex items-center gap-1">
              <span className="font-semibold text-foreground">{usedPct}%</span>
              <span>{t('quotaUsed')}</span>
            </div>
            <Link to="/license" className="underline-offset-2 hover:text-foreground hover:underline">
              {t('goActivate')}
            </Link>
          </div>
          <span className="sr-only">{t('quotaLeft', { pct: leftPct })}</span>
        </FramePanel>
      </Frame>
    </SidebarGroup>
  )
}

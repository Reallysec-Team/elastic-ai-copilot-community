/*
 * 「深度思考」开关：一个账号级偏好，智能查询 / 研判 / 规则副驾 / Offense 调查
 * 共用一份。开着 → 请求带 reasoning: 'on'，模型充分推理（准，但等 1–2 分钟）；
 * 关着 → 'off'，不推理（几秒出结果）。默认关：这几步的输出格式都是死的，
 * 长链推理换不来准确率（2026-09-18 实测 ark-code-latest：研判 high 900s 不回，
 * low 66s / 30 簇全评）。管理员在 AI 设置里给 provider 设的 reasoning 覆盖
 * 仍压过这个开关（后端 llm_reasoning.resolve）。
 *
 * 偏好走 prefs（localStorage + 服务端镜像），订阅方式和头像一样：
 * useSyncExternalStore + PREFS_EVENT，四个页面同时变。
 */
import { useSyncExternalStore } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { Brain02Icon } from '@hugeicons/core-free-icons'

import { Toggle } from '@/components/ui/toggle'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useT } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'
import { getPrefs, savePref, PREFS_EVENT } from '@/lib/prefs'
import { cn } from '@/lib/utils'

export type Reasoning = 'on' | 'off'

function subscribe(cb: () => void): () => void {
  window.addEventListener(PREFS_EVENT, cb)
  return () => window.removeEventListener(PREFS_EVENT, cb)
}

/** 当前的深度思考偏好；请求体直接带 `reasoning: useThinking()`。 */
export function useThinking(): Reasoning {
  return useSyncExternalStore(
    subscribe,
    () => (getPrefs().thinking === 'on' ? 'on' : 'off'),
    () => 'off',
  )
}

export function ThinkingToggle({ className }: { className?: string }) {
  const c = useT(commonCopy)
  const on = useThinking() === 'on'
  return (
    <TooltipProvider delay={150}>
      <Tooltip>
        <TooltipTrigger
          render={
            <Toggle
              variant="outline"
              size="sm"
              pressed={on}
              onPressedChange={(next) => savePref({ thinking: next ? 'on' : 'off' })}
              aria-label={c('thinkingToggle')}
              className={cn(
                'rounded-full text-12',
                on && 'border-primary/40 bg-primary/10 text-primary aria-pressed:bg-primary/10',
                className,
              )}
            />
          }
        >
          <HugeiconsIcon icon={Brain02Icon} strokeWidth={2} className="size-3.5" />
          {c('thinkingToggle')}
        </TooltipTrigger>
        <TooltipContent side="top">{on ? c('thinkingOnHint') : c('thinkingOffHint')}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

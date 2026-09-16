import { HugeiconsIcon } from '@hugeicons/react'
import { Cancel01Icon, Loading03Icon, TriangleAlertIcon } from '@hugeicons/core-free-icons'

import { useT } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { commonCopy } from '@/locales/common'

/*
 * 一块内容正在加载 / 加载失败时占位的那两行。
 *
 * 这两个形状在基线的三个 tab、实时告警、告警摄取配置里各写过一份，字面一模一样
 * ——「居中的转圈 + 加载中…」和「浅红底 + 三角 + 一句错误」。写成组件不是为了少
 * 打几个字：其中一份的浅红底当初写的是 `[box-shadow:0_0_0_1px_rgba(255,91,79,…)]`
 * 这种硬编码 rgba，主题切到深色时不跟着走，而另外几份是对的 —— 五份各自演化正是
 * 这种偏差的来源。
 *
 * `EmptyState` 那类每页定制的空态不在此列：那是有意为之的（每页的空态要说的是
 * 这一页特有的下一步），合并了反而变成一句谁都不针对的废话。
 */

export function BlockLoading({ className }: { className?: string }) {
  const c = useT(commonCopy)
  return (
    <div
      role="status"
      className={cn('py-16 text-center text-sm text-muted-foreground', className)}
    >
      <HugeiconsIcon
        icon={Loading03Icon}
        strokeWidth={2}
        aria-hidden="true"
        className="mx-auto mb-2 size-5 animate-spin"
      />
      {c('loading')}…
    </div>
  )
}

export function BlockError({
  message,
  onRetry,
  onDismiss,
  className,
}: {
  message: string
  /** 给了就显示一个「重试」；不给就只是一条说明。 */
  onRetry?: () => void
  /** 给了就显示一个关掉它的叉。 */
  onDismiss?: () => void
  className?: string
}) {
  const c = useT(commonCopy)
  return (
    <div
      role="alert"
      className={cn(
        'flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive',
        className,
      )}
    >
      <HugeiconsIcon
        icon={TriangleAlertIcon}
        strokeWidth={2}
        aria-hidden="true"
        className="size-4 shrink-0"
      />
      <span className="flex-1">{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 underline underline-offset-2 hover:opacity-80"
        >
          {c('retry')}
        </button>
      )}
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label={c('close')}
          className="shrink-0 rounded p-0.5 hover:opacity-70"
        >
          <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} className="size-3.5" />
        </button>
      )}
    </div>
  )
}

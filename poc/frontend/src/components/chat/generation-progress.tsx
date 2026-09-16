/*
 * 生成中的进度：理解问题 → 生成查询 → 执行，每段带已用秒数。
 *
 * 以前生成中只有一行「正在把这句话翻译成查询…」转圈。思考模型一想 20 秒，
 * 用户看到的是一动不动的转圈，分不清是慢还是死了。这里把三段拆开、各自计时，
 * 供应商吐推理增量（豆包 / DeepSeek / Qwen 的 reasoning_content）就折叠成一行
 * 「AI 在想：…」滚动着显示——同样 20 秒，看得见进展和看不见，体感差一倍。
 *
 * 什么时候进入哪段由 Turn 上的时间戳决定（ChatPage 写）：startedAt 一定有，
 * writingAt = 第一个正文字符到达，phase=executing = 查询在跑。
 */
import { useEffect, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { ChevronDownIcon, ChevronRightIcon, Loading03Icon, Tick02Icon } from '@hugeicons/core-free-icons'

import { useT } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { chatCopy } from '@/locales/chat'

export interface GenerationProgressProps {
  /** 这一轮发出去的时刻（Date.now()）。 */
  startedAt: number
  /** 第一个正文字符到达的时刻；null = 还在想。 */
  writingAt: number | null
  /** 查询开始执行的时刻；null = 还没到执行。 */
  runningAt: number | null
  /** 模型的推理文本（累计）。空串 = 这家不吐推理，只显示计时。 */
  thinking: string
  scope: string
}

/** 每秒刷一次的「现在」。只在有活跃段时跑。 */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [active])
  return now
}

function secs(from: number, to: number): string {
  return `${Math.max(0, Math.round((to - from) / 1000))}s`
}

type StageStatus = 'pending' | 'active' | 'done'

function StageRow({
  status, label, elapsed, children,
}: {
  status: StageStatus
  label: string
  elapsed: string | null
  children?: React.ReactNode
}) {
  return (
    <li className="flex flex-col gap-1">
      <div
        className={cn(
          'flex items-center gap-2 text-13',
          status === 'pending' ? 'text-muted-foreground/60' : 'text-muted-foreground',
          status === 'active' && 'text-foreground',
        )}
      >
        <span className="inline-flex size-3.5 shrink-0 items-center justify-center">
          {status === 'active' && (
            <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" />
          )}
          {status === 'done' && (
            <HugeiconsIcon icon={Tick02Icon} strokeWidth={2.5} className="size-3.5 text-success" />
          )}
          {status === 'pending' && <span className="size-1.5 rounded-full bg-current" />}
        </span>
        <span>{label}</span>
        {elapsed && <span className="tabular-nums text-12 text-muted-foreground/80">{elapsed}</span>}
      </div>
      {children}
    </li>
  )
}

export function GenerationProgress({ startedAt, writingAt, runningAt, thinking, scope }: GenerationProgressProps) {
  const t = useT(chatCopy)
  const now = useNow(true)
  const [open, setOpen] = useState(false)

  const understand: StageStatus = writingAt || runningAt ? 'done' : 'active'
  const write: StageStatus = runningAt ? 'done' : writingAt ? 'active' : 'pending'
  const run: StageStatus = runningAt ? 'active' : 'pending'
  // 历史回放：查询是现成的，没有前两段可言，只剩执行。
  const replay = runningAt !== null && writingAt === null

  // 折叠态只露最后一截：推理文本是给人瞄一眼「它在看哪儿」的，不是拿来读的。
  const tail = thinking.length > 160 ? '…' + thinking.slice(-160) : thinking

  return (
    <ol className="space-y-1.5" aria-label={t('stageProgressAria')} aria-live="polite">
      {!replay && (
      <StageRow
        status={understand}
        label={t('stageUnderstand')}
        elapsed={secs(startedAt, writingAt ?? now)}
      >
        {thinking && (
          <div className="ml-5.5 text-12 text-muted-foreground">
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
              aria-expanded={open}
            >
              <HugeiconsIcon
                icon={open ? ChevronDownIcon : ChevronRightIcon}
                strokeWidth={2}
                className="size-3"
              />
              {t('stageThinkingLabel')}
              <span className="sr-only">{open ? t('stageThinkingHide') : t('stageThinkingShow')}</span>
            </button>
            {open ? (
              <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md bg-muted/50 p-2 font-sans text-12 leading-relaxed">
                {thinking}
              </pre>
            ) : (
              <span className="ml-1 line-clamp-1 break-all opacity-80" aria-hidden="true">
                {tail.replace(/\s+/g, ' ')}
              </span>
            )}
          </div>
        )}
      </StageRow>
      )}
      {!replay && (
      <StageRow
        status={write}
        label={t('stageWrite')}
        elapsed={writingAt ? secs(writingAt, runningAt ?? now) : null}
      />
      )}
      <StageRow
        status={run}
        label={scope ? t('stageRun', { scope }) : t('stageRunPlain')}
        elapsed={runningAt ? secs(runningAt, now) : null}
      />
    </ol>
  )
}

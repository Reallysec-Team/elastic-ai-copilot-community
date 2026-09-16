import { useEffect, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import { Cancel01Icon, Delete02Icon, RotateCcwIcon } from '@hugeicons/core-free-icons'
import { Sheet, SheetClose, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import {
  clearHistory,
  deleteHistory,
  loadHistory,
  relativeTime,
  setPending,
  type HistoryEntry,
} from '@/lib/history'
import { useT } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { commonCopy } from '@/locales/common'
import { componentsCopy, type ComponentsKey } from '@/locales/components'

export const OPEN_HISTORY_EVENT = 'rst-open-history'

/*
 * History drawer — really slides in from the right, on the Base UI Sheet
 * primitive (it used to be a centred Dialog wearing a drawer's comment). Stores
 * up to 30 entries (HISTORY_MAX). Replay sets pending question/index in
 * localStorage and navigates to the 查询页 (ChatPage) which picks them up on
 * mount.
 *
 * The trigger lives in the shell header now and reaches this over an event, the
 * same way the ⌘K button reaches the command palette. It used to be a floating
 * pill in the bottom-right corner: atlas-admin has no floating action button
 * anywhere, and on narrow screens that pill had to be lifted above ChatPage's
 * fixed composer or it covered 发送.
 */

export function HistoryDrawer() {
  const t = useT(componentsCopy)
  const c = useT(commonCopy)
  const [open, setOpen] = useState(false)
  const [entries, setEntries] = useState<HistoryEntry[]>([])
  const navigate = useNavigate()

  useEffect(() => {
    const refresh = () => setEntries(loadHistory())
    refresh()
    const openIt = () => setOpen(true)
    window.addEventListener('rst-history-changed', refresh)
    window.addEventListener('storage', refresh)
    window.addEventListener(OPEN_HISTORY_EVENT, openIt)
    return () => {
      window.removeEventListener('rst-history-changed', refresh)
      window.removeEventListener('storage', refresh)
      window.removeEventListener(OPEN_HISTORY_EVENT, openIt)
    }
  }, [])

  function onReplay(e: HistoryEntry) {
    // Pass the cached DSL through so 查询页 (ChatPage) can skip the LLM call.
    setPending({
      question: e.question,
      index: e.index,
      dsl: e.dsl ?? null,
      confidence: e.confidence ?? null,
      prompt_version: e.prompt_version ?? null,
    })
    setOpen(false)
    navigate({ to: '/' })
  }

  return (
    <>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side="right"
          variant="inset"
          showCloseButton={false}
          className={cn(
            'w-[min(32rem,calc(100vw-2rem))] gap-0 bg-card',
            '[box-shadow:var(--shadow-pop)] motion-reduce:transition-none',
          )}
        >
          <header className="flex items-start justify-between gap-4 px-5 pt-5 pb-4 [box-shadow:0_1px_0_var(--color-line)_inset]">
            <div className="flex flex-col gap-1">
              <span className="label-mono">{t('recentLocal', { n: entries.length })}</span>
              <SheetTitle className="text-base font-semibold text-foreground">
                {t('queryHistory')}
              </SheetTitle>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {entries.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    if (window.confirm(t('confirmClearHistory'))) clearHistory()
                  }}
                >
                  <HugeiconsIcon icon={Delete02Icon} strokeWidth={2} className="size-3.5" />
                  {t('clearHistory')}
                </Button>
              )}
              <SheetClose
                aria-label={c('close')}
                className={cn(
                  'inline-flex size-7 items-center justify-center rounded-md',
                  'text-fg-muted transition-colors hover:bg-accent hover:text-foreground',
                  'focus-visible:outline-none focus-visible:[box-shadow:var(--shadow-focus)]',
                )}
              >
                <HugeiconsIcon icon={Cancel01Icon} strokeWidth={2} className="size-4" />
              </SheetClose>
            </div>
          </header>
          <ScrollArea className="min-h-0 flex-1">
            {entries.length === 0 ? (
              <div className="flex flex-col items-center gap-3 py-16 text-center">
                <span className="label-mono">{t('emptyShort')}</span>
                <p className="max-w-[280px] text-14 leading-[1.55] text-muted-foreground">
                  {t('historyEmpty')}
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-line">
                {entries.map((e) => (
                  <Row key={e.id} entry={e} onReplay={() => onReplay(e)} />
                ))}
              </ul>
            )}
          </ScrollArea>
        </SheetContent>
      </Sheet>
    </>
  )
}

const CONFIDENCE_KEY: Record<string, ComponentsKey> = {
  high: 'confHigh',
  medium: 'confMedium',
  low: 'confLow',
}

function Row({
  entry,
  onReplay,
}: {
  entry: HistoryEntry
  onReplay: () => void
}) {
  const t = useT(componentsCopy)
  const c = useT(commonCopy)
  return (
    <li className="group flex items-start gap-3 px-5 py-3 transition-colors hover:bg-accent">
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-baseline gap-2">
          <code className="font-mono text-11 text-muted-foreground truncate">
            {entry.index}
          </code>
          <span className="label-mono shrink-0">{relativeTime(entry.ts)}</span>
          {/* 原来直接把 'high' 打在每行末尾，没有名目也没翻译 —— 读起来像个标签
              而不是「这条生成的置信度」。 */}
          {entry.confidence && (
            <span className="label-mono shrink-0 text-fg-faint">
              {t('confidence', {
                level: CONFIDENCE_KEY[entry.confidence]
                  ? t(CONFIDENCE_KEY[entry.confidence])
                  : entry.confidence,
              })}
            </span>
          )}
        </div>
        <p className="line-clamp-2 text-13 leading-[1.5] text-foreground">
          {entry.question}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        <button
          onClick={onReplay}
          className={cn(
            'inline-flex items-center gap-1 rounded-md px-2 py-1',
            'bg-card text-12 font-medium text-foreground',
            '[box-shadow:var(--shadow-ring-light)]',
            'transition-shadow hover:[box-shadow:var(--shadow-ring)]',
          )}
          title={t('replayTitle')}
        >
          <HugeiconsIcon icon={RotateCcwIcon} strokeWidth={2} className="size-3" />
          {t('replay')}
        </button>
        <button
          onClick={() => deleteHistory(entry.id)}
          className={cn(
            'inline-flex size-6 items-center justify-center rounded-md',
            'text-muted-foreground hover:bg-destructive-subtle hover:text-destructive',
          )}
          title={c('delete')}
        >
          <HugeiconsIcon icon={Delete02Icon} strokeWidth={2} className="size-3.5" />
        </button>
      </div>
    </li>
  )
}

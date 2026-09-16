import { useEffect, useState, type ReactNode } from "react"
import { translate } from '@/lib/i18n'
import { componentsCopy } from '@/locales/components'
import { createPortal } from "react-dom"
import { Badge } from "@/components/reui/badge"

import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Spinner } from "@/components/ui/spinner"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { ChatThread } from "./chat-thread"
import { Composer } from "./composer"
import type {
  StarterCategory,
  ThreadRecord,
  TranscriptRecord,
} from "./data"
import { HugeiconsIcon } from '@hugeicons/react'
import { ChevronDownIcon, PlusIcon } from '@hugeicons/core-free-icons'

/** Switcher tabs. `全部` leads and stays the default, so the whole history is
    still one scan and the other three narrow it rather than hide it. */
const THREAD_TABS = [
  { id: "all", label: translate(componentsCopy, 'threadAll') },
  { id: "pinned", label: translate(componentsCopy, 'threadPinned') },
  { id: "today", label: translate(componentsCopy, 'threadToday') },
  { id: "earlier", label: translate(componentsCopy, 'threadEarlier') },
]

function threadGroups(threads: ThreadRecord[]) {
  return [
    { label: translate(componentsCopy, 'threadPinned'), threads: threads.filter((thread) => thread.pinned) },
    ...(
      [
        [translate(componentsCopy, 'threadToday'), "today"],
        [translate(componentsCopy, 'threadEarlier'), "earlier"],
      ] as const
    ).map(([label, recency]) => ({
      label,
      threads: threads.filter(
        (thread) => !thread.pinned && thread.recency === recency
      ),
    })),
  ].filter((group) => group.threads.length > 0)
}

function threadsForTab(threads: ThreadRecord[], tabId: string) {
  if (tabId === "pinned") return threads.filter((thread) => thread.pinned)
  return threads.filter((thread) => thread.recency === tabId)
}

function SwitcherRow({
  thread,
  isActive,
  live,
  activityLabel,
  onSelect,
}: {
  thread: ThreadRecord
  isActive: boolean
  /** True while this thread's reply is still being written. */
  live: boolean
  activityLabel: string
  onSelect: (id: string) => void
}) {
  return (
    // Height follows content: a row with no artifact stays a single tight line.
    <Button
      variant={isActive ? "secondary" : "ghost"}
      aria-current={isActive ? "true" : undefined}
      onClick={() => onSelect(thread.id)}
      className="h-auto w-full flex-col items-stretch justify-center gap-0.5 px-2 py-1.5 text-sm font-normal"
    >
      <span className="flex min-w-0 items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-start">
          {thread.title}
        </span>
        <span className="text-muted-foreground w-14 shrink-0 text-end text-11 tabular-nums">
          {thread.updatedLabel}
        </span>
      </span>
      {live ? (
        <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-11/4">
          <Spinner className="size-3 shrink-0" />
          <span className="shimmer min-w-0 truncate">{activityLabel}</span>
        </span>
      ) : thread.artifact ? (
        <span className="flex min-w-0">
          <Badge
            variant="outline"
            size="sm"
            className="text-muted-foreground min-w-0 font-mono font-normal"
          >
            <span className="min-w-0 truncate">{thread.artifact}</span>
          </Badge>
        </span>
      ) : null}
    </Button>
  )
}

/** Header leading control: names the open chat and switches between them. */
function ThreadSwitcher({
  title,
  threads,
  activeThreadId,
  streaming,
  activityLabel,
  onSelectThread,
  onNewChat,
}: {
  title: string
  threads: ThreadRecord[]
  activeThreadId: string
  streaming: boolean
  /** The streaming thread's current step, shown inline on its row. */
  activityLabel: string
  onSelectThread: (id: string) => void
  onNewChat: () => void
}) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState(THREAD_TABS[0].id)

  function renderRow(thread: ThreadRecord) {
    return (
      <SwitcherRow
        key={thread.id}
        thread={thread}
        isActive={thread.id === activeThreadId}
        live={streaming && thread.id === activeThreadId}
        activityLabel={activityLabel}
        onSelect={(id) => {
          setOpen(false)
          onSelectThread(id)
        }}
      />
    )
  }

  const groups = threadGroups(threads)

  return (
    // A tablist is invalid inside role="menu", so the surface is a popover and
    // every row is a real button rather than a menu item.
    <Popover open={open} onOpenChange={setOpen}>
      {/* Button ships shrink-0, so the switcher re-enables shrink: the title
          truncates instead of shoving the trailing controls off. */}
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            className="-ms-1 min-w-0 shrink gap-1.5 px-2 font-medium"
          />
        }
      >
        <span className="min-w-0 truncate">{title}</span>
        <HugeiconsIcon icon={ChevronDownIcon} strokeWidth={2} className="opacity-60" data-icon="inline-end" aria-hidden="true" />
      </PopoverTrigger>
      {/* The popup unmounts on close, so the live row never animates unseen. */}
      <PopoverContent
        align="start"
        className="flex max-h-96 w-84 max-w-(--available-width) flex-col p-0"
      >
        <Tabs
          value={tab}
          onValueChange={(value) => setTab(String(value))}
          className="flex min-h-0 flex-1 flex-col gap-0"
        >
          {/* The strip never scrolls: it is shrink-0 and the list below owns
              the whole scroll, so no row can pass under it. */}
          <div className="border-border flex h-11 shrink-0 items-center gap-1 border-b px-2">
            {/* Zero padding plus a full-height trigger seats the line underline
                on the strip's own border instead of floating above it. */}
            <TabsList variant="line" className="h-full gap-0 p-0">
              {THREAD_TABS.map((item) => (
                <TabsTrigger
                  key={item.id}
                  value={item.id}
                  className="h-full! flex-none px-2 after:-bottom-px!"
                >
                  {item.label}
                </TabsTrigger>
              ))}
            </TabsList>

            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={translate(componentsCopy, 'newThreadAria')}
                    onClick={() => {
                      setOpen(false)
                      onNewChat()
                    }}
                    className="ms-auto"
                  />
                }
              >
                <HugeiconsIcon icon={PlusIcon} strokeWidth={2} aria-hidden="true" />
              </TooltipTrigger>
              <TooltipContent>{translate(componentsCopy, 'newThreadAria')}</TooltipContent>
            </Tooltip>
          </div>

          {THREAD_TABS.map((item) => (
            <TabsContent
              key={item.id}
              value={item.id}
              className="scrollbar min-h-0 flex-1 overflow-y-auto p-2"
            >
              {item.id === "all" ? (
                <div className="flex flex-col">
                  {groups.length === 0 ? (
                    <p className="text-muted-foreground px-2 py-6 text-center text-xs">
                      {translate(componentsCopy, 'noThreads')}
                    </p>
                  ) : null}
                  {groups.map((group) => (
                    <div
                      key={group.label}
                      className="flex flex-col gap-1 pt-3 first:pt-0"
                    >
                      <span className="text-muted-foreground px-2 text-xs">
                        {group.label}
                      </span>
                      {group.threads.map(renderRow)}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col gap-1">
                  {threadsForTab(threads, item.id).map(renderRow)}
                </div>
              )}
            </TabsContent>
          ))}
        </Tabs>
      </PopoverContent>
    </Popover>
  )
}

/*
 * The block's chat surface, turned inside out: it held its own state and read
 * a seeded storyline out of `data.ts`. Every one of those is a prop now, and
 * the state that drives them lives in the query engine (`routes/ChatPage.tsx`),
 * which is the thing that actually knows when a reply is still arriving.
 *
 * Dropped with the demo data: a model picker (this product picks its model in
 * AI 配置, not per message), a memory toggle, a Terms notice, and a Copy link /
 * Export transcript menu whose targets did not exist.
 */
/*
 * 这一行头去哪儿渲染（本仓改动）。给了 portal 目标就搬进外壳顶栏，本地不再画一条
 * ——否则桌面上会有两条并排的顶栏，上面那条还是空的。插槽是外壳里的兄弟节点，首帧
 * 还没提交，所以照 page-header 的做法等一次挂载。
 */
function ChatHeaderShell({
  portalTargetId,
  children,
}: {
  portalTargetId?: string
  children: ReactNode
}) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  if (portalTargetId) {
    if (!mounted) return null
    const slot = document.getElementById(portalTargetId)
    if (slot) return createPortal(children, slot)
    // 插槽不在（外壳换了、或这个块被单独用在别处）—— 退回自带的头，
    // 而不是让整行消失。
  }
  return (
    <header className="bg-background/70 supports-backdrop-filter:bg-background/60 after:from-background sticky top-(--header-height) z-10 flex h-14 shrink-0 items-center gap-2 px-3 backdrop-blur-md after:pointer-events-none after:absolute after:inset-x-0 after:top-full after:h-6 after:bg-gradient-to-b after:to-transparent sm:px-4">
      {children}
    </header>
  )
}

export function AiChat({
  threads,
  activeThreadId,
  transcript,
  title,
  streaming,
  stopped,
  arrivingId,
  stoppedIds,
  activityLabel,
  starters,
  heading,
  subheading,
  emptyExtra,
  headerEnd,
  headerPortalTargetId,
  composerTools,
  composerPlaceholder,
  disclaimer,
  onSelectThread,
  onDeleteThread,
  onNewChat,
  onSend,
  onStop,
  onArrived,
}: {
  threads: ThreadRecord[]
  activeThreadId: string
  transcript: TranscriptRecord
  title: string
  streaming: boolean
  stopped: boolean
  arrivingId: string | null
  stoppedIds: string[]
  activityLabel: string
  starters: StarterCategory[]
  heading: string
  subheading: string
  emptyExtra?: React.ReactNode
  /** Host controls at the end of the header row. */
  headerEnd?: ReactNode
  /**
   * 把这一行渲染进外壳顶栏（本仓改动）。这个块自带一条 h-14 的头，而外壳也有
   * 一条顶栏 —— 两条叠在一起，桌面上等于白占 50px，上面那条还是空的。给了 id
   * 就把这一行 portal 过去，本地那条头不再画。留空则保持原样（手机端就是这样：
   * 外壳顶栏被 logo 和菜单占满，这一行只能留在页面里）。
   */
  headerPortalTargetId?: string
  /** Host controls on the composer's bottom row. */
  composerTools?: ReactNode
  composerPlaceholder?: string
  disclaimer?: ReactNode
  onSelectThread: (id: string) => void
  /** 空态「最近的会话」每行的删除。不传就不画按钮。 */
  onDeleteThread?: (id: string) => void
  onNewChat: () => void
  onSend: (text: string) => void
  onStop: () => void
  onArrived: () => void
}) {
  const empty = transcript.messages.length === 0 && !transcript.pending
  // 示例卡的「自己写一句」：把大标题放进输入框，让人接着写。
  const [seed, setSeed] = useState<{ text: string; nonce: number } | undefined>()
  const composer = (
    <Composer
      streaming={streaming}
      tools={composerTools}
      placeholder={composerPlaceholder}
      disclaimer={disclaimer}
      seed={seed}
      onSend={onSend}
      onStop={onStop}
    />
  )

  return (
    // Every tooltip in the block needs this ancestor to open.
    <TooltipProvider>
      <div className="bg-background text-foreground flex min-h-full w-full flex-1 flex-col">
        {/* Header floats over the transcript, so it blurs what scrolls beneath. */}
        <ChatHeaderShell portalTargetId={headerPortalTargetId}>
          {/* The switcher leads: it names the open chat and is the only nav
              this block has. */}
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <ThreadSwitcher
              title={title}
              threads={threads}
              activeThreadId={activeThreadId}
              streaming={streaming}
              activityLabel={activityLabel}
              onSelectThread={onSelectThread}
              onNewChat={onNewChat}
            />
            {/* Below md the transcript carries this state, where it has room. */}
            {streaming ? (
              <Badge
                variant="primary-light"
                size="sm"
                className="shrink-0 max-md:hidden"
              >
                {translate(componentsCopy, 'inProgress')}
              </Badge>
            ) : null}
          </div>

          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={translate(componentsCopy, 'newThreadAria')}
                  onClick={onNewChat}
                />
              }
            >
              <HugeiconsIcon icon={PlusIcon} strokeWidth={2} aria-hidden="true" />
            </TooltipTrigger>
            <TooltipContent>{translate(componentsCopy, 'newThreadAria')}</TooltipContent>
          </Tooltip>

          {headerEnd}
        </ChatHeaderShell>

        <main className="flex min-h-0 flex-1 flex-col">
          {/* 照 ai-chat-10 的欢迎页：空态时 ask box 就在标题正下方、示例问题之上，
              是页面的焦点；问出第一句之后才退到底部跟着对话走。同一个 Composer
              元素，只是挂的位置不同。 */}
          <ChatThread
            composer={empty ? composer : null}
            transcript={transcript}
            title={title}
            streaming={streaming}
            stopped={stopped}
            arrivingId={arrivingId}
            stoppedIds={stoppedIds}
            threads={threads}
            starters={starters}
            heading={heading}
            subheading={subheading}
            emptyExtra={emptyExtra}
            activityLabel={activityLabel}
            onStart={onSend}
            onSelectThread={onSelectThread}
            onDeleteThread={onDeleteThread}
            onDraft={(text) => setSeed({ text, nonce: Date.now() })}
            onArrived={onArrived}
          />

          {!empty && (
            <div className="shrink-0 px-3 pb-4 sm:px-4">{composer}</div>
          )}
        </main>
      </div>
    </TooltipProvider>
  )
}
